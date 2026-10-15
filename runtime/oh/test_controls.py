"""Saved controls fence completion; native cancellation remains a real-host rollout check."""
import unittest
import json
import os
from pathlib import Path
from unittest.mock import patch
from . import native
from .storage import Refused
from .workflow import load_run
from .test_workflow import NativeFixture


class ControlsTest(NativeFixture,unittest.TestCase):
    def test_plain_native_control_turns_need_no_internal_artifact_path(self):
        from .storage import now
        self.approve();before=load_run(self.root)[1]
        home=Path(self.temp.name)/'host';sessions=home/'.codex/sessions';sessions.mkdir(parents=True)
        with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,{'CODEX_HOME':str(home/'.codex')}), \
                patch('oh.authority.native_human',side_effect=self.native_human_original):
            def direct(session,text):
                path=sessions/(session+'.jsonl')
                rows=[{'type':'session_meta','payload':{'id':session,'source':'cli','cwd':str(self.root)}},
                      {'type':'response_item','timestamp':now(),'payload':{'type':'message','role':'assistant',
                       'content':[{'type':'output_text','text':'The current approved work is waiting for your instruction.'}]}},
                      {'type':'event_msg','timestamp':now(),'payload':{'type':'user_message','turn_id':'control','message':text}}]
                path.write_text(''.join(json.dumps(row)+'\n' for row in rows),newline='\n')
                return {'host':'codex','session':session,'turn':'control','prompt':text,'transcript_path':str(path)}
            native.decision(self.root,'pause',direct('s','/oh-pause'))
            native.decision(self.root,'stop',direct('s','Stop now'))
            self.assertEqual(native.resume(self.root)['status'],'stopped')
            native.resume(self.root,direct('fresh-parent','/oh-resume'))
            native.decision(self.root,'stop',direct('fresh-parent','Stop and take over'))
            self.assertEqual(native.resume(self.root)['status'],'stopped')
            native.resume(self.root,direct('fresh-parent','Resume the approved work.'))
            with self.assertRaises(Refused):
                native.decision(self.root,'stop',direct('fresh-parent','[$oh-stop](plugin://o-harness/skills/oh-stop/SKILL.md) unexpected args'))
            self.assertEqual(native.resume(self.root)['status'],'running')
            native.decision(self.root,'pause',direct('fresh-parent','/oh-pause'))
            native.resume(self.root,direct('fresh-parent','[$oh-resume](plugin://o-harness/skills/oh-resume/SKILL.md)'))
        after=load_run(self.root)[1]
        self.assertEqual(after['human']['session'],'fresh-parent')
        self.assertEqual(after['granted'],before['granted']);self.assertEqual(after['config'],before['config'])

    def test_live_legacy_executor_blocks_adoption_without_changing_its_records(self):
        from .controls import busy
        from .storage import checkout_file, checkout_id, lock, Journal, identifier, atomic_json
        self.approve();journal,state=load_run(self.root)
        legacy=Journal(state['project'],identifier());start=dict(journal.records()[0]['data']);start['id']=legacy.path.name
        for key in ('native_version','scope_id','scope_snapshot'):start.pop(key,None)
        legacy.append('run.started',start)
        for record in journal.records()[1:]:legacy.append(record['kind'],record['data'])
        legacy.append('run.status',{'status':'stopped'})
        atomic_json(checkout_file(self.root,'oh-active-run.json'),
                    {'project':state['project'],'run':legacy.path.name,'checkout':checkout_id(self.root)})
        before=legacy.records()
        with lock(checkout_file(self.root,'oh-runner.lock'),wait=False):
            self.assertTrue(busy(self.root))
            with self.assertRaises(Refused):native.resume(self.root,self.human('resume',session='fresh-parent'))
            with self.assertRaises(Refused):native.admit(self.root,'assessment')
        self.assertEqual(legacy.records(),before)

    def test_pause_after_review_fences_commit_and_resume_keeps_exact_review_and_allowance(self):
        self.approve();self.assess();self.implement();review=self.reviewed()
        before=load_run(self.root)[1];head=self.git('rev-parse','HEAD')
        native.decision(self.root,'pause',self.human('pause'))
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        native.resume(self.root,self.human('resume',session='fresh-parent'))
        after=load_run(self.root)[1]
        self.assertEqual(after['granted'],before['granted'])
        self.assertEqual(after['attempts'],before['attempts'])
        native.complete(self.root,review['id'])
        self.assertEqual(load_run(self.root)[1]['done'],['1'])

    def test_edits_while_paused_cannot_borrow_the_previous_review(self):
        self.approve();self.assess();self.implement();review=self.reviewed()
        native.decision(self.root,'pause',self.human('pause'))
        (self.root/'output.txt').write_text('Retained authorized correction.',newline='\n')
        native.resume(self.root,self.human('resume'))
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        self.assertEqual((self.root/'output.txt').read_text(),'Retained authorized correction.')
        self.assertEqual(load_run(self.root)[1]['done'],[])
        self.assertEqual(native.resume(self.root)['reviews_used'],1)
