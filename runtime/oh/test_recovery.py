"""Delivery recovery decisions exercise real Git, journals and tool revocation."""
from datetime import datetime, timedelta, timezone
from .system import Path
import json
import unittest
from unittest.mock import patch
from . import cancellation, decisions, native, recovery
from .storage import Refused, now
from .test_fixtures_workflow import NativeFixture
from .workflow import load_run
from .authority import coordinator as native_coordinator


class RecoveryTest(NativeFixture, unittest.TestCase):
    # Exercise existing recovery cases with old, ordinary path strings beyond MAX_PATH.
    state_folder='/'.join(['long-state-'+'a'*80,'b'*90,'c'*90])

    def test_single_folder_new_delivery_completes_then_restores_old_delivery_on_both_hosts(self):
        from . import workspace
        for host in ('codex','claude'):
            with self.subTest(host=host):
                self.approve();journal,old=load_run(self.root)
                (self.root/'product.txt').write_text('staged old work '+host,newline='\n')
                self.git('add','product.txt')
                (self.root/'product.txt').write_text('unstaged old work '+host,newline='\n')
                (self.root/'old notes.txt').write_text('untracked old notes',newline='\n')
                index=self.git('write-tree');before=self.git('status','--porcelain')
                request=self.human('Deliver the independent fix',host=host)
                native.switch_workspace(self.root,'deliver/new-'+host,request,base='main')
                self.approve(tasks=[{'id':'new','title':'Independent fix','instructions':'Implement the independent fix.'}],keep_checkout=True)
                current=load_run(self.root)[1]
                self.assertEqual(current['scope_snapshot']['starting_edits'],[])
                self.assess();self.implement();review=self.reviewed()
                native.complete(self.root,review['id'])
                (self.root/'later notes.txt').write_text('keep the newer checkout edits',newline='\n')
                gate=decisions.prepare(self.root,'recover',run=old['id'])
                self.assertIn('restoring its parked changes',gate['question'])
                answer=self.answer(gate,'Continue',host=host)
                # This loop starts another host immediately; do not date its prior answer in the future.
                answered_at=now()
                answer.update(at=answered_at,question_at=answered_at)
                native.decision(self.root,'resume',answer,run=old['id'])
                resumed=load_run(self.root)[1]
                self.assertEqual(self.git('branch','--show-current'),old['branch'])
                self.assertEqual(self.git('status','--porcelain'),before)
                self.assertEqual(self.git('write-tree'),index)
                self.assertEqual((self.root/'product.txt').read_text(),'unstaged old work '+host)
                self.assertEqual((self.root/'old notes.txt').read_text(),'untracked old notes')
                self.assertFalse((self.root/'later notes.txt').exists())
                self.assertTrue(workspace.parked(self.root,current['branch']))
                for key in ('id','scope_id','granted','attempts','config','done'):
                    self.assertEqual(resumed[key],old[key])
                records=journal.records();stashes=self.git('stash','list','--format=%H')
                native.decision(self.root,'resume',answer,run=old['id'])
                self.assertEqual(journal.records(),records)
                self.assertEqual(self.git('stash','list','--format=%H'),stashes)
                native.decision(self.root,'stop',self.human('stop',host=host))
                self.git('reset','--mixed','HEAD');self.git('restore','product.txt')
                (self.root/'old notes.txt').unlink()

    def test_offline_recovery_explains_cached_base_and_keeps_existing_choices(self):
        self.approve();before=load_run(self.root)[1]
        self.git('remote','add','origin',str(Path(self.temp.name)/'unavailable-origin'))
        gate=decisions.prepare(self.root,'recover')
        self.assertEqual(gate['base_observation']['freshness'],'unavailable')
        self.assertIn('Base freshness: unavailable',gate['question'])
        self.assertEqual(set(gate['options']),{'Continue','Start fresh','Stop and take over'})
        after=load_run(self.root)[1]
        for key in ('id','human','granted','attempts','config'):self.assertEqual(after[key],before[key])

    def test_recovery_offers_stop_when_the_saved_base_ref_is_missing(self):
        self.approve()
        self.git('branch','-D','main')
        self.git('update-ref','-d','refs/remotes/origin/main')
        gate=decisions.prepare(self.root,'recover')
        self.assertEqual(gate['options'],['Stop and take over'])
        self.assertIn('fetch origin main',gate['question'])
        result=native.decision(self.root,'stop',self.answer(gate,'Stop and take over')|{'via':'text'})
        self.assertEqual(result['status'],'stopped')

    def answer(self, gate, label, host='claude', session='new-parent'):
        at=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()
        return self.human(label,host=host,session=session,decision=gate['decision'],
            question=gate['question'],question_at=at,at=at,via='question',question_options=gate['options'])

    def test_recovery_menu_cannot_reclaim_a_newer_selection_with_an_old_answer(self):
        from .storage import digest, read_json
        from .workflow import active_file
        self.approve();old_journal,old=load_run(self.root)
        current=decisions.prepare(self.root,'recover')
        stored=read_json(native._home(self.root)/'decisions'/(current['decision']+'.json'))
        historical={k:v for k,v in stored.items() if k not in ('bound_question','stop_boundary')}
        historical['question']=historical['question'].replace('Saved run: '+old['id']+'\n','')
        identity=digest(historical)
        native._immutable(native._home(self.root)/'decisions'/(identity+'.json'),historical)
        foreign=current|{'decision':identity,'question':current['question'].replace(old['id'],'another-run')}
        records=old_journal.records()
        for effect,label in (('stop','Stop and take over'),('restart','Start fresh')):
            with self.assertRaisesRegex(Refused,'pending historical menu'):
                native.decision(self.root,effect,self.answer(foreign,label))
        self.assertEqual(old_journal.records(),records)
        for kind,label in (('resume','Continue'),('restart','Start fresh'),('stop','Stop and take over')):
            with self.subTest(kind=kind):
                gate=decisions.prepare(self.root,'recover',run=old['id'])
                stale=self.answer(gate,label)|{'at':now(),'question_at':now()}
                self.approve(tasks=[{'id':kind,'title':'Different '+kind,'instructions':'Keep this work selected.'}])
                current_journal,current=load_run(self.root)
                def retained():
                    return (old_journal.records(),current_journal.records(),read_json(active_file(self.root)),
                            cancellation._read(self.root)['current'],self.git('rev-parse','HEAD'),self.git('status','--porcelain'))
                before=retained()
                with self.assertRaisesRegex(Refused,'superseded'):
                    native.decision(self.root,kind,stale,run=old['id'])
                self.assertEqual(retained(),before)
                fresh=self.answer(gate,label)|{'at':now(),'question_at':now()}
                if kind=='stop':
                    with patch('oh.receipts.index',side_effect=OSError('interrupted index write')),self.assertRaisesRegex(OSError,'index write'):
                        native.decision(self.root,kind,fresh,run=old['id'])
                    records=old_journal.records()
                native.decision(self.root,kind,fresh,run=old['id'])
                if kind=='stop':
                    self.assertEqual(old_journal.records(),records)
                    self.assertIn('**Current state:** stopped',(old_journal.path/'index.md').read_text())
                selected=load_run(self.root)[1]
                self.assertEqual(selected['id'],current['id'] if kind=='stop' else old['id'])
                if kind=='stop':self.assertEqual(cancellation._read(self.root)['current'],before[3])
                updated=load_run(self.root,old['id'])[1]
                self.assertEqual(updated['granted'],old['granted'])
                self.assertEqual(updated['config'],old['config'])

    def test_recovery_waits_for_owned_commands_before_transfer_and_replays_final_binding(self):
        from .storage import read_json
        from .workflow import active_file
        self.approve();native.decision(self.root,'stop',self.human('stop'));old_journal,old=load_run(self.root)
        self.approve(tasks=[{'id':'other','title':'Different work','instructions':'Keep its native tools fenced.'}])
        finished=self.assess();other_journal,other=load_run(self.root)
        pending=native.prepare_scope(self.root,{'tasks':[{'id':'pending','title':'Pending other approval',
                                                       'instructions':'Respect later ownership selections.'}]})
        with cancellation._edit(self.root) as value:
            value['commands']['pending-command']={'attempt':finished['id'],'started':now()}
        gate=decisions.prepare(self.root,'recover',run=old['id'])
        def timed(value):return value|{'at':datetime.now(timezone.utc).isoformat()}
        older_approval=timed(self.human(session='pending-scope'))
        older_review=timed(self.human('/oh-review changes',session='pending-review'))
        older_recovery=timed(self.answer(gate,'Continue',session='pending-recovery'))
        older_resume=timed(self.resume_choice(run=old['id'],session='pending-resume'))
        answer=timed(self.answer(gate,'Continue'))
        def retained():
            return (old_journal.records(),other_journal.records(),read_json(active_file(self.root)),
                    cancellation._read(self.root)['current'],self.git('rev-parse','HEAD'),self.git('status','--porcelain'))
        before=retained()
        with self.assertRaisesRegex(Refused,'unsettled native'):
            native.decision(self.root,'resume',answer,run=old['id'])
        self.assertEqual(retained(),before)
        # A finished workflow label cannot settle an actual owned command.
        with cancellation._edit(self.root) as value:value['commands']['pending-command'].update(ended=now(),returncode=0)
        original=native._resume_binding
        def interrupted(*args,**kwargs):
            if kwargs.get('write'):raise OSError('interrupted final selection write')
            return original(*args,**kwargs)
        with patch.object(native,'_resume_binding',side_effect=interrupted),self.assertRaisesRegex(OSError,'final selection'):
            native.decision(self.root,'resume',answer,run=old['id'])
        records=old_journal.records()
        self.assertEqual(load_run(self.root)[1]['id'],other['id'])
        control=cancellation._read(self.root)
        self.assertEqual(control['owners'][control['current']]['run'],old['id'])
        self.assertIn('**Current state:** stopped',(old_journal.path/'index.md').read_text())
        partial=retained()
        # The pointer still names B, but A already owns a newer native epoch.
        # All selection routes must honor that epoch, including another A answer.
        for stale in (lambda:native.approve_scope(self.root,pending['scope_id'],older_approval),
                      lambda:native.review(self.root,'changes',older_review),
                      lambda:native.decision(self.root,'resume',older_recovery,run=old['id']),
                      lambda:native.resume(self.root,older_resume,run=old['id']),
                      lambda:native.admit(self.root,'implementation'),
                      lambda:native.candidate(self.root),lambda:native.verify(self.root)):
            with self.assertRaisesRegex(Refused,'superseded'):stale()
            self.assertEqual(retained(),partial)
        native.decision(self.root,'resume',answer|{'question_call':'newly-exposed-native-call'},run=old['id'])
        self.assertEqual(load_run(self.root)[1]['id'],old['id'])
        self.assertEqual(old_journal.records(),records)
        self.assertEqual(load_run(self.root)[1]['granted'],old['granted'])
        self.assertIn('**Current state:** running',(old_journal.path/'index.md').read_text())
        native._owner(self.root,load_run(self.root)[1])  # Upgraded identity still owns the original journal epoch.
        # A genuinely newer choice can still select different idle work.
        self.assertEqual(native.approve_scope(self.root,pending['scope_id'],timed(self.human()))['task']['id'],'pending')
        # Ordinary decisions share the same replay visibility contract as the
        # recovery menu, including a missing or opposite-state readable index.
        current_journal,_=load_run(self.root)
        from .receipts import index
        index(current_journal,load_run(self.root)[1])
        for kind in ('stop','resume'):
            answer=timed(self.human('stop') if kind=='stop' else self.resume_choice())
            with patch('oh.receipts.index',side_effect=OSError('interrupted ordinary index')),self.assertRaisesRegex(OSError,'ordinary index'):
                native.decision(self.root,kind,answer)
            records=current_journal.records()
            replay=native.decision(self.root,kind,answer)
            expected='stopped' if kind=='stop' else 'running'
            self.assertEqual(replay['status'],expected)
            self.assertEqual(current_journal.records(),records)
            self.assertIn('**Current state:** '+expected,(current_journal.path/'index.md').read_text())

    def test_selection_replay_repairs_failed_control_write_and_both_host_turn_fences(self):
        for host in ('codex','claude'):
            for route in ('resume','scope','review','recover'):
                with self.subTest(host=host,route=route):
                    initial=native.prepare_scope(self.root,{'tasks':[{'id':'old','title':'Before '+host+route,
                        'instructions':'Preserve the prior selection.'}]})
                    native.approve_scope(self.root,initial['scope_id'],self.human(host=host,session='old-'+host+route))
                    _,old=load_run(self.root)
                    if route in ('resume','recover'):
                        native.decision(self.root,'stop',self.human('stop',host=host,session=old['human']['session']))
                        gate=decisions.prepare(self.root,'resume' if route=='resume' else 'recover')
                        source=self.answer(gate,'Resume' if route=='resume' else 'Continue',host=host,session='new-'+host+route)
                        action=lambda:native.decision(self.root,'resume',source)
                    elif route=='scope':
                        scope=native.prepare_scope(self.root,{'tasks':[{'id':'new','title':'After '+host+route,
                            'instructions':'Keep this one original grant.'}]})
                        source=self.human(host=host,session='new-'+host+route)
                        action=lambda:native.approve_scope(self.root,scope['scope_id'],source)
                    else:
                        selector='changes' if host=='codex' else 'tree'
                        source=self.human('/oh-review '+selector,host=host,session='new-'+host+route)
                        action=lambda:native.review(self.root,selector,source)
                    at=datetime.now(timezone.utc).isoformat()
                    source=source|{'at':at,'question_at':at,'record_hashes':['native-human'],'transcript_path':str(self.parent_path)}
                    if host=='claude' and route=='resume':
                        with cancellation._edit(self.root) as value:
                            value['owners'][value['current']]['since']=None  # Older control metadata.
                    old_key=cancellation._read(self.root)['current'];write=cancellation.atomic_json
                    def fail_owner(path,value,*args,**kwargs):
                        if Path(path).name=='oh-native-execution.json' and value.get('current')!=old_key:
                            raise OSError('interrupted execution-owner write')
                        return write(path,value,*args,**kwargs)
                    # The fake native boundary retains the same occurrence time
                    # when the production retry reattests its original locator.
                    with patch('oh.authority.coordinator',side_effect=lambda root,state,locator=None,**kw:source if locator else state['human']):
                        with patch.object(cancellation,'atomic_json',side_effect=fail_owner),self.assertRaisesRegex(OSError,'execution-owner write'):
                            action()
                        journal,pending=load_run(self.root);records=journal.records()
                        self.assertEqual(cancellation._read(self.root)['current'],old_key)
                        payload={'hook_event_name':'PreToolUse','session_id':source['session'],'turn_id':source['turn'],
                                 'tool_name':'mcp__o_harness__status','tool_input':{},'tool_use_id':'retry-'+host+route}
                        # A newer proposed turn can reach its checked retry; it
                        # is not superseded by the older, incompletely saved owner.
                        self.assertEqual(cancellation.hook(self.root,host,payload),{})
                        result=action()
                    _,settled=load_run(self.root)
                    self.assertEqual(result['status'],'running')
                    self.assertEqual(cancellation._read(self.root)['current'],cancellation.owner_key(settled))
                    self.assertEqual(journal.records()[:len(records)],records)
                    self.assertEqual(settled['granted'],pending['granted'] or ['new' if route=='scope' else 'review'])
                    completed=journal.records();action()
                    self.assertEqual(journal.records(),completed)
                    self.assertEqual(cancellation.hook(self.root,host,payload),{})
                    stale=payload|{'session_id':old['human']['session'],'turn_id':old['human']['turn'],'tool_use_id':'late-'+host+route}
                    self.assertIn('superseded work selection',cancellation.hook(self.root,host,stale)['hookSpecificOutput']['permissionDecisionReason'])
            # A Stop in the proposed conversation still wins before an owner
            # write is repaired, including Claude's transcript-only occurrence.
            gate=decisions.prepare(self.root,'resume');source=self.answer(gate,'Resume',host=host,session='stopped-proposal-'+host)
            transcript=Path(self.temp.name)/('stopped-'+host+'.jsonl');transcript.write_text('',newline='\n')
            at=datetime.now(timezone.utc).isoformat()
            source=source|{'at':at,'question_at':at,'record_hashes':['native-human'],'transcript_path':str(transcript)}
            old_key=cancellation._read(self.root)['current']
            with patch('oh.authority.coordinator',side_effect=lambda root,state,locator=None,**kw:source if locator else state['human']):
                with patch.object(cancellation,'atomic_json',side_effect=fail_owner),self.assertRaisesRegex(OSError,'execution-owner write'):
                    native.decision(self.root,'resume',source)
                event=({'type':'event_msg','timestamp':now(),'payload':{'type':'turn_aborted','turn_id':source['turn'],'reason':'interrupted'}}
                       if host=='codex' else {'type':'user','timestamp':now(),'sessionId':source['session'],'uuid':source['turn'],
                           'message':{'content':[{'type':'text','text':'[Request interrupted by user]'}]}})
                transcript.write_text(json.dumps(event)+'\n',newline='\n')
                payload={'hook_event_name':'PreToolUse','session_id':source['session'],'turn_id':source['turn'],
                         'tool_name':'mcp__o_harness__status','tool_input':{},'tool_use_id':'stopped-retry-'+host}
                self.assertIn('was stopped',cancellation.hook(self.root,host,payload)['hookSpecificOutput']['permissionDecisionReason'])
                with self.assertRaisesRegex(Refused,'stopped after this Resume answer'):native.decision(self.root,'resume',source)
                self.assertEqual(cancellation._read(self.root)['current'],old_key)

    def test_free_text_entry_retries_the_same_saved_selection_after_host_save_delay(self):
        from .test_fixtures_workflow import configure
        configure(self.root,plans={'location':'private'})
        for workflow in ('review', 'propose'):
            with self.subTest(workflow=workflow):
                source=self.human('Please review this tree' if workflow=='review' else 'Please propose a fixture change')
                manifest={'tasks':[{'id':'1','title':'Propose a change','instructions':'Inspect the fixture.'}]}
                def enter(subject='tree', proposed=manifest):
                    if workflow=='review':return native.review(self.root,subject,source)
                    return native.prepare_scope(self.root,proposed,workflow=workflow,human=source)
                with patch.object(cancellation,'poll',return_value=False):
                    with self.assertRaisesRegex(Refused,'interruption evidence is still being saved'):enter()
                journal,pending=next((j,s) for j,s in native._saved_runs(self.root) if s['workflow']==workflow)
                initial=journal.records()
                self.assertEqual([r['kind'] for r in initial],['run.started'])
                self.assertFalse(pending['granted'])
                with self.assertRaisesRegex(Refused,'predates the current'):
                    enter('tree --feedback-only',{'tasks':[manifest['tasks'][0]|{'instructions':'Different scope.'}]})
                self.assertEqual(journal.records(),initial)
                self.assertEqual(enter()['run'],pending['id'])
                self.assertEqual(enter()['run'],pending['id'])
                records=journal.records()
                self.assertEqual(records[:1],initial)
                self.assertEqual([r['kind'] for r in records].count('grant'),1)
                self.assertEqual(load_run(self.root)[1]['granted'],['review' if workflow=='review' else '1'])
                self.assertEqual(cancellation._read(self.root)['current'],cancellation.owner_key(load_run(self.root)[1]))

    def test_new_owner_resume_finishes_an_accepted_entry_before_admission(self):
        for workflow,role in (('review','review'),('deliver','assessment')):
            with self.subTest(workflow=workflow):
                request=self.human('Please review this tree.' if workflow=='review' else 'approve')
                if workflow=='deliver':
                    preview=native.prepare_scope(self.root,{'tasks':self.tasks[:1]})
                with patch.object(cancellation,'poll',return_value=False):
                    with self.assertRaisesRegex(Refused,'interruption evidence is still being saved'):
                        if workflow=='review':
                            native.review(self.root,'tree',request)
                        else:
                            native.approve_scope(self.root,preview['scope_id'],request)
                journal,pending=next((j,s) for j,s in native._saved_runs(self.root) if s['workflow']==workflow)
                original=journal.records()
                self.assertEqual([r['kind'] for r in original],['run.started'])
                self.assertFalse(pending['granted'])
                if workflow=='review':
                    answer=self.resume_choice(run=pending['id'],session='new-review-coordinator')
                else:
                    # Continue may refresh an absorbed branch. The base transfer
                    # must preserve the grant completed in the same transition.
                    base=self.git('commit-tree','HEAD^{tree}','-p','HEAD','-m','Advance the fixture base').strip()
                    self.git('update-ref','refs/remotes/origin/main',base)
                    gate=decisions.prepare(self.root,'recover',run=pending['id'])
                    answer=self.answer(gate,'Continue',session='new-delivery-coordinator')
                selected=native.decision(self.root,'resume',answer,run=pending['id'])
                self.assertEqual(selected['run'],pending['id'])
                self.assertEqual(selected['status'],'running')
                saved=journal.records()
                self.assertEqual(saved[:1],original)
                grant,=[e['data'] for r in saved if r['kind']=='transition'
                        for e in r['data']['events'] if e['kind']=='grant']
                self.assertEqual(grant['source'],pending['source'])
                self.assertEqual(grant['kind'],'standalone' if workflow=='review' else 'initial')
                expected=['review'] if workflow=='review' else [self.tasks[0]['id']]
                self.assertEqual(grant['tasks'],expected)
                self.assertEqual(load_run(self.root)[1]['granted'],expected)
                native.decision(self.root,'resume',answer,run=pending['id'])
                self.assertEqual(journal.records(),saved)
                admitted=native.admit(self.root,role)
                self.assertEqual(admitted['task'],expected[0])
                self.native_results[admitted['id']]={'status':'cancelled','text':''}
                native.bind(self.root,admitted['id'],{'child_session':'fixture-'+admitted['id']})
                native.retain(self.root,admitted['id'],{})

    def test_entry_replay_finishes_both_pointers_and_records_its_initial_grant_once(self):
        from . import prepared
        from .test_fixtures_plans import delivery_documents
        from .test_fixtures_workflow import configure
        from .storage import Journal,atomic_json,read_json
        from .workflow import active_file,reduce
        configure(self.root,tasks_per_batch=1);delivery_documents(self)
        for route,host in (('repair','codex'),('design','claude')):
            for fault in ('canonical','review-deselection','grant')+(('owner-before-review',) if route=='design' else ()):
                with self.subTest(route=route,fault=fault):
                    self.approve(tasks=[{'id':'old','title':'Prior '+route+fault,'instructions':'Preserve this idle scope.'}])
                    old_journal,old=load_run(self.root);old_records=old_journal.records()
                    native.review(self.root,'tree',self.human('/oh-review tree',host=host,session='feedback-'+route+fault))
                    self.finish_attempt('review',{'verdict':'blocking','summary':'Repair the fixture behavior.',
                        'findings':[{'severity':'blocking','family':'handoff-fixture','description':'The fixture behavior needs repair.'}]})
                    if fault=='owner-before-review':
                        import os
                        with patch.dict(os.environ,{'CODEX_THREAD_ID':'','OH_NATIVE_SESSION_ID':'idle-feedback'}):
                            native.review(self.root,'changes')
                    review_journal,feedback=load_run(self.root);review_records=review_journal.records()
                    if route=='repair':
                        manifest=Path(self.temp.name)/'handoff-repairs.json'
                        atomic_json(manifest,{'tasks':[{'id':'fix','title':'Repair fixture behavior','instructions':'Fix the retained feedback.'}]})
                        scope=prepared.prepare(self.root,manifest=manifest,review=feedback['id'])
                        source=self.human(host=host,session='entry-'+route+fault)
                        action=lambda:native.approve_scope(self.root,scope['scope_id'],source)
                    else:
                        source=self.human('/oh-deliver 0001',host=host,session='entry-'+route+fault)
                        action=lambda:native.prepare_scope(self.root,doc='0001',human=source,keep_checkout=True)
                    source=source|{'at':datetime.now(timezone.utc).isoformat()}
                    key=native._human_key(source);write=native.atomic_json;append=Journal.append
                    control_write=cancellation.atomic_json;old_owner=cancellation._read(self.root)['current']
                    def fail_pointer(path,value,*args,**kwargs):
                        if ((fault=='canonical' and Path(path).name=='oh-active-run.json' and value.get('run')!=old['id']) or
                                (fault=='review-deselection' and Path(path).name=='oh-active-review.json' and value.get('selected') is False)):
                            raise OSError('interrupted entry '+fault)
                        return write(path,value,*args,**kwargs)
                    def fail_owner(path,value,*args,**kwargs):
                        if fault=='owner-before-review' and Path(path).name=='oh-native-execution.json' and value.get('current')!=old_owner:
                            raise OSError('interrupted entry owner')
                        return control_write(path,value,*args,**kwargs)
                    def fail_grant(journal,kind,data):
                        if fault=='grant' and kind=='grant' and data.get('source')==key:raise OSError('interrupted entry grant')
                        return append(journal,kind,data)
                    def entries():
                        result=[]
                        for path in old_journal.path.parent.glob('*/000001.json'):
                            if read_json(path)['data'].get('source')!=key:continue
                            journal=Journal(old['project'],path.parent.name)
                            result.append((journal,reduce(journal.records())))
                        return result
                    with patch.object(native,'atomic_json',side_effect=fail_pointer),patch.object(Journal,'append',new=fail_grant), \
                            patch.object(cancellation,'atomic_json',side_effect=fail_owner):
                        with self.assertRaisesRegex(OSError,'interrupted entry'):action()
                    pending=entries();self.assertEqual(len(pending),1)
                    pending_journal,pending_state=pending[0];records=pending_journal.records()
                    self.assertEqual(load_run(self.root)[1]['id'],feedback['id'])
                    if fault=='owner-before-review':
                        with self.assertRaisesRegex(Refused,'superseded'):native.admit(self.root,'review')
                        self.assertEqual(review_journal.records(),review_records)
                    result=action();journal,selected=load_run(self.root)
                    self.assertEqual(selected['id'],result['run'])
                    if fault!='canonical':
                        self.assertEqual(selected['id'],pending_state['id'])
                        self.assertEqual(journal.records()[:len(records)],records)
                    else:
                        self.assertEqual(pending_journal.records(),records)
                        self.assertFalse(pending_state['granted'])
                    grants=[r for j,_ in entries() for r in j.records() if r['kind']=='grant']
                    self.assertEqual(len(grants),1);self.assertEqual(grants[0]['data']['source'],key)
                    self.assertEqual(selected['granted'],['fix' if route=='repair' else '1'])
                    self.assertEqual(read_json(active_file(self.root))['run'],selected['id'])
                    self.assertEqual(cancellation._read(self.root)['current'],cancellation.owner_key(selected))
                    complete=journal.records();action();self.assertEqual(journal.records(),complete)
                    self.assertEqual(old_journal.records(),old_records)
                    self.assertEqual(review_journal.records(),review_records)
                    if fault in ('canonical','owner-before-review'):
                        # Exercise next admission once per entry route and after owner repair.
                        self.assess()
                    if route=='repair' and fault=='review-deselection':
                        current=cancellation._read(self.root)['current'];save=cancellation.atomic_json
                        def newer_failed_owner(path,value,*args,**kwargs):
                            if Path(path).name=='oh-native-execution.json' and value.get('current')!=current:
                                raise OSError('newer feedback owner still saving')
                            return save(path,value,*args,**kwargs)
                        with patch.object(cancellation,'atomic_json',side_effect=newer_failed_owner),self.assertRaisesRegex(OSError,'newer feedback'):
                            native.review(self.root,'paths product.txt',self.human('/oh-review paths product.txt',session='newer-feedback'))
                        newer_journal,_=load_run(self.root);newer_records=newer_journal.records()
                        pointer=read_json(active_file(self.root));before=journal.records()
                        with self.assertRaisesRegex(Refused,'newer'):action()
                        self.assertEqual(read_json(active_file(self.root)),pointer)
                        self.assertEqual(cancellation._read(self.root)['current'],current)
                        self.assertEqual(journal.records(),before);self.assertEqual(newer_journal.records(),newer_records)

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

    def test_failed_codex_turn_ignores_legacy_tool_callbacks_and_reuses_cross_host_continue(self):
        from . import authority
        from .storage import read_json
        self.approve();self.assess()
        admitted=native.admit(self.root,'implementation')
        native.bind(self.root,admitted['id'],{'child_session':'failed-child'})
        attempt=load_run(self.root)[1]['attempts'][-1]
        with cancellation._edit(self.root) as value:
            value['attempts'][admitted['id']]['guard_observed']=True
            for key,name in (('missed-patch','apply_patch'),('external-write','mcp__external__write')):
                value['tools'][key]={'attempt':admitted['id'],'kind':'tool','name':name,'started':now()}
        (self.root/'output.txt').write_text('Keep the implementation.\n',newline='\n')
        before=load_run(self.root)[1]
        error={'message':'Selected model is at capacity.','codex_error_info':'server_overloaded'}
        event={'type':'event_msg','timestamp':now(),'payload':{
            'type':'task_complete','last_agent_message':None,'error':error}}
        self.parent_path.write_text(json.dumps(event)+'\n',newline='\n')
        gate=decisions.prepare(self.root,'recover');answer=self.answer(gate,'Continue')
        # Parse native terminal evidence rather than mocking a successful result.
        with patch('oh.authority._path',return_value=self.parent_path), \
                patch('oh.authority.native_result',side_effect=authority._native_result):
            # The failed worker outcome is real; ordinary per-tool callbacks are
            # no longer extra cleanup obligations, even for old snapshot records.
            native.decision(self.root,'resume',answer)
            native.decision(self.root,'resume',answer)
        after=load_run(self.root)[1]
        self.assertEqual(after['host'],'claude')
        for key in ('missed-patch','external-write'):
            self.assertNotIn('ended',cancellation._read(self.root)['tools'][key])
        for key in ('granted','done','config'):self.assertEqual(after[key],before[key])
        self.assertTrue(after['attempts'][-1]['finished'])
        self.assertNotEqual(after['attempts'][-1]['outcome'],'reported')
        retained=read_json(Path(attempt['evidence'])/'native-result.json')
        self.assertEqual((retained['status'],retained['error']),('failed',error))
        self.assertEqual((self.root/'output.txt').read_text(),'Keep the implementation.\n')
        fresh=native.admit(self.root,'implementation')
        self.assertNotEqual(fresh['id'],admitted['id'])

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
        from . import authority
        attempt=self.orphan()
        with cancellation._edit(self.root) as value:
            value['tools']['pending-resume']={'attempt':attempt['id'],'kind':'resume','name':'SendMessage','started':now()}
        (self.root/'output.txt').write_text('human takes over',newline='\n')
        before=self.git('status','--porcelain')
        gate=decisions.prepare(self.root,'recover')
        answer=self.answer(gate,'Stop and take over',host='codex')
        new_parent=Path(self.temp.name)/'new-parent.jsonl';new_parent.write_text('',newline='\n')
        answer['transcript_path']=str(new_parent)
        with patch('oh.authority.native_result',side_effect=FileNotFoundError('deleted native transcript')), \
                patch('oh.recovery.facts',side_effect=FileNotFoundError('missing private plan after preparation')):
            with patch.object(authority,'claude_operations',side_effect=authority.Unavailable('Deleted parent')):
                with self.assertRaisesRegex(Refused,'operations are still settling'):native.decision(self.root,'stop',answer)
                self.assertNotIn('ended',cancellation._read(self.root)['tools']['pending-resume'])
            with patch.object(authority,'claude_operations',return_value={'pending-resume':{'state':'rejected','started':now()}}):
                native.decision(self.root,'stop',answer)
            with patch.object(authority,'claude_operations',side_effect=authority.Unavailable('Deleted parent')):
                native.decision(self.root,'stop',answer)
        self.assertEqual(load_run(self.root)[1]['status'],'stopped')
        self.assertEqual(self.git('status','--porcelain'),before)
        with self.assertRaisesRegex(Refused,'not running'):native.admit(self.root,'assessment')

    def test_takeover_settles_guarded_saved_review_without_changing_files(self):
        self.approve()
        delivery_journal,delivery=load_run(self.root)
        review=native.review(self.root,'changes',self.human('Review my work'))
        pending=native.admit(self.root,'review')
        with cancellation._edit(self.root) as value:
            value['attempts'][pending['id']]['guard_observed']=True
        artifact=load_run(self.root,review['run'])[1]['standalone_artifact']
        (Path(artifact['root'])/'product.txt').unlink()
        note=self.root/'local.txt';note.write_text('Keep my draft.\n',newline='\n')
        offer=decisions.prepare(self.root,'resume',run=review['run'])
        answer=self.answer(offer,'Stop and take over')
        before=delivery_journal.records()
        with self.assertRaisesRegex(Refused,'different decision'):
            native.decision(self.root,'stop',answer,run=delivery['id'])
        unbound={k:v for k,v in answer.items() if k!='decision'}
        with self.assertRaisesRegex(Refused,'bound decision effect'):
            native.decision(self.root,'stop',unbound,run=delivery['id'])
        self.assertEqual(native.decision(self.root,'stop',answer)['status'],'stopped')
        journal,state=load_run(self.root,review['run'])
        self.assertEqual(state['attempts'][0]['outcome'],'abandoned')
        self.assertEqual(state.get('review_grants',[]),[])
        self.assertEqual(note.read_text(),'Keep my draft.\n')
        self.assertEqual(delivery_journal.records(),before)
        retained=journal.records()
        self.assertEqual(native.decision(self.root,'stop',answer,run=review['run'])['status'],'stopped')
        self.assertEqual(journal.records(),retained)

        resume=decisions.prepare(self.root,'recover',run=delivery['id'])
        native.decision(self.root,'resume',self.answer(resume,'Continue',session='delivery-resume'))
        explicit=decisions.prepare(self.root,'stop',run=review['run'])
        self.assertEqual(explicit['options'],['Stop and take over'])
        result=native.decision(self.root,'stop',self.answer(explicit,'Stop and take over')|{'via':'text'})
        self.assertEqual(result['run'],review['run'])
        self.assertEqual(load_run(self.root)[1]['id'],delivery['id'])
        self.assertEqual(native.admit(self.root,'assessment')['role'],'assessment')

    def test_partial_native_report_and_recovery_keep_findings_when_late_retention_retries(self):
        from . import authority,handoff
        from .storage import digest,read_json
        from .workflow import reduce
        self.approve();self.assess();self.implement();native.candidate(self.root);native.verify(self.root)
        pending=native.admit(self.root,'review');native.bind(self.root,pending['id'],{'child_session':'pending-review'})
        findings=[{'severity':s,'family':s,'description':'Retain original '+s} for s in ('blocking','concern','scope')]
        row={'type':'fixture-native','report':findings}
        self.parent_path.write_text(json.dumps(row)+'\n',newline='\n')
        report={'status':'completed','text':json.dumps({'verdict':'findings','findings':findings}),'record_hashes':[digest(row)]}
        self.native_results[pending['id']]=report
        with cancellation._edit(self.root) as value:value['attempts'][pending['id']]['guard_observed']=True
        write=native._immutable
        def interrupted(path,value):
            if Path(path).name=='result.json':raise OSError('Partial canonical selection')
            return write(path,value)
        with patch.object(native,'_immutable',side_effect=interrupted),self.assertRaises(OSError):native.retain(self.root,pending['id'],{})
        canonical=Path(pending['request']).parent/'native-result.json';original=canonical.read_bytes()
        del self.native_results[pending['id']]
        offer=decisions.prepare(self.root,'recover')
        native.decision(self.root,'resume',self.answer(offer,'Continue',host='codex'))
        journal,state=load_run(self.root);old=next(a for a in state['attempts'] if a['id']==pending['id'])
        self.assertEqual(old['outcome'],'abandoned');self.assertEqual(old['findings'],[])
        diagnostics=handoff.finding_index(state,'1')['diagnostics']
        self.assertEqual([f['severity'] for f in next(d for d in diagnostics if d['findings'])['findings']],['blocking','concern','scope'])
        self.assertEqual(old['source_ref']['kind'],'revocation');self.assertEqual(canonical.read_bytes(),original)
        projection={k:old.get(k) for k in ('findings','finding_positions','finding_sources','report_issues')}
        self.native_results[pending['id']]={'status':'completed','text':json.dumps({'verdict':'clean','findings':[]})}
        def interrupted_late(path,value):
            if Path(path).name.startswith('late-report-'):raise OSError('Partial late report')
            return write(path,value)
        with patch.object(native,'_immutable',side_effect=interrupted_late),self.assertRaises(OSError):native.retain(self.root,pending['id'],{})
        native.retain(self.root,pending['id'],{})
        journal,state=load_run(self.root);old=next(a for a in state['attempts'] if a['id']==pending['id'])
        self.assertEqual({k:old.get(k) for k in projection},projection)
        self.assertEqual(canonical.read_bytes(),original)
        self.assertEqual(read_json(old['late_report']['path'])['findings'],[])
        index=handoff.finding_index(state,'1')
        self.assertEqual(index['families'],[])
        self.assertEqual(len(next(d for d in index['diagnostics'] if d['findings'])['findings']),3)
        records=journal.records();native.retain(self.root,pending['id'],{});self.assertEqual(journal.records(),records)
        with self.assertRaisesRegex(Refused,'cannot change'):
            reduce(records+[{'kind':'attempt.late-result','at':now(),'data':{'id':pending['id'],'findings':[{'severity':'blocking','description':'Late replacement'}]}}])

    def test_changed_files_invalidate_destructive_choice_and_pending_commands_still_block(self):
        old=self.orphan()
        gate=decisions.prepare(self.root,'recover')
        answer=self.answer(gate,'Start fresh')
        (self.root/'surprise.txt').write_text('new user edit',newline='\n')
        with self.assertRaisesRegex(Refused,'changed since'):native.decision(self.root,'restart',answer)
        self.assertTrue((self.root/'surprise.txt').exists())
        displayed=decisions.prepare(self.root,'recover')
        (self.root/'surprise.txt').write_text('More edits at the same path',newline='\n')
        updated=decisions.prepare(self.root,'recover')
        self.assertEqual(displayed['options'],updated['options'])
        self.assertNotEqual(displayed['question'],updated['question'])
        with self.assertRaisesRegex(Refused,'does not match the prepared offer'):
            native.decision(self.root,'restart',self.answer(displayed,'Start fresh')|{'decision':updated['decision']})
        typed=self.answer(displayed,'Start fresh')|{'via':'text','question_context':[
            {'text':offer['question'],'at':now()} for offer in (displayed,updated)]}
        with self.assertRaisesRegex(Refused,'actual native question'):
            native.decision(self.root,'restart',typed)
        self.assertEqual((self.root/'surprise.txt').read_text(),'More edits at the same path')
        with cancellation._edit(self.root) as value:
            value['commands']['pending-command']={'attempt':old['id'],'started':now()}
        with self.assertRaisesRegex(Refused,'cleanup is still pending'):self.recover('resume')
        self.assertFalse(load_run(self.root)[1]['attempts'][0]['finished'])
        # Continue keeps work written while the question was open or cleanup ran.
        # Its already-selected effect does not authorize a reset of those files.
        gate=decisions.prepare(self.root,'recover');answer=self.answer(gate,'Continue')
        new_parent=Path(self.temp.name)/'new-parent.jsonl';new_parent.write_text('',newline='\n')
        answer['transcript_path']=str(new_parent)
        original_settle=recovery._settle
        def settle(*args):
            with cancellation._edit(self.root) as value:value['commands']['pending-command'].update(ended=now(),returncode=0)
            (self.root/'surprise.txt').write_text('final worker write',newline='\n')
            return original_settle(*args)
        with patch('oh.authority.native_result',side_effect=FileNotFoundError('deleted native transcript')), \
                patch.object(recovery,'_settle',side_effect=settle):
            native.decision(self.root,'resume',answer)
        self.assertEqual((self.root/'surprise.txt').read_text(),'final worker write')
        self.assertEqual(native.decision(self.root,'resume',answer)['status'],'running')

    def test_restart_keeps_review_spend_and_findings(self):
        self.approve();self.assess();self.implement()
        review=self.reviewed({'verdict':'blocking','findings':[{'severity':'blocking','description':'Repair this behavior'}]})
        stale=decisions.prepare(self.root,'approve-repair',repair='An earlier proposed repair.')
        subject=native._subject(self.root,load_run(self.root)[1])
        gate=decisions.prepare(self.root,'approve-repair',repair='Repair the shared fixture needed by this task.')
        native.decision(self.root,'approve-repair',self.answer(gate,gate['options'][0],host='codex',session='s'))
        self.assertTrue(load_run(self.root)[1]['approved_repairs'])
        self.recover('restart')
        state=load_run(self.root)[1]
        self.assertFalse(state['approved_repairs'])
        (self.root/'output.txt').write_text('implemented\n',newline='\n')
        self.assertEqual(native._subject(self.root,state),subject)
        with self.assertRaisesRegex(Refused,'subject changed'):
            native.decision(self.root,'approve-repair',self.answer(stale,stale['options'][0],host='claude'))
        self.assertEqual(state['attempts'][-1]['findings'][0]['description'],'Repair this behavior')
        self.assertTrue(state['attempts'][-1]['superseded'])
        self.assertEqual(sum(a['role']=='review' for a in state['attempts']),1)
        with self.assertRaisesRegex(Refused,'Recovery changed'):native.complete(self.root,review['id'])

    def test_continue_clean_delivery_keeps_assessment_and_retries_reported_work(self):
        from .test_fixtures_plans import delivery_documents
        from .storage import read_json
        delivery_documents(self)
        self.git('switch','-c','deliver/0001')
        prepared=native.prepare_scope(self.root,doc='0001')
        native.approve_scope(self.root,prepared['scope_id'],self.human())
        assessed=self.assess()
        text='Blocked before source inspection. No source edits, candidate, or verification.'
        author=self.finish_attempt('implementation',text)
        self.assertEqual(author['outcome'],'reported')
        before=load_run(self.root)[1]
        self.recover('resume')
        journal,state=load_run(self.root)
        self.assertEqual(state['branch'],before['branch'])
        self.assertEqual(state['assessments']['1']['attempt'],assessed['id'])
        self.assertFalse(any(a.get('superseded') for a in state['attempts']))
        self.assertEqual(state['granted'],before['granted'])
        self.assertFalse(any(r['kind']=='recovery.started' for r in journal.records()))
        self.assertEqual(read_json(Path(author['evidence'])/'native-result.json')['text'],text)
        # Old snapshots may already have superseded every attempt on a no-op Continue.
        # The retained assessment still determines which role can be admitted.
        legacy=dict(state,attempts=[dict(a,superseded=True) for a in state['attempts']])
        self.assertEqual(native._continuation(legacy)['phase'],'implementation')
        with self.assertRaisesRegex(Refused,'final configured checks'):native.admit(self.root,'review')
        self.implement();review=self.reviewed();native.complete(self.root,review['id'])
        self.assertIn('1',load_run(self.root)[1]['done'])

    def test_private_restart_restores_approved_plan_and_completes_with_valid_publication_evidence(self):
        from .test_fixtures_plans import delivery_documents
        from . import plans, delivery_verify
        where,path=delivery_documents(self,'private')
        initial=path.read_text()
        prepared=native.prepare_scope(self.root,doc='0001')
        native.approve_scope(self.root,prepared['scope_id'],self.human())
        path.unlink()
        unavailable=decisions.prepare(self.root,'recover')
        self.assertEqual(unavailable['options'],['Stop and take over'])
        self.assertIn('Restore the required recovery input',unavailable['question'])
        stopped=native.decision(self.root,'stop',self.answer(unavailable,'Stop and take over')|{'via':'text'})
        self.assertEqual(stopped['status'],'stopped')
        self.assertFalse(path.exists())
        path.write_text(initial,newline='\n')
        self.recover('resume')
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

    def test_legacy_late_report_preserves_projection_and_retries_partial_save(self):
        from .storage import Journal,read_json
        from .handoff import report_reference,finding_index
        from .workflow import reduce
        self.approve();self.assess();self.implement();native.candidate(self.root);native.verify(self.root)
        pending=native.admit(self.root,'review');native.bind(self.root,pending['id'],{'child_session':'legacy-revoked-review'})
        journal,state=load_run(self.root);directory=Path(pending['request']).parent
        original={'severity':'blocking','family':'legacy','description':'Committed legacy blocker'}
        (directory/'result.json').write_text(json.dumps({'verdict':'findings','findings':[None]*6+[original]}),newline='\n')
        (directory/'revoked-result.json').write_text(json.dumps({'status':'cancelled','text':'Stopped'}),newline='\n')
        journal.append('attempt.finished',{'id':pending['id'],'outcome':'abandoned',
            'revocation':{'decision':'legacy-stop'},'findings':[original],'finding_positions':[7],'summary':'Original stopped attempt'})
        # Model an old writer that saved the file but never committed its late event.
        (directory/'native-result.json').write_text('{"partial":"legacy source"}',newline='\n')
        self.native_results[pending['id']]={'status':'completed','text':json.dumps({'verdict':'findings','findings':[
            {'severity':'concern','family':'late','description':'New late observation'}]})}
        append=Journal.append
        def crash(j,kind,data):
            if kind=='attempt.late-result':raise OSError('Late event not committed')
            return append(j,kind,data)
        with patch.object(Journal,'append',new=crash),self.assertRaisesRegex(OSError,'Late event'):
            native.retain(self.root,pending['id'],{})
        result=native.retain(self.root,pending['id'],{})
        self.assertEqual(result['findings'],[original]);self.assertEqual(result['finding_positions'],[7])
        self.assertEqual(result['outcome'],'abandoned');self.assertEqual(result['summary'],'Original stopped attempt')
        self.assertEqual(report_reference(result)['path'],str(directory/'result.json'))
        self.assertEqual(read_json(result['late_report']['path'])['findings'][0]['description'],'New late observation')
        journal,state=load_run(self.root);records=journal.records()
        native.retain(self.root,pending['id'],{})
        self.assertEqual(journal.records(),records)
        self.assertEqual(finding_index(state,'1')['families'][0]['occurrences'][0]['id'],pending['id']+'#7')
        self.assertEqual(len(finding_index(state,'1')['diagnostics']),1)
        with self.assertRaisesRegex(Refused,'cannot change'):
            reduce(records+[{'kind':'attempt.late-result','at':now(),'data':{
                'id':pending['id'],'late_source':result['late_source'],'findings':[]}}])


if __name__=='__main__':unittest.main()
