"""Planning artifacts use native agents and retain human approval independently of review."""
import unittest
from pathlib import Path
from . import native, plans
from .config import change
from .storage import Refused
from .workflow import load_run
from .test_workflow import NativeFixture
from .test_design import BODY


class PlanningTest(NativeFixture,unittest.TestCase):
    def planning(self,workflow,location):
        change(self.root,'plans.private_folder',str(Path(self.temp.name)/'plans'))
        change(self.root,'plans.location',location)
        self.where=plans.layout(self.root)
        plans.start_roadmap(self.where,'Fixture');plans.add_milestone(self.root,self.where,'M1','First','It works')
        plans.add_initiative(self.root,self.where,'M1','auth','Sign-in',[])
        if location=='repo':self.git('add','.');self.git('commit','-qm','planning context')
        manifest={'tasks':[{'id':workflow,'title':'Plan the sign-in flow','instructions':'Write the requested bounded plan.'}]}
        prompt='Plan the sign-in flow.' if workflow=='design' else 'Propose the sign-in flow.'
        return native.prepare_scope(self.root,manifest,workflow=workflow,human=self.human(prompt))

    def test_private_design_requires_human_approval_of_the_exact_reviewed_artifacts(self):
        self.planning('design','private');head=self.git('rev-parse','HEAD')
        with self.assertRaises(Refused):native.admit(self.root,'assessment')
        def write_plan():
            number,path=plans.write_design(self.root,self.where,'auth','Sign-in',BODY,'draft')
            plans.claim(self.root,self.where,'auth',number);self.document=Path(path)
        self.finish_attempt('analysis',{'summary':'Wrote the bounded design.'},edit=write_plan)
        review=self.reviewed()
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        original=self.document.read_text();self.document.write_text(original+'\nChanged after review.\n',newline='\n')
        with self.assertRaises(Refused):
            native.decision(self.root,'approve-private',self.human('approve'),attempt=review['id'])
        self.document.write_text(original,newline='\n')
        native.decision(self.root,'approve-private',self.human('approve'),attempt=review['id'])
        native.complete(self.root,review['id'])
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertEqual(self.git('status','--porcelain'),'')
        self.assertEqual(load_run(self.root)[1]['done'],['design'])
        self.assertTrue(review['artifacts'])

    def test_proposal_approval_does_not_replace_review_or_grant_product_implementation(self):
        self.planning('propose','repo')
        author=self.finish_attempt('analysis',{'summary':'Propose a search initiative in the first milestone.'})
        native.decision(self.root,'approve-proposal',self.human('approve'),attempt=author['id'])
        plans.add_initiative(self.root,self.where,'M1','search','Search notes',[])
        native.candidate(self.root);native.verify(self.root)
        self.assertEqual(load_run(self.root)[1]['done'],[])
        review=self.finish_attempt('review',{'verdict':'clean','summary':'Reviewed the approved addition.','findings':[]})
        native.complete(self.root,review['id'])
        self.assertIn('Search notes',self.git('show','HEAD:docs/roadmap.md'))
        self.assertEqual(load_run(self.root)[1]['done'],['propose'])
