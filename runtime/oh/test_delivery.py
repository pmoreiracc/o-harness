import json
from pathlib import Path
import unittest
from unittest.mock import patch
from . import delivery,plans
from .cli import host_hook
from .config import change
from .runner import run
from .storage import Refused,read_json
from .workflow import choose,load_run
from . import test_workflow as fixtures
from .test_design import BODY


class DeliveryTest(unittest.TestCase):
    git=fixtures.WorkflowTest.git
    event=fixtures.WorkflowTest.event
    fake=fixtures.WorkflowTest.fake

    def setUp(self):
        fixtures.WorkflowTest.setUp(self)
        self.git('switch','main')
        fixtures.configure(self.root,tasks_per_batch=1)

    def documents(self,location='repo',body=BODY):
        change(self.root,'plans.private_folder',str(Path(self.temp.name)/'plans'))
        change(self.root,'plans.location',location)
        where=plans.layout(self.root)
        plans.start_roadmap(where,'Fixture');plans.add_milestone(self.root,where,'M1','First','It works')
        plans.add_initiative(self.root,where,'M1','auth','Sign in',[])
        number,path=plans.write_design(self.root,where,'auth','Sign in',body,'approved')
        plans.claim(self.root,where,'auth',number)
        if location=='private':plans.approve(self.root,where,number,'human-approved',False)
        else:self.git('add','.');self.git('commit','-qm','approved plan')
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        return where,Path(path)

    def start_delivery(self,arguments='0001',turn='delivery'):
        prompt='/oh-deliver '+arguments
        return host_hook(self.root,'codex',{'prompt':prompt},verified=self.event(turn,prompt))

    def test_code_routes_list_document_track_and_quick_fix(self):
        self.assertEqual(delivery.parse('')['kind'],'list')
        self.assertEqual(delivery.parse('0005 code'),{'kind':'design','doc':'0005','track':'code','request':None})
        self.assertEqual(delivery.parse('fix the sign-in timeout')['kind'],'quick_fix')
        for invalid in ('0005 code extra','123','0005 request:bad'):
            with self.assertRaises(Refused):delivery.parse(invalid)
        from .entry import receive
        from .authority import pending_file
        result=receive(self.root,'codex',{'prompt':'/oh-deliver fix X'})
        self.assertTrue(result['prepare']);self.assertFalse(result['authorized'])
        self.assertFalse(pending_file(self.root).exists())

    def test_repository_design_starts_once_and_uses_existing_batch_runner(self):
        where,path=self.documents();listed=delivery.listing(self.root)
        self.assertEqual(len(listed['ready']),1);self.assertEqual(len(self.calls),0)
        self.start_delivery();first=load_run(self.root)[1]['id']
        self.start_delivery();self.assertEqual(load_run(self.root)[1]['id'],first)
        self.assertTrue(self.git('branch','--show-current').startswith('codex/oh-'))
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertIn('- [x] **1.**',path.read_text())
        self.start_delivery();self.assertEqual(load_run(self.root)[1]['id'],first)
        self.assertEqual(run(self.root,self.fake)['completed'],1)
        choose(self.root,'continue',self.event('next','continue'))
        self.assertEqual(run(self.root,self.fake)['status'],'completed')
        self.assertIn('status: frozen',path.read_text())
        self.assertEqual(self.git('status','--porcelain'),'')

    def test_private_progress_is_reviewed_then_published_after_code_commit(self):
        where,path=self.documents('private');original=path.read_bytes();observed=[]
        def worker(*args,**kwargs):
            if args[4]=='review':
                admission=read_json(args[5]/'request.json');candidate=Path(next(iter(admission['artifact']['files'])))
                observed.append(candidate.read_text())
                if len(observed)==1:self.assertEqual(path.read_bytes(),original)
            return self.fake(*args,**kwargs)
        self.start_delivery();self.assertEqual(run(self.root,worker)['status'],'checkpoint')
        self.assertIn('- [x] **1.**',observed[0]);self.assertEqual(plans.approval(self.root,where,'0001'),'approved')
        self.assertEqual(self.git('ls-files','docs'),'')
        choose(self.root,'continue',self.event('next','continue'))
        self.assertEqual(run(self.root,worker)['status'],'completed')
        self.assertIn('status: frozen',path.read_text());self.assertEqual(len(observed),2)
        self.assertEqual(self.git('status','--porcelain'),'')

    def test_unmerged_or_edited_private_design_does_not_grant_work(self):
        where,path=self.documents()
        path.write_text(path.read_text()+'\nUnmerged scope\n');self.git('add','.');self.git('commit','-qm','unmerged')
        with self.assertRaisesRegex(Refused,'origin/main'):self.start_delivery()

    def test_private_edits_invalidate_start_and_inflight_work(self):
        where,path=self.documents('private');original=path.read_bytes()
        path.write_text(path.read_text()+'\nUnapproved scope\n')
        with self.assertRaisesRegex(Refused,'approval'):self.start_delivery()
        path.write_bytes(original);self.start_delivery()
        path.write_text(path.read_text()+'\nChanged during delivery\n')
        with self.assertRaisesRegex(Refused,'changed outside'):run(self.root,self.fake)
        self.assertEqual(self.calls,[])

    def test_ready_selection_skips_blocked_tasks_and_orders_dependencies(self):
        body=BODY.replace('- [ ] **1.** Add the credential store.','- [ ] **1.** Add the credential store. Blocked on §3.')
        body+='\n### UI track\n\n- [ ] **3.** Add a sign-in placeholder.\n\n## 3. Open questions\n\nChoose the storage.\n'
        self.documents(body=body)
        manifest,_=delivery.selection(self.root,'0001')
        self.assertEqual([t['id'] for t in manifest['tasks']],['3'])
        with self.assertRaisesRegex(Refused,'No ready'):delivery.selection(self.root,'0001','core')
        with self.assertRaisesRegex(Refused,'Unknown'):delivery.selection(self.root,'0001','missing')

    def test_private_commit_recovery_does_not_repeat_workers_or_review(self):
        where,path=self.documents('private');self.start_delivery();original=delivery.atomic_json
        def fail_after_publish(target,value,**kw):
            original(target,value,**kw)
            raise OSError('published but interrupted')
        with patch('oh.delivery.atomic_json',side_effect=fail_after_publish):
            with self.assertRaises(OSError):run(self.root,self.fake)
        committed=self.git('rev-parse','HEAD');calls=len(self.calls)
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertEqual(self.git('rev-parse','HEAD'),committed);self.assertEqual(len(self.calls),calls)
        self.assertEqual(plans.approval(self.root,where,'0001'),'approved')

    def test_private_stop_before_commit_leaves_the_approved_document_untouched(self):
        where,path=self.documents('private');original=path.read_bytes();self.start_delivery()
        def blocked(*args,**kw):
            answer=self.fake(*args,**kw)
            if args[4]=='review':answer['structured']={'verdict':'blocking','summary':'Fix code','findings':[{'severity':'blocking','description':'Wrong','path':'output.txt','family':'wrong','relation':'original'}],'evidence':fixtures.EVIDENCE}
            return answer
        self.assertEqual(run(self.root,blocked)['status'],'review_checkpoint')
        choose(self.root,'stop',self.event('stop','stop'))
        self.assertEqual(path.read_bytes(),original);self.assertEqual(plans.approval(self.root,where,'0001'),'approved')

    def test_hook_stages_a_bare_design_and_list_never_grants_work(self):
        from .entry import receive
        from .authority import pending_file
        self.documents()
        event={'hook_event_name':'UserPromptSubmit','session_id':'s','turn_id':'1','prompt':'/oh-deliver'}
        self.assertEqual(len(receive(self.root,'codex',event)['ready']),1)
        self.assertFalse(pending_file(self.root).exists())
        self.assertTrue(receive(self.root,'codex',event|{'prompt':'/oh-deliver 0001'})['pending'])

    def test_unmerged_context_and_unfinished_initiative_dependency_block_delivery(self):
        where,path=self.documents()
        plans.add_initiative(self.root,where,'M1','ledger','Ledger',['auth'])
        n,ledger=plans.write_design(self.root,where,'ledger','Ledger',BODY,'approved');plans.claim(self.root,where,'ledger',n)
        self.git('add','.');self.git('commit','-qm','unmerged context')
        with self.assertRaisesRegex(Refused,'origin/main'):self.start_delivery()
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        with self.assertRaisesRegex(Refused,'unfinished auth'):self.start_delivery(n)

    def test_private_recovery_after_code_commit_before_document_publish(self):
        where,path=self.documents('private');original=path.read_bytes();self.start_delivery()
        write=plans.write
        def interrupt(target,*args,**kwargs):
            if Path(target)==path:raise OSError('interrupted before progress publication')
            return write(target,*args,**kwargs)
        with patch('oh.plans.write',side_effect=interrupt):
            with self.assertRaises(OSError):run(self.root,self.fake)
        committed=self.git('rev-parse','HEAD');calls=len(self.calls)
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertEqual(len(self.calls),calls);self.assertEqual(self.git('rev-parse','HEAD'),committed)
        self.assertIn('- [x] **1.**',path.read_text())

    def test_worker_plan_mutation_stops_without_commit_and_retains_attempt(self):
        where,path=self.documents('private');self.start_delivery();head=self.git('rev-parse','HEAD')
        def mutate(*args,**kwargs):
            value=self.fake(*args,**kwargs);path.write_text(path.read_text()+'\nUnapproved edit\n');return value
        self.assertEqual(run(self.root,mutate)['status'],'needs_attention')
        state=load_run(self.root)[1]
        self.assertEqual(state['attempts'][-1]['outcome'],'delivery_context_changed')
        self.assertTrue((Path(state['attempts'][-1]['evidence'])/'result.json').exists())
        self.assertEqual(self.git('rev-parse','HEAD'),head)

    def test_reviewer_cannot_change_the_private_progress_candidate(self):
        where,path=self.documents('private');original=path.read_bytes();self.start_delivery();head=self.git('rev-parse','HEAD')
        def mutate(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            if args[4]=='review':
                artifact=read_json(args[5]/'request.json')['artifact'];candidate=Path(next(iter(artifact['files'])))
                candidate.write_text(candidate.read_text()+'\nChanged scope\n')
            return value
        self.assertEqual(run(self.root,mutate)['status'],'needs_attention')
        self.assertEqual(path.read_bytes(),original);self.assertEqual(self.git('rev-parse','HEAD'),head)

    def test_private_progress_cannot_skip_code_missing_from_another_branch(self):
        self.documents('private');self.start_delivery()
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        branch=self.git('branch','--show-current')
        choose(self.root,'stop',self.event('stop','stop'));self.git('switch','main')
        with self.assertRaisesRegex(Refused,'checkout does not contain'):self.start_delivery(turn='other')
        self.git('merge','--ff-only',branch)
        self.start_delivery(turn='merged')
        self.assertEqual([t['id'] for t in load_run(self.root)[1]['tasks']],['2'])

    def test_private_progress_accepts_exact_code_after_squash_merge(self):
        self.documents('private');self.start_delivery();run(self.root,self.fake)
        branch=self.git('branch','--show-current')
        choose(self.root,'stop',self.event('stop','stop'));self.git('switch','main')
        self.git('merge','--squash',branch);self.git('commit','-qm','Squash reviewed code')
        self.start_delivery(turn='squashed')
        self.assertEqual([t['id'] for t in load_run(self.root)[1]['tasks']],['2'])
