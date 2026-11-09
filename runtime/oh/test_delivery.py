import json
from pathlib import Path
import unittest
from unittest.mock import patch
from . import delivery,plans
from .config import change
from .storage import digest,Refused,read_json
from .workflow import load_run
from .authority import coordinator as native_coordinator
from . import test_fixtures_workflow as fixtures
from .test_fixtures_plans import BODY, delivery_documents


class DeliveryRequestTest(unittest.TestCase):
    def test_design_choice_binds_delivery_effect_for_menu_and_typed_reply(self):
        for via in ('question','typed'):
            source={'prompt':'0001','via':via,'question':delivery.DESIGN_QUESTION}
            delivery.requested(source,'0001','',None)
            with self.assertRaises(Refused):delivery.requested(source,'0002','',None)
            with self.assertRaises(Refused):
                delivery.requested(source|{'question':'Which design should I inspect before we deliver 0001?'},'0001','',None)


    def test_action_identifies_selected_design_even_with_an_agent_written_question(self):
        choice='Deliver 0001 core'
        menu={'via':'question','question':'Which work would you like to start?', 'prompt':choice,
              'question_options':['Deliver 0001 other',choice]}
        delivery.requested(menu,'0001','core',None)
        recommended=menu|{'prompt':choice+' (Recommended)','question_options':[choice+' (Recommended)','Deliver 0001 other']}
        delivery.requested(recommended,'0001','core',None)
        with self.assertRaises(Refused):delivery.requested(recommended,'0001','other',None)
        with self.assertRaises(Refused):delivery.requested(menu,'0001','other',None)
        with self.assertRaises(Refused):delivery.requested(menu|{'question_options':['Inspect 0001 core']},'0001','core',None)

    def test_explicit_typed_request_binds_design_and_track(self):
        from .native import _command
        for text in ('Deliver 0001 core','Please implement design 0001 track core.','/oh-deliver 0001 core'):
            source={'prompt':text,'via':'typed'}
            delivery.requested(source,'0001','core',_command(source))
            for doc,track in (('0002','core'),('0001','ui'),('0001','')):
                with self.subTest(text=text,doc=doc,track=track),self.assertRaisesRegex(Refused,'different design or track'):
                    delivery.requested(source,doc,track,_command(source))
        delivery.requested({'prompt':'Please deliver 0001.'},'0001','',None)


