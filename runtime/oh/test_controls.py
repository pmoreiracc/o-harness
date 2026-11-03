"""Saved controls fence completion; native cancellation remains a real-host rollout check."""
import unittest
import json
import os
from pathlib import Path
from unittest.mock import patch
from . import native
from .authority import coordinator as native_coordinator
from .storage import Refused
from .workflow import load_run
from .test_workflow import NativeFixture


class ControlsTest(NativeFixture,unittest.TestCase):
    def test_idle_selection_publishes_exact_reviewed_commits_without_stopping_prior_work(self):
        from . import publication
        from .test_workflow import configure
        configure(self.root,tasks_per_batch=1)
        self.git('remote','add','origin','https://github.com/example/product.git')
        self.approve(self.tasks);self.assess();self.implement()
        first=self.reviewed();native.complete(self.root,first['id'])
        old_journal,old=load_run(self.root);old_records=old_journal.records()
        self.assertEqual(old['status'],'checkpoint')
        self.assertEqual(old['done'],['1']);self.assertEqual(old['granted'],['1'])
        self.approve([self.tasks[0]|{'title':'Different approved work'}])
        self.assess();self.implement(edit=lambda:(self.root/'different.txt').write_text('new work\n',newline='\n'))
        second=self.reviewed();native.complete(self.root,second['id'])
        # Reviewed commits alone do not grant publication, even on the same branch.
        with self.assertRaisesRegex(Refused,'publication grant|human PR choice'):publication.render(self.root)
        native.decision(self.root,'publish',self.human('publish',question='Publish the reviewed work branch to example/product?'))
        current=load_run(self.root)[1]
        self.assertEqual(current['publication']['commits'],[old['summaries'][0]['commit'],current['summaries'][0]['commit']])
        body=publication.render(self.root)
        self.assertIn(first['id'],body);self.assertIn(second['id'],body)
        self.assertEqual(old_journal.records(),old_records)
        self.assertEqual(load_run(self.root,old['id'])[1]['status'],'checkpoint')
        # The retained history still needs exact commit evidence and an exact-range grant.
        from copy import deepcopy
        made=publication.made
        altered=deepcopy(current);altered['publication']['commits']=altered['publication']['commits'][1:]
        with patch('oh.publication.made',side_effect=lambda root,project,commit:
                altered if commit==current['summaries'][0]['commit'] else made(root,project,commit)):
            with self.assertRaisesRegex(Refused,'exact reviewed run commits'):publication.render(self.root)
        unsettled=old|{'extra_review':{'task':'1'}}
        with patch('oh.publication.made',side_effect=lambda root,project,commit:
                unsettled if commit==old['summaries'][0]['commit'] else made(root,project,commit)):
            with self.assertRaisesRegex(Refused,'requested task review'):publication.render(self.root)
        prior_journal,prior=load_run(self.root);prior_records=prior_journal.records()
        self.approve([self.tasks[0]|{'title':'Further approved work'}])
        self.assess();self.implement(edit=lambda:(self.root/'further.txt').write_text('further work\n',newline='\n'))
        third=self.reviewed();native.complete(self.root,third['id'])
        # A new exact choice covers the old reviewed range and its earlier PR
        # choice, without altering the original decisions.
        native.decision(self.root,'publish',self.human('publish',question='Publish the reviewed work branch to example/product?'))
        latest_journal,latest=load_run(self.root)
        self.assertEqual(latest['publication']['commits'],prior['publication']['commits']+[latest['summaries'][0]['commit']])
        self.assertIn(third['id'],publication.render(self.root))
        self.git('remote','set-url','origin','https://github.com/example/other.git')
        with self.assertRaisesRegex(Refused,'destination changed'):publication.render(self.root)
        native.decision(self.root,'publish',self.human('publish',question='Publish the reviewed work branch to example/other?'))
        self.assertIn(third['id'],publication.render(self.root))
        latest=load_run(self.root)[1];latest_records=latest_journal.records()
        self.assertEqual(prior_journal.records(),prior_records)
        self.assertEqual(old_journal.records(),old_records)
        # Resume may return to an earlier run after other runs' reviewed commits.
        native.resume(self.root,self.resume_choice(run=old['id']),run=old['id'])
        native.decision(self.root,'continue',self.human('continue'))
        self.assess();self.implement(edit=lambda:(self.root/'remaining.txt').write_text('remaining work\n',newline='\n'))
        final=self.reviewed();native.complete(self.root,final['id'])
        native.decision(self.root,'publish',self.human('publish',question='Publish the reviewed work branch to example/other?'))
        finished=load_run(self.root)[1]
        self.assertEqual(finished['done'],['1','2'])
        self.assertEqual(finished['publication']['commits'],latest['publication']['commits']+[finished['summaries'][-1]['commit']])
        self.assertIn(final['id'],publication.render(self.root))
        self.assertEqual(old_journal.records()[:len(old_records)],old_records)
        self.assertEqual(prior_journal.records(),prior_records)
        self.assertEqual(latest_journal.records(),latest_records)
        final_records=old_journal.records()
        from . import cancellation
        from .storage import now
        with cancellation._edit(self.root) as control:
            control['tools']['late-old-tool']={'attempt':first['id'],'kind':'tool','name':'Edit','started':now()}
        with self.assertRaisesRegex(Refused,'unsettled native attempt or operation'):publication.render(self.root)
        self.assertEqual(old_journal.records(),final_records)
        with self.parent_path.open('a',newline='\n') as stream:
            stream.write(json.dumps({'type':'response_item','payload':{'type':'function_call_output',
                                    'call_id':'late-old-tool','output':'Completed'}})+'\n')
        body=publication.render(self.root)
        self.assertEqual(load_run(self.root)[1]['publication'],finished['publication'])
        from .test_workflow import pull_request
        pr=pull_request(finished)|{'body':body}
        with patch('oh.publication.github',side_effect=lambda root,host,path,**kw:[pr] if kw.get('pages') else pr):
            published=publication.reconcile(self.root)
            self.assertEqual(publication.reconcile(self.root)['published'],published['published'])
        self.assertEqual(published['published']['number'],pr['number'])
        self.assertEqual(old_journal.records()[:len(final_records)],final_records)
        self.assertEqual(prior_journal.records(),prior_records)
        self.assertEqual(latest_journal.records(),latest_records)

    def test_idle_selection_preserves_authority_findings_and_edits_and_fences_old_selection(self):
        self.approve();self.assess();self.implement()
        self.reviewed({'verdict':'blocking','summary':'Retain the unresolved defect.',
                       'findings':[{'severity':'blocking','family':'retained-idle','description':'The original defect remains unresolved.'}]})
        journal,original=load_run(self.root)
        # An original finding stays historical; new selection cannot resolve it.
        before=journal.records()
        (self.root/'manual.txt').write_text('keep these manual edits',newline='\n')
        prepared=native.prepare_scope(self.root,{'tasks':[self.tasks[0]|{'title':'A different approved fix'}]})
        selected=native.approve_scope(self.root,prepared['scope_id'],self.human(session='new-parent'))
        self.assess()
        newer_journal,newer=load_run(self.root);newer_records=newer_journal.records()
        from .storage import read_json
        packet=read_json(Path(newer['attempts'][-1]['evidence'])/'task-context.json')
        self.assertEqual(packet['retained_work']['runs'][0]['run'],original['id'])
        self.assertNotEqual(selected['run'],original['id'])
        self.assertEqual(journal.records(),before)
        self.assertEqual(selected['retained_work'][0]['run'],original['id'])
        self.assertEqual((self.root/'manual.txt').read_text(),'keep these manual edits')
        with self.assertRaisesRegex(Refused,'superseded'):native._owner(self.root,original)
        with self.assertRaisesRegex(Refused,'predates'):
            native.approve_scope(self.root,original['scope_id'],original['human'])
        resumed=native.resume(self.root,self.resume_choice(run=original['id'],session='returning-parent'),run=original['id'])
        self.assertEqual(resumed['run'],original['id'])
        after=load_run(self.root)[1]
        for key in ('config','granted','attempts','done','resolutions'):
            self.assertEqual(after[key],original[key])
        self.assertEqual(newer_journal.records(),newer_records)

    def test_idle_selection_fences_prior_coordinator_turns_on_both_hosts(self):
        from . import cancellation
        for host in ('codex','claude'):
            with self.subTest(host=host),patch.object(self,'human',side_effect=lambda prompt='approve',**kw:
                    {'host':host,'session':'s','turn':'old-'+host,'prompt':prompt,**kw}):
                self.approve();old=load_run(self.root)[1]
            prepared=native.prepare_scope(self.root,{'tasks':[self.tasks[0]|{'title':'New '+host+' work'}]})
            native.approve_scope(self.root,prepared['scope_id'],self.human(host=host,session='s',turn='new-'+host))
            event={'hook_event_name':'PreToolUse','session_id':'s','tool_name':'mcp__o_harness__status',
                   'tool_use_id':'late-'+host,'turn_id':old['human']['turn']}
            self.assertIn('superseded work selection',cancellation.hook(self.root,host,event)['hookSpecificOutput']['permissionDecisionReason'])
            self.assertEqual(cancellation.hook(self.root,host,event|{'turn_id':'fresh-human-'+host}),{})

    def test_idle_selection_still_requires_cleanup_of_finished_attempt_operations(self):
        from . import cancellation
        from .storage import now
        self.approve();self.assess();journal,state=load_run(self.root)
        prepared=native.prepare_scope(self.root,{'tasks':[self.tasks[0]|{'title':'Different work'}]})
        attempt=state['attempts'][-1]['id']
        with cancellation._edit(self.root) as value:
            value['tools']['unfinished']={'attempt':attempt,'kind':'tool','name':'Edit','started':now()}
            value['tools']['settled-command']={'attempt':attempt,'kind':'command','started':now(),'ended':now(),
                                              'receipt':str(Path(self.temp.name)/'expired-command-receipt')}
        before=journal.records()
        self.assertEqual(native.select(self.root)['execution']['state'],'unsettled')
        with self.assertRaisesRegex(Refused,'unsettled native attempt or operation'):
            native.approve_scope(self.root,prepared['scope_id'],self.human())
        self.assertEqual(journal.records(),before)
        # A lost post-hook is routine bookkeeping once the original native
        # transcript actually contains this tool's completed result.
        with self.parent_path.open('a',newline='\n') as stream:
            stream.write(json.dumps({'type':'response_item','payload':{'type':'function_call_output',
                                     'call_id':'unfinished','output':'Completed'}})+'\n')
        self.assertTrue(native.approve_scope(self.root,prepared['scope_id'],self.human())['run'])
        self.assertEqual(journal.records(),before)

    def test_selection_orders_native_decisions_instead_of_their_later_journal_writes(self):
        from datetime import datetime
        from .storage import now
        self.approve()
        prepared=native.prepare_scope(self.root,{'tasks':[self.tasks[0]|{'title':'New native request'}]})
        stopped=self.human('stop',at=now());native.decision(self.root,'stop',stopped)
        journal,_=load_run(self.root)
        native_at=datetime.fromisoformat(stopped['at']);written_at=datetime.fromisoformat(journal.records()[-1]['at'])
        # A new input can arrive while the preceding helper is still saving it.
        newer_input=native_at+(written_at-native_at)/2
        selected=native.approve_scope(self.root,prepared['scope_id'],self.human(at=newer_input.isoformat()))
        self.assertEqual(selected['task']['title'],'New native request')

    def test_standalone_review_repairs_can_select_over_idle_work_without_losing_its_history(self):
        from . import prepared,review
        from .storage import atomic_json
        self.approve();old_journal,old=load_run(self.root);old_records=old_journal.records()
        self.git('switch','main')
        (self.root/'manual.txt').write_text('manual correction target',newline='\n')
        native.review(self.root,'changes',self.human('/oh-review changes'))
        result=self.finish_attempt('review',{'verdict':'blocking','summary':'Repair the manual behavior.',
            'findings':[{'severity':'blocking','family':'manual-repair','description':'The manual behavior is wrong.'}]})
        review_journal,feedback=load_run(self.root);receipt_records=review_journal.records()
        self.git('switch','-c','repair/manual-behavior')
        source=review.repair_source(self.root,feedback['id'])
        self.assertEqual(source['attempt'],result['id'])
        manifest=Path(self.temp.name)/'repairs.json'
        atomic_json(manifest,{'tasks':[{'id':'repair','title':'Repair the reviewed behavior',
                                     'instructions':'Fix the retained manual-repair finding and include the original changes.'}]})
        scope=prepared.prepare(self.root,manifest=manifest,review=feedback['id'])
        selected=native.approve_scope(self.root,scope['scope_id'],self.human())
        self.assertNotIn(selected['run'],(old['id'],feedback['id']))
        self.assertEqual(old_journal.records(),old_records)
        self.assertEqual(review_journal.records(),receipt_records)
        self.assertEqual(load_run(self.root)[1]['repair_source']['attempt'],result['id'])
        self.assertEqual((self.root/'manual.txt').read_text(),'manual correction target')
        (self.root/'manual.txt').write_text('Changed after feedback',newline='\n')
        with self.assertRaisesRegex(Refused,'reviewed work changed'):review.repair_source(self.root,feedback['id'])

    def test_plain_native_control_turns_need_no_internal_artifact_path(self):
        from .storage import now
        from datetime import datetime,timedelta
        self.approve();before=load_run(self.root)[1]
        home=Path(self.temp.name)/'host';sessions=home/'.codex/sessions';sessions.mkdir(parents=True)
        with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,{'CODEX_HOME':str(home/'.codex')}), \
                patch('oh.authority.native_human',side_effect=self.native_human_original):
            def direct(session,text):
                path=sessions/(session+'.jsonl');at=now()
                question_at=(datetime.fromisoformat(at)-timedelta(seconds=1)).isoformat()
                rows=[{'type':'session_meta','payload':{'id':session,'source':'cli','cwd':str(self.root)}},
                      {'type':'response_item','timestamp':question_at,'payload':{'type':'message','role':'assistant',
                       'content':[{'type':'output_text','text':'Resume '+native._saved_subject(before)+' on '+before['branch']+'?'}]}},
                      {'type':'event_msg','timestamp':at,'payload':{'type':'user_message','turn_id':'control','message':text}}]
                path.write_text(''.join(json.dumps(row)+'\n' for row in rows),newline='\n')
                return {'host':'codex','session':session,'turn':'control','prompt':text,'transcript_path':str(path)}
            native.decision(self.root,'pause',direct('s','/oh-pause'))
            native.decision(self.root,'stop',direct('s','Stop now'))
            self.assertEqual(native.resume(self.root)['status'],'stopped')
            native.resume(self.root,direct('fresh-parent','/oh-resume'))
            native.decision(self.root,'stop',direct('fresh-parent','/oh-stop'))
            self.assertEqual(native.resume(self.root)['status'],'stopped')
            native.resume(self.root,direct('fresh-parent','Resume the approved work.'))
            with self.assertRaises(Refused):
                native.decision(self.root,'stop',direct('fresh-parent','[$oh-stop](plugin://o-harness/skills/oh-stop/SKILL.md) unexpected args'))
            self.assertEqual(native.resume(self.root)['status'],'running')
            native.decision(self.root,'pause',direct('fresh-parent','/oh-pause'))
            native.resume(self.root,direct('fresh-parent','[$oh-resume](plugin://o-harness/skills/oh-resume/SKILL.md)'))
            native.decision(self.root,'pause',direct('fresh-parent','/oh-pause'))
            with self.assertRaises(Refused):native.resume(self.root,direct('fresh-parent','/oh-deliver'))
            with self.assertRaises(Refused):native.resume(self.root,direct('fresh-parent','/oh-deliver finish the same bounded change'),run=before['id'])
            native.resume(self.root,direct('fresh-parent','Resume'),run=before['id'])
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
            with self.assertRaises(Refused):native.resume(self.root,self.resume_choice(session='fresh-parent'))
            with self.assertRaises(Refused):native.admit(self.root,'assessment')
        self.assertEqual(legacy.records(),before)

    def test_explicit_continuation_transfers_running_work_and_fences_the_old_parent(self):
        from .storage import now
        self.approve();journal,before=load_run(self.root)
        home=Path(self.temp.name)/'host'
        question='Resume '+native._saved_subject(before)+' on '+before['branch']+'?'
        with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,{'CODEX_HOME':str(home/'.codex')}), \
                patch('oh.authority.native_human',side_effect=self.native_human_original), \
                patch('oh.authority.coordinator',side_effect=native_coordinator):
            previous=None
            for host in ('codex','claude'):
                session=host+'-new-parent'
                path=home/('.codex/sessions' if host=='codex' else '.claude/projects/p')/(session+'.jsonl')
                path.parent.mkdir(parents=True,exist_ok=True)
                prompt='/oh-deliver finish the same bounded work'
                entry={'host':host,'session':session,'turn':'entry','prompt':prompt,'transcript_path':str(path)}
                rows=([{'type':'session_meta','payload':{'id':session,'source':'cli','cwd':str(self.root)}},
                       {'type':'event_msg','timestamp':now(),'payload':{'type':'user_message','turn_id':'entry','message':prompt}}]
                      if host=='codex' else [{'type':'user','sessionId':session,'promptId':'entry','cwd':str(self.root),
                          'timestamp':now(),'message':{'role':'user','content':prompt}}])
                def save():path.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8',newline='\n')
                def choose(use,answer,shown=question):
                    if host=='codex':
                        replies=[{'questionItemId':json.dumps(['request_user_input_async',use,0]),'question':shown,'answer':answer}]
                        rows.extend([{'type':'response_item','timestamp':now(),'payload':{'type':'function_call','call_id':use,
                            'name':'request_user_input_async','arguments':json.dumps({'questions':[{'title':shown,'options':['Resume','Not now']}]})}},
                            {'type':'event_msg','timestamp':now(),'payload':{'type':'user_message','turn_id':use,
                            'message':'<send_user_message_question_reply>'+json.dumps(replies)+'</send_user_message_question_reply>'}}])
                    else:
                        rows.extend([{'type':'assistant','sessionId':session,'cwd':str(self.root),'timestamp':now(),'message':{'content':[
                            {'type':'tool_use','id':use,'name':'AskUserQuestion','input':{'questions':[{'question':shown,
                            'options':[{'label':'Resume'},{'label':'Not now'}]}]}}]}},
                            {'type':'user','sessionId':session,'cwd':str(self.root),'timestamp':now(),
                            'toolUseResult':{'answers':{shown:answer}},'message':{'content':[
                            {'type':'tool_result','tool_use_id':use,'content':'The user answered.'}]}}])
                    save()
                    return {'host':host,'session':session,'tool_use_id':use,'transcript_path':str(path)}
                save()
                env={'CODEX_THREAD_ID':session if host=='codex' else '', 'OH_NATIVE_SESSION_ID':session if host=='claude' else ''}
                with patch.dict(os.environ,env):
                    records=journal.records()
                    with self.assertRaisesRegex(Refused,'Ask whether to resume'):native.resume(self.root,entry,run=before['id'])
                    declined=choose('decline','Not now')
                    with self.assertRaises(Refused):native.resume(self.root,declined,run=before['id'])
                    unrelated=choose('unrelated','Resume',question.replace(before['branch'],'another-branch'))
                    with self.assertRaises(Refused):native.resume(self.root,unrelated,run=before['id'])
                    self.assertEqual(journal.records(),records)
                    locator=choose('confirm','Resume')
                    native.resume(self.root,locator,run=before['id'])
                    state=load_run(self.root)[1]
                    self.assertEqual((state['status'],state['human']['session']),('running',session))
                    self.assertEqual(state['granted'],before['granted']);self.assertEqual(state['config'],before['config'])
                    records=journal.records()
                    native.resume(self.root,locator,run=before['id'])
                    self.assertEqual(journal.records(),records)
                    if previous:
                        with self.assertRaisesRegex(Refused,'superseded'):native.resume(self.root,previous,run=before['id'])
                    admitted=native.admit(self.root,'assessment')
                    attempt=load_run(self.root)[1]['attempts'][-1]
                    self.assertEqual(attempt['parent'],{'host':host,'session':session,'transcript_path':str(path.resolve())})
                    with self.assertRaisesRegex(Refused,'current native attempt'):native.admit(self.root,'assessment')
                    from .authority import Saving
                    with patch('oh.authority.native_result',side_effect=Saving('Native result pending')),self.assertRaisesRegex(Refused,'tool guard'):
                        native.resume(self.root,choose('again','Resume'))
                    self.native_results[admitted['id']]={'text':'Interrupted assessment','status':'interrupted'}
                    native.retain(self.root,admitted['id'],{})
                with patch.dict(os.environ,{'CODEX_THREAD_ID':'superseded-parent','OH_NATIVE_SESSION_ID':''}):
                    with self.assertRaisesRegex(Refused,'superseded'):native.admit(self.root,'assessment')
                    with self.assertRaisesRegex(Refused,'superseded'):native.verify(self.root)
                previous=locator
        state=load_run(self.root)[1]
        self.assertEqual([a['parent']['host'] for a in state['attempts']],['codex','claude'])
        self.assertTrue(all(a['finished'] for a in state['attempts']))

    def test_checks_keep_human_controls_available_and_block_transfer_until_quiescent(self):
        self.approve();before=load_run(self.root)[1]
        different=native.prepare_scope(self.root,{'tasks':[self.tasks[0]|{'title':'Different work after checks'}]})
        continuation=self.resume_choice(session='fresh-parent')
        def checking(*args,**kwargs):
            with self.assertRaisesRegex(Refused,'still executing'):native.resume(self.root,continuation)
            with self.assertRaisesRegex(Refused,'still executing'):native.admit(self.root,'assessment')
            with self.assertRaisesRegex(Refused,'still executing'):native.review(self.root,'tree',self.human('/oh-review tree'))
            with self.assertRaisesRegex(Refused,'still executing'):native.approve_scope(self.root,different['scope_id'],self.human())
            native.decision(self.root,'pause',self.human('pause'))
            native.decision(self.root,'stop',self.human('stop'))
            self.assertEqual(native.resume(self.root)['status'],'stopped')
            return [{'name':'fixture','returncode':0}]
        with patch('oh.verification.verify',side_effect=checking):proof=native.verify(self.root)
        state=load_run(self.root)[1]
        self.assertEqual(state['status'],'stopped')
        self.assertEqual(state['human']['session'],before['human']['session'])
        self.assertEqual(state['verification']['1'],proof)
        # Stop remains until a later explicit continuation; discovery did not lift it.
        native.resume(self.root,self.resume_choice(session='fresh-parent'))
        self.assertEqual(load_run(self.root)[1]['human']['session'],'fresh-parent')
        self.assertEqual(load_run(self.root)[1]['granted'],before['granted'])

    def test_pause_stop_and_continuation_preserve_the_pending_phase_and_decision(self):
        self.approve();journal,before=load_run(self.root)
        publication={'choice':'pr','source':'original-publication','head':self.git('rev-parse','HEAD')}
        journal.append('decision',publication)
        for phase in ('pr','prepared_checkpoint','approval_checkpoint'):
            with self.subTest(phase=phase):
                journal.append('run.status',{'status':phase})
                if phase!='pr':journal.append('refinement.requested',{'feedback':'Keep the pending human refinement.'})
                native.decision(self.root,'pause',self.human('pause'))
                native.decision(self.root,'stop',self.human('stop'))
                native.saved_work(self.root);native.resume(self.root)
                self.assertEqual(load_run(self.root)[1]['status'],'stopped')
                native.resume(self.root,self.resume_choice(session='fresh-parent'))
                state=load_run(self.root)[1]
                self.assertEqual(state['status'],phase)
                self.assertEqual(state['publication'],publication)
                self.assertEqual(state['granted'],before['granted'])
                if phase!='pr':self.assertEqual(state['refinement']['feedback'],'Keep the pending human refinement.')
                with self.assertRaises(Refused):native.admit(self.root,'assessment')
        # A recoverable executor label grants nothing and must not strand approved work.
        for control in (None,'pause','stop'):
            with self.subTest(recoverable_control=control):
                journal.append('run.status',{'status':'needs_attention'})
                if control:native.decision(self.root,control,self.human(control))
                resumed=native.resume(self.root,self.resume_choice(session='fresh-parent'))
                self.assertEqual(resumed['status'],'running')
                self.assertEqual(resumed['granted'],before['granted'])
        # Requested review of a completed task is still pending work after a control.
        journal.append('task.completed',{'task':'1','commit':self.git('rev-parse','HEAD')})
        journal.append('review.requested',{'task':'1','return_status':'completed'})
        native.decision(self.root,'pause',self.human('pause'))
        resumed=native.resume(self.root,self.resume_choice(session='fresh-parent'))
        self.assertEqual(resumed['status'],'running')
        self.assertEqual(resumed['task']['id'],'1')
        self.assertEqual(load_run(self.root)[1]['extra_review']['task'],'1')

    def test_bound_author_can_finish_candidate_and_checks_after_pause(self):
        self.approve();self.assess()
        admitted=native.admit(self.root,'implementation')
        native.bind(self.root,admitted['id'],{'child_session':'active-author'})
        for caller in ('parent','other-child'):
            with patch.dict(os.environ,{'CODEX_THREAD_ID':caller}),self.assertRaisesRegex(Refused,'bound author'):
                native.verify(self.root)
        native.decision(self.root,'pause',self.human('pause'))
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'active-author'}):
            candidate=native.candidate(self.root)
            proof=native.verify(self.root)
        self.assertEqual(proof['tree'],candidate['tree'])
        self.assertEqual(load_run(self.root)[1]['status'],'paused')
        with self.assertRaises(Refused):native.admit(self.root,'review')
        self.native_results[admitted['id']]={'text':'Author finished its paused step.','status':'completed'}
        native.retain(self.root,admitted['id'],{})
        self.assertEqual(load_run(self.root)[1]['status'],'paused')

    def test_pause_after_review_fences_commit_and_resume_keeps_exact_review_and_allowance(self):
        self.approve();self.assess();self.implement();review=self.reviewed()
        before=load_run(self.root)[1];head=self.git('rev-parse','HEAD')
        native.decision(self.root,'pause',self.human('pause'))
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        native.resume(self.root,self.resume_choice(session='fresh-parent'))
        after=load_run(self.root)[1]
        self.assertEqual(after['granted'],before['granted'])
        self.assertEqual(after['attempts'],before['attempts'])
        native.complete(self.root,review['id'])
        self.assertEqual(load_run(self.root)[1]['done'],['1'])

    def test_edits_while_paused_cannot_borrow_the_previous_review(self):
        self.approve();self.assess();self.implement();review=self.reviewed()
        native.decision(self.root,'pause',self.human('pause'))
        (self.root/'output.txt').write_text('Retained authorized correction.',newline='\n')
        native.resume(self.root,self.resume_choice())
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        self.assertEqual((self.root/'output.txt').read_text(),'Retained authorized correction.')
        self.assertEqual(load_run(self.root)[1]['done'],[])
        self.assertEqual(native.resume(self.root)['reviews_used'],1)

    def test_discovery_and_selected_reads_preserve_both_bindings_and_live_work(self):
        from .storage import checkout_file, now
        from .config import change
        change(self.root,'review_rounds','1')
        self.approve()
        continuation=self.resume_choice(at=now())
        native.resume(self.root,continuation)
        journal,original=load_run(self.root)
        request=self.human('/oh-review tree',session='review-parent',at=now())
        feedback=native.review(self.root,'tree',request)
        feedback_journal,review_state=load_run(self.root)
        before={name:checkout_file(self.root,name).read_bytes() for name in ('oh-active-run.json','oh-active-review.json')}
        records=journal.records();review_records=feedback_journal.records()
        self.assertEqual({x['run'] for x in native.saved_work(self.root)['saved_work']},{original['id'],feedback['run']})
        self.assertEqual(native.resume(self.root,run=original['id'])['run'],original['id'])
        self.assertEqual(native.review(self.root,'tree',request)['run'],feedback['run'])
        with self.assertRaisesRegex(Refused,'superseded'):
            native.resume(self.root,continuation,run=original['id'])
        self.assertEqual(load_run(self.root)[1]['id'],feedback['run'])
        self.assertEqual(journal.records(),records);self.assertEqual(feedback_journal.records(),review_records)
        # An old approval must not steal a newer explicit work selection.
        prepared=native.prepare_scope(self.root,{'tasks':self.tasks[:1]})
        with self.assertRaises(Refused):
            native.approve_scope(self.root,prepared['scope_id'],original['human'])
        self.assertEqual({name:checkout_file(self.root,name).read_bytes() for name in before},before)
        # A failed binding write recovers with the same valid command, without
        # allowing an older command to steal a newer selection.
        selection=self.resume_choice(run=original['id'],at=now())
        bind_selection=native._resume_binding
        def interrupted_binding(root,state,*,write=False):
            if write:raise OSError('Interrupted active binding write')
            return bind_selection(root,state)
        with patch('oh.native._resume_binding',side_effect=interrupted_binding):
            with self.assertRaisesRegex(OSError,'Interrupted active binding'):
                native.resume(self.root,selection,run=original['id'])
        self.assertEqual(load_run(self.root)[1]['id'],feedback['run'])
        native.resume(self.root,selection,run=original['id'])
        self.assertEqual(load_run(self.root)[1]['id'],original['id'])
        self.assertEqual({x['run'] for x in native.saved_work(self.root)['saved_work']},{original['id'],feedback['run']})
        native.resume(self.root,self.resume_choice(run=feedback['run']),run=feedback['run'])
        self.assertEqual(load_run(self.root)[1]['id'],feedback['run'])
        admitted=native.admit(self.root,'review')
        records=journal.records()
        with self.assertRaisesRegex(Refused,'native attempt'):
            native.resume(self.root,self.resume_choice(run=original['id']),run=original['id'])
        self.assertEqual(journal.records(),records)
        pending=native.saved_work(self.root)['saved_work'][1]['pending_attempts'][0]
        self.assertEqual(pending['id'],admitted['id'])
        self.assertEqual((pending['binding_status'],pending['execution_status']),('unbound','not_checked'))
        self.assertIn('does not mean it was never launched',pending['next'])
        self.assertEqual(pending['request'],admitted['request'])
        attempt=load_run(self.root)[1]['attempts'][-1]
        self.assertEqual(pending['parent'],attempt['parent'])
        self.assertEqual(native.select(self.root)['continuation']['pending_attempts'][0],pending)
        self.assertEqual(journal.records(),records)
        native.bind(self.root,admitted['id'],{'child_session':'failed-reviewer'})
        bound=native.select(self.root)['continuation']['pending_attempts'][0]
        self.assertEqual((bound['native_child'],bound['binding_status'],bound['execution_status']),('failed-reviewer','bound','not_checked'))
        self.assertIn('does not mean it is still running',bound['next'])
        # A different current coordinator must not replace the admitted parent in hints.
        _,state=load_run(self.root)
        moved=state|{'host':'claude','human':{'session':'another-parent'}}
        self.assertEqual(native._continuation(moved)['pending_attempts'][0]['parent'],pending['parent'])
        from .storage import now
        retry=self.human('/oh-review tree',session='new-review-parent',at=now())
        self.native_results[admitted['id']]={'text':'','status':'failed'}
        native.retain(self.root,admitted['id'],{})
        self.assertTrue(native.saved_work(self.root)['saved_work'][1]['resumable'])
        discovered=native.review(self.root,'tree',retry)
        self.assertTrue(discovered['resume_required'])
        continued=native.resume(self.root,self.resume_choice(run=feedback['run'],session='new-review-parent'),run=feedback['run'])
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
        # Structured command identity supports discovery, never resume authority.
        for prompt in ('/oh-deliver 0001 code','[$oh-deliver](plugin://o-harness/skills/oh-deliver/SKILL.md) 0001 code'):
            self.assertEqual(native._command({'prompt':prompt}),('oh-deliver','0001 code'))
        legacy={'workflow':'design','design':None,'entry_human':{'prompt':'/oh-design auth'},'human':{'prompt':'Resume'}}
        self.assertEqual(native._initiative(legacy),'auth')
        from .config import change
        from .storage import encode
        change(self.root,'context.result_chars','1000')
        self.approve();journal,state=load_run(self.root);records=journal.records()
        self.assertLessEqual(len(encode(native.saved_work(self.root))),state['config']['context']['result_chars'])
        with self.assertRaises(Refused):native.resume(self.root,self.resume_choice(),run=identifier())
        self.assertEqual(journal.records(),records)

    def test_continuation_hints_use_the_requested_review_task_not_the_next_task(self):
        self.approve(self.tasks[:2])
        _,state=load_run(self.root)
        state.update(done=['1'],extra_review={'task':'1'},attempts=[{'id':'prior-review','task':'1','role':'review','finished':True,'outcome':'clean'}])
        hints=native._continuation(state)
        self.assertEqual(hints['phase'],'task_review')
        self.assertNotIn('next_action',hints)
        self.assertEqual(hints['latest_result']['id'],'prior-review')
        state['correction']={'task':'1'}
        self.assertEqual(native._continuation(state)['phase'],'task_correction')
        self.assertNotIn('next_action',native._continuation(state))
