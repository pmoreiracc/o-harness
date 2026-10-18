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
    def planning(self,workflow,location,request=None):
        change(self.root,'plans.private_folder',str(Path(self.temp.name)/'plans'))
        change(self.root,'plans.location',location)
        self.where=plans.layout(self.root)
        plans.start_roadmap(self.where,'Fixture');plans.add_milestone(self.root,self.where,'M1','First','It works')
        plans.add_initiative(self.root,self.where,'M1','auth','Sign-in',[])
        if location=='repo':self.git('add','.');self.git('commit','-qm','planning context')
        manifest={'tasks':[{'id':workflow,'title':'Plan the sign-in flow','instructions':'Write the requested bounded plan.'}]}
        prompt=request or ('Plan the sign-in flow.' if workflow=='design' else 'Propose the sign-in flow.')
        return native.prepare_scope(self.root,manifest,workflow=workflow,human=self.human(prompt))

    def test_private_design_requires_human_approval_of_the_exact_reviewed_artifacts(self):
        self.planning('design','private',request='/oh-design auth');head=self.git('rev-parse','HEAD')
        with self.assertRaises(Refused):native.admit(self.root,'assessment')
        def write_plan():
            number,path=plans.write_design(self.root,self.where,'auth','Sign-in',BODY,'draft')
            plans.claim(self.root,self.where,'auth',number);self.document=Path(path)
        self.finish_attempt('analysis',{'summary':'Wrote the bounded design.'},edit=write_plan)
        outside={'severity':'scope','description':'Add a separate sign-out task later.','family':'signout','path':''}
        review=self.reviewed({'verdict':'scope','summary':'The bounded design is ready; retain a future task.','findings':[outside]})
        from .scope import track,followups
        self.assertEqual(track(self.root,review['id'])['destination'],{'saved':True})
        self.assertEqual(followups(load_run(self.root)[1])[0]['findings'],[outside])
        self.assertEqual(native.select(self.root)['continuation']['pending_decision'],'private_approval')
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        original=self.document.read_text();self.document.write_text(original+'\nChanged after review.\n',newline='\n')
        with self.assertRaises(Refused):
            native.decision(self.root,'approve-private',self.human('approve'),attempt=review['id'])
        self.document.write_text(original,newline='\n')
        native.decision(self.root,'approve-private',self.human('approve'),attempt=review['id'])
        native.complete(self.root,review['id'])
        completed=load_run(self.root)[1]
        records=load_run(self.root)[0].records()
        again=native.prepare_scope(self.root,{'tasks':[]},workflow='design',human=self.human('/oh-design auth'))
        self.assertEqual(again['run'],completed['id'])
        self.assertEqual(again['continuation']['phase'],'finished')
        self.assertEqual(load_run(self.root)[0].records(),records)
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

    def test_design_reentry_preserves_draft_and_scope_before_preparation(self):
        first=self.planning('design','private',request='/oh-design auth')
        journal,before=load_run(self.root)
        draft=Path(self.where['designs'])/'0001-auth.md'
        draft.parent.mkdir(parents=True,exist_ok=True)
        draft.write_text('Human-edited unfinished draft.\n',newline='\n')
        admitted=native.admit(self.root,'analysis')
        native.bind(self.root,admitted['id'],{'child_session':'old-author'})
        native.decision(self.root,'pause',self.human('pause'))
        from .storage import now
        request=self.human('/o-harness:oh-design auth',session='new-parent',host='claude',at=now())
        manifest={'tasks':[{'id':'replacement','title':'Do not restart','instructions':'This must not replace the saved scope.'}]}
        scopes=list((journal.path.parent.parent/'scopes').iterdir())
        discovered=native.prepare_scope(self.root,manifest,workflow='design',human=request)
        self.assertTrue(discovered['resume_required'])
        choice=self.resume_choice(session='new-parent',host='claude',at=now())
        with self.assertRaisesRegex(Refused,'native attempt'):native.resume(self.root,choice,run=first['run'])
        # Host terminal evidence arrives after the valid human command. Keep that
        # command while settling the old author instead of asking for it again.
        self.native_results[admitted['id']]={'text':'{"summary":"Retained the interrupted draft."}','status':'completed'}
        native.retain(self.root,admitted['id'],{})
        before=load_run(self.root)[1]
        self.assertTrue(native.prepare_scope(self.root,manifest,workflow='design',human=request)['resume_required'])
        self.assertEqual(load_run(self.root)[1]['human'],before['human'])
        resumed=native.resume(self.root,choice,run=first['run'])
        self.assertEqual(resumed['run'],first['run'])
        self.assertEqual(list((journal.path.parent.parent/'scopes').iterdir()),scopes)
        self.assertEqual(draft.read_text(),'Human-edited unfinished draft.\n')
        after=load_run(self.root)[1]
        for key in ('scope_id','tasks','config','granted','attempts'):self.assertEqual(after[key],before[key])
        records=journal.records()
        self.assertEqual(native.resume(self.root,choice,run=first['run'])['run'],first['run'])
        self.assertEqual(journal.records(),records)
        for prompt in ('/oh-design','/oh-design other'):
            with self.assertRaises(Refused):native.resume(self.root,self.human(prompt),run=first['run'])
        with self.assertRaises(Refused):native.prepare_scope(self.root,manifest|{'design':'other'},workflow='design',human=self.human('/oh-design auth'))

    def test_proposal_reentry_keeps_preview_and_does_not_approve_additions(self):
        self.planning('propose','repo')
        author=self.finish_attempt('analysis',{'summary':'The proposal preview still needs a human decision.'})
        journal,before=load_run(self.root);records=journal.records()
        facts=native.saved_work(self.root)['saved_work'][0]
        self.assertEqual(facts['phase'],'analysis_result')
        self.assertEqual(facts['pending_decision'],'proposal_approval')
        self.assertEqual(journal.records(),records)
        with self.assertRaises(Refused):native.resume(self.root,self.human('/oh-propose improve sign-in',session='new-parent'),run=before['id'])
        native.resume(self.root,self.resume_choice(session='new-parent'),run=before['id'])
        after=load_run(self.root)[1]
        for key in ('scope_id','tasks','config','granted','attempts'):self.assertEqual(after[key],before[key])
        self.assertFalse(after.get('proposal_answers'))
        self.assertEqual(after['attempts'][-1]['id'],author['id'])
