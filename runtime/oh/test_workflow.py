import json
import io
import os
from .system import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from .config import load
from .authority import coordinator as native_coordinator
from .storage import Refused, atomic_json, identifier, Journal
from .workflow import load_run, reduce
from .telemetry import collect, connect, analytics, emit, usage_values
from .verification import tree, verify


from .test_fixtures_workflow import (
    EVIDENCE, NativeFixture, WorkflowFixture, configure, pull_request, task_context, write_settings,
)


class WorkflowTest(WorkflowFixture):
    def test_config_unknown_fields_fail_closed_and_no_false_zero(self):
        write_settings(self.root,{'taskz':10})
        with self.assertRaises(Refused):load(self.root)
        self.assertEqual(usage_values({}),{'input':None,'cached':None,'output':None,'reasoning':None})
        with self.assertRaises(Refused):usage_values({'input':10,'cached':11})

    def test_verification_cache_invalidates_actual_dependencies(self):
        (self.root/'value').write_text('one',newline='\n')
        # A version change outside the bounded tail must still invalidate reuse.
        probe=Path(self.temp.name)/'version.py'
        probe.write_text('print("first");print("v"*2000)',newline='\n')
        checks=[{'name':'read','command':[sys.executable,'-c','print("verified")'],'inputs':['value'],
                 'toolchain':[[sys.executable,str(probe)]]}]
        first=verify(self.root,checks,self.project_id)[0]
        self.assertFalse(first['reused'])
        reused=verify(self.root,checks,self.project_id)[0]
        self.assertTrue(reused['reused'])
        self.assertEqual(reused['logs'],first['logs'])
        from .storage import read_json
        self.assertIn('verified',Path(read_json(reused['logs'][-1])['stdout']['path']).read_text())
        probe.write_text('print("second");print("v"*2000)',newline='\n')
        self.assertFalse(verify(self.root,checks,self.project_id)[0]['reused'])
        (self.root/'value').write_text('two',newline='\n')
        self.assertFalse(verify(self.root,checks,self.project_id)[0]['reused'])

    def test_failed_checks_and_probes_retain_complete_bytes_with_bounded_feedback(self):
        # Windows process handles must preserve binary output for both checks and probes.
        import hashlib
        from .storage import read_json
        from .verification import check_failed,failure_summary
        stdout=b'AssertionError: ORIGINAL_CAUSE\n'+b'x'*20000+b'\xff\x00stdout-tail'
        stderr=b'ORIGINAL_STDERR\n'+b'e'*20000+b'stderr-tail'
        script=Path(self.temp.name)/'noisy.py'
        script.write_text('import sys\nsys.stdout.buffer.write('+repr(stdout)+')\nsys.stderr.buffer.write('+repr(stderr)+')\nsys.exit(3)\n',newline='\n')
        noisy=[sys.executable,str(script)]
        for probe in (False,True):
            with self.subTest(probe=probe):
                check={'name':'noisy','command':noisy}
                if probe:check.update(command=[sys.executable,'-c','raise AssertionError("must not run")'],toolchain=[noisy])
                result=verify(self.root,[check],self.project_id)[0]
                self.assertTrue(check_failed(result));self.assertEqual(result['returncode'],3)
                self.assertEqual(result.get('unavailable',False),probe)
                self.assertLessEqual(len(result['output']),12000)
                self.assertNotIn('ORIGINAL_CAUSE',result['output'])
                record=read_json(result['logs'][-1])
                self.assertEqual(record['command'],noisy)
                self.assertEqual(record['returncode'],3);self.assertIsNotNone(record['finished'])
                for name,expected in (('stdout',stdout),('stderr',stderr)):
                    stream=record[name];path=Path(stream['path'])
                    self.assertFalse(path.is_relative_to(self.root))
                    self.assertEqual(path.read_bytes(),expected)
                    self.assertEqual(stream['bytes'],len(expected))
                    self.assertEqual(stream['sha256'],hashlib.sha256(expected).hexdigest())
                summary=failure_summary([result],1000)
                self.assertLessEqual(len(summary),1000)
                self.assertIn(result['logs'][-1],summary)

    def test_dot_dependency_tracks_all_files_and_unknown_path_refused(self):
        check={'name':'all','command':['python3','-c','pass'],'inputs':['.'],'toolchain':[['python3','--version']]}
        self.assertFalse(verify(self.root,[check],self.project_id)[0]['reused'])
        self.assertTrue(verify(self.root,[check],self.project_id)[0]['reused'])
        (self.root/'changed').write_text('x',newline='\n')
        self.assertFalse(verify(self.root,[check],self.project_id)[0]['reused'])
        with self.assertRaises(Refused):verify(self.root,[check|{'inputs':['missing']}],self.project_id)

    def test_clean_filter_transformation_rejected_before_review(self):
        # Keep Git for Windows filter execution covered separately from CRLF conversion.
        from .verification import candidate_tree
        (self.root/'.gitattributes').write_bytes(b'*.dat filter=upper\n')
        self.git('config','filter.upper.clean','tr a-z A-Z')
        (self.root/'data.dat').write_bytes(b'lower\n')
        with self.assertRaisesRegex(Refused,'beyond line endings'):candidate_tree(self.root)

    def test_collection_is_idempotent_and_subsets_are_not_added_twice(self):
        run_id=identifier();attempt=identifier()
        emit('run.started',self.project_id,run_id,name='Fixture',work_kind='product',host='codex',version='v1',config_hash='c')
        emit('task.started',self.project_id,run_id,'1',title='Task',difficulty='standard',rubric=1)
        emit('attempt.started',self.project_id,run_id,'1',attempt,role='implementation',phase='implementation',host='codex',model='model',effort='medium')
        u={'response_id':'response','input':100,'cached':80,'output':20,'reasoning':10,'source':'test'}
        emit('usage',self.project_id,run_id,'1',attempt,**u);emit('usage',self.project_id,run_id,'1',attempt,**u)
        emit('task.finished',self.project_id,run_id,'1',status='completed',wall_ms=100)
        collect();self.assertEqual(collect(),0)
        with connect() as db:
            summary=analytics(db,{'from':'2000','to':'2100'})['summary']
        self.assertEqual(summary['input'],100);self.assertEqual(summary['tokens_per_completed'],120)
        self.assertEqual(summary['cached'],80);self.assertEqual(summary['reasoning'],10)


