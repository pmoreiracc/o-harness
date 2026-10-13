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

    def test_stop_during_worker_settles_without_rereading_unsaved_human_turn(self):
        # docs/usage.md: an accepted stop drains its worker even if the host's newest turn is not yet readable.
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        def pending(*args,**kwargs):
            if load_run(self.root)[1]['status']=='stopping':
                raise Refused('Codex has not saved the calling human turn yet; retry the same OH operation.')
        def stopped(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            self.assertEqual(request(self.root,'stop')['status'],'stopping')
            return value|{'failed':True,'returncode':-15,'cancellation':['stopped'],'structured':None}
        with patch('oh.authority.materialize',side_effect=pending):
            result=run(self.root,stopped)
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(result['completed'],0)
        self.assertEqual(result['last_failure']['cancellation'],['stopped'])
        self.assertEqual([c[0] for c in self.calls],['implementation'])
        self.assertTrue((self.root/'output.txt').exists())

    def test_stop_arriving_during_human_record_read_still_settles(self):
        # The same control can race the read after the implementation has already returned.
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        def pending(*args,**kwargs):
            if any(a['role']=='implementation' for a in load_run(self.root)[1]['attempts']):
                request(self.root,'stop')
                raise Refused('Codex has not saved the calling human turn yet; retry the same OH operation.')
        with patch('oh.authority.materialize',side_effect=pending):
            result=run(self.root,self.fake)
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(result['completed'],0)
        self.assertEqual([c[0] for c in self.calls],['implementation'])

    def test_pause_drains_worker_and_resume_keeps_allowances_without_repeating_it(self):
        journal,_=start(self.root,{'tasks':self.tasks[:1]},self.event())
        def paused(*args,**kwargs):
            result=self.fake(*args,**kwargs)
            if args[4]!='review':
                from .worker_checks import run as checks
                self.assertTrue(checks(args[5])['passed'])
                self.assertEqual(request(self.root,'pause')['status'],'pausing')
            return result
        self.assertEqual(run(self.root,paused)['status'],'paused')
        self.assertEqual([c[0] for c in self.calls],['implementation'])
        before=len(journal.records())
        request(self.root,'pause');self.assertEqual(len(journal.records()),before)
        _,state=load_run(self.root);granted=state['granted']
        choose(self.root,'resume',self.event('2','oh-resume'))
        # Already checked implementation resumes directly at review; a paused run grants nothing new.
        from .verification import verify
        import subprocess
        with patch('oh.processes.capture',return_value=(subprocess.CompletedProcess([],1,'','version unavailable'),[])):
            result=verify(self.root,[{'name':'toolchain','command':[sys.executable,'-c','pass'],
                         'toolchain':[[sys.executable,'--version']]}],self.project_id)[0]
        self.assertTrue(result['unavailable']);self.assertEqual(result['returncode'],1)
        self.assertIn('version unavailable',result['output'])
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
        journal,state=start(self.root,{'tasks':self.tasks[:1]},self.event())
        before=len(journal.records())
        self.assertEqual(request(self.root,'stop',expected_run=state['id'],source={'session':'previous-owner'})['status'],'running')
        self.assertEqual(request(self.root,'stop',expected_run='previous-run',source={'session':'s'})['status'],'running')
        self.assertEqual(request(self.root,'stop',expected_run=state['id'],source={'host':'claude','session':'s'})['status'],'running')
        self.assertEqual(len(journal.records()),before)
        self.assertEqual(request(self.root,'pause')['status'],'paused')
        (self.root/'manual').write_text('preserve')
        with self.assertRaises(Refused):choose(self.root,'resume',self.event('2','oh-resume'))
        self.assertEqual(request(self.root,'stop')['status'],'stopped')
        self.assertEqual(request(self.root,'stop')['status'],'stopped')
        with self.assertRaises(Refused):choose(self.root,'resume',self.event('3','oh-resume'))
        self.assertEqual((self.root/'manual').read_text(),'preserve')

    def test_stop_during_check_cancels_owned_group_and_preserves_results(self):
        # docs/usage.md: Codex Stop cancels the owned step even without MCP cancellation delivery.
        from .registry import profile_path
        from .storage import atomic_json
        signal_file=Path(self.temp.name)/'check-started'
        code='import pathlib,time,signal; signal.signal(signal.SIGTERM,signal.SIG_IGN); pathlib.Path('+repr(str(signal_file))+').touch(); time.sleep(90)'
        from .test_workflow import configure
        configure(self.root,checks=[{'name':'blocking','command':[sys.executable,'-c',code]}])
        home=Path(self.temp.name)/'codex'
        transcript=home/'sessions/2026/10/11/rollout-s.jsonl';transcript.parent.mkdir(parents=True)
        import json
        transcript.write_bytes(('\n'.join(json.dumps(e) for e in [
            {'type':'session_meta','payload':{'id':'s','source':'cli','cwd':str(self.root)}},
            {'type':'event_msg','payload':{'type':'task_started','turn_id':'current-turn'}},
            {'type':'event_msg','payload':{'type':'user_message','turn_id':'current-turn','message':'Please wait.'}}])+'\n').encode())
        environment=patch.dict(os.environ,{'CODEX_HOME':str(home),'CODEX_THREAD_ID':'s','OH_CODEX_TURN_ID':'current-turn'})
        environment.start();self.addCleanup(environment.stop)
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        outcomes=[]
        def execute():
            try:outcomes.append(run(self.root,self.fake))
            except Exception as exc:outcomes.append(exc)
        thread=threading.Thread(target=execute);thread.start()
        deadline=time.monotonic()+15
        while not signal_file.exists() and thread.is_alive() and time.monotonic()<deadline:time.sleep(.05)
        self.assertTrue(signal_file.exists(),outcomes)
        def aborted(turn,reason='interrupted'):
            return json.dumps({'type':'event_msg','payload':{'type':'turn_aborted','turn_id':turn,'reason':reason}})+'\n'
        with transcript.open('a',newline='\n') as saved:
            saved.write(aborted('1'))  # an earlier authority turn cannot stop a new execution turn
            saved.write(aborted('current-turn','failed'))  # an ordinary host failure is not Codex Stop
        time.sleep(.2);self.assertEqual(load_run(self.root)[1]['status'],'running')
        native=aborted('current-turn');middle=len(native)//2
        with transcript.open('a',newline='\n') as saved:saved.write(native[:middle])
        time.sleep(.2);self.assertEqual(load_run(self.root)[1]['status'],'running')
        with transcript.open('a',newline='\n') as saved:saved.write(native[middle:])
        thread.join(12)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(outcomes[0],dict)
        self.assertEqual(outcomes[0]['status'],'stopped')
        self.assertEqual(outcomes[0]['completed'],0)
        self.assertTrue((self.root/'output.txt').exists())
        self.assertEqual([c[0] for c in self.calls],['implementation'])
        journal,state=load_run(self.root)
        stopping=next(r['data'] for r in journal.records() if r['kind']=='run.status' and r['data']['status']=='stopping')
        self.assertEqual(stopping['source']['turn'],'current-turn')
        self.assertEqual(stopping['source']['session'],'s')
        self.assertIn('record_hash',stopping['source']);self.assertNotIn('recovery_grants',state)

    def test_codex_stop_after_worker_prevents_checks_review_and_commit(self):
        """docs/usage.md: a saved native Stop also fences the handoff between execution steps."""
        import json
        home=Path(self.temp.name)/'codex'
        transcript=home/'sessions/rollout-s.jsonl';transcript.parent.mkdir(parents=True)
        transcript.write_bytes(('\n'.join(json.dumps(e) for e in [
            {'type':'session_meta','payload':{'id':'s','source':'cli','cwd':str(self.root)}},
            {'type':'event_msg','payload':{'type':'task_started','turn_id':'1'}},
            {'type':'event_msg','payload':{'type':'user_message','turn_id':'1','message':'Please wait.'}}])+'\n').encode())
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        head=self.git('rev-parse','HEAD')
        def stopped(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            with transcript.open('a',newline='\n') as saved:
                # Many small host records must not hide the final Stop at a handoff.
                for _ in range(120):saved.write(json.dumps({'type':'event_msg','payload':{'type':'token_count'}})+'\n')
                saved.write(json.dumps({'type':'event_msg','payload':{'type':'turn_aborted','turn_id':'1','reason':'interrupted'}})+'\n')
            return value
        with patch.dict(os.environ,{'CODEX_HOME':str(home),'CODEX_THREAD_ID':'s','OH_CODEX_TURN_ID':'1'}),patch('oh.worker_checks.verify') as checks:
            result=run(self.root,stopped)
        checks.assert_not_called();self.assertEqual(result['status'],'stopped')
        self.assertEqual(result['completed'],0);self.assertEqual(result['review_rounds'],0)
        self.assertEqual([c[0] for c in self.calls],['implementation'])
        self.assertEqual(self.git('rev-parse','HEAD'),head);self.assertTrue((self.root/'output.txt').exists())

    def test_pause_at_batch_checkpoint_cannot_grant_next_batch_on_resume(self):
        fixtures.configure(self.root,tasks_per_batch=1)  # one task per batch shows it; more only add Git work
        start(self.root,{'tasks':self.tasks[:2]},self.event())
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertEqual(request(self.root,'pause')['status'],'paused')
        choose(self.root,'resume',self.event('2','oh-resume'))
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertEqual(len(self.calls),2)  # task 1's implementation and review; resume ran nothing more
        choose(self.root,'continue',self.event('3','continue'))
        self.assertEqual(run(self.root,self.fake)['completed'],2)

    def test_accepted_concern_survives_pause_without_spending_another_review(self):
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        def concern(*args,**kwargs):
            result=self.fake(*args,**kwargs)
            if args[4]=='review':
                result['structured'].update(verdict='concern',findings=[{'severity':'concern','description':'Accepted tradeoff','path':'output.txt','family':'accepted-tradeoff','relation':'original'}])
            return result
        self.assertEqual(run(self.root,concern)['status'],'findings_checkpoint')
        choose(self.root,'accept concerns',self.event('2','accept concerns'))
        request(self.root,'pause')
        choose(self.root,'resume',self.event('3','oh-resume'))
        self.assertEqual(run(self.root,self.fake)['completed'],1)
        self.assertEqual([c[0] for c in self.calls],['implementation','review'])


if __name__=='__main__' :unittest.main()
