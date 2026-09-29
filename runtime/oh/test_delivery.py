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
        self.git('branch','deliver/0001')  # an earlier delivery main already absorbed: retired for a fresh one
        self.start_delivery();first=load_run(self.root)[1]['id']
        self.start_delivery();self.assertEqual(load_run(self.root)[1]['id'],first)
        self.assertEqual(self.git('branch','--show-current'),'deliver/0001')
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertIn('- [x] **1.**',path.read_text())
        self.start_delivery();self.assertEqual(load_run(self.root)[1]['id'],first)
        self.assertEqual(run(self.root,self.fake)['completed'],1)
        choose(self.root,'continue',self.event('next','continue'))
        self.assertEqual(run(self.root,self.fake)['status'],'completed')
        self.assertIn('status: frozen',path.read_text())
        self.assertEqual(self.git('status','--porcelain'),'')

    def test_a_delivery_resumes_on_its_branch_and_one_pr_publishes_both_runs(self):
        from .publication import render
        blocked='- [ ] **2.** Add the sign-in endpoint. Depends on task 1.\n  *Blocked on §3.*'
        _,path=self.documents(body=BODY.replace('- [ ] **2.** Add the sign-in endpoint. Depends on task 1.',blocked)+'\n## 3. Open questions\n\nChoose the storage.\n')
        self.start_delivery();self.assertEqual(run(self.root,self.fake)['status'],'completed')  # task 2 waits on §3
        first=load_run(self.root)[1]['id'];done=self.git('rev-parse','HEAD')
        # A commit that only claims to be OH's cannot change the approved design.
        path.write_text(path.read_text().replace('credential store','credential store and send it out'),newline='\n')
        self.git('commit','-qam','tweak\n\nOH-Run: '+first)
        with self.assertRaisesRegex(Refused,'origin/main'):self.start_delivery(turn='forged')
        self.git('reset','-q','--hard',done)
        # Meanwhile main answers the open question.
        self.git('switch','-q','main');path.write_text(path.read_text().replace('\n  *Blocked on §3.*',''),newline='\n')
        self.git('commit','-qam','Answer the storage question');self.git('update-ref','refs/remotes/origin/main','HEAD')
        self.start_delivery(turn='again')
        self.assertEqual((self.git('branch','--show-current'),self.git('rev-parse','HEAD^1')),('deliver/0001',done))  # main merged in
        self.assertEqual([t['id'] for t in load_run(self.root)[1]['tasks']],['2'])
        self.assertEqual(run(self.root,self.fake)['status'],'completed')
        choose(self.root,'pr',self.event('pr','pr'))
        body=json.loads(render(self.root).split('```json\n',1)[1].rsplit('\n```',1)[0])
        self.assertEqual([r['commit'] for r in body['records']],self.git('rev-list','--reverse','--no-merges','origin/main..HEAD').splitlines())
        self.assertEqual(len(body['records']),2);self.assertEqual(list(body['grants']),[load_run(self.root)[1]['id']])

    def finish(self):
        """Deliver the whole design and stop at its pull request choice."""
        self.start_delivery();run(self.root,self.fake);choose(self.root,'continue',self.event('next','continue'))
        self.assertEqual(run(self.root,self.fake)['status'],'completed')
        return load_run(self.root)[1]['id'],self.git('rev-parse','HEAD')

    def test_a_finished_delivery_goes_to_its_pull_request_and_takes_no_more_tasks(self):
        from .workflow import _choose
        self.documents();first,head=self.finish()
        # Meanwhile the person merges a proposal that adds a task to the same design.
        self.git('switch','-q','main');where=plans.layout(self.root)
        plans.add_task(self.root,where,'0001','Core','Add sign-out.',[]);self.git('commit','-qam','Add task 3')
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        again=self.start_delivery(turn='again')  # no merge of main, no new task: the finished delivery's PR choice
        self.assertEqual((again['run'],again['gate']['choices']),(first,['pr','stop']))
        self.assertEqual((self.git('branch','--show-current'),self.git('rev-parse','HEAD')),('deliver/0001',head))
        choose(self.root,'stop',self.event('declined','stop'))  # typed at completion, like the menu's Stop
        self.assertEqual(load_run(self.root)[1]['status'],'stopped')
        # Days later, from a new conversation: the PR choice is back, and answered there.
        from .workflow import human_event
        def typed(session,host='codex'):
            event=human_event({'hook_event_name':'UserPromptSubmit','session_id':session,'turn_id':'later','prompt':'/oh-deliver 0001'},host)
            return host_hook(self.root,host,{'prompt':'/oh-deliver 0001'},verified=event)
        from .storage import Final
        with self.assertRaisesRegex(Final,'belongs to Codex'):typed('elsewhere','claude')  # said once, then spent
        self.assertEqual(typed('new')['gate']['choices'],['pr','stop'])
        self.assertEqual(load_run(self.root)[1]['human']['session'],'new')
        _choose(self.root,'pr',self.event('pr','pr'))
        self.assertEqual(load_run(self.root)[1]['status'],'pr')

    def stopped_in_conflict(self,location='repo'):
        """A delivery stopped after task 1 while someone else's change on main touches the file it wrote."""
        where,path=self.documents(location)
        self.start_delivery();self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        choose(self.root,'stop',self.event('stop','stop'));head=self.git('rev-parse','HEAD')
        self.git('switch','-q','main');(self.root/'output.txt').write_text('main\n',newline='\n')
        self.git('add','output.txt');self.git('commit','-qm','main work');self.git('update-ref','refs/remotes/origin/main','HEAD')
        with self.assertRaisesRegex(Refused,'conflicts with origin/main in output.txt. Ask the person with a menu: start over'):
            self.start_delivery(turn='again')
        self.assertEqual((self.git('rev-parse','deliver/0001'),self.git('status','--porcelain')),(head,''))
        return where,path,head

    def test_finishing_a_conflicting_delivery_without_main_hands_it_over_when_the_plans_moved(self):
        from .delivery import conflict
        _,_,head=self.stopped_in_conflict()
        conflict(self.root,'keep','0001')
        self.start_delivery(turn='kept')  # carries on without main's changes
        self.assertEqual((self.git('branch','--show-current'),self.git('rev-parse','HEAD')),('deliver/0001',head))
        self.assertEqual([t['id'] for t in load_run(self.root)[1]['tasks']],['2'])
        choose(self.root,'stop',self.event('stop again','stop'))
        # Main also changes the plans: OH can't carry on without them, so it hands the branch over, once.
        self.git('switch','-q','main');where=plans.layout(self.root)
        plans.add_initiative(self.root,where,'M1','search','Search notes',[]);self.git('add','.');self.git('commit','-qm','row')
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        conflict(self.root,'keep','0001')
        from .storage import Final
        with self.assertRaisesRegex(Final,"From here it's yours"):self.start_delivery(turn='handed over')

    def test_starting_a_conflicting_delivery_over_discards_its_branch_and_private_progress(self):
        from .delivery import conflict
        where,path,_=self.stopped_in_conflict('private')
        before=read_json(plans.approvals_file(self.root))['0001']
        self.assertIn('- [x] **1.**',path.read_text())
        with patch.dict('os.environ',{'OH_CHILD_ATTEMPT':'a'}),self.assertRaises(Refused):conflict(self.root,'fresh','0001')
        conflict(self.root,'fresh','0001')
        self.assertIn('- [ ] **1.**',path.read_text());self.assertNotIn('delivery_commit',read_json(plans.approvals_file(self.root))['0001'])
        self.assertNotEqual(read_json(plans.approvals_file(self.root))['0001'],before)
        self.start_delivery(turn='fresh')
        self.assertEqual(self.git('rev-parse','HEAD'),self.git('rev-parse','origin/main'))
        self.assertEqual([t['id'] for t in load_run(self.root)[1]['tasks']],['1','2'])  # all of it again

    def test_a_conflict_resolved_by_hand_is_reviewed_with_the_next_task_before_it_is_published(self):
        from .publication import render
        _,path,_=self.stopped_in_conflict()
        # Main also rewords the task this delivery hasn't done yet.
        self.git('switch','-q','main');path.write_text(path.read_text().replace('sign-in endpoint.','sign-in endpoint, rate limited.'),newline='\n')
        self.git('commit','-qam','Reword task 2');self.git('update-ref','refs/remotes/origin/main','HEAD')
        # The person approved the agent's plan: it merges main, resolves the conflict and commits the merge.
        self.git('switch','-q','deliver/0001')
        import subprocess
        subprocess.run(['git','-C',str(self.root),'merge','-q','origin/main'],capture_output=True)
        (self.root/'output.txt').write_text('both\n',newline='\n')
        self.git('checkout','--ours','--',str(path));self.git('commit','-qam','Merge main, keeping ours')
        with self.assertRaisesRegex(Refused,"plans must be exactly main's"):self.start_delivery(turn='stale plan')  # old task 2
        path.write_text(self.git('show','origin/main:'+path.relative_to(self.root).as_posix()).replace('- [ ] **1.**','- [x] **1.**')+'\n',newline='\n')
        self.git('commit','-qa','--amend','--no-edit')
        merge=self.git('rev-parse','HEAD')
        from .publication import commits
        with self.assertRaisesRegex(Refused,'not a clean merge'):commits(self.root,'origin/main')  # unreviewed yet
        self.start_delivery(turn='resolved');self.assertEqual(run(self.root,self.fake)['status'],'completed')
        request=read_json(next(Path(load_run(self.root)[0].path/'attempts').glob('*/merges.diff')).parent/'request.json')
        self.assertEqual(request['merges']['commits'],[merge])
        choose(self.root,'pr',self.event('pr','pr'))
        body=json.loads(render(self.root).split('```json\n',1)[1].rsplit('\n```',1)[0])
        self.assertEqual([r['evidence'].get('merges') for r in body['records']],[None,[merge]])

    def test_a_worktree_delivers_while_main_is_checked_out_elsewhere(self):
        from .registry import register
        self.documents();side=Path(self.temp.name)/'side'
        self.git('worktree','add','-q','-b','side',str(side));register(side)
        host_hook(side,'codex',{'prompt':'/oh-deliver 0001'},verified=self.event('side','/oh-deliver 0001'))
        self.assertEqual(self.git('-C',str(side),'branch','--show-current'),'deliver/0001')

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
        where,path=self.documents();self.git('switch','-qc','deliver/0001')  # scope added on the branch, not by OH
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
        body+='\n### UI track\n\n- [ ] **3.** Add a sign-in placeholder.\n  Difficulty: simple — one static page.\n\n## 3. Open questions\n\nChoose the storage.\n'
        self.documents(body=body)
        manifest,_=delivery.selection(self.root,'0001')
        self.assertEqual([t['id'] for t in manifest['tasks']],['3'])
        self.start_delivery()  # the run builds each task with the difficulty the design gave it
        self.assertEqual({k:load_run(self.root)[1]['tasks'][0][k] for k in ('difficulty','difficulty_reason')},
                         {'difficulty':'simple','difficulty_reason':'Set by the design: one static page.'})
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
        where,path=self.documents();self.git('switch','-qc','deliver/0001')
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

    def test_private_progress_resumes_the_branch_holding_its_code(self):
        self.documents('private');self.start_delivery()
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        choose(self.root,'stop',self.event('stop','stop'));self.git('switch','main')
        self.start_delivery(turn='other')
        self.assertEqual(self.git('branch','--show-current'),'deliver/0001')
        self.assertEqual([t['id'] for t in load_run(self.root)[1]['tasks']],['2'])

    def test_private_progress_accepts_exact_code_after_squash_merge(self):
        self.documents('private');self.start_delivery();run(self.root,self.fake)
        branch=self.git('branch','--show-current')
        choose(self.root,'stop',self.event('stop','stop'));self.git('switch','main')
        self.git('merge','--squash',branch);self.git('commit','-qm','Squash reviewed code')
        self.git('update-ref','refs/remotes/origin/main','HEAD')  # the pull request was squash-merged
        self.start_delivery(turn='squashed')
        self.assertEqual([t['id'] for t in load_run(self.root)[1]['tasks']],['2'])
        self.assertEqual(self.git('rev-parse','HEAD'),self.git('rev-parse','main'))  # the squashed branch was retired

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

    def test_reapproving_added_task_preserves_delivered_code_lineage(self):
        where,path=self.documents('private');self.start_delivery();run(self.root,self.fake)
        old=read_json(plans.approvals_file(self.root))['0001']
        choose(self.root,'stop',self.event('stop','stop'))
        plans.add_task(self.root,where,'0001','core','Add session expiry.',[])
        plans.approve(self.root,where,'0001','reapproved',False)
        new=read_json(plans.approvals_file(self.root))['0001']
        self.assertEqual(new['delivery_commit'],old['delivery_commit'])
        self.git('switch','main')
        with self.assertRaisesRegex(Refused,'checkout does not contain'):delivery.selection(self.root,'0001')
        with self.assertRaisesRegex(Refused,'checkout does not contain'):plans.approve(self.root,where,'0001','wrong-checkout',False)

    def test_legacy_completed_progress_requires_reapproval_bound_to_code(self):
        where,path=self.documents('private')
        (self.root/'legacy.txt').write_text('completed task code')
        self.git('add','.');self.git('commit','-qm','legacy completed work')
        path.write_text(path.read_text().replace('- [ ] **1.**','- [x] **1.**'))
        records=read_json(plans.approvals_file(self.root));records['0001']['sha256']=plans.digest_of(path)
        plans.approvals_file(self.root).write_text(json.dumps(records))
        with self.assertRaisesRegex(Refused,'reapprove'):delivery.selection(self.root,'0001')
        plans.approve(self.root,where,'0001','human-reapproval',False)
        self.assertEqual([t['id'] for t in delivery.selection(self.root,'0001')[0]['tasks']],['2'])
        self.git('checkout','HEAD^')
        with self.assertRaisesRegex(Refused,'checkout does not contain'):delivery.selection(self.root,'0001')

    def test_recovery_rejects_same_hash_approval_lineage_replacement(self):
        where,path=self.documents('private');self.start_delivery()
        original=delivery.atomic_json
        def interrupted(*args,**kwargs):raise OSError('before approval publication')
        with patch('oh.delivery.atomic_json',side_effect=interrupted):
            with self.assertRaises(OSError):run(self.root,self.fake)
        approval=plans.approvals_file(self.root);bound=read_json(approval);calls=len(self.calls)
        altered=json.loads(json.dumps(bound));altered['0001']['delivery_base']=self.git('rev-parse','HEAD')
        original(approval,altered)
        with self.assertRaisesRegex(Refused,'approval changed'):run(self.root,self.fake)
        self.assertEqual(len(self.calls),calls)
        original(approval,bound)
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertEqual(len(self.calls),calls)

    def test_no_code_completion_is_explicit_and_empty_unrecorded_ranges_are_refused(self):
        self.documents('private');self.start_delivery()
        def no_code(*args,**kwargs):
            return {'failed':False,'returncode':0,'duration_ms':10,'text':'already implemented',
                    'structured':{'verdict':'clean','summary':'Checked existing code','findings':[],'evidence':fixtures.EVIDENCE},'usage_observed':False}
        self.assertEqual(run(self.root,no_code)['status'],'checkpoint')
        record=read_json(plans.approvals_file(self.root))['0001']
        self.assertTrue(record['delivery_no_code'])
        delivery.delivered_base(self.root,record,progressed=True)
        with self.assertRaisesRegex(Refused,'empty delivery range'):
            delivery.delivered_base(self.root,record|{'delivery_no_code':False},progressed=True)
        with self.assertRaisesRegex(Refused,'checkout does not contain'):
            delivery.delivered_base(self.root,record|{'delivery_base':'0'*40},progressed=True)

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
                    path=Path(path);path.write_text(path.read_text().replace('- [ ]','- [x]'))
                    plans.write(path,freeze_render(self.root,number,layout=where))
                freeze(auth,'0001');approve_and_sync()
                with self.assertRaisesRegex(Refused,'unfinished M1'):delivery.selection(self.root,target)
                freeze(ledger,n);approve_and_sync()
                self.assertEqual(len(delivery.selection(self.root,target)[0]['tasks']),2)
                roadmap=Path(where['roadmap']);text=roadmap.read_text();start=text.index('### M1');end=text.index('### M2')
                prefix=auth.parent.relative_to(roadmap.parent).as_posix()
                roadmap.write_text(text[:start]+f'### M1 First ✅\n\nDelivered as [0001](./{prefix}/{auth.name}), [{n}](./{prefix}/{Path(ledger).name}).\n\n'+text[end:])
                approve_and_sync();self.assertEqual(len(delivery.selection(self.root,target)[0]['tasks']),2)
                if location=='private':
                    auth.write_text(auth.read_text()+'\nChanged completed design\n')
                    with self.assertRaisesRegex(Refused,'changed since'):delivery.selection(self.root,target)

    def test_crlf_plans_deliver_and_freeze_without_changing_line_endings(self):
        for location in ('repo','private'):
            with self.subTest(location=location):
                if location=='private':self.setUp()
                where,path=self.documents(location)
                for target in (path,Path(where['roadmap'])):
                    target.write_bytes(target.read_bytes().replace(b'\n',b'\r\n'))
                if location=='private':plans.approve(self.root,where,'0001','human-crlf',False)
                else:self.git('add','.');self.git('commit','-qm','CRLF plans')
                self.git('update-ref','refs/remotes/origin/main','HEAD')
                self.start_delivery();self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
                self.assertIn(b'- [x] **1.**',path.read_bytes())
                self.assertNotIn(b'\n',path.read_bytes().replace(b'\r\n',b''))
                choose(self.root,'continue',self.event('next','continue'))
                self.assertEqual(run(self.root,self.fake)['status'],'completed')
                self.assertIn(b'status: frozen\r\ndelivered: M1\r\n',path.read_bytes())
                self.assertNotIn(b'\n',path.read_bytes().replace(b'\r\n',b''))
