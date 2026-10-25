import json
from pathlib import Path
import unittest
from unittest.mock import patch
from . import delivery,plans
from .config import change
from .storage import digest,Refused,read_json
from .workflow import load_run
from . import test_workflow as fixtures
from .test_design import BODY


class DeliveryTest(fixtures.NativeFixture,unittest.TestCase):
    git=fixtures.WorkflowTest.git
    event=fixtures.WorkflowTest.event
    fake=fixtures.WorkflowTest.fake

    def setUp(self):
        fixtures.NativeFixture.setUp(self)
        self.git('switch','main')
        fixtures.configure(self.root,tasks_per_batch=1)

    def documents(self,location='repo',body=BODY,base='main'):
        change(self.root,'plans.private_folder',str(Path(self.temp.name)/'plans'))
        change(self.root,'plans.location',location)
        where=plans.layout(self.root)
        plans.start_roadmap(where,'Fixture');plans.add_milestone(self.root,where,'M1','First','It works')
        plans.add_initiative(self.root,where,'M1','auth','Sign in',[])
        number,path=plans.write_design(self.root,where,'auth','Sign in',body,'approved')
        plans.claim(self.root,where,'auth',number)
        if location=='private':plans.approve(self.root,where,number,'human-approved',False)
        else:self.git('add','.');self.git('commit','-qm','approved plan')
        self.git('update-ref','refs/remotes/origin/'+base,'HEAD')
        return where,Path(path)

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
        answer=self.human(gate['options'][0],decision=gate['decision'],question=gate['question'],question_at=now(),via='question')
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
        self.assertFalse(registry.exists())
        self.documents('private');before=registry.read_bytes()
        self.assertEqual(len(delivery.listing(self.root)['ready']),1)
        self.assertEqual(registry.read_bytes(),before)

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
            self.assertIn(manual,Path(prepared['preview']).read_text())
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
