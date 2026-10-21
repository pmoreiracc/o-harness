"""Delivery recovery decisions exercise real Git, journals and tool revocation."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import unittest
from unittest.mock import patch
from . import cancellation, decisions, native, recovery
from .storage import Refused, now
from .test_workflow import NativeFixture
from .workflow import load_run
from .authority import coordinator as native_coordinator


class RecoveryTest(NativeFixture, unittest.TestCase):
    def answer(self, gate, label, host='claude', session='new-parent'):
        at=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()
        return self.human(label,host=host,session=session,decision=gate['decision'],
            question=gate['question'],question_at=at,at=at,via='question',question_options=gate['options'])

    def orphan(self, host='claude'):
        with patch.object(self,'human',return_value={'host':host,'session':'s','turn':'initial',
                          'prompt':'approve','transcript_path':str(self.parent_path)}):
            self.approve()
        admitted=native.admit(self.root,'assessment')
        child=Path(self.temp.name)/'child.jsonl'
        child.write_text('',newline='\n')
        with patch('oh.authority.native_child',return_value={'child_session':'old-child','parent_session':'s',
                   'profile':admitted['profile'],'transcript_path':str(child),'record_hashes':['spawn']}):
            native.bind(self.root,admitted['id'],{})
        with cancellation._edit(self.root) as value:
            item=value['attempts'][admitted['id']]
            item.update(guard_observed=True,launch='corrected-launch')
            value['tools']['rejected-launch']={'attempt':admitted['id'],'kind':'launch','started':now()}
        self.parent_path.unlink();child.unlink()
        return admitted

    def recover(self, action, *, host='claude', native_answer=False):
        gate=decisions.prepare(self.root,'recover')
        self.assertEqual(gate['options'],['Continue','Start fresh','Stop and take over'])
        locator=self.answer(gate,{'resume':'Continue','restart':'Start fresh','stop':'Stop and take over'}[action],host)
        # New human records remain available even though the old chat was deleted.
        new_parent=Path(self.temp.name)/'new-parent.jsonl';new_parent.write_text('',newline='\n')
        locator['transcript_path']=str(new_parent)
        if native_answer:
            home=Path(self.temp.name)/'host'
            home_patch=patch('pathlib.Path.home',return_value=home);home_patch.start();self.addCleanup(home_patch.stop)
            new_parent=home/'.claude/projects/new-parent.jsonl';new_parent.parent.mkdir(parents=True)
            common={'sessionId':'new-parent','cwd':str(self.root),'timestamp':locator['at'],'entrypoint':'cli'}
            rows=[common|{'type':'assistant','message':{'content':[{'type':'tool_use','id':'recovery-answer',
                'name':'AskUserQuestion','input':{'questions':[{'question':gate['question'],'multiSelect':False,
                'options':[{'label':option,'description':option} for option in gate['options']]}]}}]}},
                common|{'type':'user','toolUseResult':{'answers':{gate['question']:locator['prompt']}},
                'message':{'content':[{'type':'tool_result','tool_use_id':'recovery-answer','content':'Answered'}]}}]
            new_parent.write_text(''.join(json.dumps(row)+'\n' for row in rows),newline='\n')
            locator={'host':'claude','session':'new-parent','decision':gate['decision'],'transcript_path':str(new_parent)}
            for name,callback in [('native_human',self.native_human_original),('coordinator',native_coordinator)]:
                mocked=patch('oh.authority.'+name,side_effect=callback);mocked.start();self.addCleanup(mocked.stop)
        with patch('oh.authority.native_result',side_effect=FileNotFoundError('deleted native transcript')):
            result=native.decision(self.root,action,locator)
        return gate,locator,result

    def test_continue_deleted_chat_finishes_delivery_without_reusing_missing_result(self):
        old=self.orphan()
        (self.root/'output.txt').write_text('kept work',newline='\n')
        before=load_run(self.root)[1]
        gate,locator,result=self.recover('resume',native_answer=True)
        state=load_run(self.root)[1]
        self.assertEqual(state['granted'],before['granted'])
        self.assertEqual(state['attempts'][0]['outcome'],'abandoned')
        self.assertEqual((self.root/'output.txt').read_text(),'kept work')
        self.assertEqual(cancellation.hook(self.root,'claude',{'hook_event_name':'PreToolUse',
            'session_id':'s','agent_id':'old-child','tool_name':'Read','tool_use_id':'late'})['hookSpecificOutput']['permissionDecision'],'deny')
        self.assertEqual(native.decision(self.root,'resume',locator)['run'],result['run'])
        self.assess();self.implement();review=self.reviewed();native.complete(self.root,review['id'])
        state=load_run(self.root)[1]
        self.assertEqual(state['done'],['1'])
        self.assertEqual(len([a for a in state['attempts'] if a['role']=='review']),1)
        self.assertNotEqual(old['id'],state['assessments']['1']['attempt'])

    def test_restart_discards_only_presented_work_and_finishes_on_updated_base(self):
        self.orphan()
        (self.root/'product.txt').write_text('discard me',newline='\n')
        (self.root/'new.txt').write_text('discard me too',newline='\n')
        (self.root/'.gitignore').write_text('local.secret\n',newline='\n')
        (self.root/'local.secret').write_text('keep ignored data',newline='\n')
        # Keep ignore rules in the base, so an approved reset cannot change their meaning.
        self.git('add','.gitignore');self.git('commit','-qm','ignore local data')
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        gate,locator,result=self.recover('restart',host='codex')
        self.assertEqual((self.root/'product.txt').read_text(),'fixture')
        self.assertFalse((self.root/'new.txt').exists())
        self.assertEqual((self.root/'local.secret').read_text(),'keep ignored data')
        self.assertEqual(self.git('rev-parse','HEAD'),self.git('rev-parse','origin/main'))
        self.assertNotEqual(self.git('branch','--show-current'),'main')
        native.decision(self.root,'restart',locator)
        self.assess();self.implement();review=self.reviewed();native.complete(self.root,review['id'])
        self.assertEqual(load_run(self.root)[1]['done'],['1'])

    def test_stop_deleted_chat_revokes_worker_without_changing_files(self):
        self.orphan()
        (self.root/'output.txt').write_text('human takes over',newline='\n')
        before=self.git('status','--porcelain')
        self.recover('stop',host='codex')
        self.assertEqual(load_run(self.root)[1]['status'],'stopped')
        self.assertEqual(self.git('status','--porcelain'),before)
        with self.assertRaisesRegex(Refused,'not running'):native.admit(self.root,'assessment')

    def test_changed_files_invalidate_destructive_choice_and_pending_tools_still_block(self):
        old=self.orphan()
        gate=decisions.prepare(self.root,'recover')
        answer=self.answer(gate,'Start fresh')
        (self.root/'surprise.txt').write_text('new user edit',newline='\n')
        with self.assertRaisesRegex(Refused,'changed since'):native.decision(self.root,'restart',answer)
        self.assertTrue((self.root/'surprise.txt').exists())
        with cancellation._edit(self.root) as value:
            value['tools']['pending-edit']={'attempt':old['id'],'kind':'tool','name':'Edit','started':now()}
        with self.assertRaisesRegex(Refused,'still settling'):self.recover('resume')
        self.assertFalse(load_run(self.root)[1]['attempts'][0]['finished'])

    def test_restart_keeps_review_spend_and_findings(self):
        self.approve();self.assess();self.implement()
        review=self.reviewed({'verdict':'blocking','findings':[{'severity':'blocking','description':'Repair this behavior'}]})
        self.recover('restart')
        state=load_run(self.root)[1]
        self.assertEqual(state['attempts'][-1]['findings'][0]['description'],'Repair this behavior')
        self.assertTrue(state['attempts'][-1]['superseded'])
        self.assertEqual(sum(a['role']=='review' for a in state['attempts']),1)
        with self.assertRaisesRegex(Refused,'Recovery changed'):native.complete(self.root,review['id'])

    def test_private_restart_restores_approved_plan_and_completes_with_valid_publication_evidence(self):
        from .test_delivery import DeliveryTest
        from . import plans, delivery_verify
        where,path=DeliveryTest.documents(self,'private')
        initial=path.read_text()
        prepared=native.prepare_scope(self.root,doc='0001')
        native.approve_scope(self.root,prepared['scope_id'],self.human())
        self.assess();self.implement();native.candidate(self.root)
        self.assertNotEqual(path.read_text(),initial)
        self.recover('restart')
        self.assertEqual(path.read_text(),initial)
        self.assertEqual(plans.approval(self.root,where,'0001'),'approved')
        self.assess();self.implement();review=self.reviewed();native.complete(self.root,review['id'])
        self.assertEqual(delivery_verify.verify_run(self.root,load_run(self.root)[1],current=True)['tasks'],1)

    def test_stop_after_recovery_answer_prevents_transfer(self):
        self.approve()
        gate=decisions.prepare(self.root,'recover')
        answer=self.answer(gate,'Continue',host='codex',session='s')
        # Same-chat Stop occurs after the new recovery answer.
        at=(datetime.fromisoformat(answer['at'])+timedelta(seconds=1)).isoformat()
        self.parent_path.write_text(json.dumps({'type':'event_msg','timestamp':at,'payload':{
            'type':'turn_aborted','turn_id':answer['turn'],'reason':'interrupted'}})+'\n',newline='\n')
        with self.assertRaisesRegex(Refused,'stopped after'):native.decision(self.root,'resume',answer)
        self.assertNotIn('recovery',load_run(self.root)[1]['human'])

    def test_restart_retry_after_git_change_does_not_discard_new_edits(self):
        self.approve()
        gate=decisions.prepare(self.root,'recover')
        answer=self.answer(gate,'Start fresh')
        journal,_=load_run(self.root)
        from .storage import Journal
        original=Journal.append
        def fail_transition(target,kind,data):
            if kind=='transition' and any(e['kind']=='delivery.recovered' for e in data.get('events',[])):
                raise OSError('Simulated interruption after Git switch')
            return original(target,kind,data)
        with patch.object(Journal,'append',fail_transition),self.assertRaisesRegex(OSError,'Simulated'):
            native.decision(self.root,'restart',answer)
        (self.root/'after-stop.txt').write_text('new edit',newline='\n')
        with self.assertRaisesRegex(Refused,'changed since'):native.decision(self.root,'restart',answer)
        self.assertTrue((self.root/'after-stop.txt').exists())
        (self.root/'after-stop.txt').unlink()
        native.decision(self.root,'restart',answer)
        self.assertNotIn('recovery_intent',load_run(self.root)[1])

    def test_restart_after_merged_task_keeps_completion_evidence_and_selects_next_batch(self):
        from .delivery_verify import verify_run
        self.approve(tasks=self.tasks[:2]);self.assess();self.implement()
        review=self.reviewed();native.complete(self.root,review['id'])
        prior=load_run(self.root)[1]['commit_intents']['1']
        self.git('switch','main');self.git('merge','--no-ff','--no-edit','work')
        self.git('update-ref','refs/remotes/origin/main','HEAD');self.git('switch','work')
        self.recover('restart')
        state=load_run(self.root)[1]
        self.assertEqual(state['done'],['1']);self.assertEqual(state['granted'],['2'])
        self.assertEqual(state['commit_intents']['1'],prior)
        self.assess();self.implement();review=self.reviewed();native.complete(self.root,review['id'])
        self.assertEqual(verify_run(self.root,load_run(self.root)[1],current=True)['tasks'],2)


if __name__=='__main__':unittest.main()