class DeliveryTest(fixtures.NativeFixture):
    def setUp(self):
        super().setUp()
        self.git('switch','main')
        fixtures.configure(self.root,tasks_per_batch=1)

    documents=delivery_documents

    def test_checkpoint_explains_saved_design_without_expanding_selection(self):
        from .decisions import _checkpoint
        body=('## 5. Open decisions\n\nChoose the storage owner.\n\n## Tasks\n\n### Core track\n\n'
              '- [ ] **1.** Store credentials.\n'
              '- [ ] **2.** Add sign-in. Depends on task 1.\n'
              '- [ ] **3.** Add recovery. Depends on task 2. Blocked on §5.\n'
              '- [ ] **4.** Test recovery. Depends on task 3.\n'
              '\n### UI track\n\n- [ ] **5.** Show sign-in. Depends on task 2.\n')
        _,path=self.documents(body=body)
        manifest,extra=delivery.selection(self.root,'0001','core')
        self.assertEqual([t['id'] for t in manifest['tasks']],['1','2'])
        original=path.read_text()
        state=manifest|extra|{'status':'checkpoint','branch':self.git('branch','--show-current'),'done':['1'],'summaries':[{}],
            'granted':['1'],'config':{'tasks_per_batch':1},'attempts':[],
            'human':{'host':'codex','session':'checkpoint'},
            'scope_snapshot':{'documents':{str(path):original}}}
        with patch('oh.publication.settled'),patch('oh.publication.destination',return_value=None):
            ready=_checkpoint(self.root,state,'continue','Work: saved design')
            self.assertIn('Continue authorizes tasks: 2',ready['disclosure'])
            self.assertIn('Pending task 3',ready['disclosure'])
            self.assertIn('blocked on §5',ready['disclosure'])
            self.assertIn('requires completed task(s): 3',ready['disclosure'])
            self.assertIn('belongs to another track: ui',ready['disclosure'])
            self.assertEqual(set(ready['choices']),{'continue','stop'})
            completed=state|{'status':'completed','done':['1','2'],'granted':['1','2']}
            blocked=_checkpoint(self.root,completed,'publish','Work: saved design')
            self.assertEqual(set(blocked['choices']),{'stop'})
            self.assertIn('Selected work is complete;',blocked['disclosure'])
            self.assertIn('get the revised design approved through Design',blocked['disclosure'])
            # A local edit cannot silently remove the saved blocker from an offer.
            path.write_text(original.replace(' Blocked on §5.',''),newline='\n')
            self.assertEqual(_checkpoint(self.root,completed,'publish','Work: saved design'),blocked)
            # Pre-fix runs use their existing starting authority, with no migration.
            older={k:v for k,v in completed.items() if k!='scope_snapshot'}
            self.assertEqual(_checkpoint(self.root,older,'publish','Work: saved design'),blocked)
            with patch('oh.publication.destination',return_value={'destination':'example/product'}), \
                    patch('oh.storage.changes',return_value=[]),patch('oh.decisions.state_head',return_value='reviewed'), \
                    patch('oh.branches.trunk',return_value='main'):
                published=completed|{'summaries':[{'commit':'reviewed'}]}
                offer=_checkpoint(self.root,published,'publish','Work: saved design')
                self.assertEqual(set(offer['choices']),{'publish','stop'})
                self.assertIn('blocked on §5',offer['disclosure'])
            done=completed|{'done':['1','2','3','4','5']}
            final=_checkpoint(self.root,done,'publish','Work: saved design')
            self.assertIn('Design complete: all approved design tasks are complete.',final['disclosure'])
            self.assertNotIn('Pending task',final['disclosure'])
        self.assertEqual([t['id'] for t in state['tasks']],['1','2'])
        self.assertEqual(state['granted'],['1'])

    def _track_selection(self,host,typed=False):
        import os
        from datetime import datetime,timedelta,timezone
        from itertools import count
        from . import native
        started=datetime.now(timezone.utc);ticks=count()
        # Native records have an explicit order even on hosts with coarse clocks.
        def now():return (started+timedelta(microseconds=next(ticks))).isoformat()
        self.documents(body='## Tasks\n\n### Core track\n\n- [ ] **1.** Core behavior.\n\n### UI track\n\n- [ ] **2.** UI behavior.\n')
        home=Path(self.temp.name)/'native';session='track-selection'
        path=home/('.codex/sessions' if host=='codex' else '.claude/projects/p')/(session+'.jsonl')
        path.parent.mkdir(parents=True)
        def human(text):
            return ({'type':'event_msg','timestamp':now(),'payload':{'type':'user_message','turn_id':'entry','message':text}}
                    if host=='codex' else {'type':'user','sessionId':session,'promptId':'entry','cwd':str(self.root),
                        'timestamp':now(),'message':{'role':'user','content':text}})
        rows=([{'type':'session_meta','payload':{'id':session,'source':'cli','cwd':str(self.root)}}] if host=='codex' else [])
        rows.append(human('/oh-deliver 0001'))
        def save():path.write_text(''.join(json.dumps(row)+'\n' for row in rows),newline='\n')
        save()
        locator={'host':host,'session':session,'transcript_path':str(path)}
        request=locator|{'turn':'entry','prompt':'/oh-deliver 0001'}
        question=delivery.track_question('0001');answer='Core (recommended)';use='select-track'
        env={'CODEX_HOME':str(home/'.codex'),'CODEX_THREAD_ID':session if host=='codex' else '',
             'OH_NATIVE_SESSION_ID':session if host=='claude' else ''}
        with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,env), \
                patch('oh.authority.native_human',side_effect=self.native_human_original), \
                patch('oh.authority.coordinator',side_effect=native_coordinator):
            with self.assertRaisesRegex(Refused,'Choose one design track'):
                native.prepare_scope(self.root,doc='0001',human=request)
            if typed:
                rows.extend([{'type':'response_item','timestamp':now(),'payload':{'type':'message','role':'assistant',
                    'content':[{'type':'output_text','text':question}]}},human(answer)])
                reply=locator|{'turn':'entry','prompt':answer}
            elif host=='codex':
                rows.extend([{'type':'response_item','timestamp':now(),'payload':{'type':'function_call','call_id':use,
                    'name':'request_user_input_async','arguments':json.dumps({'questions':[{'title':question,'options':[answer,'UI']}]})}},
                    human('<send_user_message_question_reply>'+json.dumps([{'questionItemId':json.dumps(['request_user_input_async',use,0]),
                        'question':question,'answer':answer}])+'</send_user_message_question_reply>')])
                reply=locator|{'tool_use_id':use}
            else:
                rows.extend([{'type':'assistant','sessionId':session,'cwd':str(self.root),'timestamp':now(),'message':{'content':[
                    {'type':'tool_use','id':use,'name':'AskUserQuestion','input':{'questions':[{'question':question,
                        'options':[{'label':answer},{'label':'UI'}]}]}}]}},
                    {'type':'user','sessionId':session,'cwd':str(self.root),'timestamp':now(),
                     'toolUseResult':{'answers':{question:answer}},'message':{'content':[
                        {'type':'tool_result','tool_use_id':use,'content':'Answered'}]}}])
                reply=locator|{'tool_use_id':use}
            save();branch=self.git('branch','--show-current')
            # A genuine native answer to inspection does not authorize delivery,
            # even when the question mentions the same design and delivery verb.
            saved=path.read_text()
            path.write_text(saved.replace(question,'Which track should I inspect before we deliver 0001?'),newline='\n')
            with self.assertRaisesRegex(Refused,'Request delivery'):
                native.prepare_scope(self.root,doc='0001',track='core',human=reply)
            self.assertEqual(self.git('branch','--show-current'),branch)
            if not typed:
                for label in ('Deliver 0001 core','/oh-deliver 0001 core'):
                    altered=saved.replace(question,'Which track should I inspect before we deliver 0001?').splitlines()
                    altered[-1]=altered[-1].replace(answer,label)
                    path.write_text('\n'.join(altered)+'\n',newline='\n')
                    for selected_track in ('core','ui'):
                        with self.subTest(label=label,track=selected_track),self.assertRaisesRegex(Refused,'Request delivery'):
                            native.prepare_scope(self.root,doc='0001',track=selected_track,human=reply)
                        self.assertEqual(self.git('branch','--show-current'),branch)
            path.write_text(saved,newline='\n')
            # The old request remains stale, and a genuine choice cannot select another track/design.
            if host=='codex':
                with self.assertRaises(Refused):native.prepare_scope(self.root,doc='0001',track='core',human=request)
            for doc,track in (('0001','ui'),('0002','core')):
                with self.assertRaisesRegex(Refused,'Request delivery'):
                    native.prepare_scope(self.root,doc=doc,track=track,human=reply)
                self.assertEqual(self.git('branch','--show-current'),branch)
            selected=native.prepare_scope(self.root,doc='0001',track='core',human=reply)
            self.assertTrue(selected['approved']);self.assertEqual(selected['task']['id'],'1')
            self.assertEqual(load_run(self.root)[1]['track'],'core')
            self.assertEqual(native.prepare_scope(self.root,doc='0001',track='core',human=reply)['run'],selected['run'])
            self.assertEqual(native.admit(self.root,'assessment')['role'],'assessment')
            rows.append(human('Stop'));save()
            with self.assertRaises(Refused):native.prepare_scope(self.root,doc='0001',track='core',human=reply)

    def test_codex_track_selection_continues_delivery(self):self._track_selection('codex')

    def test_claude_track_selection_continues_delivery(self):self._track_selection('claude')

    def test_typed_track_selection_uses_native_question_context(self):self._track_selection('codex',typed=True)

    def test_additional_repair_continues_same_design_through_checks_review_and_publication(self):
        import sys
        from . import native,decisions,publication
        from .storage import now
        check={'name':'fixture setup','command':[sys.executable,'-I','-c',
            'from pathlib import Path; assert Path("fixture.txt").read_text() == "ready"']}
        fixtures.configure(self.root,checks=[check],review_rounds=2)
        _,path=self.documents(body='## Tasks\n\n### Core track\n\n- [ ] **1.** Add the credential store.\n')
        self.git('switch','-c','deliver/0001')
        prepared=native.prepare_scope(self.root,doc='0001')
        native.approve_scope(self.root,prepared['scope_id'],self.human())
        self.assess();self.implement()
        native.candidate(self.root)
        self.assertTrue(native.verify(self.root)['checks'][0]['returncode'])
        with self.assertRaisesRegex(Refused,'configured checks'):native.admit(self.root,'review')
        before=load_run(self.root)[1]
        gate=decisions.prepare(self.root,'approve-repair',repair='Restore the shared fixture required by the credential-store checks; preserve all assertions.')
        answer=self.offered_answer(gate,gate['options'][0])
        native.decision(self.root,'approve-repair',answer)
        journal,approved=load_run(self.root);records=journal.records()
        native.decision(self.root,'approve-repair',answer)
        self.assertEqual(journal.records(),records)
        for key in ('id','scope_snapshot','delivery','tasks','granted','config','project_checks','assessments'):
            self.assertEqual(approved[key],before[key])
        # A fresh conversation retains the added authority rather than requesting it again.
        native.decision(self.root,'resume',self.resume_choice(session='fresh-parent'))
        self.assertEqual(load_run(self.root)[1]['approved_repairs'],approved['approved_repairs'])
        self.implement(edit=lambda:(self.root/'fixture.txt').write_text('ready',newline='\n'))
        review=self.reviewed()
        packet=read_json(Path(review['evidence'])/'task-context.json')
        self.assertEqual(packet['approved_repairs'],approved['approved_repairs']['1'])
        self.assertIn('Restore the shared fixture',(Path(review['evidence'])/'request.md').read_text())
        native.complete(self.root,review['id'])
        final=load_run(self.root)[1]
        self.assertEqual(final['id'],before['id']);self.assertEqual(final['done'],['1'])
        self.assertIn('status: frozen',path.read_text())
        evidence=final['commit_intents']['1']['publication']
        self.assertEqual(evidence['approved_repairs'],approved['approved_repairs']['1'])
        # Later task reviewers need earlier repair authority for accumulated-branch review;
        # later authors must not receive it as authority to extend their own task.
        from .handoff import prepare as handoff
        admission=read_json(Path(review['evidence'])/'request.json')
        for role in ('implementation','review'):
            packet_ref,_=handoff(final,self.tasks[1],role,journal.path/'attempts'/('later-'+role),admission)
            packet=read_json(packet_ref['path'])
            self.assertEqual(packet['approved_repairs'],approved['approved_repairs']['1'] if role=='review' else [])
        self.git('remote','add','origin','https://github.com/example/product.git')
        native.decision(self.root,'publish',self.human('publish',session='fresh-parent',question='Publish deliver/0001 to example/product?'))
        self.assertIn('Restore the shared fixture',publication.render(self.root))

    def test_private_progress_keeps_reviewed_code_lineage_and_rejects_another_checkout(self):
        from . import native
        where,path=self.documents('private')
        self.git('switch','-c','deliver/private-fixture')
        prepared=native.prepare_scope(self.root,doc='0001')
        native.approve_scope(self.root,prepared['scope_id'],self.human())
        self.assess();self.implement();review=self.reviewed()
        completed=native.complete(self.root,review['id'])
        approval=read_json(plans.approvals_file(self.root))['0001']
        self.assertEqual(approval['delivery_commit'],completed['commit'])
        self.assertEqual(approval['delivery_base'],prepared.get('base',load_run(self.root)[1]['base']))
        self.assertIn('- [x] **1.**',path.read_text())
        delivery.delivered_base(self.root,approval,progressed=True)
        self.git('checkout','HEAD^')
        with self.assertRaises(Refused):delivery.delivered_base(self.root,approval,progressed=True)

    def test_listing_does_not_claim_private_storage(self):
        from .storage import state_home
        change(self.root,'plans.private_folder',str(Path(self.temp.name)/'empty-plans'))
        change(self.root,'plans.location','private')
        registry=state_home()/'registry/private-plans.json'
        registry.unlink(missing_ok=True)
        self.assertEqual(delivery.listing(self.root)['ready'],[])
        self.assertEqual(delivery.listing(self.root)['source'],'checkout')
        self.assertFalse(registry.exists())
        self.documents('private');before=registry.read_bytes()
        self.assertEqual(len(delivery.listing(self.root)['ready']),1)
        self.assertEqual(registry.read_bytes(),before)

    def test_deliberately_selected_checkout_skips_updates_but_preserves_approval_checks(self):
        from . import native
        from unittest.mock import patch
        _,path=self.documents()
        self.git('switch','-c','deliver/0001')
        (self.root/'notes.txt').write_text('keep my work',newline='\n')
        head=self.git('rev-parse','HEAD');before=self.git('status','--porcelain')
        with patch('oh.branches.fetched',side_effect=AssertionError('the chosen checkout must stay selected')):
            prepared=native.prepare_scope(self.root,doc='0001',keep_checkout=True)
            self.assertFalse(prepared['approved'])
            self.assertEqual(self.git('branch','--show-current'),'deliver/0001')
            self.assertEqual(self.git('rev-parse','HEAD'),head)
            self.assertEqual(self.git('status','--porcelain'),before)
            with self.assertRaisesRegex(Refused,'Request delivery of this approved design explicitly'):
                native.prepare_scope(self.root,doc='0001',keep_checkout=True,human=self.human('Stop the work'))

    def test_interrupted_idle_design_with_missing_branch_does_not_reserve_new_delivery(self):
        import io
        from . import native,cancellation
        from .cli import main
        from .mcp_server import command
        self.documents();self.git('switch','-c','design/old-auth')
        native.prepare_scope(self.root,{'tasks':[{'id':'decisions','title':'Record auth decisions',
                             'instructions':'Record the chosen auth decisions.'}]},workflow='design',
                             human=self.human('/oh-design auth'))
        self.finish_attempt('analysis',{'status':'completed','summary':'Decision text retained.'})
        journal,old=load_run(self.root)
        cancellation.hook(self.root,'codex',{'hook_event_name':'Interrupt','session_id':'s','turn_id':old['human']['turn']})
        self.git('switch','main');self.git('branch','-D','design/old-auth')
        path=next((self.root/'docs/design').glob('0001-*.md'))
        path.write_text(path.read_text().replace('- [ ] **1.**','- [x] **1.**'),newline='\n')
        self.git('commit','-qam','merged decisions and first task');self.git('update-ref','refs/remotes/origin/main','HEAD')
        nested=self.root/'.claude/worktrees/held';self.git('worktree','add','-qb','held',str(nested))
        before=journal.records()
        discovery=native.saved_work(self.root)['saved_work'][0]
        factual=native.resume(self.root,run=old['id'])
        self.assertEqual(discovery['status'],factual['status'])
        self.assertEqual(discovery['status'],'running')
        self.assertEqual(discovery['execution'],factual['execution'])
        self.assertIsNotNone(factual['execution']['interruption'])
        self.assertEqual(factual['execution']['state'],'idle')
        request=self.human('/oh-deliver 0001')
        preview=native.prepare_scope(self.root,doc='0001',keep_checkout=True)
        self.assertFalse(preview['approved']);self.assertTrue(preview['execution_branch_required'])
        with self.assertRaisesRegex(Refused,'execution branch'):
            native.prepare_scope(self.root,doc='0001',keep_checkout=True,human=request)
        for args in (command('scope_prepare',{'doc':'0001','human':request},self.root),
                     ['scope','prepare','--doc','0001','--human',json.dumps(request)]):
            with patch('sys.stdout',new=io.StringIO()) as output:main(['--root',str(self.root),*args])
            selected=json.loads(output.getvalue())
            self.assertEqual(selected['task']['id'],'2')
            self.assertEqual(selected['retained_work'][0]['run'],old['id'])
        self.assertEqual(journal.records(),before)
        self.assertTrue((nested/'.git').is_file())
        retained=load_run(self.root,old['id'])[1]
        for key in ('granted','attempts','done','config'):self.assertEqual(retained[key],old[key])

    def test_design_preparation_checks_selection_and_serializes_git_with_admission(self):
        from datetime import datetime,timezone
        from . import native,cancellation,branches
        from .storage import checkout_file,lock
        self.documents();self.git('switch','-c','new-owner')
        stale=self.human('/oh-deliver 0001',session='pending-request',at=datetime.now(timezone.utc).isoformat())
        self.approve();journal,current=load_run(self.root)
        def retained():
            return (self.git('branch','--show-current'),self.git('rev-parse','HEAD'),journal.records(),
                    cancellation._read(self.root)['current'])
        before=retained()
        with self.assertRaisesRegex(Refused,'superseded'):native.prepare_scope(self.root,doc='0001',human=stale)
        self.assertEqual(retained(),before)
        fetched=branches.fetched;competing=[]
        def interleave(*args):
            # A real nonblocking claim of the same control lock models an
            # admission arriving after preflight and before the first Git write.
            with patch.object(native,'_locked',side_effect=lambda root:lock(checkout_file(root,'oh-control.lock'),wait=False)):
                with self.assertRaisesRegex(Refused,'active OH runner'):native.admit(self.root,'assessment')
            if not competing:self.assertEqual(retained(),before)
            competing.append(True)
            return fetched(*args)
        with patch.object(branches,'fetched',side_effect=interleave):
            selected=native.prepare_scope(self.root,doc='0001',human=self.human('/oh-deliver 0001'))
        self.assertTrue(competing);self.assertEqual(selected['task']['id'],'1')
        self.assertEqual(journal.records(),before[2])
        native.admit(self.root,'assessment')
        active_journal,_=load_run(self.root);records=active_journal.records();branch=self.git('branch','--show-current')
        with patch.object(branches,'fetched',side_effect=AssertionError('active checkout must stay selected')):
            with self.assertRaisesRegex(Refused,'unsettled native'):native.prepare_scope(self.root,doc='0001')
        self.assertEqual(self.git('branch','--show-current'),branch);self.assertEqual(active_journal.records(),records)

    def test_delivery_request_survives_only_its_bound_prerequisite_on_both_hosts(self):
        import os
        from datetime import datetime,timezone
        from . import native,decisions
        from .entry import request_source
        from .storage import now
        self.documents();self.git('switch','-c','prerequisite-test')
        for host in ('codex','claude'):
            with self.subTest(host=host):
                self.approve(tasks=[{'id':'old-'+host,'title':'Earlier idle work','instructions':'Retain this scope.'}])
                journal,old=load_run(self.root)
                home=Path(self.temp.name)/('native-'+host);session='entry-'+host
                path=home/('.codex/sessions' if host=='codex' else '.claude/projects/p')/(session+'.jsonl')
                path.parent.mkdir(parents=True)
                def human_record(turn,text):
                    at=datetime.now(timezone.utc).isoformat()
                    return ({'type':'event_msg','timestamp':at,'payload':{'type':'user_message','turn_id':'entry','message':text}}
                            if host=='codex' else {'type':'user','sessionId':session,'promptId':turn,'cwd':str(self.root),
                                'timestamp':at,'message':{'role':'user','content':text}})
                rows=([{'type':'session_meta','payload':{'id':session,'source':'cli','cwd':str(self.root)}}] if host=='codex' else [])
                rows.append(human_record('entry','/oh-deliver 0001'))
                def save():path.write_text(''.join(json.dumps(row)+'\n' for row in rows),newline='\n')
                def choose(gate,use):
                    rows.append(self.offer_record(host,session,gate,now()))
                    if 'disclosure' in gate:
                        rows.append({'type':'response_item','timestamp':now(),'payload':{'type':'message','role':'assistant',
                            'content':[{'type':'output_text','text':gate['disclosure']}]}} if host=='codex' else
                            {'type':'assistant','sessionId':session,'cwd':str(self.root),'timestamp':now(),
                             'message':{'content':[{'type':'text','text':gate['disclosure']}]}})
                    if host=='codex':
                        rows.extend([{'type':'response_item','timestamp':now(),'payload':{'type':'function_call','call_id':use,
                            'name':'request_user_input_async','arguments':json.dumps({'questions':[{'title':gate['question'],'options':gate['options']}]})}},
                            human_record(use,'<send_user_message_question_reply>'+json.dumps([{'questionItemId':json.dumps(['request_user_input_async',use,0]),
                                'question':gate['question'],'answer':gate['options'][0]}])+'</send_user_message_question_reply>')])
                    else:
                        rows.extend([{'type':'assistant','sessionId':session,'cwd':str(self.root),'timestamp':now(),'message':{'content':[
                            {'type':'tool_use','id':use,'name':'AskUserQuestion','input':{'questions':[{'question':gate['question'],
                                'options':[{'label':label} for label in gate['options']]}]}}]}},
                            {'type':'user','sessionId':session,'cwd':str(self.root),'timestamp':now(),
                             'toolUseResult':{'answers':{gate['question']:gate['options'][0]}},'message':{'content':[
                                {'type':'tool_result','tool_use_id':use,'content':'Answered'}]}}])
                    save()
                    return {'host':host,'session':session,'transcript_path':str(path),'tool_use_id':use,'decision':gate['decision']}
                save()
                request={'host':host,'session':session,'turn':'entry','prompt':'/oh-deliver 0001','transcript_path':str(path)}
                env={'CODEX_HOME':str(home/'.codex'),'CODEX_THREAD_ID':session if host=='codex' else '',
                     'OH_NATIVE_SESSION_ID':session if host=='claude' else ''}
                with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,env), \
                        patch('oh.authority.native_human',side_effect=self.native_human_original), \
                        patch('oh.authority.coordinator',side_effect=native_coordinator):
                    gate=decisions.prepare(self.root,'stop',request=request)
                    with self.assertRaisesRegex(Refused,'Bind the actual prerequisite answer'):
                        request_source(self.root,request,gate['decision'])
                    answer=choose(gate,'choose')
                    native.decision(self.root,'stop',answer)
                    # Codex can keep the same turn across several question replies.
                    # Equal labels still belong to distinct actual native questions.
                    again=decisions.prepare(self.root,'stop',request=request,after=gate['decision'])
                    native.decision(self.root,'stop',choose(again,'second-prerequisite'))
                    gate=again;stopped=journal.records()
                    with self.assertRaises(Refused):native.prepare_scope(self.root,doc='0001',human=request,keep_checkout=True)
                    selected=native.prepare_scope(self.root,doc='0001',human=request,keep_checkout=True,after=gate['decision'])
                    self.assertEqual(selected['task']['id'],'1')
                    active=load_run(self.root)[1]
                    self.assertEqual(active['entry_request']['prompt'],'/oh-deliver 0001')
                    self.assertEqual(active['human']['prompt'],'Stop and take over')
                    self.assertEqual(active['entry_prerequisite'],gate['decision'])
                    self.assertEqual(native.prepare_scope(self.root,doc='0001',human=request,keep_checkout=True,
                                     after=gate['decision'])['run'],selected['run'])
                    self.assertEqual(journal.records(),stopped)
                    self.assertEqual(load_run(self.root,old['id'])[1]['granted'],old['granted'])
                    # An already accepted quick-fix preview also survives a real
                    # cleanup prerequisite, without borrowing a different answer.
                    scope=native.prepare_scope(self.root,{'tasks':[{'id':'fix','title':'A bounded fix','instructions':'Keep the approved starting work.'}]})
                    approval=choose(scope['approval'],'approve-scope')
                    from .storage import lock,checkout_file
                    with lock(checkout_file(self.root,'oh-runner.lock'),wait=False):
                        with self.assertRaisesRegex(Refused,'still executing'):
                            native.approve_scope(self.root,scope['scope_id'],approval)
                    prerequisite=decisions.prepare(self.root,'stop',request=approval)
                    native.decision(self.root,'stop',choose(prerequisite,'stop-prerequisite'))
                    fixed=native.approve_scope(self.root,scope['scope_id'],approval,after=prerequisite['decision'])
                    self.assertEqual(fixed['task']['id'],'fix')
                    self.assertEqual(load_run(self.root)[1]['entry_prerequisite'],prerequisite['decision'])
                    # Positive continuation transfers install the prerequisite
                    # as current owner. The exact accepted effect must still
                    # carry both a design request and an unchanged scope approval.
                    for kind in ('resume','recover'):
                        rows.append(human_record('entry-'+kind,'/oh-deliver 0001'));save()
                        carried_request={'host':host,'session':session,'turn':'entry' if host=='codex' else 'entry-'+kind,
                                 'prompt':'/oh-deliver 0001','transcript_path':str(path)}
                        prerequisite=decisions.prepare(self.root,kind,request=carried_request)
                        native.decision(self.root,'resume',choose(prerequisite,'continue-'+kind))
                        selected=native.prepare_scope(self.root,doc='0001',human=carried_request,keep_checkout=True,after=prerequisite['decision'])
                        self.assertTrue(selected['approved']);self.assertEqual(selected['task']['id'],'1')
                        scope=native.prepare_scope(self.root,{'tasks':[{'id':'fix','title':'After '+kind,
                            'instructions':'Keep the unchanged accepted scope.'}]})
                        approval=choose(scope['approval'],'approve-after-'+kind)
                        prerequisite=decisions.prepare(self.root,kind,request=approval)
                        native.decision(self.root,'resume',choose(prerequisite,'continue-approval-'+kind))
                        fixed=native.approve_scope(self.root,scope['scope_id'],approval,after=prerequisite['decision'])
                        self.assertEqual(fixed['task']['title'],'After '+kind)
                    # Retaining a typed "approve" through cleanup must preserve
                    # its original artifact binding, not just its time/order.
                    for shown in ('unrelated report','another scope','actual scope'):
                        candidate=native.prepare_scope(self.root,{'tasks':[{'id':'typed','title':'Typed '+shown,
                            'instructions':'Use only the scope the person actually saw.'}]})
                        actual=native._home(self.root)/'scopes'/candidate['scope_id']/'scope.md'
                        context=(str(actual) if shown=='actual scope' else str(actual.parent.parent/'other'/'scope.md')
                                 if shown=='another scope' else 'The unrelated report is ready.')
                        message={'content':[{'type':'output_text' if host=='codex' else 'text','text':context}]}
                        rows.append({'type':'response_item','timestamp':now(),'payload':message|{'type':'message','role':'assistant'}}
                                    if host=='codex' else {'type':'assistant','sessionId':session,'cwd':str(self.root),
                                        'timestamp':now(),'message':message})
                        rows.append(human_record('typed-'+shown,'approve'));save()
                        typed={'host':host,'session':session,'transcript_path':str(path),'prompt':'approve',
                               **({'turn':'entry'} if host=='codex' else {'turn':'typed-'+shown})}
                        prerequisite=decisions.prepare(self.root,'stop',request=typed)
                        native.decision(self.root,'stop',choose(prerequisite,'stop-'+shown))
                        retained_journal,retained=load_run(self.root);records=retained_journal.records()
                        if shown!='actual scope':
                            with self.assertRaisesRegex(Refused,'identifying the reviewed artifact'):
                                native.approve_scope(self.root,candidate['scope_id'],typed,after=prerequisite['decision'])
                            self.assertEqual(retained_journal.records(),records)
                            self.assertEqual(load_run(self.root)[1]['granted'],retained['granted'])
                        else:
                            selected=native.approve_scope(self.root,candidate['scope_id'],typed,after=prerequisite['decision'])
                            self.assertEqual(selected['task']['title'],'Typed actual scope')
                    if host=='claude':
                        for amended in (False,True):
                            candidate=native.prepare_scope(self.root,{'tasks':[{'id':'plan','title':'Native plan',
                                'instructions':'Retain only the exact accepted preview.'}]})
                            actual=native._home(self.root)/'scopes'/candidate['scope_id']/'scope.md'
                            plan=actual.read_text()+('\nAmended scope\n' if amended else '')
                            use='plan-'+str(amended)
                            rows.extend([{'type':'assistant','sessionId':session,'cwd':str(self.root),'timestamp':now(),
                                'message':{'content':[{'type':'tool_use','name':'ExitPlanMode','id':use,'input':{'plan':plan}}]}},
                                {'type':'user','sessionId':session,'cwd':str(self.root),'timestamp':datetime.now(timezone.utc).isoformat(),
                                 'toolUseResult':{'plan':plan,'filePath':'native-plan.md','isAgent':False},
                                 'message':{'content':[{'type':'tool_result','tool_use_id':use,'content':'Approved'}]}}]);save()
                            accepted={'host':host,'session':session,'tool_use_id':use,'transcript_path':str(path)}
                            prerequisite=decisions.prepare(self.root,'stop',request=accepted)
                            native.decision(self.root,'stop',choose(prerequisite,'stop-'+use))
                            if amended:
                                with self.assertRaisesRegex(Refused,'accepted changed scope'):
                                    native.approve_scope(self.root,candidate['scope_id'],accepted,after=prerequisite['decision'])
                            else:
                                self.assertEqual(native.approve_scope(self.root,candidate['scope_id'],accepted,
                                    after=prerequisite['decision'])['task']['id'],'plan')
                    rows.append(human_record('before-cancel','/oh-deliver 0001'));save()
                    cancel_request={'host':host,'session':session,'turn':'entry' if host=='codex' else 'before-cancel',
                                    'prompt':'/oh-deliver 0001','transcript_path':str(path)}
                    gate=decisions.prepare(self.root,'stop',request=cancel_request)
                    native.decision(self.root,'stop',choose(gate,'last-prerequisite'))
                    self.assertEqual(request_source(self.root,cancel_request,gate['decision'])['prompt'],'/oh-deliver 0001')
                    rows.append(human_record('later','Do not deliver 0001; leave it.'));save()
                    with self.assertRaisesRegex(Refused,'newer'):request_source(self.root,cancel_request,gate['decision'])

    def test_new_delivery_leaves_merged_branch_and_selects_remaining_task_from_main(self):
        from . import native
        _,path=self.documents()
        self.git('switch','-c','old-task-1')
        path.write_text(path.read_text().replace('- [ ] **1.**','- [x] **1.**'),newline='\n')
        (self.root/'first.txt').write_text('delivered',newline='\n')
        self.git('add','.');self.git('commit','-qm','first task delivered')
        self.git('switch','main');self.git('merge','--no-ff','--no-edit','old-task-1')
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        main=self.git('rev-parse','HEAD')
        self.git('switch','old-task-1')
        selected=native.prepare_scope(self.root,doc='0001',human=self.human('/oh-deliver 0001'))
        self.assertEqual(self.git('branch','--show-current'),'deliver/0001')
        self.assertEqual(self.git('rev-parse','HEAD'),main)
        self.assertEqual(selected['task']['id'],'2')

    def test_merged_track_selects_only_runnable_track_without_another_question(self):
        from . import native
        body=('## 5. Open decisions\n\nOwner decisions remain unresolved.\n\n## Tasks\n\n### Dashboard track\n\n'
              '- [ ] **1.** Resolve forecast transition. *Blocked on §5.*\n'
              '- [ ] **2.** Compose Budget. *Depends on task 1.*\n'
              '- [ ] **3.** Deliver Transactions. *Depends on task 2.*\n'
              '- [ ] **6.** Later independent work.\n'
              '- [ ] **4.** Deliver the import-rule editor.\n'
              '- [ ] **5.** Deliver Memory. *Depends on task 8.* *Blocked on §5.*\n\n'
              '### Registry track\n\n- [ ] **8.** Deliver invocation policy.\n')
        _,path=self.documents(body=body)
        self.git('switch','-c','deliver/0001-registry')
        path.write_text(path.read_text().replace('- [ ] **8.**','- [x] **8.**'),newline='\n')
        self.git('commit','-qam','delivered registry')
        self.git('switch','main');self.git('merge','--no-ff','--no-edit','deliver/0001-registry')
        self.git('update-ref','refs/remotes/origin/main','HEAD');base=self.git('rev-parse','HEAD')
        self.git('switch','deliver/0001-registry')
        # Explicit selection of the completed track must not silently switch scope.
        with self.assertRaisesRegex(Refused,'No ready pending tasks'):
            delivery.selection(self.root,'0001','registry')
        request=self.human('/oh-deliver 0001')
        selected=native.prepare_scope(self.root,doc='0001',human=request)
        journal,state=load_run(self.root)
        self.assertTrue(selected['approved']);self.assertEqual(selected['task']['id'],'4')
        self.assertEqual(state['track'],'dashboard');self.assertEqual(state['granted'],['4'])
        self.assertEqual([t['id'] for t in state['tasks']],['4','6'])
        self.assertEqual(self.git('branch','--show-current'),'deliver/0001-dashboard')
        self.assertEqual(self.git('rev-parse','HEAD'),base)
        records=journal.records()
        self.assertEqual(native.prepare_scope(self.root,doc='0001',human=request)['run'],state['id'])
        self.assertEqual(journal.records(),records)
        native.admit(self.root,'assessment')
        self.assertEqual(native.prepare_scope(self.root,doc='0001',human=request)['run'],state['id'])
        self.assertEqual(len(load_run(self.root)[1]['attempts']),1)

    def test_automatic_track_ignores_blocked_tracks_but_preserves_real_choices(self):
        _,path=self.documents(body=('## 5. Open decisions\n\nOwner decision remains unresolved.\n\n## Tasks\n\n### Dashboard track\n\n'
            '- [ ] **1.** Dashboard. *Blocked on §5.*\n\n'
            '### Registry track\n\n- [ ] **8.** Registry.\n'))
        manifest,_=delivery.selection(self.root,'0001')
        self.assertEqual(manifest['track'],'registry')
        self.assertEqual([t['id'] for t in manifest['tasks']],['8'])
        text=path.read_text()
        path.write_text(text.replace(' *Blocked on §5.*',''),newline='\n')
        self.git('commit','-qam','resolve dashboard blocker');self.git('update-ref','refs/remotes/origin/main','HEAD')
        with self.assertRaisesRegex(Refused,'Choose one design track: dashboard, registry'):
            delivery.selection(self.root,'0001')
        path.write_text(text.replace('**8.** Registry.','**8.** Registry. *Depends on task 1.*'),newline='\n')
        self.git('commit','-qam','both tracks blocked');self.git('update-ref','refs/remotes/origin/main','HEAD')
        with self.assertRaisesRegex(Refused,'No ready pending tasks'):
            delivery.selection(self.root,'0001')

    def test_external_merge_of_saved_checkpoint_selects_next_task_without_resume(self):
        from . import native
        from .entry import inspect
        self.documents()
        first=native.prepare_scope(self.root,doc='0001',human=self.human('/oh-deliver 0001'))
        self.assess();self.implement();review=self.reviewed()
        native.complete(self.root,review['id'])
        journal,old=load_run(self.root);records=journal.records()
        branch=self.git('branch','--show-current')
        origin=Path(self.temp.name)/'origin.git'
        self.git('clone','--bare',str(self.root),str(origin));self.git('remote','add','origin',str(origin))
        self.git('fetch','origin','main')
        before=inspect(self.root)
        self.assertTrue(next(item for item in before['saved_work'] if item['run']==old['id'])['resumable'])
        self.git('switch','main');self.git('merge','--no-ff','--no-edit',branch)
        self.git('push','origin','main');self.git('switch',branch)
        # The original path treats the historical checkpoint as resumable.
        with patch('oh.delivery.merged_batch',return_value=None):
            stale=inspect(self.root)
            self.assertTrue(next(item for item in stale['saved_work'] if item['run']==old['id'])['resumable'])
        (self.root/'notes.txt').write_text('Keep these local edits',newline='\n')
        dirty=inspect(self.root)
        self.assertTrue(next(item for item in dirty['saved_work'] if item['run']==old['id'])['resumable'])
        (self.root/'notes.txt').unlink()
        facts=inspect(self.root)
        saved=next(item for item in facts['saved_work'] if item['run']==old['id'])
        self.assertFalse(saved['resumable'])
        compact={'saved_work':[{'run':old['id'],'resumable':True}]}
        with patch('oh.native.saved_work',return_value=compact):
            self.assertEqual(inspect(self.root)['saved_work'][0]['next_action']['arguments']['doc'],'0001')
        from .decisions import prepare
        self.assertFalse(prepare(self.root,'recover',run=old['id'])['recovery_required'])
        selected=native.prepare_scope(self.root,doc='0001',human=self.human('/oh-deliver 0001',session='fresh'))
        self.assertNotEqual(selected['run'],first['run'])
        self.assertEqual(selected['task']['id'],'2')
        self.assertEqual(selected['granted'],['2'])
        self.assertIsNone(old.get('published'))
        self.assertEqual(journal.records(),records)

    def test_entry_discovers_merged_progress_before_reconciled_delivery_selection(self):
        from . import native
        from .entry import inspect
        _,path=self.documents();old=self.git('rev-parse','HEAD')
        origin=Path(self.temp.name)/'origin.git'
        self.git('clone','--bare',str(self.root),str(origin));self.git('remote','add','origin',str(origin))
        path.write_text(path.read_text().replace('- [ ] **1.**','- [x] **1.**'),newline='\n')
        self.git('commit','-qam','merged decisions and task progress')
        current=self.git('rev-parse','HEAD');self.git('push','origin','HEAD:main')
        self.git('reset','--hard',old);self.git('update-ref','refs/remotes/origin/main',old)
        self.assertFalse(self.git('status','--porcelain'))
        facts=inspect(self.root)
        self.assertEqual(facts['base']['commit'],current)
        self.assertEqual(self.git('rev-parse','HEAD'),old)
        self.assertIn('- [ ] **1.**',path.read_text())
        self.assertEqual(delivery.listing(self.root)['source'],'checkout')
        # Native Git applies the chosen lossless update; observation never does it.
        self.git('merge','--ff-only','origin/main');self.git('switch','-c','deliver/0001')
        selected=native.prepare_scope(self.root,doc='0001',keep_checkout=True,human=self.human('/oh-deliver 0001'))
        self.assertEqual(selected['task']['id'],'2')
        self.assertEqual(self.git('rev-parse','HEAD'),current)

    def test_original_manual_work_is_in_both_delivery_intakes_and_publication(self):
        from . import native,publication
        where,path=self.documents()
        self.git('switch','-c','deliver/manual')
        (self.root/'manual.txt').write_text('Original included work.\n',newline='\n')
        self.git('add','.');self.git('commit','-qm','manual work');manual=self.git('rev-parse','HEAD')
        for selection in ({'manifest':{'tasks':self.tasks[:1],'covers':[manual]}},{'doc':'0001'}):
            prepared=native.prepare_scope(self.root,**selection)
            snapshot=read_json(Path(prepared['preview']).with_name('scope.json'))
            self.assertEqual(snapshot['covers'],[manual])
            self.assertIn(manual[:12],Path(prepared['preview']).read_text())
        native.approve_scope(self.root,prepared['scope_id'],self.human())
        self.assess();self.implement();review=self.reviewed()
        packet=read_json(Path(review['evidence'])/'task-context.json')
        self.assertEqual(packet['included_original_work']['covers'],[manual])
        self.assertIn('Included original work',(Path(review['evidence'])/'request.md').read_text())
        native.complete(self.root,review['id'])
        state=load_run(self.root)[1]
        self.assertEqual(state['commit_intents']['1']['publication']['covers'],[manual])
        self.git('remote','add','origin','https://github.com/example/product.git')
        native.decision(self.root,'publish',self.human('publish',question='Publish deliver/manual to example/product?'))
        self.assertIn(manual,publication.render(self.root))

    def test_converged_tracks_finalize_through_native_check_review_and_completion(self):
        from . import native
        body='## Why\n\nComplete both parts.\n\n## Tasks\n\n### Core track\n\n- [ ] **1.** Core behavior.\n\nCore implementation notes.\n\n### UI track\n\n- [ ] **2.** UI behavior.\n'
        where,path=self.documents(body=body)
        plans.add_initiative(self.root,where,'M1','reports','Reports',['auth'])
        downstream,_=plans.write_design(self.root,where,'reports','Reports',BODY,'approved')
        plans.claim(self.root,where,'reports',downstream)
        self.git('add','.');self.git('commit','-qm','dependent approved design')
        self.git('update-ref','refs/remotes/origin/main','HEAD');base=self.git('rev-parse','HEAD')
        with self.assertRaisesRegex(Refused,'unfinished auth'):delivery.selection(self.root,downstream)
        for track in ('core','ui'):
            self.git('switch','-c','deliver/0001-'+track,base)
            selected=native.prepare_scope(self.root,doc='0001',track=track)
            native.approve_scope(self.root,selected['scope_id'],self.human())
            self.assess();self.implement(edit=lambda:(self.root/(track+'.txt')).write_text(track,newline='\n'))
            review=self.reviewed();native.complete(self.root,review['id'])
            self.assertIn('status: approved',path.read_text())
        self.git('switch','main')
        for track in ('core','ui'):self.git('merge','--no-edit','deliver/0001-'+track)
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        self.assertIn('status: approved',path.read_text());self.assertNotIn('- [ ]',path.read_text())
        self.git('switch','-c','deliver/finalize')
        selected=native.prepare_scope(self.root,doc='0001')
        self.assertEqual([task['id'] for task in selected['tasks']],['finalize'])
        native.approve_scope(self.root,selected['scope_id'],self.human())
        self.assess();self.implement(edit=lambda:None)
        candidate=native.candidate(self.root)
        self.assertIn('status: frozen',path.read_text())
        native.verify(self.root)
        review=self.finish_attempt('review',{'verdict':'clean','findings':[]})
        native.complete(self.root,review['id'])
        self.assertEqual(self.git('rev-parse','HEAD^{tree}'),candidate['git_tree'])
        self.assertEqual(load_run(self.root)[1]['done'],['finalize'])
        self.assertEqual(len(delivery.selection(self.root,downstream)[0]['tasks']),2)

    def test_missing_remote_base_is_an_actionable_listing_result(self):
        self.documents();self.git('update-ref','-d','refs/remotes/origin/main')
        result=delivery.listing(self.root)
        self.assertEqual(result['ready'],[])
        self.assertIn('Fetch origin/main',result['unavailable'][0]['reason'])

    def test_legacy_completed_progress_requires_reapproval_bound_to_code(self):
        where,path=self.documents('private')
        (self.root/'legacy.txt').write_text('completed task code',newline='\n')
        self.git('add','.');self.git('commit','-qm','legacy completed work')
        path.write_text(path.read_text().replace('- [ ] **1.**','- [x] **1.**'),newline='\n')
        records=read_json(plans.approvals_file(self.root));records['0001']['sha256']=plans.digest_of(path)
        plans.approvals_file(self.root).write_text(json.dumps(records),newline='\n')
        with self.assertRaisesRegex(Refused,'reapprove'):delivery.selection(self.root,'0001')
        plans.approve(self.root,where,'0001','human-reapproval',False)
        self.assertEqual([t['id'] for t in delivery.selection(self.root,'0001')[0]['tasks']],['2'])
        self.git('checkout','HEAD^')
        with self.assertRaisesRegex(Refused,'checkout does not contain'):delivery.selection(self.root,'0001')

    def test_milestone_dependencies_require_every_design_and_support_collapsed_milestones(self):
        from .design_parse import freeze_render
        for location in ('repo','private'):
            with self.subTest(location=location):
                # Independent fixture so roadmap and code lineage cannot leak between locations.
                if location=='private':self.setUp()
                where,auth=self.documents(location)
                plans.add_initiative(self.root,where,'M1','ledger','Ledger',[])
                n,ledger=plans.write_design(self.root,where,'ledger','Ledger',BODY,'approved');plans.claim(self.root,where,'ledger',n)
                plans.add_milestone(self.root,where,'M2','Next','Reports work')
                plans.add_initiative(self.root,where,'M2','reports','Reports',['M1'])
                target,report=plans.write_design(self.root,where,'reports','Reports',BODY,'approved');plans.claim(self.root,where,'reports',target)
                def approve_and_sync():
                    if location=='private':
                        for number in ('0001',n,target):plans.approve(self.root,where,number,'human',False)
                    else:self.git('add','.');self.git('commit','--allow-empty','-qm','plan progress')
                    self.git('update-ref','refs/remotes/origin/main','HEAD')
                def freeze(path,number):
                    path=Path(path);path.write_text(path.read_text().replace('- [ ]','- [x]'),newline='\n')
                    plans.write(path,freeze_render(self.root,number,layout=where))
                freeze(auth,'0001');approve_and_sync()
                with self.assertRaisesRegex(Refused,'unfinished M1'):delivery.selection(self.root,target)
                freeze(ledger,n);approve_and_sync()
                self.assertEqual(len(delivery.selection(self.root,target)[0]['tasks']),2)
                roadmap=Path(where['roadmap']);text=roadmap.read_text();start=text.index('### M1');end=text.index('### M2')
                prefix=auth.parent.relative_to(roadmap.parent).as_posix()
                roadmap.write_text(text[:start]+f'### M1 First ✅\n\nDelivered as [0001](./{prefix}/{auth.name}), [{n}](./{prefix}/{Path(ledger).name}).\n\n'+text[end:],newline='\n')
                approve_and_sync();self.assertEqual(len(delivery.selection(self.root,target)[0]['tasks']),2)
                if location=='private':
                    auth.write_text(auth.read_text()+'\nChanged completed design\n',newline='\n')
                    with self.assertRaisesRegex(Refused,'changed since'):delivery.selection(self.root,target)