class NativeWorkflowTest(NativeFixture):
    def test_takeover_choice_stops_only_its_prepared_saved_work(self):
        from . import decisions,native
        from .storage import now
        self.approve()
        journal,original=load_run(self.root)
        note=self.root/'local.txt';note.write_text('Preserve this edit.\n',newline='\n')
        def answer(offer,prompt='Stop and take over',options=None):
            return self.human(prompt,decision=offer['decision'],question=offer['question'],question_at=now(),
                              question_options=offer['options'] if options is None else options,via='question')
        offer=decisions.prepare(self.root,'resume')
        self.assertEqual(offer['actions'],{'Resume saved work':'resume','Stop and take over':'stop'})
        for invalid in (answer(offer,'Not now'),answer(offer,'Yes'),answer(offer,options=['Resume saved work'])):
            with self.assertRaises(Refused):native.decision(self.root,'stop',invalid)
        for via in ('question','text'):
            unbound=answer(offer)|{'via':via}
            unbound.pop('decision')
            with self.assertRaisesRegex(Refused,'bound decision effect'):
                native.decision(self.root,'stop',unbound)
        with self.assertRaises(Refused):native.decision(self.root,'resume',answer(offer))
        native.decision(self.root,'pause',self.human('pause'))
        with self.assertRaisesRegex(Refused,'saved work changed'):native.decision(self.root,'stop',answer(offer))
        accepted=answer(decisions.prepare(self.root,'resume'))
        self.assertEqual(native.decision(self.root,'stop',accepted)['status'],'stopped')
        records=journal.records()
        self.assertEqual(native.decision(self.root,'stop',accepted)['status'],'stopped')
        self.assertEqual(journal.records(),records)
        self.assertEqual(load_run(self.root)[1]['granted'],original['granted'])
        self.assertEqual(note.read_text(),'Preserve this edit.\n')

        native.resume(self.root,self.resume_choice())
        legacy=self.human('Stop and take over')
        with patch('oh.native._affirmed',return_value=True):
            native.decision(self.root,'stop',legacy)
        records=journal.records()
        self.assertEqual(native.decision(self.root,'stop',legacy)['status'],'stopped')
        self.assertEqual(journal.records(),records)

        native.resume(self.root,self.resume_choice())
        repair=decisions.prepare(self.root,'approve-repair',repair='Repair the required fixture input.')
        with patch('oh.native._subject',side_effect=Refused('Candidate damaged after the question')):
            self.assertEqual(native.decision(self.root,'stop',answer(repair))['status'],'stopped')
        self.assertEqual(note.read_text(),'Preserve this edit.\n')

    def test_quick_fix_stop_binds_once_without_selecting_or_creating_a_run(self):
        from . import native
        from .storage import now
        from .workflow import active_file
        for prior in (None,'stopped'):
            if prior:
                self.approve()
                native.decision(self.root,'stop',self.human('stop'))
            active=active_file(self.root)
            selection=active.read_bytes() if active.exists() else None
            scope=native.prepare_scope(self.root,{'tasks':self.tasks[:1]})
            offer=scope['approval']
            earlier=self.offered_answer(offer,offer['options'][0],session='previous',at=now())
            answer=self.offered_answer(offer,'Stop and take over',via='text' if prior else 'question',at=now())
            before=[journal.records() for journal,_ in native._saved_runs(self.root)]
            with self.assertRaises(Refused):native.decision(self.root,'stop',answer|{'prompt':'Approve and fix'})
            conversation=answer.copy();conversation.pop('decision')
            resolved=(native.approve_scope(self.root,scope['scope_id'],conversation) if prior else
                      native.decision(self.root,'stop',conversation))
            self.assertEqual(resolved['status'],'declined')
            self.assertFalse(native.decision(self.root,'stop',answer)['approved'])
            with self.assertRaisesRegex(Refused,'later refusal'):
                native.approve_scope(self.root,scope['scope_id'],earlier)
            receipts=list((Path(scope['preview']).parent/'declines').glob('*.json'))
            self.assertEqual(len(receipts),1)
            self.assertEqual(json.loads(receipts[0].read_text())['decision'],offer['decision'])
            self.assertEqual([journal.records() for journal,_ in native._saved_runs(self.root)],before)
            self.assertEqual(active.read_bytes() if active.exists() else None,selection)
            self.assertEqual(self.git('status','--porcelain'),'')

        # A later genuine approval can enter. Stale scope-only Stop is not a run Stop.
        approved=self.offered_answer(offer,offer['options'][0],session='renewed',at=now())
        entered=native.approve_scope(self.root,scope['scope_id'],approved)
        journal,state=load_run(self.root);before=journal.records()
        self.assertEqual(entered['granted'],['1'])
        for stale in (answer,self.offered_answer(offer,'Stop and take over',session='other')):
            with self.assertRaisesRegex(Refused,'decision-request stop --run '+state['id']):
                native.decision(self.root,'stop',stale)
        self.assertEqual(journal.records(),before)
        self.assertEqual(native.approve_scope(self.root,scope['scope_id'],approved)['run'],entered['run'])

    def test_codex_plan_approval_binds_the_latest_native_plan_to_the_exact_scope(self):
        from datetime import datetime, timedelta
        from . import native
        from .workflow import active_file
        offer=native.prepare_scope(self.root,{'tasks':self.tasks[:1]})
        preview=Path(offer['preview']).read_text()
        self.assertIn(offer['scope_id'],preview)
        self.git('switch','-qc','other-scope')
        other=native.prepare_scope(self.root,{'tasks':self.tasks[:1]},keep_checkout=True)
        from .storage import read_json
        created=max(datetime.fromisoformat(read_json(Path(scope['preview']).with_name('scope.json'))['created_at'])
                    for scope in (offer,other))
        home=Path(self.temp.name)/'host';path=home/'.codex/sessions/native-plan.jsonl'
        path.parent.mkdir(parents=True)
        def save(text,*,mode='plan',intervening=False,accept_mode='default',displayed=True):
            at=created
            def row(kind,**payload):
                nonlocal at
                # The synthetic transcript must establish order on clocks with coarse resolution.
                at+=timedelta(milliseconds=1)
                return {'type':kind,'timestamp':at.isoformat(),'payload':payload}
            def user(turn,text):
                return row('event_msg',type='item_completed',turn_id=turn,
                           item={'type':'UserMessage','id':turn+'-input','content':[{'type':'text','text':text}]})
            def context(turn,mode):
                return row('turn_context',turn_id=turn,cwd=str(self.root),collaboration_mode={'mode':mode})
            rows=[row('session_meta',id='native-plan',cwd=str(self.root),source='cli'),
                  context('preview',mode),user('preview','Show the scope')]
            if displayed:rows.append(row('event_msg',type='item_completed',turn_id='preview',item={'type':'Plan','text':text}))
            if intervening:rows.append(user('refine','Revise the plan'))
            rows.extend([context('accept',accept_mode),user('accept','Implement the plan.')])
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
        human={'host':'codex','session':'native-plan','turn':'accept','transcript_path':str(path),'prompt':'Implement the plan.'}
        with patch.dict(os.environ,{'CODEX_HOME':str(home/'.codex'),'CODEX_THREAD_ID':'native-plan'}), \
                patch('oh.authority.native_human',side_effect=self.native_human_original), \
                patch('oh.authority.coordinator',side_effect=native_coordinator):
            for kwargs in ({'mode':'default'},{'intervening':True},{'accept_mode':'plan'},{'displayed':False}):
                save(preview,**kwargs)
                with self.assertRaises(Refused):native.approve_scope(self.root,offer['scope_id'],human)
                self.assertFalse(active_file(self.root).exists())
            save(preview+'\nExtra work.')
            with self.assertRaisesRegex(Refused,'accepted changed scope'):native.approve_scope(self.root,offer['scope_id'],human)
            self.assertFalse(active_file(self.root).exists())
            readable=Path(offer['preview'])
            readable.chmod(0o600)
            readable.write_text(preview+'\nExtra work.',newline='\n')
            with self.assertRaisesRegex(Refused,'accepted changed scope'):native.approve_scope(self.root,offer['scope_id'],human)
            self.assertFalse(active_file(self.root).exists())
            readable.write_text(preview,newline='\n')
            save(preview)
            with self.assertRaisesRegex(Refused,'accepted changed scope'):
                native.approve_scope(self.root,other['scope_id'],human)
            self.assertFalse(active_file(self.root).exists())
            self.git('switch','-q','work')
            result=native.approve_scope(self.root,offer['scope_id'],human)
            journal,state=load_run(self.root)
            self.assertEqual(state['accepted_scope'],preview)
            self.assertEqual(result['granted'],['1'])
            records=journal.records()
            self.assertEqual(native.approve_scope(self.root,offer['scope_id'],human)['run'],result['run'])
            self.assertEqual(journal.records(),records)

    def test_failed_verification_log_references_survive_journal_status_and_handoff(self):
        from . import native
        from .storage import read_json
        script=Path(self.temp.name)/'failed-check.py'
        script.write_text('import sys\nprint("original failure");print("x"*20000);sys.exit(1)\n',newline='\n')
        configure(self.root,checks=[{'name':'noisy','command':[sys.executable,str(script)]}])
        self.approve()
        proof=native.verify(self.root)
        checked=proof['checks'][0]
        self.assertEqual(load_run(self.root)[1]['verification']['1'],proof)
        selected=native.select(self.root)['verification']
        self.assertFalse(selected['passed'])
        self.assertEqual(selected['checks'][0]['logs'],checked['logs'])
        admitted=native.admit(self.root,'assessment')
        packet=read_json(admitted['task_context']['path'])
        self.assertEqual(packet['verification']['checks'][0]['logs'],checked['logs'])
        self.assertNotIn('output',packet['verification']['checks'][0])
        record=read_json(checked['logs'][0])
        self.assertIn('original failure',Path(record['stdout']['path']).read_text())

    def test_repair_approval_invalidates_readiness_without_replenishing_authority(self):
        from . import native,decisions,publication,handoff
        from .storage import now
        configure(self.root,review_rounds=1)
        self.approve();self.assess();self.implement();review=self.reviewed()
        def offer(text):return decisions.prepare(self.root,'approve-repair',repair=text)
        def answer(gate,**extra):
            return self.offered_answer(gate,extra.pop('prompt',gate['options'][0]),**extra)
        gate=offer('Repair the shared fixture without changing product behavior.')
        stale=offer('A different supporting repair.')
        # The prepared scope is exact, even when the product tree later returns to the same contents.
        (self.root/'unexpected.txt').write_text('later edit',newline='\n')
        with self.assertRaisesRegex(Refused,'subject changed'):native.decision(self.root,'approve-repair',answer(gate))
        (self.root/'unexpected.txt').unlink()
        with self.assertRaises(Refused):native.decision(self.root,'approve-repair',answer(gate,prompt='Not now'))
        accepted=answer(gate)
        native.decision(self.root,'approve-repair',accepted)
        journal,state=load_run(self.root)
        self.assertTrue(state['attempts'][-1]['superseded'])
        self.assertFalse(handoff.confirms_repairs(state,state['attempts'][-1]))
        self.assertNotIn('1',state.get('verification',{}))
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        with self.assertRaisesRegex(Refused,'superseded'):
            publication.task_evidence(self.root,state,state['tasks'][0],state['attempts'][-1],review['head'])
        with self.assertRaisesRegex(Refused,'subject changed'):native.decision(self.root,'approve-repair',answer(stale))
        newer=offer('Another supporting repair with separate approval.')
        reused=answer(newer);reused['turn']=accepted['turn']
        with self.assertRaisesRegex(Refused,'already used'):native.decision(self.root,'approve-repair',reused)
        with self.assertRaisesRegex(Refused,'Finish the approved task'):native.admit(self.root,'review')
        self.implement(edit=lambda:None);native.candidate(self.root);native.verify(self.root)
        with self.assertRaisesRegex(Refused,'allowance is spent'):native.admit(self.root,'review')
        self.assertEqual(sum(a['role']=='review' for a in load_run(self.root)[1]['attempts']),1)

    def test_scope_needs_native_approval_and_preserves_its_immutable_task_window(self):
        from . import native
        from .storage import digest, now, read_json
        from .workflow import active_file
        configure(self.root,tasks_per_batch=1)
        original=self.root/'manual.txt';original.write_text('Included original work.',newline='\n')
        prepared=native.prepare_scope(self.root,{'tasks':self.tasks[:2]})
        self.assertFalse(active_file(self.root).exists())
        self.assertIn('manual.txt',Path(prepared['preview']).read_text())
        original.write_text('Changed since the preview.',newline='\n')
        unrelated=self.root/'unrelated.txt';unrelated.write_text('New work.',newline='\n')
        with self.assertRaisesRegex(Refused,'starting contents changed'):
            native.approve_scope(self.root,prepared['scope_id'],self.human())
        self.assertEqual(unrelated.read_text(),'New work.')
        # An initiating human locator identifies the request, not scope approval.
        # It must return the same bindable question as preparation without one.
        prepared=native.prepare_scope(self.root,{'tasks':self.tasks[:2]},
                                      human=self.human('Fix the bounded fixture tasks.'))
        self.assertFalse(prepared['approved'])
        self.assertFalse(active_file(self.root).exists())
        self.assertIn('approval',prepared)
        self.assertIn(prepared['approval']['decision'],'\n'.join(json.dumps(prepared,indent=2).splitlines()[:60]))
        self.assertEqual(prepared['approval']['options'],['Approve 2 tasks · '+self.tasks[0]['title'],'Stop and take over'])
        with self.assertRaisesRegex(Refused,'named action'):
            native.approve_scope(self.root,prepared['scope_id'],self.offered_answer(prepared['approval'],'Investigate CI failures'))
        refused=self.offered_answer(prepared['approval'],'Stop and take over')
        key=refused.pop('decision')
        result=native.approve_scope(self.root,prepared['scope_id'],refused,after=key)
        self.assertEqual((result['status'],result['approved']),('declined',False))
        self.assertFalse(active_file(self.root).exists())
        without_identity=self.offered_answer(prepared['approval'],'approve',via='text')
        without_identity.pop('decision')
        with self.assertRaisesRegex(Refused,'original prepared scope decision'):
            native.approve_scope(self.root,prepared['scope_id'],without_identity)
        other=native.prepare_scope(self.root,{'tasks':[self.tasks[0]|{'instructions':'Different scope.'},self.tasks[1]]})
        folder=native._home(self.root)/'decisions'
        historical=read_json(folder/(other['approval']['decision']+'.json'))
        historical.pop('disclosure')
        historical.pop('menu_version',None)
        historical['question']='Approve the previously prepared scope?'
        key=digest(historical)
        native._immutable(folder/(key+'.json'),historical)
        with self.assertRaisesRegex(Refused,'does not approve the presented scope'):
            native.approve_scope(self.root,other['scope_id'],
                                 self.human('Approve this scope',question=prepared['approval']['question'],question_at=now(),decision=key))
        self.assertFalse(active_file(self.root).exists())
        for text in ('Discuss the change.','stop','publish','Do not approve this scope.',
                     'Do not approve this scope; revise it.','Approve neither this scope nor publication.'):
            with self.subTest(text=text),self.assertRaises(Refused):
                native.approve_scope(self.root,prepared['scope_id'],self.human(text))
        # An unused preview left by an older plugin is historical evidence, not occupied execution.
        from .storage import checkout_file, checkout_id
        scope=json.loads(Path(prepared['preview']).with_name('scope.json').read_text())
        unused=Journal(self.project_id,identifier())
        unused.append('run.started',{'id':unused.path.name,'project':self.project_id,'name':'Fixture','work_kind':'product',
            'host':'codex','human':{'host':'codex','session':'older-session','turn':'old','prompt':'Prepare the older idea.'},
            'source':'older-native-input','checkout':checkout_id(self.root),'workflow':'deliver',
            'branch':'work','base':self.git('rev-parse','HEAD'),'tasks':[self.tasks[0]],'checks':[],
            **{key:scope[key] for key in ('config','config_hash','harness_version','project_checks')}})
        unused.append('run.status',{'status':'prepared_checkpoint'});prior=unused.records()
        atomic_json(checkout_file(self.root,'oh-active-run.json'),
                    {'project':self.project_id,'run':unused.path.name,'checkout':checkout_id(self.root)})
        approval=prepared['approval']
        native.approve_scope(self.root,prepared['scope_id'],self.offered_answer(approval,approval['options'][0],session='fresh-parent'))
        journal,state=load_run(self.root);original=journal.records()
        self.assertEqual(read_json(journal.path/'scope'/'approval.json')['decision'],approval['decision'])
        self.assertEqual(state['granted'],['1'])
        self.assertNotEqual(state['id'],unused.path.name)
        self.assertEqual(unused.records()[:len(prior)],prior)
        self.assertEqual((reduce(unused.records())['status'],reduce(unused.records())['granted']),('stopped',[]))
        newer=native.prepare_scope(self.root,{'tasks':[self.tasks[0]|{'instructions':'A different fresh scope.'}]})
        with self.assertRaises(Refused):native.approve_scope(self.root,newer['scope_id'],state['human'])
        self.assertEqual(journal.records(),original)
        configure(self.root,tasks_per_batch=4,review_rounds=9)
        self.assertEqual(native.resume(self.root)['granted'],['1'])
        self.assertEqual(load_run(self.root)[1]['config'],state['config'])
        native.approve_scope(self.root,prepared['scope_id'],self.human('Approve'))
        self.assertEqual(journal.records(),original)
        (self.root/'manual.txt').write_text('Authorized implementation after activation.',newline='\n')
        native.approve_scope(self.root,prepared['scope_id'],state['human'])
        self.assertEqual(journal.records(),original)
        path=Path(prepared['preview']).with_name('scope.json');value=json.loads(path.read_text())
        value['tasks'][0]['instructions']='Unapproved expansion';path.write_text(json.dumps(value),newline='\n')
        with self.assertRaises(Refused):native.approve_scope(self.root,prepared['scope_id'],self.human())

    def test_native_admissions_are_sequential_fresh_and_use_explicit_profiles(self):
        from . import native
        configure(self.root,models={'codex':{'standard':{'model':'gpt-6.11-sol','effort':'high'}}},context={'handoff_chars':1000})
        instructions='Implement only the approved bounded behavior and retain its acceptance proof.\n'*400
        title=('Long approved task title '*50)[:1200]
        self.approve([self.tasks[0]|{'title':title,'instructions':instructions},*self.tasks[1:4]])
        with self.assertRaises(Refused):native.admit(self.root,'implementation')
        admission=native.admit(self.root,'assessment')
        self.assertEqual(admission['fork_turns'],'none');self.assertTrue(admission['fresh_context'])
        self.assertEqual(admission['profile'],{'model':'gpt-6.1-sol','effort':'high'})
        self.assertEqual(load_run(self.root)[1]['config']['models']['codex']['standard']['model'],'gpt-6.11-sol')
        self.assertIn('gpt-6.11-sol',json.dumps(admission))
        packet_path=Path(admission['task_context']['path']);packet=json.loads(packet_path.read_text())
        self.assertLessEqual(len(packet_path.read_text()),load_run(self.root)[1]['config']['context']['handoff_chars'])
        details=json.loads((packet_path.parent/packet['details']['path']).read_text())
        self.assertEqual(admission['admission_command'],details['native_commands']['admission'])
        self.assertEqual(details['task']['instructions'],instructions)
        self.assertEqual(details['task']['title'],title)
        self.assertEqual(details['scope_snapshot']['hash'],load_run(self.root)[1]['scope_id'])
        self.assertTrue((packet_path.parent/packet['findings']['path']).is_file())
        from .receipts import request
        saved_admission=json.loads(Path(admission['request']).read_text())
        request(Path(admission['request']).parent,saved_admission)
        self.assertIn(instructions,(Path(admission['request']).with_name('request.md')).read_text())
        with self.assertRaises(Refused):native.admit(self.root,'review')
        native.bind(self.root,admission['id'],{'child_session':'first-child'})
        self.native_results[admission['id']]={'text':json.dumps({'difficulty':'standard','rationale':'Contained.'}),'status':'completed'}
        retained=native.retain(self.root,admission['id'],{})
        journal,settled=load_run(self.root);records=journal.records()
        with patch('oh.authority.native_result',side_effect=AssertionError('Completed assessment must be reused')):
            self.assertEqual(native.retain(self.root,admission['id'],{})['outcome'],retained['outcome'])
        self.assertEqual(journal.records(),records)
        self.assertEqual(len(settled['attempts']),1);self.assertEqual(settled['assessments']['1']['difficulty'],'standard')
        with self.assertRaises(Refused):native.bind(self.root,admission['id'],{'child_session':'first-child'})
        implement=native.admit(self.root,'implementation')
        with self.assertRaises(Refused):native.bind(self.root,implement['id'],{'child_session':'first-child'})
        self.assertEqual(load_run(self.root)[1]['attempts'][-1]['id'],implement['id'])
        native.candidate(self.root)
        self.assertEqual(load_run(self.root)[1]['attempts'][-1]['native_child']['child_session'],'child-'+implement['id'])

    def test_blocked_assessment_does_not_select_an_implementation_profile(self):
        from . import native
        self.approve()
        before = load_run(self.root)[1]['granted']
        for status in ('blocked', 'unfinished'):
            result = self.finish_attempt('assessment', {'status': status, 'difficulty': 'complex',
                'summary': 'Source inspection failed because the native hook could not run.'})
            self.assertEqual(result['outcome'], status)
            self.assertFalse(load_run(self.root)[1].get('assessments'))
            with self.assertRaisesRegex(Refused, 'Retain one native assessment'):
                native.admit(self.root, 'implementation')
        # Infrastructure recovery keeps the original task authority and failed attempts.
        self.assess()
        state = load_run(self.root)[1]
        self.assertEqual(state['granted'], before)
        self.assertEqual([a['outcome'] for a in state['attempts']], ['blocked', 'unfinished', 'assessed'])
        self.assertEqual(native.admit(self.root, 'implementation')['profile'],
                         state['config']['models']['codex']['standard'])

    def test_blocked_resume_retains_parent_evidence_and_does_not_spend_review_allowance(self):
        from . import native
        self.approve();self.assess()
        measurement=Path(self.temp.name)/'measurement.txt';measurement.write_text('Required service denied access.\n',newline='\n')
        source=self.root/'product.txt'
        attached=native.attach_evidence(self.root,{'paths':[str(measurement),str(source)],'summary':'Observed required input failure.'})
        reason='Restore access to the service, then finish preview/save binding.'
        blocked=self.implement({'status':'blocked','summary':reason},lambda:(self.root/'partial.txt').write_text('keep this work',newline='\n'))
        initial=load_run(self.root)[1]
        self.assertEqual(blocked['outcome'],'blocked')
        with self.assertRaises(Refused):native.admit(self.root,'review')
        facts=native.resume(self.root)
        self.assertEqual(facts['reviews_used'],0);self.assertEqual(facts['granted'],initial['granted'])
        source.write_text('Supporting repair before fresh admission.\n',newline='\n')
        resumed=native.admit(self.root,'implementation')
        packet=json.loads(Path(resumed['task_context']['path']).read_text())
        self.assertEqual(packet['current_work']['summary'],reason)
        self.assertEqual(packet['current_work']['outcome'],'blocked')
        attachment=next(e for e in packet['supplementary_evidence'] if str(measurement.resolve()) in e['files'])
        self.assertEqual(attachment['files'][str(measurement.resolve())],
                         __import__('hashlib').sha256(measurement.read_bytes()).hexdigest())
        self.assertEqual(attachment['file_status'],
                         {str(measurement.resolve()):'unchanged',str(source.resolve()):'changed'})
        self.assertEqual((self.root/'partial.txt').read_text(),'keep this work')
        self.assertNotIn('recovery_grants',load_run(self.root)[1])
        # Repairs after admission and expired diagnostic logs must not poison
        # retention or the next review, including references saved by older OH.
        source.write_text('Supporting repair completed.\n',newline='\n');measurement.unlink()
        native.bind(self.root,resumed['id'],{'child_session':'child-'+resumed['id']})
        self.native_results[resumed['id']]={'status':'completed','text':'Implemented the repair.'}
        self.assertEqual(native.retain(self.root,resumed['id'],{})['outcome'],'reported')
        self.assertEqual([e for e in load_run(self.root)[1]['supplementary'] if e.get('files')==attached['files']],[attached])
        with self.assertRaises(Refused):native.admit(self.root,'review')  # Checks still required.
        review=self.reviewed()
        review_packet=json.loads((Path(review['evidence'])/'task-context.json').read_text())
        attachment=next(e for e in review_packet['supplementary_evidence'] if str(measurement.resolve()) in e['files'])
        self.assertEqual(attachment['file_status'],
                         {str(measurement.resolve()):'unavailable',str(source.resolve()):'changed'})
        self.assertEqual(review['outcome'],'clean')
        native.complete(self.root,review['id'])
        self.assertEqual(load_run(self.root)[1]['done'],['1'])
        self.assertEqual([e for e in load_run(self.root)[1]['supplementary'] if e.get('files')==attached['files']],[attached])

    def test_review_requires_completed_work_and_passing_checks_for_the_final_candidate(self):
        from . import native
        configure(self.root,review_rounds=3)
        self.approve();self.assess();self.implement({'status':'unfinished','summary':'Finish the final assertion.'})
        native.candidate(self.root);native.verify(self.root)
        with self.assertRaises(Refused):native.admit(self.root,'review')
        self.implement();native.candidate(self.root)
        cancelled={'name':'fixture','command':['fixture'],'returncode':0,'cancellation':['timeout'],'duration_ms':1}
        with patch('oh.verification.verify',return_value=[cancelled]):native.verify(self.root)
        with self.assertRaises(Refused):native.admit(self.root,'review')
        native.verify(self.root)
        (self.root/'output.txt').write_text('changed after verification',newline='\n')
        with self.assertRaises(Refused):native.admit(self.root,'review')
        native.verify(self.root)
        from . import handoff
        saved_write=handoff.atomic_json;before=load_run(self.root)[1]
        def failed_packet(path,value,**kwargs):
            if Path(path).name=='task-context.json':raise OSError('Simulated packet write failure before native launch.')
            return saved_write(path,value,**kwargs)
        with patch('oh.handoff.atomic_json',side_effect=failed_packet),self.assertRaises(OSError):
            native.admit(self.root,'review')
        self.assertEqual(load_run(self.root)[1]['attempts'],before['attempts'])
        self.assertEqual(native.resume(self.root)['reviews_used'],0)
        failed=native.admit(self.root,'review')
        self.native_results[failed['id']]={'text':'Native spawn failed before returning a child identity.','status':'failed'}
        self.assertEqual(native.retain(self.root,failed['id'],{'tool_use_id':'failed-native-spawn'})['outcome'],'failed')
        self.assertEqual(native.resume(self.root)['reviews_used'],1)
        rejected=native.admit(self.root,'review')
        self.native_results[rejected['id']]={'text':'Terminal child used a different actual profile.','status':'binding_failed',
            'profile':{'model':'actual-other','effort':'low'},'native_id':'rejected-child','admitted_profile':rejected['profile'],
            'terminal_status':'interrupted','binding_issues':['Actual profile differs from admission.']}
        retained=native.retain(self.root,rejected['id'],{'tool_use_id':'successful-rejected-spawn','child_session':'rejected-child'})
        self.assertEqual(retained['outcome'],'binding_failed')
        self.assertEqual(retained['native_failure']['terminal_status'],'interrupted')
        self.assertEqual(retained['native_failure']['profile'],{'model':'actual-other','effort':'low'})
        self.assertIn('actual-other / low',(Path(retained['evidence'])/'review.md').read_text())
        self.assertEqual(native.resume(self.root)['reviews_used'],2)
        before=load_run(self.root)[1]
        native.retain(self.root,rejected['id'],{'tool_use_id':'successful-rejected-spawn','child_session':'rejected-child'})
        after=load_run(self.root)[1]
        for key in ('attempts','config','scope_id','granted','decisions'):
            self.assertEqual(after[key],before[key])
        with self.assertRaises(Refused):native.complete(self.root,rejected['id'])
        review=self.finish_attempt('review',{'verdict':'clean','summary':'Checked.','findings':[]})
        (self.root/'output.txt').write_text('changed after review',newline='\n')
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        self.assertEqual(load_run(self.root)[1]['done'],[])

    def test_reviewer_mutation_preserves_the_report_without_authorizing_completion(self):
        from . import native
        self.approve();self.assess();self.implement();native.candidate(self.root);native.verify(self.root)
        review=self.finish_attempt('review',{'verdict':'clean','summary':'Claimed clean.','findings':[]},
                                   edit=lambda:(self.root/'surprise').write_text('reviewer edit',newline='\n'))
        self.assertEqual(review['outcome'],'binding_failed')
        self.assertTrue((Path(review['evidence'])/'native-result.json').is_file())
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        self.assertEqual(load_run(self.root)[1]['done'],[])

    def test_review_attempts_and_findings_survive_repairs_and_spent_window(self):
        from . import native
        from .handoff import finding_index
        configure(self.root,review_rounds=2)
        self.approve();self.assess();self.implement()
        finding={'severity':'blocking','description':'Timeout still leaks its session.','path':'output.txt','family':'session-leak','relation':'original'}
        scope={'severity':'scope','description':'Logout cleanup belongs to later work.','path':'logout.py','family':'logout','relation':'original'}
        original_report=json.dumps({'verdict':'blocking','findings':[finding,scope],'summary':'The legacy JSON receipt explains both findings.'})
        first=self.reviewed(original_report)
        self.assertEqual(first['findings'],[finding,scope])
        with self.assertRaises(Refused):native.complete(self.root,first['id'])
        repaired=self.implement()
        self.assertEqual(repaired['profile'],load_run(self.root)[1]['config']['models']['codex']['standard'])
        second=self.reviewed('OH-REVIEW-DECISION: '+json.dumps({'verdict':'findings','findings':[dict(finding,relation=None)]})+'\nDifferent receipt layout and optional null metadata; same independently observed session leak.')
        self.assertNotIn('report_issues',second)
        # Failed bindings and non-concluding attempts retain findings for audit, but
        # neither two invalid reports nor one valid plus one invalid report can escalate.
        for outcome in ('binding_failed','failed','interrupted','review_incomplete'):
            invalid=second|{'finished':True,'outcome':outcome}
            with self.subTest(outcome=outcome):
                self.assertFalse(native._repeated_family({'attempts':[first|{'finished':True},invalid]},'1'))
                self.assertFalse(native._repeated_family({'attempts':[invalid,invalid|{'id':'another-attempt'}]},'1'))
        repair=native.admit(self.root,'implementation')
        state=load_run(self.root)[1]
        self.assertEqual(repair['profile'],state['config']['models']['codex']['complex'])
        # The launch guard refuses the copied earlier profile before any child starts, on
        # either host, and lets the escalated admission through unchanged.
        from .config import HOME
        guard=HOME/'plugins/o-harness/scripts/agent-launch.py'
        def launch(host,profile,reference=None,**extra):
            prompt=f'Repair OH attempt {repair["id"]}. Request: {reference or repair["request"]}'
            arguments=({'task_name':repair['native_task_name'],'fork_turns':'none','message':prompt,
                        'model':profile['model'],'reasoning_effort':profile['effort']} if host=='codex' else
                       {'subagent_type':'o-harness:implementation','prompt':prompt,'model':profile['model'],'effort':profile['effort']})
            said=subprocess.run([sys.executable,'-I',str(guard),host],input=json.dumps({'tool_name':'Agent','tool_input':arguments|extra}),
                                capture_output=True,text=True,check=True).stdout
            return json.loads(said)['hookSpecificOutput'] if said else None
        for host in ('codex','claude'):
            refused=launch(host,repaired['profile'])
            self.assertEqual(refused['permissionDecision'],'deny')
            self.assertIn(repair['profile']['model'],refused['permissionDecisionReason'])
            self.assertIsNone(launch(host,repair['profile']))
        spaced=Path(self.temp.name)/'native requests with spaces'/'attempts'/repair['id']/'request.json'
        spaced.parent.mkdir(parents=True)
        spaced.write_bytes(Path(repair['request']).read_bytes())
        for host in ('codex','claude'):
            for reference in (str(spaced),f'"{spaced}"',f'`{spaced}`'):
                with self.subTest(host=host,reference=reference):
                    self.assertEqual(launch(host,repaired['profile'],reference)['permissionDecision'],'deny')
                    self.assertIsNone(launch(host,repair['profile'],reference))
        self.assertEqual(launch('codex',repair['profile'],fork_turns='all')['permissionDecision'],'deny')
        historical={'attempts':[dict(a,findings=[dict({k:v for k,v in f.items() if k!='family_id'},family='session-leak. Relation: '+str(f.get('relation') or 'original')+'.') for f in a.get('findings',[])]) for a in state['attempts']]}
        self.assertTrue(native._repeated_family(historical,'1'))
        native.bind(self.root,repair['id'],{})
        self.native_results[repair['id']]={'text':json.dumps({'status':'completed','summary':'Closed the family.'}),'status':'completed'}
        native.retain(self.root,repair['id'],{});native.candidate(self.root);native.verify(self.root)
        with self.assertRaises(Refused):native.admit(self.root,'review')
        before=native.resume(self.root)
        self.assertEqual((before['reviews_used'],before['reviews_allowed']),(2,2))
        for text in ('Discuss the findings.','Do not grant another review window.'):
            with self.assertRaises(Refused):native.decision(self.root,'grant-review',self.human(text))
        from .decisions import prepare as decision_request,verify as verify_decision
        from .storage import now
        # Renewal uses the run's snapshot, not a later project setting or an
        # agent's prediction that one more round will suffice. Explicit one-round
        # requests still bind exactly one, on either host.
        configure(self.root,review_rounds=9)
        default_offer=decision_request(self.root,'grant-review')
        self.assertEqual(native.resume(self.root)['reviews_allowed'],2)
        offer=decision_request(self.root,'grant-review',rounds=1,also='create an issue for the retained follow-up')
        home=Path(self.temp.name)/'native-home'
        # Exercise the same effect binding through actual saved Claude and Codex answers.
        # Host provenance is real here; only author/reviewer execution is synthetic.
        with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,{'CODEX_HOME':str(home/'.codex')}):
            repair_offer=decision_request(self.root,'approve-repair',repair='Repair the additional shared fixture without changing assertions.')
            for kind,field,expected,offered in (('approve-repair','repair','Repair the additional shared fixture without changing assertions.',repair_offer),
                                               ('grant-review','rounds',2,default_offer),('grant-review','rounds',1,offer)):
                for host in ('claude','codex'):
                    call_at=now();answer_at=now();question=offered['question'].replace('Work:','**Work:**').replace('Branch:','**Branch:**');label=offered['options'][0]
                    if kind=='approve-repair':question+=' '+expected
                    if host=='claude':
                        path=home/'.claude/projects/s.jsonl'
                        common={'sessionId':'s','cwd':str(self.root)}
                        rows=[common|{'type':'assistant','timestamp':call_at,'message':{'content':[{'type':'tool_use','id':'grant','name':'AskUserQuestion','input':{'questions':[{'question':question,'options':[*({'label':choice} for choice in offered['options'])]}]}}]}},
                              common|{'type':'user','timestamp':answer_at,'toolUseResult':{'answers':{question:label}},'message':{'content':[{'type':'tool_result','tool_use_id':'grant','content':'The user answered.'}]}}]
                    else:
                        path=home/'.codex/sessions/s.jsonl'
                        reply='<send_user_message_question_reply>'+json.dumps([{'questionItemId':json.dumps(['request_user_input_async','grant',0]),'answer':label}])+'</send_user_message_question_reply>'
                        rows=[{'type':'session_meta','payload':{'id':'s','cwd':str(self.root),'source':'vscode'}},
                              {'type':'response_item','timestamp':call_at,'payload':{'type':'function_call','name':'request_user_input_async','call_id':'grant','arguments':json.dumps({'questions':[{'title':question,'options':offered['options']}]})}},
                              {'type':'event_msg','timestamp':answer_at,'payload':{'type':'user_message','thread_id':'s','turn_id':'grant-reply','message':reply}}]
                    rows.insert(0 if host=='claude' else 1,self.offer_record(host,'s',offered,call_at))
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8',newline='\n')
                    locator={'host':host,'session':'s','tool_use_id':'grant','transcript_path':str(path),'decision':offered['decision']}
                    source=self.native_human_original(self.root,locator)
                    self.assertNotIn('result.json',source['question'])
                    self.assertEqual(verify_decision(self.root,load_run(self.root)[1],kind,locator,source)[field],expected)
                    for invalid in ('Not now','Do not allow another review.'):
                        with self.assertRaises(Refused):verify_decision(self.root,load_run(self.root)[1],kind,locator,source|{'prompt':invalid})
                    with self.assertRaises(Refused):verify_decision(self.root,load_run(self.root)[1],kind,locator,source|{'question_at':'2000-01-01T00:00:00Z'})
                    for path_hint in ({'transcript_path':str(path)},{}):
                        hooked={'host':host,'session':'s','turn':'unsaved-hook-turn','decision':offered['decision'],**path_hint}
                        with patch('oh.authority.native_human',side_effect=self.native_human_original):
                            self.assertEqual(native._presented(self.root,hooked,load_run(self.root)[1])['tool_use_id'],'grant')
            # The hook's conversation locator plus the decision identity is enough: OH finds
            # the question that showed it, even when the copied turn was never saved.
            hook={'host':'codex','session':'s','turn':'unsaved-hook-turn','transcript_path':str(path),'decision':offer['decision']}
            with patch('oh.authority.native_human',side_effect=self.native_human_original):
                with self.assertRaises(Refused):native.decision(self.root,'continue',locator)
                native.decision(self.root,'grant-review',hook)
                native.decision(self.root,'grant-review',hook)
        self.assertEqual(native.resume(self.root)['reviews_allowed'],3)
        journal,state=load_run(self.root)
        grant=state['review_grants'][-1]
        proof=json.loads((journal.path/'decisions'/(grant['source']+'.json')).read_text())
        self.assertEqual(proof['prepared']['rounds'],1)
        self.assertEqual(proof['human']['prompt'],offer['options'][0])
        clean=self.finish_attempt('review','OH-REVIEW-DECISION: '+json.dumps({'verdict':'clean','findings':[]})+'\nIndependently checked repairs. An illustrative [BLOCKING] label in prose is not another finding.')
        from .publication import task_evidence
        state=load_run(self.root)[1]
        task_evidence(self.root,state,state['tasks'][0],clean,clean['head'])  # An older unrelated finding no longer blocks completion.
        native.decision(self.root,'route-scope',self.human('Route scope'),attempt=first['id'],
                        destination={'issue':'https://github.com/example/product/issues/20'})
        with self.assertRaises(Refused):
            native.decision(self.root,'accept-concerns',self.human('Accept concerns'),attempt=first['id'])
        families=finding_index(load_run(self.root)[1],'1')['families']
        self.assertEqual(len(families[0]['occurrences']),2)
        self.assertEqual(len(families[0]['cases']),1)  # legacy and new decisions describe the same failure
        self.assertTrue(all(item['reviewed_by']==clean['id'] for item in families[0]['occurrences']))
        self.assertEqual(json.loads((Path(first['evidence'])/'native-result.json').read_text())['text'],original_report)
        self.assertEqual(families[1]['occurrences'][0]['disposition'],'routed')
        native.complete(self.root,clean['id'])

    def test_historical_reports_reach_fresh_review_without_becoming_readiness_gates(self):
        from . import native,authority,handoff,publication
        from .scope import followups
        from .storage import read_json
        self.approve();self.assess();self.implement()
        findings=[{'severity':severity,'family':severity,'description':'Original '+severity} for severity in ('blocking','concern','scope')]
        historical={'text':json.dumps({'verdict':'findings','findings':findings}),'status':'completed',
                    'record_hashes':['authenticated-report'],'request':'handback','at':'2026-10-01T00:00:00Z'}
        with patch.object(authority,'native_diagnostics',side_effect=lambda root,state,attempt:[historical] if attempt['role']=='review' else []):
            old=self.reviewed()
        self.assertEqual(old['outcome'],'unfinished')
        self.assertEqual(old['findings'],[]);self.assertNotIn('finding_sources',old)
        journal,state=load_run(self.root)
        original=next(item for item in handoff.finding_index(state,'1')['diagnostics'] if item['findings'])
        self.assertEqual([f['position'] for f in original['findings']],[1,2,3])
        self.assertEqual(original['status'],'available')
        self.assertEqual(read_json(original['report']['path'])['source'],historical)
        # Optional archive loss/alteration must preserve the saved claim and hash,
        # not strand a fresh reviewer or relabel the changed bytes as trusted.
        path=Path(original['report']['path']);path.write_text('{}',newline='\n')
        changed=next(item for item in handoff.finding_index(state,'1')['diagnostics'] if item['findings'])
        self.assertEqual(changed['status'],'changed');self.assertEqual(changed['report'],original['report'])
        from .retention import attach
        self.assertEqual(attach(journal,state,old,historical),original['report'])
        self.assertEqual(path.read_text(),'{}')
        path.unlink();Path(old['source_ref']['path']).unlink()
        scope=followups(state)[0]
        self.assertTrue(scope['historical']);self.assertEqual(scope['destination'],{'saved':True})
        fresh=native.admit(self.root,'review')
        packet=read_json(fresh['task_context']['path']);index=read_json(Path(fresh['task_context']['path']).parent/packet['findings']['path'])
        original=next(item for item in index['diagnostics'] if item['findings'])
        self.assertEqual(original['status'],'unavailable')
        self.assertEqual([f['severity'] for f in original['findings']],['blocking','concern','scope'])
        native.bind(self.root,fresh['id'],{'child_session':'fresh-review'})
        self.native_results[fresh['id']]={'status':'completed','text':json.dumps({'verdict':'clean','findings':[]})}
        native.retain(self.root,fresh['id'],{})
        completed=native.complete(self.root,fresh['id'])
        journal,state=load_run(self.root)
        self.assertEqual(followups(state)[0]['destination'],{'saved':True})
        self.assertNotIn(old['id'],state.get('resolutions',{}))
        self.assertIn('Historical diagnostic reports',(journal.path/'index.md').read_text())
        rendered=publication.readable([{'commit':completed['commit'],'evidence':state['commit_intents']['1']['publication']}],{state['id']:state},self.root)
        self.assertIn(original['report']['hash'],rendered)

    def test_pinned_review_reports_cannot_be_rehashed_by_packets_or_repair_sources(self):
        from . import native,handoff,review
        selected=native.review(self.root,'changes',self.human('Review my changes.'))
        result=self.finish_attempt('review',{'verdict':'findings','findings':[{'severity':'blocking','description':'Retained defect'}]})
        journal,state=load_run(self.root);path=Path(result['report_ref']['path']);original=path.read_bytes()
        for missing in (False,True):
            if missing:path.unlink()
            else:path.write_text(json.dumps({'verdict':'clean','findings':[]}),newline='\n')
            with self.subTest(missing=missing):
                packet,_=handoff.prepare(state,state['tasks'][0],'implementation',Path(self.temp.name)/('packet-'+str(missing)),result|{'root':str(self.root)})
                retained=json.loads(Path(packet['path']).read_text())['current_review']['report']
                self.assertEqual(retained['hash'],result['report_ref']['hash'])
                self.assertEqual(retained['status'],'unavailable' if missing else 'changed')
                with self.assertRaisesRegex(Refused,'retained report'):handoff.report(result)
                with self.assertRaisesRegex(Refused,'retained report'):review.repair_source(self.root,selected['run'])
            path.write_bytes(original)
        ref=review.repair_source(self.root,selected['run'])
        self.assertEqual(ref['hash'],result['report_ref']['hash'])

    def test_partial_retention_preserves_stale_selection_and_original_render_boundary(self):
        from . import native,authority
        from .storage import digest
        self.approve()
        admission=native.admit(self.root,'assessment')
        native.bind(self.root,admission['id'],{'child_session':'assessor'})
        fake_revocation=Path(admission['request']).parent/'revoked-result.json'
        fake_revocation.write_text(json.dumps({'status':'completed','text':json.dumps({'difficulty':'complex'})}),newline='\n')
        with self.assertRaises(Refused):native.retain(self.root,admission['id'],{})
        self.assertFalse(load_run(self.root)[1]['attempts'][-1]['finished'])
        old_record={'type':'fixture-native','text':'original'};new_record={'type':'fixture-native','text':'later'}
        self.parent_path.write_text(json.dumps(old_record)+'\n'+json.dumps(new_record)+'\n',newline='\n')
        self.native_results[admission['id']]={'status':'completed','text':json.dumps({'difficulty':'simple'}),'record_hashes':[digest(old_record)]}
        save=native._immutable
        def interrupted(path,value):
            if Path(path).name=='result.json':raise OSError('Crash after native source write')
            return save(path,value)
        with patch.object(native,'_immutable',side_effect=interrupted),self.assertRaises(OSError):native.retain(self.root,admission['id'],{})
        source_path=Path(admission['request']).parent/'native-result.json';original=source_path.read_bytes()
        self.native_results[admission['id']]={'status':'completed','text':json.dumps({'difficulty':'complex'}),'record_hashes':[digest(new_record)]}
        result=native.retain(self.root,admission['id'],{})
        self.assertEqual(result['outcome'],'unfinished');self.assertEqual(source_path.read_bytes(),original)
        self.assertNotIn('1',load_run(self.root)[1].get('assessments',{}))
        receipt=Path(result['evidence'])/'report.md';rendered=receipt.read_bytes()
        self.assess()
        native.retain(self.root,admission['id'],{})
        self.assertEqual(receipt.read_bytes(),rendered)
        self.assertEqual(load_run(self.root)[1]['assessments']['1']['difficulty'],'standard')
        # Review projection preserves the old native occurrence first, including
        # malformed positions, when a later report arrives after a partial save.
        self.implement();native.candidate(self.root);native.verify(self.root);admission=native.admit(self.root,'review')
        native.bind(self.root,admission['id'],{'child_session':'partial-reviewer'})
        (Path(admission['request']).parent/'revoked-result.json').write_text(json.dumps({'status':'completed','text':json.dumps({'verdict':'clean','findings':[]})}),newline='\n')
        with self.assertRaises(Refused):native.retain(self.root,admission['id'],{})
        self.assertFalse(load_run(self.root)[1]['attempts'][-1]['finished'])
        original_finding={'severity':'concern','description':'Original concern'}
        later_finding={'severity':'blocking','description':'Later blocker'}
        self.native_results[admission['id']]={'status':'completed','text':json.dumps({'verdict':'findings','findings':['Malformed',original_finding]}),'record_hashes':[digest(old_record)]}
        with patch.object(native,'_immutable',side_effect=interrupted),self.assertRaises(OSError):native.retain(self.root,admission['id'],{})
        self.native_results[admission['id']]={'status':'completed','text':json.dumps({'verdict':'findings','findings':[later_finding]}),'record_hashes':[digest(new_record)]}
        result=native.retain(self.root,admission['id'],{})
        self.assertEqual([f['description'] for f in result['findings']],['Later blocker'])
        self.assertEqual(result['finding_positions'],[1])
        from .retention import read,diagnostic_index
        item=next(item for item in diagnostic_index(load_run(self.root)[1],'1') if item['findings'] and item['findings'][0]['description']=='Original concern')
        self.assertEqual(item['findings'][0]['position'],2);self.assertEqual(item['unparsed'],1)
        original=read(item['report'])
        self.assertEqual(original['source']['record_hashes'],[digest(old_record)])
        self.assertEqual(original['report']['findings'][1],original_finding)
        fresh=self.reviewed();completed=native.complete(self.root,fresh['id'])
        from . import publication
        final=load_run(self.root)[1]
        sealed=final['commit_intents']['1']['publication']
        body=publication.readable([{'commit':completed['commit'],'evidence':sealed}],{final['id']:final})
        self.assertIn(item['report']['hash'],body)
        self.assertIn('not a replacement verdict',body)

    def test_legacy_completion_replays_only_missing_assessment_effects(self):
        # Old runtimes could commit the finish before its dependent assessment.
        # Retrying that receipt must neither lose the missing effect nor replace
        # an assessment supplied by a subsequent attempt.
        from . import native
        from .storage import Journal
        self.approve()
        admission=native.admit(self.root,'assessment')
        native.bind(self.root,admission['id'],{'child_session':'legacy-assessor'})
        self.native_results[admission['id']]={'status':'completed','text':json.dumps({'difficulty':'simple'})}
        append=Journal.append
        def legacy_finish(journal,kind,data):
            if kind=='transition' and data['events'][0]['kind']=='attempt.finished':
                append(journal,'attempt.finished',data['events'][0]['data'])
                raise OSError('Legacy crash before dependent assessment')
            return append(journal,kind,data)
        with patch.object(Journal,'append',legacy_finish),self.assertRaisesRegex(OSError,'Legacy crash'):
            native.retain(self.root,admission['id'],{})
        native.retain(self.root,admission['id'],{})
        self.assertEqual(load_run(self.root)[1]['assessments']['1']['difficulty'],'simple')
        journal,_=load_run(self.root)
        prior=next(e['data'] for r in journal.records() for e in (r['data']['events'] if r['kind']=='transition' else [r]) if e['kind']=='attempt.started')
        finish=next(r['data'] for r in journal.records() if r['kind']=='attempt.finished')
        journal.append('attempt.started',prior|{'id':'later-assessment'})
        journal.append('attempt.finished',finish|{'id':'later-assessment'})
        journal.append('task.assessed',{'task':'1','attempt':'later-assessment','difficulty':'standard','rationale':'Later retained assessment'})
        before=load_run(self.root)[0].records()
        native.retain(self.root,admission['id'],{})
        self.assertEqual(load_run(self.root)[0].records(),before)
        self.assertEqual(load_run(self.root)[1]['assessments']['1']['difficulty'],'standard')

    def test_structured_decision_preserves_receipt_and_original_finding_positions(self):
        from . import native
        from .handoff import finding_index
        from .review_report import PREFIX, check
        from .hosts import REVIEW_SCHEMA
        # Keep every supported legacy verdict, not a hand-picked subset of producers.
        for verdict in REVIEW_SCHEMA['properties']['verdict']['enum']:
            findings=[] if verdict=='clean' else [{'severity':verdict,'family':'legacy','description':'Legacy concrete claim.'}]
            with self.subTest(legacy_verdict=verdict):
                self.assertTrue(check(json.dumps({'verdict':verdict,'findings':findings}))['valid'])
        # Prose, including a count or an explicit failure, never grants clean authority.
        for prose in ('0 concerns.', 'No findings. INCOMPLETE: review failed.'):
            self.assertFalse(check(prose)['valid'])
        receipt='Arbitrary layout, quoted examples, code and detailed reasoning.\n'+('Full evidence. '*1000)
        clean=PREFIX+json.dumps({'verdict':'clean','findings':[]})+'\n'+receipt
        self.assertTrue(check(clean)['valid'])
        wrapped='Review finished.\n\n'+clean
        self.assertTrue(check(wrapped)['valid'])
        # Receipt examples and ambiguous decisions cannot become clean authority.
        example='```text\n'+clean+'\n```'
        self.assertFalse(check(example)['valid'])
        self.assertFalse(check(wrapped+'\n'+clean)['valid'])
        self.assertTrue(check(wrapped+'\n'+example)['valid'])
        self.assertFalse(check(PREFIX+json.dumps({'verdict':'clean','findings':[]})+'\n')['valid'])
        self.assertFalse(check('Summary only.\n'+PREFIX+json.dumps({'verdict':'clean','findings':[]}))['valid'])
        self.approve();self.assess();self.implement()
        # Replay the old first-line parser's retained failure, not a new review.
        wrapped_blocking='Review finished.\n'+PREFIX+json.dumps({'verdict':'findings','findings':[
            {'severity':'blocking','family':'retained','description':'Concrete retained defect.'}]})+'\n'+receipt
        with patch('oh.review_report.read',return_value=({'summary':wrapped_blocking,'findings':[]},['Missing structured review decision'])):
            old=self.reviewed(wrapped_blocking)
        directory=Path(old['evidence'])
        originals={name:(directory/name).read_bytes() for name in ('result.json','native-result.json','review.md')}
        journal,before=load_run(self.root)
        native_source=json.loads(originals['native-result.json'])
        with patch('oh.authority.native_result',return_value=native_source|{'text':'Changed reviewer result'}):
            with self.assertRaisesRegex(Refused,'evidence changed'):native.retain(self.root,old['id'],{})
        candidate=self.root/'output.txt';contents=candidate.read_bytes();candidate.write_bytes(b'later change\n')
        with self.assertRaisesRegex(Refused,'earlier candidate'):native.retain(self.root,old['id'],{})
        candidate.write_bytes(contents)
        recovered=native.retain(self.root,old['id'],{})
        self.assertEqual((recovered['outcome'],recovered['original_outcome']),('blocking','review_incomplete'))
        self.assertFalse(recovered['report_issues'])
        with self.assertRaises(Refused):native.complete(self.root,old['id'])
        self.assertEqual({name:(directory/name).read_bytes() for name in originals},originals)
        _,after=load_run(self.root)
        self.assertEqual(len(after['attempts']),len(before['attempts']))
        self.assertEqual(after.get('review_grants'),before.get('review_grants'))
        records=journal.records()
        self.assertEqual(native.retain(self.root,old['id'],{}),recovered)
        self.assertEqual(journal.records(),records)
        self.assertIn('reparsed-review.json',(journal.path/'index.md').read_text())
        collect()
        with connect() as db:
            observed=db.execute('SELECT outcome,ended,duration_ms FROM attempts WHERE id=?',(old['id'],)).fetchone()
        self.assertEqual(observed['outcome'],'blocking')
        self.assertEqual(observed['duration_ms'],old['duration_ms'])
        findings=[{'severity':'unknown','description':'Unclassified neighboring risk.'},
            {'severity':'blocking','description':'Concrete retained defect.','family':'retained','relation':None},
            {'severity':'concern','description':'A concrete concern.','family':'concern'}]
        # A contradictory clean decision cannot hide even one known blocker behind an unknown item.
        original=PREFIX+json.dumps({'verdict':'clean','findings':findings})+'\n'+receipt
        self.assertFalse(check(original)['valid'])
        review=self.reviewed(original)
        self.assertEqual(review['outcome'],'blocking')
        self.assertEqual(review['finding_positions'],[2,3])
        self.assertEqual(review['review_fragments'],[{'position':1,'finding':findings[0]}])
        retained=json.loads((Path(review['evidence'])/'result.json').read_text())
        self.assertEqual(retained['findings'],findings)
        self.assertEqual(retained['receipt'],receipt)
        self.assertIn(receipt,(Path(review['evidence'])/'review.md').read_text())
        self.assertEqual(json.loads((Path(review['evidence'])/'native-result.json').read_text())['text'],original)
        index=finding_index(load_run(self.root)[1],'1')
        self.assertEqual(index['families'][0]['occurrences'][-1]['id'],review['id']+'#2')
        self.assertEqual(index['families'][1]['occurrences'][0]['id'],review['id']+'#3')
        self.assertTrue(index['incomplete_reviews'][-1]['issues'])
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        repair=native.admit(self.root,'implementation')
        packet_path=Path(repair['task_context']['path']);packet=json.loads(packet_path.read_text())
        if packet.get('details'):packet=json.loads((packet_path.parent/packet['details']['path']).read_text())
        self.assertEqual(json.loads((packet_path.parent/packet['findings']['path']).read_text()),index)
        self.assertEqual(json.loads(Path(packet['current_review']['report']['path']).read_text())['receipt'],receipt)
        self.assertEqual(packet['current_review']['attempt'],review['id'])

    def test_native_lifecycle_events_recover_binding_and_retain_once(self):
        from . import native,worker_checks
        from .native_events import handle
        with patch.object(self,'human',return_value={'host':'claude','session':'s','turn':'1','prompt':'approve'}):self.approve()
        admitted=native.admit(self.root,'assessment')
        event={'hook_event_name':'PostToolUse','session_id':'s','tool_name':'Agent','tool_use_id':'spawn',
               'tool_input':{'subagent_type':'o-harness:assessment','prompt':admitted['id']},
               'tool_response':{'agentId':'child','status':'async_launched'}}
        journal,before=load_run(self.root)
        records=journal.records()
        self.assertEqual(handle(self.root,'codex',event),{})
        self.assertEqual(handle(self.root,'claude',event|{'session_id':'foreign'}),{})
        self.assertEqual(journal.records(),records)
        nested=self.root/'source';nested.mkdir()
        self.assertEqual(handle(nested,'claude',event)['binding'],'saved')
        records=journal.records()
        handle(self.root,'claude',event)
        self.assertEqual(journal.records(),records)
        bound=load_run(self.root)[1]['attempts'][-1]['native_child']
        with patch('oh.authority.native_child',return_value=bound|{'record_hashes':['later-native-message']}):
            self.assertEqual(native.bind(self.root,admitted['id'],{'child_session':'child'}),bound)
        self.assertEqual(journal.records(),records)
        with patch('oh.authority.native_child',return_value=bound|{'child_session':'different-child'}):
            with self.assertRaisesRegex(Refused,'cannot be replaced'):
                native.bind(self.root,admitted['id'],{'child_session':'different-child'})
        self.native_results[admitted['id']]={'text':json.dumps({'difficulty':'standard','rationale':'Bound.'}),'status':'completed'}
        stopped={'hook_event_name':'SubagentStop','session_id':'s','agent_id':'child','last_assistant_message':'Untrusted summary'}
        self.assertEqual(handle(self.root,'claude',stopped)['outcome'],'assessed')
        records=journal.records();self.assertEqual(handle(self.root,'claude',stopped),{})
        self.assertEqual(journal.records(),records)
        # The same checked fallback works when the host has no lifecycle hooks.
        author=native.admit(self.root,'implementation')
        validated=worker_checks.admission(Path(author['request']).parent)
        packet_path=Path(author['task_context']['path'])
        self.assertEqual(validated['task_context'],json.loads(packet_path.read_text()))
        self.assertTrue(load_run(self.root)[1]['attempts'][-1]['native_child'])
        self.assertEqual(len(load_run(self.root)[1]['attempts']),len(before['attempts'])+1)
        import stat
        packet_path.chmod(stat.S_IWRITE|stat.S_IREAD)
        packet_path.write_text('{}',newline='\n')
        with self.assertRaisesRegex(Refused,'task context changed'):
            worker_checks.admission(Path(author['request']).parent)

    def test_completion_commits_exact_reviewed_tree_once_and_task_grants_do_not_expand(self):
        from . import native
        # Git history and exact candidate evidence suffice; reflog files may be disabled or expired.
        self.git('config','core.logAllRefUpdates','false')
        (self.root/'.git/logs/refs/heads/work').unlink()
        configure(self.root,tasks_per_batch=1)
        self.approve(self.tasks[:2]);self.assess();self.implement()
        # Completion itself repairs the old preamble failure on the same candidate.
        wrapped='Finished review.\nOH-REVIEW-DECISION: {"verdict":"clean","findings":[]}\nChecked the exact candidate.'
        with patch('oh.review_report.read',return_value=({'summary':wrapped,'findings':[]},['Missing structured review decision'])):
            review=self.reviewed(wrapped)
        head=self.git('rev-parse','HEAD')
        completed=native.complete(self.root,review['id'])
        self.assertEqual(load_run(self.root)[1]['attempts'][-1]['original_outcome'],'review_incomplete')
        self.assertEqual(self.git('rev-parse','HEAD^'),head)
        self.assertEqual(self.git('rev-parse','HEAD^{tree}'),review['git_tree'])
        self.assertEqual(native.complete(self.root,review['id']),completed)
        self.assertEqual(native.resume(self.root)['status'],'checkpoint')
        saved=load_run(self.root)[1]
        resumed=native.resume(self.root,self.resume_choice(session='fresh-parent'))
        self.assertEqual(resumed['status'],'checkpoint')
        self.assertEqual(resumed['granted'],saved['granted'])
        self.assertEqual(resumed['continuation']['pending_decision'],'task_window')
        next_action=completed['continuation']['next_action']
        self.assertEqual(next_action['tool'],'decision_request')
        self.assertEqual(next_action['arguments'],{'kind':'continue','run':saved['id']})
        self.assertEqual(resumed['continuation']['next_action'],next_action)
        collect()
        with connect() as db:
            observations=analytics(db,{'from':'2000','to':'2100'})['summary']
        self.assertGreaterEqual(observations['attempts'],3)
        self.assertIsNone(observations['input'])
        self.assertIsNone(observations['output'])
        with self.assertRaises(Refused):native.admit(self.root,'assessment')
        from .decisions import prepare as decision_request,verify as verify_decision
        from .storage import now
        # Missing publication configuration must not hide Continue or Stop.
        unavailable=decision_request(self.root,'continue')
        self.assertEqual(set(unavailable['actions'].values()),{'continue','stop'})
        self.assertIn('PR unavailable',unavailable['disclosure'])
        self.git('remote','add','origin','https://github.com/example/product.git')
        offer=decision_request(self.root,'continue')
        self.assertEqual(offer['options'],['Start task 2','Open PR to example/product → main','Stop and take over'])
        self.assertIn('Continue authorizes tasks: 2',offer['disclosure'])
        self.assertIn(self.git('rev-parse','HEAD'),offer['disclosure'])
        history=load_run(self.root)[0].records()
        unbound=self.offered_answer(offer,'Continue',via='text')
        unbound.pop('decision')
        with self.assertRaisesRegex(Refused,'bound decision effect'):
            native.decision(self.root,'continue',unbound)
        # The same native question supports all three effects on both hosts.
        home=Path(self.temp.name)/'checkpoint-host'
        with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,{'CODEX_HOME':str(home/'.codex')}):
            for host in ('claude','codex'):
                journal,original=load_run(self.root)
                state=original|{'human':original['human']|{'host':host,'session':'checkpoint'}}
                with patch('oh.decisions.load_run',return_value=(journal,state)):
                    menu_offer=decision_request(self.root,'continue')
                for label,kind in menu_offer['actions'].items():
                    asked=now();answered=now()
                    question='Task one passed review. Which action would you like?'
                    if host=='claude':
                        path=home/'.claude/projects/checkpoint.jsonl'
                        common={'sessionId':'checkpoint','cwd':str(self.root)}
                        rows=[common|{'type':'assistant','timestamp':asked,'message':{'content':[{'type':'text','text':'One task has passed review.'},{'type':'tool_use','id':'menu','name':'AskUserQuestion',
                            'input':{'questions':[{'question':question,'multiSelect':False,'options':[{'label':x} for x in menu_offer['options']]}]}}]}},
                              common|{'type':'user','timestamp':answered,'toolUseResult':{'answers':{question:label}},
                                      'message':{'content':[{'type':'tool_result','tool_use_id':'menu','content':'Answered.'}]}}]
                    else:
                        path=home/'.codex/sessions/checkpoint.jsonl'
                        reply='<send_user_message_question_reply>'+json.dumps([{'questionItemId':json.dumps(['request_user_input_async','menu',0]),'answer':label}])+'</send_user_message_question_reply>'
                        rows=[{'type':'session_meta','payload':{'id':'checkpoint','cwd':str(self.root),'source':'vscode'}},
                              {'type':'response_item','timestamp':asked,'payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'One task has passed review.'}]}},
                              {'type':'response_item','timestamp':asked,'payload':{'type':'function_call','name':'request_user_input_async',
                               'call_id':'menu','arguments':json.dumps({'questions':[{'title':question,'options':menu_offer['options']}]})}},
                              {'type':'event_msg','timestamp':answered,'payload':{'type':'user_message','turn_id':'answer','message':reply}}]
                    # In the real 0012 session, asking to see a clickable menu
                    # separated the offer from the native call. The effect stayed the same.
                    clarification=(common|{'type':'user','promptId':'clarify','timestamp':asked,
                                     'message':{'role':'user','content':'Show me the clickable menu.'}} if host=='claude' else
                                   {'type':'event_msg','timestamp':asked,'payload':{'type':'user_message',
                                     'turn_id':'clarify','message':'Show me the clickable menu.'}})
                    index=0 if host=='claude' else 1
                    rows[index:index]=[self.offer_record(host,'checkpoint',menu_offer,asked),clarification]
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
                    locator={'host':host,'session':'checkpoint','tool_use_id':'menu','transcript_path':str(path),'decision':menu_offer['decision']}
                    source=self.native_human_original(self.root,locator)
                    self.assertEqual(verify_decision(self.root,state,kind,locator,source)['kind'],kind)
                    # The transcript locates the exact prepared native menu.
                    hook={k:v for k,v in locator.items() if k!='tool_use_id'}
                    with patch('oh.authority.native_human',side_effect=self.native_human_original):
                        self.assertEqual(native._presented(self.root,hook,state)['tool_use_id'],'menu')
                    verify_decision(self.root,state,kind,locator,source|{'question':'Which next step makes sense?',
                        'question_context':[],'question_options':list(reversed(menu_offer['options']))})
                    with self.assertRaises(Refused):
                        verify_decision(self.root,state,kind,locator,source|{'prepared_offer':{'decision':'different'}})
                    verify_decision(self.root,state,kind,locator,source|{'question_options':[label,'Discuss']})
                    for labels in (None,[option for option in menu_offer['options'] if option!=label],[label,label]):
                        with self.subTest(host=host,labels=labels),self.assertRaises(Refused):
                            verify_decision(self.root,state,kind,locator,source|{'question_options':labels})
                    with self.assertRaises(Refused):
                        verify_decision(self.root,state,kind,locator,source|{'question_at':'2000-01-01T00:00:00Z'})
                    with self.assertRaisesRegex(Refused,'coordinator'):
                        verify_decision(self.root,state,kind,locator,source|{'session':'another-parent'})
                    with self.assertRaisesRegex(Refused,'coordinator changed'):
                        verify_decision(self.root,state|{'human':state['human']|{'session':'new-owner'}},kind,locator,source)
                    for other in {'continue','publish','stop'}-{kind}:
                        with self.assertRaises(Refused):verify_decision(self.root,state,other,locator,source)
                    for invalid in ('Yes','Not now','Continue with the next task batch, Open PR with completed tasks'):
                        with self.assertRaises(Refused):verify_decision(self.root,state,kind,locator,source|{'prompt':invalid})
        self.assertEqual(load_run(self.root)[0].records(),history)
        publish=self.offered_answer(offer,offer['options'][-2],session='fresh-parent')
        self.git('remote','set-url','origin','https://github.com/example/elsewhere.git')
        with self.assertRaisesRegex(Refused,'destination changed'):native.decision(self.root,'publish',publish)
        self.git('remote','set-url','origin','https://github.com/example/product.git')
        (self.root/'new-edit.txt').write_text('Preserve this later edit.',newline='\n')
        with self.assertRaisesRegex(Refused,'subject changed'):native.decision(self.root,'publish',publish)
        stop=self.offered_answer(offer,'Stop and take over',session='fresh-parent')
        native.decision(self.root,'stop',stop);native.decision(self.root,'stop',stop)
        self.assertEqual((self.root/'new-edit.txt').read_text(),'Preserve this later edit.')
        (self.root/'new-edit.txt').unlink()
        self.assertEqual(native.resume(self.root)['status'],'stopped')
        self.assertNotIn('next_action',native.resume(self.root)['continuation'])
        self.assertIsNone(load_run(self.root)[1].get('publication'))
        self.assertEqual(load_run(self.root)[1]['done'],['1'])
        with self.assertRaisesRegex(Refused,'checkpoint changed'):native.decision(self.root,'publish',publish)
        native.resume(self.root,self.resume_choice())
        offer=decision_request(self.root,'continue')
        locator=self.offered_answer(offer,offer['options'][0])
        native.decision(self.root,'continue',locator)
        native.decision(self.root,'continue',locator)
        state=load_run(self.root)[1]
        self.assertEqual(state['granted'],['2']);self.assertEqual(state['done'],['1'])
        self.assertEqual(native.resume(self.root)['task']['id'],'2')
        self.assess();self.implement(edit=lambda:(self.root/'second.txt').write_text('Task two is complete.',newline='\n'))
        self.git('add','.');self.git('commit','-qm','checkpoint during second task')
        checkpoint=self.git('rev-parse','HEAD')
        second=self.reviewed();last=native.complete(self.root,second['id'])
        self.assertEqual(last['continuation']['next_action']['arguments'],{'kind':'publish','run':saved['id']})
        self.assertEqual(load_run(self.root)[1]['commit_intents']['2']['publication']['covers'],[checkpoint])
        final=decision_request(self.root,'publish')
        self.assertEqual(final['options'],['Open PR to example/product → main','Stop and take over'])
        self.git('remote','remove','origin')
        self.assertEqual(native.resume(self.root)['continuation']['next_action'],last['continuation']['next_action'])
        final=decision_request(self.root,'publish')
        self.assertEqual(final['options'],['Stop and take over'])
        self.assertEqual(final['actions'],{'Stop and take over':'stop'})
        self.assertIn('PR unavailable',final['disclosure'])
        self.assertEqual(verify_decision(self.root,load_run(self.root)[1],'stop',{'decision':final['decision']},
                         self.offered_answer(final,'Stop and take over',via='text'))['kind'],'stop')
        self.git('remote','add','origin','https://github.com/example/product.git')
        self.git('update-ref','refs/remotes/origin/main',head)
        second_commit=self.git('rev-parse','HEAD');original_summaries=load_run(self.root)[1]['summaries']
        records=load_run(self.root)[0].records()
        requested=native.review(self.root,['task','1'],self.human('/oh-review task 1',session='task-review-parent'))
        self.assertTrue(requested['resume_required'])
        self.assertEqual(load_run(self.root)[0].records(),records)
        native.review(self.root,['task','1'],self.resume_choice(session='task-review-parent'));native.verify(self.root)
        records=load_run(self.root)[0].records()
        self.assertEqual(native.review(self.root,['task','1'])['run'],load_run(self.root)[1]['id'])
        self.assertEqual(load_run(self.root)[0].records(),records)
        reentered=native.review(self.root,['task','1'],self.human('/oh-review task 1',session='review-parent'))
        self.assertEqual(reentered['run'],load_run(self.root)[1]['id'])
        self.assertTrue(reentered['resume_required'])
        self.assertEqual(load_run(self.root)[0].records(),records)
        native.review(self.root,['task','1'],self.resume_choice(session='review-parent'))
        self.assertEqual(load_run(self.root)[1]['human']['session'],'review-parent')
        self.assertEqual(load_run(self.root)[1]['extra_review']['task'],'1')
        publication_choice=lambda:native.decision(self.root,'publish',self.human('publish',question='Publish the reviewed work branch to example/product?'))
        with self.assertRaisesRegex(Refused,'requested task review'):publication_choice()
        blocker=self.finish_attempt('review',{'verdict':'blocking','summary':'Task one needs a scoped correction.','findings':[
            {'severity':'blocking','description':'Task one leaves stale timeout state.','family':'earlier-task','path':'output.txt'}]})
        with self.assertRaises(Refused):native.complete(self.root,blocker['id'])
        with self.assertRaisesRegex(Refused,'requested task review'):publication_choice()
        from . import publication
        unresolved=load_run(self.root)[1]
        with patch('oh.publication.made',return_value=unresolved|{'status':'pr'}),self.assertRaisesRegex(Refused,'requested task review'):
            publication.render(self.root)
        self.implement(edit=lambda:(self.root/'output.txt').write_text('Corrected task one after task two.',newline='\n'))
        fixed=self.reviewed();correction=native.complete(self.root,fixed['id'])
        self.assertEqual(self.git('rev-parse','HEAD^'),second_commit)
        self.assertEqual(correction['correction_of'],completed['commit'])
        state=load_run(self.root)[1]
        self.assertEqual(state['summaries'][:2],original_summaries)
        self.assertEqual(state['done'],['1','2'])
        evidence=state['commit_intents'][correction['commit_key']]['publication']
        self.assertEqual(evidence['parent'],second_commit)
        self.assertEqual(evidence['correction_of'],completed['commit'])
        publication_choice()
        self.assertIn('Correction:',publication.render(self.root))

    def test_interrupted_commit_recovers_without_another_review_or_duplicate_commit(self):
        from . import native
        self.approve();self.assess()
        author=native.admit(self.root,'implementation');native.bind(self.root,author['id'],{})
        (self.root/'output.txt').write_text('Retain this implementation once.\n',newline='\n')
        self.native_results[author['id']]={'text':json.dumps({'status':'completed','summary':'Implementation is ready.'}),'status':'completed'}
        save=native.atomic_json
        def interrupted_result(path,value,**kwargs):
            result=save(path,value,**kwargs)
            if Path(path).name=='native-result.json':raise OSError('Interrupted after retaining the original native result.')
            return result
        with patch('oh.native.atomic_json',side_effect=interrupted_result),self.assertRaises(OSError):
            native.retain(self.root,author['id'],{})
        source_path=Path(author['request']).with_name('native-result.json');source=source_path.read_bytes()
        self.assertFalse(load_run(self.root)[1]['attempts'][-1]['finished'])
        native.retain(self.root,author['id'],{})
        self.assertEqual(source_path.read_bytes(),source)
        self.assertEqual(len(load_run(self.root)[1]['attempts']),2)
        review=self.reviewed()
        # Upgrade after sealing an old-format intent, but before Git commits.
        # The new producer adds verification evidence; retry must keep the old seal.
        from . import publication
        journal,state=load_run(self.root);checked=state['verification']['1']
        # Reproduce the old producer's actual same-tree rebinding history.
        # Its selected check originated on another HEAD under the same identity.
        legacy=checked|{'at':'legacy-check-time'}
        journal.append('verification',legacy|{'head':'earlier-check-head'})
        journal.append('verification',legacy)
        producer=publication.task_evidence;run_git=native.git
        def old_evidence(*args):return {k:v for k,v in producer(*args).items() if k!='verification'}
        def before_commit(root,*args):
            if args[0]=='commit':raise OSError('Interrupted before Git commit')
            return run_git(root,*args)
        with patch.object(publication,'task_evidence',side_effect=old_evidence),patch.object(native,'git',side_effect=before_commit), \
                patch.object(native,'provenance',return_value=legacy),patch('oh.verification.provenance',return_value=legacy),self.assertRaises(OSError):
            native.complete(self.root,review['id'])
        sealed=load_run(self.root)[1]['commit_intents']['1']['publication']
        self.assertNotIn('verification',sealed)
        with self.assertRaisesRegex(Refused,'Passing verification'):native.complete(self.root,review['id'])
        journal,state=load_run(self.root);original=Journal.append
        def interrupted(this,kind,data):
            if kind=='task.completed':raise OSError('Interrupted after exact commit.')
            return original(this,kind,data)
        # The legacy runtime wrote the exact sealed commit, then crashed before
        # its completion event. New readers recover that fact without a new Git write.
        with patch.object(Journal,'append',interrupted),patch.object(native,'provenance',return_value=legacy), \
                patch('oh.verification.provenance',return_value=legacy),self.assertRaises(OSError):
            native.complete(self.root,review['id'])
        committed=self.git('rev-parse','HEAD');attempts=len(load_run(self.root)[1]['attempts'])
        recovered=native.complete(self.root,review['id'])
        self.assertEqual(recovered['commit'],committed)
        self.assertEqual(self.git('rev-parse','HEAD'),committed)
        self.assertEqual(len(load_run(self.root)[1]['attempts']),attempts)
        self.assertEqual(load_run(self.root)[1]['done'],['1'])
        self.assertEqual(load_run(self.root)[1]['commit_intents']['1']['publication'],sealed)
        publication.verify_record(self.root,committed,sealed)
        self.assertIsNone(publication.original_verification(sealed,self.root))

    def test_precommit_intent_rechecks_proof_and_accepts_fresh_reviewed_repair(self):
        from . import native,publication
        self.approve();self.assess();self.implement();review=self.reviewed()
        run_git=native.git
        def before_commit(root,*args):
            if args[0]=='commit':raise OSError('Interrupted before Git commit')
            return run_git(root,*args)
        with patch.object(native,'git',side_effect=before_commit),self.assertRaises(OSError):
            native.complete(self.root,review['id'])
        journal,state=load_run(self.root);original=state['commit_intents']['1'];parent=self.git('rev-parse','HEAD')
        path=Path(review['report_ref']['path']);report=path.read_bytes()
        for missing in (False,True):
            if missing:path.unlink()
            else:path.write_text('{}',newline='\n')
            with self.subTest(missing=missing),self.assertRaisesRegex(Refused,'retained report'):
                native.complete(self.root,review['id'])
            self.assertEqual(self.git('rev-parse','HEAD'),parent)
            path.write_bytes(report)
        self.reviewed({'verdict':'blocking','findings':[{'severity':'blocking','family':'retry','description':'Repair the candidate.'}]})
        with self.assertRaisesRegex(Refused,'Final review does not match'):native.complete(self.root,review['id'])
        self.assertEqual(self.git('rev-parse','HEAD'),parent)
        self.implement(edit=lambda:(self.root/'output.txt').write_text('Repaired candidate.\n',newline='\n'))
        fresh=self.reviewed();completed=native.complete(self.root,fresh['id'])
        journal,final=load_run(self.root)
        intents=[r['data'] for r in journal.records() if r['kind']=='commit.intent']
        self.assertEqual(len(intents),2);self.assertEqual(intents[0],original)
        self.assertEqual(intents[1]['review'],fresh['id']);self.assertEqual(intents[1]['parent'],parent)
        publication.verify_record(self.root,completed['commit'],intents[1]['publication'])
        self.assertEqual(final['done'],['1'])

    def test_additional_review_reverifies_actual_inputs_and_completes_a_clean_scoped_repair(self):
        from . import native,publication
        baseline=self.git('rev-parse','HEAD')
        program=("import pathlib,subprocess,sys; head=subprocess.check_output(['git','rev-parse','HEAD']).decode().strip(); "
                 "sys.exit(0 if head=="+repr(baseline)+" or pathlib.Path('output.txt').read_text().strip()=='repaired' else 1)")
        configure(self.root,review_rounds=4,checks=[{'name':'history-sensitive','command':['python3','-c',program]}])
        self.approve();self.assess();self.implement();first=self.reviewed();native.complete(self.root,first['id'])
        native.review(self.root,['task','1'],self.resume_choice())
        journal,state=load_run(self.root);old=state['verification']['1']
        self.assertNotEqual(old['head'],self.git('rev-parse','HEAD'))
        with self.assertRaisesRegex(Refused,'checks'):native.admit(self.root,'review')
        # Already-saved legacy synthetic rebinding is not actual verification either.
        journal.append('verification',old|native._subject(self.root,state))
        with self.assertRaisesRegex(Refused,'checks'):native.admit(self.root,'review')
        author=native.admit(self.root,'implementation');native.bind(self.root,author['id'],{'child_session':'repair-author'})
        from copy import deepcopy
        legacy=deepcopy(load_run(self.root)[0].records())
        for row in legacy:
            if row['kind']=='review.requested':row['data'].pop('baseline',None)
        self.assertEqual(reduce(legacy)['extra_review']['baseline']['git_tree'],author['git_tree'])
        failed=native.verify(self.root,attempt_id=author['id'])
        self.assertEqual(failed['checks'][0]['returncode'],1)
        (self.root/'output.txt').write_text('repaired\n',newline='\n')
        native.candidate(self.root);passed=native.verify(self.root,attempt_id=author['id'])
        self.assertEqual(passed['checks'][0]['returncode'],0)
        self.native_results[author['id']]={'status':'unfinished','text':''}
        native.retain(self.root,author['id'],{})
        self.assertTrue(load_run(self.root)[1].get('correction'))
        self.finish_attempt('implementation','Verified the existing scoped repair without further edits.')
        fresh=self.finish_attempt('review',{'verdict':'clean','findings':[]})
        completed=native.complete(self.root,fresh['id'])
        journal,state=load_run(self.root);self.assertEqual(self.git('status','--porcelain'),'')
        intent=next(v for v in state['commit_intents'].values() if v['review']==fresh['id'])
        evidence=intent['publication'];publication.verify_record(self.root,completed['commit'],evidence)
        self.assertEqual(evidence['verification']['checks'][0]['returncode'],0)
        later=dict(state);later['attempts']=state['attempts']+[state['attempts'][-1]|{'id':'later-incomplete','outcome':'unfinished','findings':[]}]
        later['verification']={'1':{'checks':[{'name':'later-only-check','returncode':1}]}}
        body=publication.readable([{'commit':completed['commit'],'evidence':evidence}],{state['id']:later},self.root)
        self.assertIn('Final receipt: `'+fresh['id']+'`',body)
        self.assertIn('history-sensitive: passed',body)
        self.assertNotIn('later-only-check',body)
        self.assertIn('later-incomplete: unfinished',body)
        # A separate approved Deliver can repair a shared prerequisite. Resuming
        # the original additional review preserves its owner and both commits.
        original_run=state['id'];original_records=journal.records()
        native.review(self.root,['task','1'],self.resume_choice())
        self.approve([{'id':'shared-repair','title':'Repair shared prerequisite','instructions':'Add the shared prerequisite for verification.','needs':[]}])
        repair_run=load_run(self.root)[1]['id'];self.assertNotEqual(repair_run,original_run)
        self.assess();self.implement(edit=lambda:(self.root/'shared.txt').write_text('ready\n',newline='\n'))
        repair_review=self.reviewed();repair_commit=native.complete(self.root,repair_review['id'])
        repair_state=load_run(self.root)[1]
        native.resume(self.root,self.resume_choice(run=original_run),run=original_run)
        self.assertEqual(load_run(self.root)[1]['id'],original_run)
        final_review=self.reviewed();checked=native.complete(self.root,final_review['id'])
        self.assertFalse(checked['committed'])
        resumed=load_run(self.root)[1]
        self.assertEqual(self.git('rev-parse','HEAD'),repair_commit['commit'])
        self.assertFalse(resumed.get('extra_review'))
        self.assertEqual(journal.records()[:len(original_records)],original_records)
        records=[{'commit':completed['commit'],'evidence':evidence},
                 {'commit':repair_commit['commit'],'evidence':repair_state['commit_intents']['shared-repair']['publication']}]
        combined=publication.readable(records,{original_run:resumed,repair_run:repair_state},self.root)
        self.assertIn(fresh['id'],combined);self.assertIn(repair_review['id'],combined)
        for record in records:publication.verify_record(self.root,record['commit'],record['evidence'])
        self.assertEqual(self.git('status','--porcelain'),'')

    def test_stop_refuses_unsettled_native_child_and_resume_never_renews_allowance(self):
        from . import native
        self.approve();self.assess();attempt=native.admit(self.root,'implementation')
        before=load_run(self.root)[1]
        with self.assertRaises(Refused):native.decision(self.root,'stop',self.human('stop'))
        self.assertEqual(native.resume(self.root)['granted'],before['granted'])
        native.bind(self.root,attempt['id'],{})
        self.native_results[attempt['id']]={'text':'Host confirms the child was cancelled.','status':'interrupted'}
        native.retain(self.root,attempt['id'],{})
        native.decision(self.root,'stop',self.human('stop'))
        with self.assertRaises(Refused):native.admit(self.root,'implementation')
        native.resume(self.root,self.resume_choice(session='new-session',host='claude'))
        after=load_run(self.root)[1]
        self.assertEqual(after['granted'],before['granted']);self.assertEqual(after['config'],before['config'])
        self.assertEqual(len(after['attempts']),len(before['attempts']))
        self.assertEqual(after['attempts'][-1]['outcome'],'interrupted')

    def test_journal_tampering_cannot_rewrite_task_authority(self):
        self.approve();journal,state=load_run(self.root)
        grant=next(record for record in journal.records() if record['kind']=='grant')
        path=journal.path/f"{grant['sequence']:06}.json";value=json.loads(path.read_text());value['data']['tasks']=['unauthorized']
        path.write_text(json.dumps(value),newline='\n')
        with self.assertRaises(Refused):journal.records()

    def test_outside_scope_followups_preserve_ready_work_and_remain_visible(self):
        from . import native,scope,publication
        from .cli import main
        from .mcp_server import command
        self.approve();self.assess();self.implement()
        finding={'severity':'scope','description':'A separate indexing task is needed.','family':'index','path':'index.py'}
        review=self.reviewed({'verdict':'scope','summary':'Approved behavior is ready.','findings':[finding]})
        state=load_run(self.root)[1];before=self.git('status','--porcelain')
        self.assertIsNone(native.select(self.root)['continuation']['pending_decision'])
        self.assertEqual(scope.track(self.root,review['id'])['destination'],{'saved':True})
        # Tracking facts do not consume a human source, change scope, or renew a budget.
        issue='https://github.com/example/product/issues/158'
        journal=load_run(self.root)[0];records=journal.records()
        with patch('sys.stdout',new=io.StringIO()),patch('sys.stderr',new=io.StringIO()) as error:
            with self.assertRaises(SystemExit) as refused:
                main(['--root',str(self.root),'finding-track',review['id'],'--destination',issue.replace('/issues/','/pull/')])
        self.assertEqual(refused.exception.code,2)
        self.assertIn('Supply the actual created or linked issue URL',error.getvalue())
        self.assertEqual(journal.records(),records)
        for arguments in (['finding-track',review['id'],'--destination',issue],
                          command('finding_track',{'attempt':review['id'],'destination':{'issue':issue}},self.root)):
            with patch('sys.stdout',new=io.StringIO()) as output:
                main(['--root',str(self.root),*arguments])
            tracked=json.loads(output.getvalue())
            self.assertEqual(tracked['destination'],{'issue':issue})
            self.assertFalse(tracked['candidate_changed'])
            self.assertFalse(tracked['requires_review'])
            self.assertIn(issue,(journal.path/'index.md').read_text())
        self.assertEqual(len(journal.records()),len(records)+1)
        self.assertEqual(scope.track(self.root,review['id'])['destination'],{'issue':issue})
        after=load_run(self.root)[1]
        for key in ('decisions','granted','scope_id','config'):self.assertEqual(after[key],state[key])
        self.assertEqual(self.git('status','--porcelain'),before)
        native.complete(self.root,review['id'])
        self.assertIn(finding['description'],(load_run(self.root)[0].path/'index.md').read_text())
        self.assertEqual(native.select(self.root)['followups']['count'],1)
        self.assertEqual(scope.followups(load_run(self.root)[1])[0]['destination'],{'issue':issue})
        evidence=load_run(self.root)[1]['commit_intents']['1']['publication']
        publication.validate_evidence(evidence)
        self.assertEqual(evidence['attempts'][0]['findings'],[finding])

    def test_scope_routing_and_concern_acceptance_are_separate_exact_subject_decisions(self):
        from . import native
        self.approve();self.assess();self.implement()
        concern={'severity':'concern','description':'Optional timeout wording.','family':'wording','path':'output.txt'}
        scope={'severity':'scope','description':'Logout cleanup belongs to later work.','family':'logout','path':'logout.py'}
        review=self.reviewed({'verdict':'concern','summary':'Two distinct dispositions.','findings':[concern,scope]})
        with self.assertRaises(Refused):
            native.decision(self.root,'accept-concerns',self.human('Do not accept concerns; fix them.'),attempt=review['id'])
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        from .decisions import prepare as decision_request
        from .storage import now
        offer=decision_request(self.root,'accept-concerns',attempt=review['id'])
        self.assertEqual(offer['options'],['Accept concerns · '+self.tasks[0]['title'],'Fix concerns'])
        before=load_run(self.root)[1]
        for answer in ('Fix concerns','Not now'):
            with self.assertRaises(Refused):
                native.decision(self.root,'accept-concerns',self.human(answer,question=offer['question'],question_at=now(),decision=offer['decision'],via='question'),attempt=review['id'])
        self.assertEqual(load_run(self.root)[1],before)
        native.decision(self.root,'accept-concerns',self.offered_answer(offer,offer['options'][0]),attempt=review['id'])
        state=load_run(self.root)[1]
        from .publication import task_evidence
        # Concern acceptance is complete even while the outside-scope work stays saved.
        task_evidence(self.root,state,state['tasks'][0],review,review['head'])
        issue='https://github.com/example/product/issues/19'
        from .scope import track
        track(self.root,review['id'],{'issue':issue})
        state=load_run(self.root)[1]
        self.assertEqual(state['scope_records'][review['id']]['findings'],[scope])
        self.assertIn(issue,json.dumps(state['scope_records']))
        self.assertEqual(state['attempts'][-1]['findings'],[concern,scope])
        native.complete(self.root,review['id'])
        self.assertEqual(load_run(self.root)[1]['done'],['1'])
        from . import publication
        self.git('remote','add','origin','https://github.com/example/product.git')
        native.decision(self.root,'publish',self.human('publish',question='Publish the reviewed work branch to example/product?'))
        self.assertIn(issue,publication.render(self.root))
        from copy import deepcopy
        state=load_run(self.root)[1];evidence=state['commit_intents']['1']['publication']
        for issue_reference in (issue,{'url':issue}):
            for scope_record in (True,False):
                historical=deepcopy(state);portable=deepcopy(evidence)
                historical['resolutions'][review['id']]['issue']=issue_reference
                portable['resolutions'][review['id']]['issue']=issue_reference
                if scope_record:
                    historical['scope_records'][review['id']]['destination']['issue']=issue_reference
                    portable['scope'][review['id']]['destination']['issue']=issue_reference
                else:
                    historical['scope_records']={};portable.pop('scope',None)
                with self.subTest(issue_reference=issue_reference,historical_scope=scope_record):
                    rendered=publication.readable([{'commit':self.git('rev-parse','HEAD'),'evidence':portable}],{state['id']:historical})
                    self.assertIn(issue,rendered)
                    from .receipts import index as receipt_index
                    journal=load_run(self.root)[0]
                    receipt_index(journal,historical)
                    self.assertIn(issue,(journal.path/'index.md').read_text())
        historical=deepcopy(evidence)
        record=historical['scope'][review['id']]
        record.update(action='dismiss',destination={'design':'docs/design/0900-fixture.md','section':'## Scope decisions'})
        resolution=historical['resolutions'][review['id']]
        resolution.update(choice='accept concerns and dismiss scope',scope=record)
        resolution.pop('issue',None)
        publication.validate_evidence(historical)
        record['destination']['section']='## Unrecorded decisions'
        with self.assertRaises(Refused):publication.validate_evidence(historical)

    def test_standalone_review_after_stop_is_feedback_and_preserves_the_original_run(self):
        from . import native
        self.approve();self.assess();self.implement()
        native.decision(self.root,'stop',self.human('stop'))
        original_journal,original=load_run(self.root);records=original_journal.records();head=self.git('rev-parse','HEAD')
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'s'}):
            standalone=native.review(self.root,['tree'])
            reviewed=self.finish_attempt('review',{'verdict':'clean','summary':'Feedback on the stopped changes.','findings':[]})
            packet=json.loads((Path(reviewed['evidence'])/'task-context.json').read_text())
            self.assertEqual(packet['purpose'],'standalone')
            self.assertTrue(packet['standalone_subject'])
            self.assertNotIn('human_scope_approval',packet)
            self.assertNotIn('original_scope_provenance',packet)
            with self.assertRaises(Refused):native.complete(self.root,reviewed['id'])
            with self.assertRaises(Refused):native.admit(self.root,'implementation')
        self.assertNotEqual(standalone['run'],original['id'])
        self.assertEqual(original_journal.records(),records)
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertEqual(original['granted'],['1'])
        feedback=Journal(self.project_id,standalone['run']);feedback_records=feedback.records()
        from .storage import checkout_file
        pointer=checkout_file(self.root,'oh-active-review.json');binding=pointer.read_bytes()
        # Upgrading registration must preserve a stopped delivery, completed feedback,
        # and the spent review round before either host's saved-work discovery runs.
        from .test_registry import legacy_registration
        legacy_registration(self.root,remounted=True,birth=False)
        from .cli import main
        from .mcp_server import command
        import contextlib
        for arguments in (['status','--saved'],command('status',{'saved':True},self.root)):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):main(['--root',str(self.root),*arguments])
            saved=json.loads(output.getvalue())['saved_work']
            self.assertEqual({item['run'] for item in saved},{original['id'],standalone['run']})
        self.assertEqual(original_journal.records(),records)
        self.assertEqual(feedback.records(),feedback_records)
        self.assertEqual(native.resume(self.root)['run'],original['id'])
        self.assertEqual(pointer.read_bytes(),binding)
        discovered=native.saved_work(self.root)['saved_work']
        self.assertEqual({item['run'] for item in discovered},{original['id'],standalone['run']})
        self.assertFalse(next(item for item in discovered if item['workflow']=='review')['resumable'])
        resumed=native.resume(self.root,self.resume_choice(session='delivery-parent'))
        self.assertEqual(resumed['run'],original['id'])
        self.assertEqual(resumed['granted'],original['granted'])
        self.assertEqual(load_run(self.root)[1]['attempts'],original['attempts'])
        self.assertEqual(feedback.records(),feedback_records)
        continuation=native.admit(self.root,'implementation')
        self.assertEqual(continuation['task'],'1')

    def test_legacy_resume_preserves_original_findings_and_consumed_review_allowance(self):
        from . import native
        from .storage import checkout_file, checkout_id, read_json
        configure(self.root,review_rounds=2)
        self.approve();self.assess();self.implement()
        first=self.reviewed({'verdict':'blocking','summary':'Original blocker.','findings':[
            {'severity':'blocking','description':'Retain this original defect.','family':'legacy','path':'output.txt'}]})
        journal,state=load_run(self.root);legacy=Journal(self.project_id,identifier())
        data=dict(journal.records()[0]['data']);data['id']=legacy.path.name
        for key in ('native_version','scope_id','scope_snapshot'):data.pop(key,None)
        legacy.append('run.started',data)
        for record in journal.records()[1:]:legacy.append(record['kind'],record['data'])
        atomic_json(checkout_file(self.root,'oh-active-run.json'),
                    {'project':self.project_id,'run':legacy.path.name,'checkout':checkout_id(self.root)})
        original=legacy.records();before=reduce(original);result=read_json(Path(first['evidence'])/'result.json')
        self.assertEqual(before['status'],'running')
        with self.assertRaisesRegex(Refused,'predates'):
            native.resume(self.root,self.resume_choice(session='fresh-session',at=original[0]['at']))
        self.assertEqual(legacy.records(),original)
        self.assertNotIn('native_version',load_run(self.root)[1])
        resumed=native.resume(self.root,self.resume_choice(session='fresh-session'))
        self.assertEqual(resumed['granted'],state['granted'])
        self.assertEqual((resumed['reviews_used'],resumed['reviews_allowed']),(1,2))
        after=load_run(self.root)[1]
        self.assertEqual(after['config'],state['config']);self.assertEqual(after['attempts'],before['attempts'])
        self.assertEqual(legacy.records()[:len(original)],original)
        self.assertEqual(read_json(Path(first['evidence'])/'result.json'),result)
        self.assertNotIn('recovery_grants',after)
        live=native.admit(self.root,'implementation')
        packet=read_json(live['task_context']['path'])
        self.assertNotIn('human_scope_approval',packet)
        provenance=Path(packet['original_scope_provenance']['path'])
        self.assertEqual(provenance,legacy.path/'000001.json')
        self.assertEqual(read_json(provenance),original[0])
        from .authority import Saving
        with patch('oh.authority.native_result',side_effect=Saving('Native result pending')),self.assertRaises(Refused):
            native.resume(self.root,self.resume_choice(session='other-session'))
        self.assertEqual(load_run(self.root)[1]['attempts'][-1]['id'],live['id'])

    def test_publication_reuses_the_existing_pr_and_unknown_discovery_does_not_reopen_work(self):
        from . import native, publication
        configure(self.root,context={'result_chars':1000})
        self.git('remote','add','origin','https://github.com/example/product.git')
        (self.root/'manual.txt').write_text('Existing manual PR work to review.',newline='\n')
        self.git('add','.');self.git('commit','-qm','manual PR starting work')
        manual=self.git('rev-parse','HEAD');base=self.git('rev-parse','origin/main')
        pr=pull_request({'publication':{'destination':'https://github.com/example/product.git',
            'base_branch':'main','branch':'work','head':manual}})
        from . import branches, prepared
        run_git=branches.run_git
        def local_fetch(root,*args,**kwargs):
            if args[:3]==('fetch','--quiet','origin'):
                return run_git(root,'fetch','--quiet',str(self.root),*args[3:],**kwargs)
            return run_git(root,*args,**kwargs)
        manifest=Path(self.temp.name)/'correction-tasks.json'
        atomic_json(manifest,{'tasks':self.tasks[:1]})
        with patch('oh.publication.github',return_value=pr),patch('oh.branches.run_git',side_effect=local_fetch):
            selected=prepared.prepare(self.root,manifest=manifest,pr=144)
        scope=json.loads(Path(selected['preview']).with_name('scope.json').read_text())
        self.assertNotIn('repair_source',scope)
        self.assertEqual(scope['pr_target']['covers'],[manual])
        self.assertEqual(scope['pr_target']['review_base'],base)
        self.assertIn(manual[:12],Path(selected['preview']).read_text())
        native.approve_scope(self.root,selected['scope_id'],self.human())
        self.assess();self.implement()
        # This report used to exceed the PR budget when OH copied its finding
        # into both the readable history and the hidden machine packet.
        claim='Concrete historical defect with extensive supporting detail. '*600
        first=self.reviewed({'verdict':'blocking','summary':'Needs repair.',
            'findings':[{'severity':'blocking','family':'large-report','description':claim}]})
        self.implement()
        review=self.reviewed({'verdict':'clean','summary':'Rechecked the repair.',
            'findings':[],'evidence':EVIDENCE})
        packet=json.loads((Path(review['evidence'])/'task-context.json').read_text())
        if packet.get('details'):packet=json.loads((Path(review['evidence'])/packet['details']['path']).read_text())
        self.assertEqual(packet['included_original_work']['covers'],[manual])
        self.assertEqual(packet['included_original_work']['url'],scope['pr_target']['url'])
        native.complete(self.root,review['id'])
        for text in ('approve','Do not publish. Keep the work local.','No, publish nothing.'):
            with self.assertRaises(Refused):native.decision(self.root,'publish',self.human(text))
        question='Publish the reviewed work branch to example/product?'
        with self.assertRaises(Refused):
            native.decision(self.root,'publish',self.human('publish',question=question,question_at='2000-01-01T00:00:00+00:00'))
        short_question='The completed tasks are committed and reviewed clean. Open a PR or preserve local work?'
        with self.assertRaisesRegex(Refused,'branch and repository destination'):
            native.decision(self.root,'publish',self.human('publish',question=short_question))
        from .decisions import prepare as decision_request
        from .storage import now
        offer=decision_request(self.root,'publish')
        self.assertEqual(offer['options'],['Open PR to example/product → main','Stop and take over'])
        choice=self.offered_answer(offer,offer['options'][-2])
        native.decision(self.root,'publish',choice)
        native.decision(self.root,'publish',choice)
        journal,state=load_run(self.root);grant=state['publication'];attempts=state['attempts']
        with patch('oh.publication.github',side_effect=Refused('GitHub temporarily unavailable.')):
            with self.assertRaises(Refused):publication.reconcile(self.root)
        self.assertEqual(load_run(self.root)[1]['publication'],grant)
        body=publication.render(self.root)
        self.assertIn(manual,body)
        self.assertIn('## Task 1',body)
        self.assertIn('Review rounds: **2**',body)
        self.assertIn('Final receipt: `'+review['id']+'`',body)
        self.assertIn('### Final evidence manifest',body)
        self.assertIn('### Findings and dispositions',body)
        self.assertIn('**fixed**',body)
        self.assertIn('## Stop reason',body)
        self.assertIn('After task 1: pr; permitted tasks: none;',body)
        self.assertNotIn('(journal ',body)
        self.assertEqual(body.count(claim.strip()),1)
        self.assertNotIn('oh-review:start',body)
        self.assertNotIn('```json',body)
        self.assertEqual(json.loads((Path(first['evidence'])/'result.json').read_text())['findings'][0]['description'],claim)
        # A host-written narrative may summarize long receipts without losing
        # the exact publication identity. Missing/stale/duplicate IDs stay pending.
        from copy import deepcopy
        tampered=deepcopy(state)
        tampered['commit_intents']['1']['publication']['title']='Unreviewed replacement title'
        with patch('oh.publication.made',return_value=tampered),self.assertRaisesRegex(Refused,'differs from committed OH-Evidence'):
            publication.render(self.root)
        publication_key=publication.summary_identity(body)
        identity='<!-- oh-publication:'+publication_key+' -->'
        stale_key=('0' if publication_key[0]!='0' else '1')+publication_key[1:]
        pr=pull_request(state)|{'body':'A concise narrative composed by the native host.\n'+identity}
        with patch('oh.publication.github',return_value=pr):
            for invalid in ('No publication identity.','<!-- oh-publication:'+stale_key+' -->',identity+'\n'+identity):
                pr['body']=invalid
                self.assertTrue(publication.discover(self.root,state)['pending_update'])
            pr['body']='A concise narrative composed by the native host.\n'+identity
            self.assertFalse(publication.discover(self.root,state)['pending_update'])
        def github(root,host,path,**kwargs):return [pr] if kwargs.get('pages') else pr
        with patch('oh.publication.github',side_effect=github):
            saved=publication.reconcile(self.root)
            recorded=journal.records()
            self.assertNotIn('published',native.select(self.root))
            repeated=publication.reconcile(self.root)
            self.assertEqual(journal.records(),recorded)
        self.assertEqual(saved['published']['number'],144)
        receipt=load_run(self.root)[1]['published']
        self.assertEqual(saved['published'],receipt)
        self.assertEqual(repeated['published'],receipt)
        self.assertEqual(saved['publication_status'],'current')
        self.assertEqual(receipt['url'],pr['html_url'])
        self.assertEqual(receipt['approved_head'],grant['head'])
        # A compact checkpoint cannot hide the saved PR link during a lookup outage.
        with patch('oh.publication.github',side_effect=Refused('GitHub temporarily unavailable.')):
            offline=publication.reconcile(self.root)
        self.assertEqual(offline['publication_status'],'last verified')
        self.assertEqual(offline['published'],receipt)
        self.assertEqual(journal.records(),recorded)
        self.assertEqual(load_run(self.root)[1]['attempts'],attempts)
        # CI is followed on the published reviewed head until a meaningful result; an empty,
        # pending, skipped, failed or cancelled set never reads as a pass.
        import time
        published=load_run(self.root)[1]['published'];history=journal.records()
        def done(conclusion,name='verify'):return {'name':name,'status':'completed','conclusion':conclusion}
        def follow(steps,timeout=3600):
            from urllib.parse import urlsplit,parse_qs
            polls=iter(steps);current={};now=[time.time()]
            def read(root,host,endpoint):
                if '/pulls/' in endpoint:
                    step=next(polls,steps[-1])
                    if isinstance(step,Exception):raise step
                    current.clear();current.update(step)
                    return pull_request(state,head=current.get('head',published['observed_head']))
                url=urlsplit(endpoint);page=int(parse_qs(url.query).get('page',['1'])[0])
                status=url.path.endswith('/status');key='statuses' if status else 'check_runs'
                items=[dict(item,id=i) for i,item in enumerate(current.get('statuses' if status else 'runs',[]))]
                values=items[(page-1)*100:page*100]
                if page>1 and current.get('truncated'):values=[]
                result={key:values,'total_count':len(items)}
                if status:
                    states={x['state'] for x in items}
                    result['state']=current.get('combined_state') or ('failure' if states&{'failure','error'} else 'pending' if not items or 'pending' in states else 'success')
                return result
            def sleep(seconds):now[0]+=seconds
            with patch('oh.observability.observe_ci'):
                result=publication.ci_wait(self.root,None,timeout,read=read,sleep=sleep,clock=lambda:now[0])
            self.assertEqual(result['url'],published['url'])
            return result
        registering=[{},{'runs':[{'name':'verify','status':'in_progress'}],'statuses':[{'context':'legacy','state':'pending'}]},
                     {'runs':[done('success'),done('skipped','optional')],'statuses':[{'context':'legacy','state':'success'}]}]
        for steps,outcome in ((registering,'pass'),([{'runs':[done('success'),done('failure','lint')]}],'fail'),
                              ([{'runs':[done('cancelled')]}],'fail'),([{'runs':[done('skipped')]}],'skipped'),
                              ([{}],'no_checks'),([{'head':'f'*40}],'head_changed'),
                              ([Refused('GitHub temporarily unavailable.')],'unavailable')):
            with self.subTest(outcome=outcome,steps=len(steps)):
                result=follow(steps)
                self.assertEqual((result['outcome'],result['pr'],result['head']),(outcome,144,published['observed_head']))
        self.assertEqual(follow([{'runs':[done('success'),done('failure','lint')]}])['not_passed'],['lint'])
        self.assertEqual(follow([{'runs':[{'name':'verify','status':'queued'}]}],timeout=60)['outcome'],'pending')
        # A successful first page never hides failed or pending checks on later
        # pages, for either GitHub result source. Incomplete reads cannot pass.
        for kind in ('runs','statuses'):
            success=done('success') if kind=='runs' else {'context':'legacy','state':'success'}
            for ending,outcome in (('failure','fail'),('pending','pending'),('success','pass')):
                last=({'name':'last','status':'queued'} if ending=='pending' else done(ending,'last')) if kind=='runs' else {'context':'last','state':ending}
                with self.subTest(kind=kind,ending=ending):
                    result=follow([{kind:[success]*100+[last]}],timeout=60)
                    self.assertEqual(result['outcome'],outcome)
                    self.assertEqual(len(result['checks']),101)
            self.assertEqual(follow([{kind:[success]*101,'truncated':True}])['outcome'],'unavailable')
        self.assertEqual(follow([{'statuses':[{'context':'legacy','state':'success'}],'combined_state':'failure'}])['outcome'],'unavailable')
        # Discovery may legitimately recover a PR already advanced beyond the approved
        # commit. That observed head never becomes the reviewed CI subject, including
        # when reading an older publication record with those differing identities.
        advanced=published|{'observed_head':'f'*40}
        requests=[]
        def changed_head(root,host,endpoint):
            requests.append(endpoint)
            if '/pulls/' in endpoint:return pull_request(state,head=advanced['observed_head'])
            return {'check_runs':[done('success')]}
        with patch('oh.workflow.load_run',return_value=(journal,state|{'published':advanced})):
            result=publication.ci_wait(self.root,read=changed_head)
        self.assertEqual((result['outcome'],result['head'],result['observed_head']),
                         ('head_changed',published['approved_head'],advanced['observed_head']))
        self.assertEqual(requests,[f'repos/{published["repository"]}/pulls/{published["number"]}'])
        with self.assertRaisesRegex(Refused,'only that PR'):publication.ci_wait(self.root,145)
        self.assertEqual(journal.records(),history)
        with self.assertRaises(Refused):native.admit(self.root,'implementation')
        history=journal.records()
        self.approve([self.tasks[0]|{'instructions':'A separate bounded follow-up.'}])
        self.assertNotEqual(load_run(self.root)[1]['id'],state['id'])
        self.assertEqual(journal.records(),history)


if __name__=='__main__':unittest.main()
