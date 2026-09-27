import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch
from . import test_workflow as fixtures
from .controls import request
from .workflow import start, choose, load_run
from .runner import run
from .storage import Refused


class ControlsTest(unittest.TestCase):
    setUp=fixtures.WorkflowTest.setUp
    git=fixtures.WorkflowTest.git
    event=fixtures.WorkflowTest.event
    fake=fixtures.WorkflowTest.fake

    def test_pause_drains_worker_and_resume_keeps_allowances_without_repeating_it(self):
        journal,_=start(self.root,{'tasks':self.tasks[:1]},self.event())
        def paused(*args,**kwargs):
            result=self.fake(*args,**kwargs)
            if args[4]!='review':
                self.assertEqual(request(self.root,'pause')['status'],'pausing')
            return result
        self.assertEqual(run(self.root,paused)['status'],'paused')
        self.assertEqual([c[0] for c in self.calls],['implementation'])
        before=len(journal.records())
        request(self.root,'pause');self.assertEqual(len(journal.records()),before)
        _,state=load_run(self.root);granted=state['granted']
        choose(self.root,'resume',self.event('2','oh-resume'))
        self.assertEqual(run(self.root,self.fake)['status'],'completed')
        self.assertEqual([c[0] for c in self.calls],['implementation','review'])
        self.assertEqual(load_run(self.root)[1]['granted'],granted)

    def test_pause_after_review_fences_commit_and_resumes_exact_review(self):
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        original=self.git('rev-parse','HEAD')
        def paused(*args,**kwargs):
            result=self.fake(*args,**kwargs)
            if args[4]=='review':request(self.root,'pause')
            return result
        self.assertEqual(run(self.root,paused)['status'],'paused')
        self.assertEqual(self.git('rev-parse','HEAD'),original)
        choose(self.root,'resume',self.event('2','oh-resume'))
        self.assertEqual(run(self.root,self.fake)['completed'],1)
        self.assertEqual(len(self.calls),2)

    def test_stopped_is_terminal_and_manual_edits_invalidate_paused_resume(self):
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        self.assertEqual(request(self.root,'pause')['status'],'paused')
        (self.root/'manual').write_text('preserve')
        with self.assertRaises(Refused):choose(self.root,'resume',self.event('2','oh-resume'))
        self.assertEqual(request(self.root,'stop')['status'],'stopped')
        self.assertEqual(request(self.root,'stop')['status'],'stopped')
        with self.assertRaises(Refused):choose(self.root,'resume',self.event('3','oh-resume'))
        self.assertEqual((self.root/'manual').read_text(),'preserve')

    def test_stop_during_check_cancels_owned_group_and_preserves_results(self):
        from .registry import profile_path
        from .storage import atomic_json
        signal_file=Path(self.temp.name)/'check-started'
        code='import pathlib,time,signal; signal.signal(signal.SIGTERM,signal.SIG_IGN); pathlib.Path('+repr(str(signal_file))+').touch(); time.sleep(90)'
        from .test_workflow import configure
        configure(self.root,checks=[{'name':'blocking','command':[sys.executable,'-c',code]}])
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        outcomes=[]
        def execute():
            try:outcomes.append(run(self.root,self.fake))
            except Exception as exc:outcomes.append(exc)
        thread=threading.Thread(target=execute);thread.start()
        deadline=time.monotonic()+15
        while not signal_file.exists() and thread.is_alive() and time.monotonic()<deadline:time.sleep(.05)
        self.assertTrue(signal_file.exists(),outcomes)
        self.assertEqual(request(self.root,'stop')['status'],'stopping')
        thread.join(12)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(outcomes[0],dict)
        self.assertEqual(outcomes[0]['status'],'stopped')
        self.assertEqual(outcomes[0]['completed'],0)
        self.assertTrue((self.root/'output.txt').exists())
        self.assertEqual([c[0] for c in self.calls],['implementation'])

    def test_pause_at_batch_checkpoint_cannot_grant_next_batch_on_resume(self):
        start(self.root,{'tasks':self.tasks},self.event())
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertEqual(request(self.root,'pause')['status'],'paused')
        choose(self.root,'resume',self.event('2','oh-resume'))
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertEqual(len(self.calls),10)
        choose(self.root,'continue',self.event('3','continue'))
        self.assertEqual(run(self.root,self.fake)['completed'],6)

    def test_accepted_concern_survives_pause_without_spending_another_review(self):
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        def concern(*args,**kwargs):
            result=self.fake(*args,**kwargs)
            if args[4]=='review':
                result['structured'].update(verdict='concern',findings=[{'severity':'concern','description':'Accepted tradeoff','path':'output.txt'}])
            return result
        self.assertEqual(run(self.root,concern)['status'],'findings_checkpoint')
        choose(self.root,'accept concerns',self.event('2','accept concerns'))
        request(self.root,'pause')
        choose(self.root,'resume',self.event('3','oh-resume'))
        self.assertEqual(run(self.root,self.fake)['completed'],1)
        self.assertEqual([c[0] for c in self.calls],['implementation','review'])


if __name__=='__main__' :unittest.main()
