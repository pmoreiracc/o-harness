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
            native.decision(self.root,'pause',direct('fresh-parent','/oh-pause'))
            with self.assertRaises(Refused):native.resume(self.root,direct('fresh-parent','/oh-deliver'))
            native.resume(self.root,direct('fresh-parent','/oh-deliver finish the same bounded change'),run=before['id'])
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

    def test_discovery_and_selected_reads_preserve_both_bindings_and_live_work(self):
        from .storage import checkout_file
        from .config import change
        change(self.root,'review_rounds','1')
        self.approve();journal,original=load_run(self.root)
        request=self.human('/oh-review tree')
        feedback=native.review(self.root,'tree',request)
        feedback_journal,review_state=load_run(self.root)
        before={name:checkout_file(self.root,name).read_bytes() for name in ('oh-active-run.json','oh-active-review.json')}
        records=journal.records();review_records=feedback_journal.records()
        self.assertEqual({x['run'] for x in native.saved_work(self.root)['saved_work']},{original['id'],feedback['run']})
        self.assertEqual(native.resume(self.root,run=original['id'])['run'],original['id'])
        self.assertEqual(native.review(self.root,'tree',request)['run'],feedback['run'])
        self.assertEqual(journal.records(),records);self.assertEqual(feedback_journal.records(),review_records)
        # A review binding must not let new scope overwrite the hidden workflow.
        prepared=native.prepare_scope(self.root,{'tasks':self.tasks[:1]})
        with self.assertRaisesRegex(Refused,'saved scope'):
            native.approve_scope(self.root,prepared['scope_id'],self.human())
        self.assertEqual({name:checkout_file(self.root,name).read_bytes() for name in before},before)
        # Selecting the ordinary workflow retains the unfinished review for later.
        native.resume(self.root,self.human('resume'),run=original['id'])
        self.assertEqual(load_run(self.root)[1]['id'],original['id'])
        self.assertEqual({x['run'] for x in native.saved_work(self.root)['saved_work']},{original['id'],feedback['run']})
        native.resume(self.root,self.human('/oh-review tree'),run=feedback['run'])
        self.assertEqual(load_run(self.root)[1]['id'],feedback['run'])
        admitted=native.admit(self.root,'review')
        records=journal.records()
        with self.assertRaisesRegex(Refused,'native attempt'):
            native.resume(self.root,self.human('resume'),run=original['id'])
        self.assertEqual(journal.records(),records)
        self.assertEqual(native.saved_work(self.root)['saved_work'][1]['pending_attempts'][0]['id'],admitted['id'])
        native.bind(self.root,admitted['id'],{'child_session':'failed-reviewer'})
        from .storage import now
        retry=self.human('/oh-review tree',session='new-review-parent',at=now())
        self.native_results[admitted['id']]={'text':'','status':'failed'}
        native.retain(self.root,admitted['id'],{})
        self.assertTrue(native.saved_work(self.root)['saved_work'][1]['resumable'])
        continued=native.review(self.root,'tree',retry)
        self.assertEqual(continued['run'],feedback['run'])
        self.assertEqual(continued['reviews_used'],1)
        with self.assertRaisesRegex(Refused,'allowance is spent'):native.admit(self.root,'review')
        native.decision(self.root,'grant-review',self.human('grant review'))
        self.assertEqual(native.select(self.root)['reviews_allowed'],2)

    def test_unregistered_discovery_and_structured_selector_authority(self):
        from .registry import index_path
        from .storage import identifier
        # A never-registered checkout is a factual empty result, not implicit init.
        other=Path(self.temp.name)/'other';other.mkdir()
        self.assertFalse(index_path(other).exists())
        self.assertEqual(native.saved_work(other)['saved_work'],[])
        self.assertFalse(index_path(other).exists())
        state={'workflow':'deliver','design':'0001','track':'code'}
        for prompt in ('/oh-deliver 0001 code','[$oh-deliver](plugin://o-harness/skills/oh-deliver/SKILL.md) 0001 code'):
            self.assertTrue(native._workflow_resume(state,{'prompt':prompt}))
        for prompt in ('/oh-deliver','/oh-deliver 0002 code','/oh-deliver 0001 docs','/oh-propose 0001 code'):
            self.assertFalse(native._workflow_resume(state,{'prompt':prompt}))
        legacy={'workflow':'design','design':None,'entry_human':{'prompt':'/oh-design auth'},'human':{'prompt':'resume'}}
        self.assertTrue(native._workflow_resume(legacy,{'prompt':'/oh-design auth'}))
        self.assertFalse(native._workflow_resume(legacy,{'prompt':'/oh-design other'}))
        from .config import change
        from .storage import encode
        change(self.root,'context.result_chars','1000')
        self.approve();journal,state=load_run(self.root);records=journal.records()
        self.assertLessEqual(len(encode(native.saved_work(self.root))),state['config']['context']['result_chars'])
        with self.assertRaises(Refused):native.resume(self.root,self.human('resume'),run=identifier())
        self.assertEqual(journal.records(),records)

    def test_continuation_hints_use_the_requested_review_task_not_the_next_task(self):
        self.approve(self.tasks[:2])
        _,state=load_run(self.root)
        state.update(done=['1'],extra_review={'task':'1'},attempts=[{'id':'prior-review','task':'1','role':'review','finished':True,'outcome':'clean'}])
        hints=native._continuation(state)
        self.assertEqual(hints['phase'],'task_review')
        self.assertEqual(hints['latest_result']['id'],'prior-review')
        state['correction']={'task':'1'}
        self.assertEqual(native._continuation(state)['phase'],'task_correction')
