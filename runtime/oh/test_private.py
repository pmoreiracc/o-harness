import json
from pathlib import Path
import unittest
from unittest.mock import patch
from . import plans
from .config import change
from .storage import Refused,Journal
from .workflow import choose,load_run
from .runner import run
from .test_design import design
from .test_propose import idea
from . import test_design as design_fixtures, test_propose as proposal_fixtures
from . import test_workflow as fixtures


class PrivatePlansTest(unittest.TestCase):
    git=fixtures.WorkflowTest.git
    event=fixtures.WorkflowTest.event
    worker=design_fixtures.DesignRunTest.worker
    design_run=design_fixtures.DesignRunTest.design_run

    def setUp(self):
        fixtures.WorkflowTest.setUp(self)
        self.git('switch','-q','main')
        change(self.root,'plans.private_folder',str(Path(self.temp.name)/'visible plans'))
        change(self.root,'plans.location','private')
        self.where=plans.layout(self.root)
        plans.start_roadmap(self.where,'Fixture')
        plans.add_milestone(self.root,self.where,'M1','First slice','Sign-in works')
        plans.add_initiative(self.root,self.where,'M1','auth','Sign-in',[])
        self.calls=[]

    def say(self,text):return choose(self.root,text,self.event(text,text))

    def test_private_design_waits_for_hash_bound_human_approval_without_git_changes(self):
        head=self.git('rev-parse','HEAD');self.design_run()
        result=run(self.root,self.worker([design()]))
        self.assertEqual(result['status'],'approval_checkpoint')
        path=self.where['designs']/'0001-auth.md'
        self.assertIn('status: draft',path.read_text())
        self.assertIn('approve',result['plan']['choices'])
        self.assertEqual(result['plan']['path'],str(path))
        journal,state=load_run(self.root);review=state['attempts'][-1]
        self.assertEqual(review['artifact']['files'][str(path)],plans.digest_of(path))
        self.say('approve')
        self.assertEqual(run(self.root,self.worker([]))['status'],'completed')
        self.assertEqual(plans.approval(self.root,self.where,'0001'),'approved')
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertEqual(self.git('status','--porcelain'),'')
        path.write_text(path.read_text()+'\nHuman edit\n')
        self.assertEqual(plans.listing(self.root)['initiatives'][0]['status'],'edited since approval')

    def test_private_reconsider_restores_every_plan_file(self):
        before=self.where['roadmap'].read_bytes()
        self.design_run();run(self.root,self.worker([design()]))
        self.say('reconsider')
        self.assertEqual(load_run(self.root)[1]['status'],'stopped')
        self.assertEqual(self.where['roadmap'].read_bytes(),before)
        self.assertFalse((self.where['designs']/'0001-auth.md').exists())
        self.assertEqual(self.git('branch','--show-current'),'main')

    def test_approval_refuses_a_file_changed_after_review(self):
        self.design_run();run(self.root,self.worker([design()]))
        path=self.where['designs']/'0001-auth.md';path.write_text(path.read_text()+'\nHuman edit\n')
        self.say('approve')
        with self.assertRaisesRegex(Refused,'changed after'):run(self.root,self.worker([]))
        self.assertIn('Human edit',path.read_text())
        self.assertNotEqual(plans.approval(self.root,self.where,'0001'),'approved')

    def test_private_reviewer_cannot_mutate_the_plan_and_approve_it(self):
        self.design_run();normal=self.worker([design()])
        def mutate(*args,**kwargs):
            result=normal(*args,**kwargs)
            if args[4]=='review':
                path=self.where['designs']/'0001-auth.md';path.write_text(path.read_text()+'\nReview mutation\n')
            return result
        result=run(self.root,mutate)
        self.assertEqual(result['status'],'needs_attention')
        self.assertEqual(load_run(self.root)[1]['attempts'][-1]['outcome'],'review_mutated_tree')

    def test_approval_publication_recovers_without_another_worker_or_grant(self):
        self.design_run();run(self.root,self.worker([design()]))
        self.say('approve');original=Journal.append
        def interrupt(journal,kind,data):
            if kind=='task.completed':raise OSError('publication interrupted')
            return original(journal,kind,data)
        with patch.object(Journal,'append',interrupt):
            with self.assertRaisesRegex(OSError,'publication interrupted'):run(self.root,self.worker([]))
        self.assertEqual(run(self.root,self.worker([]))['status'],'completed')
        self.assertEqual(plans.approval(self.root,self.where,'0001'),'approved')
        self.assertEqual([c[0] for c in self.calls],['analysis','review'])

    def test_private_proposal_adds_a_task_and_renews_approval_only_after_the_gate(self):
        self.design_run();run(self.root,self.worker([design()]));self.say('approve');run(self.root,self.worker([]))
        proposal_fixtures.ProposeTest.propose(self,'Rate limit sign-in')
        proposal_worker=proposal_fixtures.ProposeTest.worker(self,[idea('task')])
        result=run(self.root,proposal_worker)
        self.assertEqual(result['status'],'approval_checkpoint')
        self.assertEqual(plans.approval(self.root,self.where,'0001'),'edited since approval')
        self.say('approve');run(self.root,proposal_fixtures.ProposeTest.worker(self,[]))
        self.assertEqual(plans.approval(self.root,self.where,'0001'),'approved')
        self.assertEqual(self.git('status','--porcelain'),'')
