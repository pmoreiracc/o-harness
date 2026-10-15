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
