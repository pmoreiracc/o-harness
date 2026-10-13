import json
from pathlib import Path
import unittest
from unittest.mock import patch
from . import delivery,plans
from .cli import host_hook
from .config import change
from .runner import run
from .storage import digest,Refused,read_json
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

    def start_delivery(self,arguments='0001',turn='delivery',host='codex',session='s'):
        from .workflow import human_event
        prompt='/oh-deliver '+arguments
        event=human_event({'hook_event_name':'UserPromptSubmit','session_id':session,'turn_id':turn,'prompt':prompt},host)
        return host_hook(self.root,host,{'prompt':prompt},verified=event)

    def test_stopped_draft_continues_in_new_session_and_version_on_both_hosts(self):
        # docs/usage.md: Deliver resumes retained work before clean/merged-branch checks,
        # even before its first commit; a newer installed OH retains the original authority.
        from .controls import request, status_event
        from .workflow import review_limit
        for host,target,location,control in (('codex','codex','repo','stop'),('claude','claude','private','pause'),
                                             ('codex','claude','repo','stop'),('claude','codex','private','pause')):
            with self.subTest(host=host,target=target,location=location):
                case=DeliveryTest();case.setUp()
                try:
                    case.documents(location);case.start_delivery(host=host)
                    def stopped(*args,**kwargs):
                        value=case.fake(*args,**kwargs)
                        (case.root/'draft.txt').write_text('keep this implementation',newline='\n')
                        request(case.root,control)
                        return value|{'failed':True,'returncode':-15,'cancellation':['stopped'],'structured':None}
                    # Exercise the actual retained-tree format of older installed OH too.
                    def legacy(journal,state,value,**extra):
                        if value=='stopped':extra.pop('snapshot',None)
                        status_event(journal,state,value,**extra)
                    with patch('oh.controls.status_event',side_effect=legacy if host=='codex' else status_event):
                        self.assertEqual(run(case.root,stopped)['status'],'stopped' if control=='stop' else 'paused')
                    journal,before=load_run(case.root);head=case.git('rev-parse','HEAD')
                    fixtures.configure(case.root,tasks_per_batch=2,review_rounds=10)
                    def finish(*args,**kwargs):
                        self.assertEqual((case.root/'draft.txt').read_text(),'keep this implementation')
                        self.assertEqual(args[0],target)
                        if args[4]=='implementation':
                            self.assertEqual(args[2],before['config']['models'][target][before['tasks'][0]['difficulty']])
                            self.assertIn('same unfinished approved task',args[3]);self.assertIn('Inspect the existing diff',args[3])
                        return case.fake(*args,**kwargs)
                    with patch('oh.config.version',return_value='new-installed-version'), patch('oh.branches.refresh') as refresh:
                        result=case.start_delivery(turn='again',host=target,session='new-chat')
                        self.assertEqual(result['continuation']['task'],'1');refresh.assert_not_called()
                        _,continued=load_run(case.root)
                        self.assertEqual(continued['id'],before['id'])
                        for key in ('config','config_hash','granted','attempts','tasks','done'):
                            self.assertEqual(continued[key],before[key])
                        self.assertEqual(review_limit(continued,'1'),review_limit(before,'1'))
                        self.assertEqual(continued['human']['turn'],'again')
                        self.assertEqual(continued['host'],target)
                        self.assertTrue(all(a['host']==host for a in continued['attempts']))
                        self.assertEqual(case.git('rev-parse','HEAD'),head)
                        # Replaying this command after another Stop must not restart the worker.
                        request(case.root,'stop')
                        self.assertEqual(case.start_delivery(turn='again',host=target,session='new-chat')['status'],'stopped')
                        case.start_delivery(turn='finish',host=target,session='new-chat')
                        self.assertEqual(run(case.root,finish)['status'],'checkpoint')
                    self.assertEqual([c[0] for c in case.calls],['implementation','implementation','review'])
                    self.assertEqual(load_run(case.root)[1]['done'],['1'])
                    # A later snapshot resumes at the completed-task gate, without admitting task 2.
                    before=load_run(case.root)[1];head=case.git('rev-parse','HEAD')
                    with patch('oh.config.version',return_value='gate-runtime'),patch('oh.branches.refresh') as refresh:
                        from .storage import checkout_file,lock
                        with lock(checkout_file(case.root,'oh-runner.lock'),wait=False),self.assertRaises(Refused):
                            case.start_delivery(turn='live-boundary',host=target,session='gate-chat')
                        (case.root/'mine.txt').write_text('preserve',newline='\n')
                        with self.assertRaisesRegex(Refused,'completed delivery work'):
                            case.start_delivery(turn='dirty-boundary',host=target,session='gate-chat')
                        self.assertEqual(load_run(case.root)[1],before)
                        (case.root/'mine.txt').unlink()
                        resumed=case.start_delivery(turn='gate-boundary',host=target,session='gate-chat')
                        self.assertEqual((resumed['run'],resumed['status']),(before['id'],'checkpoint'))
                        self.assertEqual(resumed['gate']['choices'],['continue','pr','stop'])
                        self.assertEqual(run(case.root,case.fake)['status'],'checkpoint')
                        updated=load_run(case.root)[1]
                        for key in ('config','config_hash','tasks','granted','attempts','done','summaries','review_grants'):
                            self.assertEqual(updated.get(key),before.get(key))
                        self.assertEqual(updated['harness_version'],'gate-runtime')
                        self.assertEqual(updated['human']['session'],'gate-chat')
                        self.assertEqual(case.git('rev-parse','HEAD'),head)
                        refresh.assert_not_called()
                        # A publication already approved at this boundary survives a fresh session too.
                        from .workflow import human_event
                        human=human_event({'hook_event_name':'UserPromptSubmit','session_id':'gate-chat','turn_id':'publish','prompt':'pr'},target)
                        case.git('remote','add','origin','https://github.com/example/fixture.git')
                        with patch('oh.branches.fetched',return_value='origin/main'):choose(case.root,'pr',human)
                        grant=load_run(case.root)[1]['publication']
                        # Later commits prove no publication. GitHub confirms the original reviewed head is in the PR.
                        case.git('commit','--allow-empty','-qm','Human post-publication change')
                        from .test_workflow import pull_request
                        pr=pull_request(load_run(case.root)[1],head=case.git('rev-parse','HEAD'))
                        def github(root,host,endpoint,**kw):
                            if '/commits?' in endpoint:return [{'sha':grant['head']},{'sha':pr['head']['sha']}]
                            return [pr] if kw.get('pages') else pr
                        with patch('oh.config.version',return_value='publication-runtime'),patch('oh.publication.github',side_effect=github):
                            event=human_event({'hook_event_name':'UserPromptSubmit','session_id':'publication-chat','turn_id':'resume','prompt':'/oh-resume'},host)
                            resumed=host_hook(case.root,host,{'prompt':'/oh-resume'},verified=event)
                            self.assertEqual(resumed['next_action']['kind'],'published')
                            self.assertEqual(resumed['published']['number'],144)
                            self.assertNotIn('gate',resumed)
                            self.assertEqual(load_run(case.root)[1]['publication'],grant)
                            self.assertEqual((load_run(case.root)[1]['host'],load_run(case.root)[1]['human']['session']),(target,'gate-chat'))
                            from .publication import render
                            with self.assertRaises(Refused):render(case.root,base='origin/main')
                            with patch('oh.branches.to_delivery',return_value='origin/main'):
                                with self.assertRaisesRegex(Refused,'previous delivery is already published'):
                                    case.start_delivery(turn='before-merge',host=host,session='publication-chat')
                            refresh.assert_not_called()  # no new tasks merged into an open PR
                            case.git('switch','-q','main');case.git('merge','-q','deliver/0001')
                            case.git('update-ref','refs/remotes/origin/main','HEAD')
                            with patch('oh.branches.fetched',return_value='origin/main'):
                                fresh=case.start_delivery(turn='after-merge',host=host,session='publication-chat')
                            self.assertNotEqual(fresh['run'],before['id'])
                            self.assertEqual([t['id'] for t in load_run(case.root)[1]['tasks']],['2'])
                    self.assertEqual([c[0] for c in case.calls],['implementation','implementation','review'])
                finally:case.doCleanups()

    def test_stopped_continuation_rejects_changed_checkout_or_live_runner(self):
        from .controls import request
        from .storage import checkout_file,lock
        self.documents();self.start_delivery()
        def stopped(*args,**kwargs):
            value=self.fake(*args,**kwargs);request(self.root,'stop')
            return value|{'failed':True,'returncode':-15,'cancellation':['stopped'],'structured':None}
        run(self.root,stopped);before=load_run(self.root)[1]
        with lock(checkout_file(self.root,'oh-runner.lock'),wait=False):
            with self.assertRaises(Refused):self.start_delivery(turn='busy')
        (self.root/'mine.txt').write_text('mine',newline='\n')
        with self.assertRaisesRegex(Refused,'differs from OH'):
            self.start_delivery(turn='changed')
        self.assertEqual((self.root/'mine.txt').read_text(),'mine')
        (self.root/'mine.txt').unlink()
        self.git('commit','--allow-empty','-qm','My new commit')
        with self.assertRaisesRegex(Refused,'differs from OH'):self.start_delivery(turn='head')
        self.git('reset','--soft',before['base'])
        self.git('switch','-qc','other')
        with self.assertRaisesRegex(Refused,'branch changed'):self.start_delivery(turn='branch')
        self.assertEqual(load_run(self.root)[1]['status'],'stopped')
        self.assertNotIn('continuations',load_run(self.root)[1])
        # A new call cannot steal a live run, even within the same host.
        self.git('switch','-q',before['branch'])
        journal,state=load_run(self.root)
        journal.append('run.status',{'status':'running'})
        with lock(checkout_file(self.root,'oh-runner.lock'),wait=False):
            with self.assertRaisesRegex(Refused,'still running'):
                self.start_delivery(turn='live',session='new-chat')
        self.assertEqual(load_run(self.root)[1]['human'],before['human'])
        # Stop is already requested: let the existing cleanup release its lock, then
        # settle and transfer automatically without a second human invocation.
        from contextlib import ExitStack
        held=ExitStack();held.enter_context(lock(checkout_file(self.root,'oh-runner.lock'),wait=False))
        journal.append('run.status',{'status':'stopping'})
        try:
            with patch('time.sleep',side_effect=lambda _:held.close()):
                result=self.start_delivery(turn='settling',host='claude',session='new-chat')
        finally:held.close()
        self.assertEqual(result['status'],'running')
        self.assertEqual(load_run(self.root)[1]['host'],'claude')

    def test_stop_after_verified_implementation_continues_at_review_without_rebuilding(self):
        from .controls import request
        self.documents();self.start_delivery()
        def stopped(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            from .worker_checks import run as checks,submit_report
            self.assertTrue(checks(args[5])['passed'])
            self.assertTrue(submit_report(args[5],value['structured'])['accepted'])
            request(self.root,'stop');return value
        self.assertEqual(run(self.root,stopped)['status'],'stopped')
        self.start_delivery(turn='again',host='claude',session='new-chat')
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertEqual([c[0] for c in self.calls],['implementation','review'])

    def test_stopped_continuation_preserves_review_findings_and_spent_window(self):
        from .controls import request
        for severity,gate in (('blocking','review_checkpoint'),('concern','findings_checkpoint')):
            with self.subTest(severity=severity):
                case=DeliveryTest();case.setUp()
                try:
                    fixtures.configure(case.root,review_rounds=1)
                    case.documents();case.start_delivery()
                    def review(*args,**kwargs):
                        value=case.fake(*args,**kwargs)
                        if args[4]=='review':value['structured'].update(verdict=severity,findings=[
                            {'severity':severity,'description':'Fix credential boundary','path':'output.txt','family':'credentials','relation':'original'}])
                        return value
                    self.assertEqual(run(case.root,review)['status'],gate)
                    _,before=load_run(case.root)
                    # A new Deliver on an updated runtime keeps this exact pending choice;
                    # no stop/restart detour and no new review grant are needed.
                    with patch('oh.config.version',return_value='new-installed-version'):
                        continued=case.start_delivery(turn='updated',host='claude',session='updated-chat')
                        self.assertEqual(continued['status'],gate)
                        updated=load_run(case.root)[1]
                        self.assertEqual(updated['harness_version'],'new-installed-version')
                        self.assertEqual(updated['attempts'],before['attempts'])
                        self.assertEqual(updated['granted'],before['granted'])
                        self.assertEqual(updated.get('review_grants'),before.get('review_grants'))
                    # A pause followed by Stop must preserve the underlying findings gate too.
                    request(case.root,'pause');request(case.root,'stop')
                    continued=case.start_delivery(turn='again',session='new-chat')
                    self.assertEqual(continued['status'],gate)
                    self.assertEqual(run(case.root,case.fake)['status'],gate)
                    self.assertEqual(load_run(case.root)[1]['attempts'],before['attempts'])
                    self.assertEqual(load_run(case.root)[1].get('review_grants'),before.get('review_grants'))
                    self.assertEqual(len(case.calls),3 if severity=='blocking' else 2)
                finally:case.doCleanups()

    def test_code_routes_list_document_track_and_quick_fix(self):
        self.assertEqual(delivery.parse('')['kind'],'list')
        self.assertEqual(delivery.parse('0005 code'),{'kind':'design','doc':'0005','track':'code','request':None})
        self.assertEqual(delivery.parse('fix the sign-in timeout')['kind'],'quick_fix')
        for invalid in ('0005 code extra','123','0005 request:bad'):
            with self.assertRaises(Refused):delivery.parse(invalid)
        from .entry import receive
        from .authority import pending_file
        result=receive(self.root,'codex',{'hook_event_name':'UserPromptSubmit','session_id':'s','turn_id':'fix','prompt':'/oh-deliver fix X'})
        self.assertTrue(result['pending'])  # preparation can now offer an owner-bound approval menu
        self.assertTrue(pending_file(self.root).exists())
        # Direct prose invocation must refresh the checkout before the coordinator inspects the fix.
        import contextlib,io
        from .cli import main
        self.git('switch','-qc','feature/old')
        with patch('oh.authority.materialize',side_effect=lambda root: self.start_delivery('fix X',turn='direct')), contextlib.redirect_stdout(io.StringIO()) as output:
            main(['--root',str(self.root),'deliver','fix X'])
        self.assertEqual(json.loads(output.getvalue())['kind'],'quick_fix')
        self.assertEqual(self.git('branch','--show-current'),'main')
        self.assertEqual(self.calls,[])

    def test_repository_design_starts_once_and_uses_existing_batch_runner(self):
        self.git('branch','-m','main','master')
        title=f'Add {self.root}/credential.py.'
        where,path=self.documents(body=BODY.replace('Add the credential store.',title),base='master');listed=delivery.listing(self.root)
        self.assertEqual(len(listed['ready']),1);self.assertEqual(len(self.calls),0)
        original=self.git('rev-parse','HEAD')
        self.git('commit','--allow-empty','-qm','merged elsewhere')
        fresh=self.git('rev-parse','HEAD');self.git('update-ref','refs/remotes/origin/master',fresh)
        self.git('reset','-q','--hard',original)
        self.git('branch','deliver/0001')  # an earlier delivery main already absorbed: retired for a fresh one
        self.start_delivery();first=load_run(self.root)[1]['id']
        self.start_delivery();self.assertEqual(load_run(self.root)[1]['id'],first)
        self.assertEqual(self.git('branch','--show-current'),'deliver/0001')
        self.assertEqual(load_run(self.root)[1]['base'],fresh)
        self.assertEqual(self.git('rev-parse','master'),fresh)
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertIn('- [x] **1.**',path.read_text())
        # docs/usage.md: PR refuses an unmarked completed task, even before an agent commits the bad edit.
        saved=path.read_bytes()
        path.write_bytes(saved.replace(b'- [x] **1.**',b'- [ ] **1.**'))
        with self.assertRaisesRegex(Refused,'task 1.*done'):
            choose(self.root,'pr',self.event('bad-pr','pr'))
        path.write_bytes(saved)
        self.start_delivery();self.assertEqual(load_run(self.root)[1]['id'],first)
        self.assertEqual(run(self.root,self.fake)['completed'],1)
        choose(self.root,'continue',self.event('next','continue'))
        self.assertEqual(run(self.root,self.fake)['status'],'completed')
        self.assertIn('status: frozen',path.read_text())
        completed=delivery.listing(self.root)
        self.assertEqual(completed['ready'],[])
        self.assertIn('completed',completed['unavailable'][0]['reason'])
        self.assertNotIn('requires approval',completed['unavailable'][0]['reason'])
        self.assertEqual(self.git('status','--porcelain'),'')
        choose(self.root,'pr',self.event('good-pr','pr'))  # a correct two-task batch, including its dependency, passes
        self.assertEqual(load_run(self.root)[1]['publication']['base_branch'],'master')
        from .publication import render
        public=render(self.root)
        self.assertIn('Base branch: `master`',public)  # the approved PR target, not its local tracking ref
        self.assertIn('Task 2:',public)
        self.assertNotIn(str(self.root.parent),public)  # display redaction must not invalidate the original commit title

    def test_a_delivery_resumes_on_its_branch_and_one_pr_publishes_both_runs(self):
        from .publication import render
        blocked='- [ ] **2.** Add the sign-in endpoint. Depends on task 1.\n  *Blocked on §3.*'
        _,path=self.documents(body=BODY.replace('- [ ] **2.** Add the sign-in endpoint. Depends on task 1.',blocked)+'\n## 3. Open questions\n\nChoose the storage.\n')
        self.start_delivery();self.assertEqual(run(self.root,self.fake)['status'],'completed')  # task 2 waits on §3
        first=load_run(self.root)[1]['id'];done=self.git('rev-parse','HEAD')
        # A commit that only claims to be OH's cannot change the approved design.
        path.write_text(path.read_text().replace('credential store','credential store and send it out'),newline='\n')
        self.git('commit','-qam','tweak\n\nOH-Run: '+first)
        with self.assertRaisesRegex(Refused,"must be main's exactly"):self.start_delivery(turn='forged')
        self.git('reset','-q','--hard',done)
        # The person commits an edit of their own on the stopped branch, as OH suggests for uncommitted changes.
        (self.root/'mine.txt').write_text('mine\n',newline='\n');self.git('add','mine.txt');self.git('commit','-qm','My edit')
        mine=self.git('rev-parse','HEAD')
        # Meanwhile main answers the open question.
        self.git('switch','-q','main');path.write_text(path.read_text().replace('\n  *Blocked on §3.*',''),newline='\n')
        self.git('commit','-qam','Answer the storage question');self.git('update-ref','refs/remotes/origin/main','HEAD')
        self.start_delivery(turn='again')
        self.assertEqual((self.git('branch','--show-current'),self.git('rev-parse','HEAD^1')),('deliver/0001',mine))  # main merged in
        self.assertEqual([t['id'] for t in load_run(self.root)[1]['tasks']],['2'])
        self.assertEqual(run(self.root,self.fake)['status'],'completed')
        choose(self.root,'pr',self.event('pr','pr'))
        body=json.loads(render(self.root).split('```json\n',1)[1].rsplit('\n```',1)[0])
        self.assertEqual([r['commit'] for r in body['records']],[c for c in self.git('rev-list','--reverse','--no-merges','origin/main..HEAD').splitlines() if c!=mine])
        self.assertEqual([r['evidence'].get('covers') for r in body['records']],[None,[mine]])  # reviewed with task 2
        self.assertEqual(len(body['records']),2);self.assertEqual(list(body['grants']),[load_run(self.root)[1]['id']])

    def test_an_oh_commit_the_person_amended_is_reviewed_again_before_it_is_published(self):
        from .publication import render
        self.documents();self.start_delivery();self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        choose(self.root,'stop',self.event('stop','stop'))
        (self.root/'mine.txt').write_text('mine\n',newline='\n');self.git('add','mine.txt');self.git('commit','-q','--amend','--no-edit')
        amended=self.git('rev-parse','HEAD')  # still says OH-Run, but OH didn't make this commit
        self.start_delivery(turn='again');self.assertEqual(run(self.root,self.fake)['status'],'completed')
        choose(self.root,'pr',self.event('pr','pr'))
        body=json.loads(render(self.root).split('```json\n',1)[1].rsplit('\n```',1)[0])
        self.assertEqual([(r['commit'],r['evidence'].get('covers')) for r in body['records']],[(self.git('rev-parse','HEAD'),[amended])])

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
        def typed(session,host='codex',turn='later'):
            event=human_event({'hook_event_name':'UserPromptSubmit','session_id':session,'turn_id':turn,'prompt':'/oh-deliver 0001'},host)
            return host_hook(self.root,host,{'prompt':'/oh-deliver 0001'},verified=event)
        self.assertEqual(typed('elsewhere','claude')['gate']['choices'],['pr','stop'])
        self.assertEqual(load_run(self.root)[1]['host'],'claude')
        with patch('oh.config.version',return_value='new-completion-runtime'):
            # A crash after the atomic transfer but before its result is returned must
            # replay the same command without another transfer or a lost checkpoint.
            with patch('oh.workflow.checkpoint',side_effect=OSError('after transfer')):
                with self.assertRaisesRegex(OSError,'after transfer'):typed('new')
            self.assertEqual(typed('new')['gate']['choices'],['pr','stop'])
            self.assertEqual(load_run(self.root)[1]['harness_version'],'new-completion-runtime')
            self.assertEqual(run(self.root,self.fake)['status'],'completed')
        self.assertEqual(load_run(self.root)[1]['human']['session'],'new')
        self.git('remote','add','origin','https://github.com/example/fixture.git')
        with patch('oh.branches.fetched',return_value='origin/main'):
            _choose(self.root,'pr',self.event('pr','pr')|{'session':'new'})
        self.assertEqual(load_run(self.root)[1]['status'],'pr')
        # The person amends OH's last commit: OH can't offer that head's PR any more, and says so once.
        (self.root/'mine.txt').write_text('mine\n',newline='\n');self.git('add','mine.txt');self.git('commit','-q','--amend','--no-edit')
        with patch('oh.publication.github',return_value=[]),self.assertRaisesRegex(Refused,'later or different work'):typed('new',turn='amended')

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

    def test_a_delivery_merged_with_the_persons_resolution_is_retired_and_keeps_its_progress(self):
        from .delivery import conflict,without_main
        _,path,head=self.stopped_in_conflict('private');conflict(self.root,'keep','0001')
        # The person resolves the conflict on the pull request on GitHub, squash-merges it, and GitHub deletes the
        # branch: only the pull request's head holds the resolution.
        import subprocess
        self.git('switch','-q','--detach',head)
        subprocess.run(['git','-C',str(self.root),'merge','-q','origin/main'],capture_output=True)
        (self.root/'output.txt').write_text('resolved\n',newline='\n');self.git('commit','-qam','Merge main')
        self.git('update-ref','refs/pull/1/head','HEAD');self.git('update-ref','refs/remotes/origin/deliver/0001',head)
        self.git('switch','-q','main');self.git('merge','-q','--squash','refs/pull/1/head');self.git('commit','-qm','Squash (#1)')
        self.git('update-ref','refs/remotes/origin/main','HEAD');self.git('remote','add','origin',str(self.root))
        from .delivery import delivered_base
        with patch('oh.branches.merged_pulls',return_value=['1']):
            delivered_base(self.root,read_json(plans.approvals_file(self.root))['0001'],progressed=True)  # before it is retired, too
            self.start_delivery(turn='next')  # the merged branch is retired and its task stays done
        self.assertEqual(self.git('rev-parse','HEAD'),self.git('rev-parse','origin/main'))
        self.assertEqual([t['id'] for t in load_run(self.root)[1]['tasks']],['2'])
        self.assertFalse(without_main(self.root))

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
        with self.assertRaisesRegex(Refused,"must be main's exactly"):self.start_delivery(turn='stale plan')  # old task 2
        path.write_text(self.git('show','origin/main:'+path.relative_to(self.root).as_posix()).replace('- [ ] **1.**','- [x] **1.**')+'\n',newline='\n')
        self.git('commit','-qa','--amend','--no-edit')
        merge=self.git('rev-parse','HEAD')
        from .publication import commits
        with self.assertRaisesRegex(Refused,'not a clean merge'):commits(self.root,'origin/main')  # unreviewed yet
        self.start_delivery(turn='resolved');self.assertEqual(run(self.root,self.fake)['status'],'completed')
        request=read_json(next(Path(load_run(self.root)[0].path/'attempts').glob('*/covered.diff')).parent/'request.json')
        self.assertEqual(request['covers']['commits'],[merge])
        choose(self.root,'pr',self.event('pr','pr'))
        body=json.loads(render(self.root).split('```json\n',1)[1].rsplit('\n```',1)[0])
        self.assertEqual([r['evidence'].get('covers') for r in body['records']],[None,[merge]])

    def test_a_worktree_delivers_while_main_is_checked_out_elsewhere(self):
        from .registry import register
        self.documents();side=Path(self.temp.name)/'side'
        self.git('worktree','add','-q','-b','side',str(side));register(side)
        host_hook(side,'codex',{'prompt':'/oh-deliver 0001'},verified=self.event('side','/oh-deliver 0001'))
        self.assertEqual(self.git('-C',str(side),'branch','--show-current'),'deliver/0001')

    def test_private_progress_is_reviewed_then_published_after_code_commit(self):
        title=f'Add {self.root}/credential.py.'
        where,path=self.documents('private',body=BODY.replace('Add the credential store.',title));original=path.read_bytes();observed=[]
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

    def test_repository_task_stays_pending_through_check_repairs_and_review(self):
        # docs/usage.md: the candidate can be complete while the visible task stays pending.
        from .verification import verify
        _,path=self.documents(body=BODY.split('- [ ] **2.**')[0]);original=path.read_bytes()
        self.start_delivery();checks=[];reviews=[]
        def worker(*args,**kwargs):
            self.assertEqual(path.read_bytes(),original)
            result=self.fake(*args,**kwargs)
            admission=read_json(args[5]/'request.json')
            if args[4]=='implementation':
                self.assertIn(str(path),admission['read_only_paths'])
                self.assertIn(str(path),args[6]['read_only_paths'])
            else:
                candidate=Path(next(iter(admission['artifact']['files'])))
                self.assertIn('- [x] **1.**',candidate.read_text())
                self.assertIn('status: frozen',candidate.read_text())
                reviews.append(admission)
                if len(reviews)==1:result['structured'].update(verdict='blocking',findings=[
                    {'severity':'blocking','description':'Repair behavior','path':'output.txt','family':'behavior','relation':'original'}])
            return result
        def check(*args,**kwargs):
            self.assertEqual(path.read_bytes(),original);checks.append(True)
            if len(checks)==1:return [{'name':'fixture','returncode':1,'output':'FAIL behavior','duration_ms':0,'reused':False}]
            return verify(*args,**kwargs)
        with patch('oh.worker_checks.verify',side_effect=check):self.assertEqual(run(self.root,worker)['status'],'completed')
        self.assertEqual((len(checks),len(reviews)),(3,2))
        self.assertIn('- [x] **1.**',path.read_text())
        self.assertEqual(self.git('rev-parse','HEAD^{tree}'),reviews[-1]['git_tree'])

    def test_stop_after_delivery_review_keeps_task_pending_until_explicit_continuation(self):
        from .controls import request
        _,path=self.documents();original=path.read_bytes();self.start_delivery()
        def stopped(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            if args[4]=='review':
                from .worker_checks import submit_report
                self.assertTrue(submit_report(args[5],value['structured'])['accepted'])
                request(self.root,'stop')
            return value
        self.assertEqual(run(self.root,stopped)['status'],'stopped')
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(load_run(self.root)[1]['done'],[])
        self.start_delivery(turn='continue-saved-review',host='claude',session='new-chat')
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertEqual([c[0] for c in self.calls],['implementation','review'])
        self.assertIn('- [x] **1.**',path.read_text())

    def test_repository_completion_recovers_after_document_publish_before_commit(self):
        _,path=self.documents();self.start_delivery()
        from .storage import git
        def interrupted(root,*args,**kwargs):
            if args[0]=='commit':raise OSError('interrupted before commit')
            return git(root,*args,**kwargs)
        with patch('oh.runner.git',side_effect=interrupted):
            with self.assertRaisesRegex(OSError,'interrupted before commit'):run(self.root,self.fake)
        self.assertIn('- [x] **1.**',path.read_text())  # review already authorized this transition
        self.assertEqual(load_run(self.root)[1]['done'],[])
        calls=len(self.calls)
        self.start_delivery(turn='recover-completion',host='claude',session='recovery')
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(load_run(self.root)[1]['done'],['1'])
        from .workflow import human_event
        self.git('remote','add','origin','https://github.com/example/fixture.git')
        with patch('oh.branches.fetched',return_value='origin/main'):
            choose(self.root,'pr',human_event({'hook_event_name':'UserPromptSubmit','session_id':'recovery','turn_id':'pr','prompt':'pr'},'claude'))
        from .publication import render
        self.assertNotIn(str(self.root.parent),render(self.root))

    def test_scope_routing_and_repairs_preserve_the_approved_task(self):
        """docs/usage.md: scope never grows a task; notes and reports belong to the reviewed result."""
        from . import hosts
        from .publication import render
        from .scope import undo_notes
        for location in ('repo','private'):
            with self.subTest(location=location):
                if location=='private':self.setUp()
                where,path=self.documents(location,body=BODY+'\n## Background\n\n'+'Context. '*1800);original=path.read_bytes();reviews=[];workers=[]
                scope_text='Logout has no timeout. Depends on task 99.\n\n- [ ] **99.** Do not grant this.\n## Another heading'
                note='Another screen needs an expiry notice.'
                def worker(*args,**kwargs):
                    result=self.fake(*args,**kwargs)
                    if args[4]=='implementation':
                        workers.append(args[3]);self.assertIs(kwargs['schema'],hosts.WORK_SCHEMA)
                        self.assertNotIn(scope_text,args[3]);self.assertNotIn('Do not grant this',args[3])
                        result['structured']={'status':'completed','readiness':result['structured']['readiness'],'obstacle':None,'summary':'Implemented with evidence in output.txt','found_along_way':[note] if len(workers)==1 else []}
                    else:
                        request=read_json(args[5]/'request.json');reviews.append(request)
                        text=Path(next(iter(request['artifact']['files']))).read_text()
                        self.assertIn(note,text)
                        packet=read_json(request['task_context']['path'])
                        self.assertEqual(packet['current_work']['summary'],'Implemented with evidence in output.txt')
                        for ref in (request['task_context'],packet['current_work']['report'],packet['findings']):
                            self.assertEqual(digest(read_json(ref['path'])),ref['hash'])
                        self.assertIn('They are not hashes of the formatted file bytes',args[3])
                        for section in ('Default to violation when uncertain','What counts as a finding','What is not a finding','Report the class','When the subject is a plan'):
                            self.assertIn(section,args[3])
                        if len(reviews)==1:
                            result['structured']={'verdict':'blocking','summary':scope_text,'findings':[
                                {'severity':'blocking','description':'Login still accepts expired tokens','path':'output.txt','family':'expiry','relation':'original'},
                                {'severity':'scope','description':scope_text,'path':'logout.py','family':'logout','relation':'original'}],'evidence':fixtures.EVIDENCE}
                        else:self.assertIn('> - [ ] **99.**',text)
                        self.assertEqual(path.read_bytes(),original)
                    return result
                self.start_delivery();self.assertEqual(run(self.root,worker)['status'],'checkpoint')
                journal,state=load_run(self.root)
                self.assertEqual(len(workers),2);self.assertEqual(len(reviews),2)
                packet=read_json(reviews[-1]['task_context']['path'])
                self.assertEqual(len(read_json(packet['findings']['path'])['families']),2)
                for request in reviews:
                    for filename,expected in request['artifact']['files'].items():self.assertEqual(plans.digest_of(Path(filename)),expected)
                self.assertIn('Login still accepts expired tokens',read_json(journal.path/'attempts'/state['attempts'][-2]['id']/'task-context.json')['remaining_work'])
                self.assertEqual(len(plans.plan(self.root,'0001',where).splitlines()),2)
                self.assertEqual(plans.verify_design(self.root,where)['designs'],1)
                self.assertIn('required by blocker-plus-scope policy',path.read_text())
                self.assertEqual(undo_notes(path.read_text(),state['scope_records'].values()).replace('- [x] **1.**','- [ ] **1.**'),original.decode())
                self.assertEqual(plans.approval(self.root,where,'0001'),'approved')
                self.git('remote','add','origin','https://github.com/example/fixture.git')
                with patch('oh.branches.fetched',return_value='origin/main'):choose(self.root,'pr',self.event('pr','pr'))
                self.assertIn('logout',render(self.root))
                # A new cycle starts after publication and merge. Routed notes are progress, not new task authority.
                from .publication import reconcile
                pr=fixtures.pull_request(load_run(self.root)[1],status='merged')
                with patch('oh.publication.github',return_value=[pr]):reconcile(self.root)
                self.git('switch','-q','main');self.git('merge','-q','deliver/0001')
                self.git('update-ref','refs/remotes/origin/main','HEAD')
                with patch('oh.publication.github',return_value=pr),patch('oh.branches.fetched',return_value='origin/main'):
                    self.start_delivery(turn='again')
                self.assertEqual([t['id'] for t in load_run(self.root)[1]['tasks']],['2'])
                self.assertIn('last pending task across all tracks',load_run(self.root)[1]['tasks'][0]['instructions'])

    def test_scope_choice_recovery_reviews_the_exact_private_candidate(self):
        """docs/usage.md: dismissed scope stays recorded; recovery cannot borrow the earlier review."""
        from .gates import options
        where,path=self.documents('private');original=path.read_bytes();self.start_delivery()
        def scoped(*args,**kwargs):
            result=self.fake(*args,**kwargs)
            if args[4]=='review':result['structured']={'verdict':'scope','summary':'Outside task','findings':[
                {'severity':'scope','description':'A future logout timeout','path':'logout.py','family':'logout','relation':'original'}],'evidence':fixtures.EVIDENCE}
            return result
        self.assertEqual(run(self.root,scoped)['status'],'findings_checkpoint')
        state=load_run(self.root)[1]
        artifact=state['attempts'][-1]['artifact']
        self.assertEqual([choice for choice,_ in options(state)],['route scope','dismiss scope','stop'])
        with self.assertRaises(Refused):choose(self.root,'fix scope',self.event('bad','fix scope'))
        host_hook(self.root,'codex',{'prompt':'dismiss scope'},verified=self.event('dismiss','dismiss scope'))
        def interrupt(*args,**kwargs):raise OSError('before candidate replacement')
        with patch('oh.plans.write',side_effect=interrupt),self.assertRaises(OSError):run(self.root,self.fake)
        self.assertEqual(path.read_bytes(),original)
        with patch('oh.worker_checks.verify') as checks:
            self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        checks.assert_not_called()  # unchanged code keeps its checks; the changed private candidate gets fresh review
        self.assertEqual([c[0] for c in self.calls],['implementation','review','review'])
        for filename,expected in artifact['files'].items():self.assertEqual(plans.digest_of(Path(filename)),expected)
        self.assertIn('## Scope decisions',path.read_text());self.assertIn('Disposition: `dismiss`',path.read_text())
        self.assertEqual(plans.approval(self.root,where,'0001'),'approved')
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertEqual(path.read_text().count('A future logout timeout'),1)

    def test_unmerged_or_edited_private_design_does_not_grant_work(self):
        where,path=self.documents();self.git('switch','-qc','deliver/0001')  # scope added on the branch, not by OH
        path.write_text(path.read_text()+'\nUnmerged scope\n');self.git('add','.');self.git('commit','-qm','unmerged')
        with self.assertRaisesRegex(Refused,"must be main's exactly"):self.start_delivery()

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
        with self.assertRaisesRegex(Refused,'several tracks'):delivery.selection(self.root,'0001')
        before=self.git('branch','--show-current')
        question=self.start_delivery()['waiting']
        self.assertEqual(question['tracks'],['core','ui'])
        self.assertEqual(self.git('branch','--show-current'),before)  # asking does not start or switch a delivery
        self.assertEqual(self.calls,[])
        manifest,_=delivery.selection(self.root,'0001','ui')
        self.assertEqual([t['id'] for t in manifest['tasks']],['3'])
        self.start_delivery('0001 ui')
        self.assertNotIn('difficulty',load_run(self.root)[1]['tasks'][0])
        self.assessment_output.update(difficulty='simple',rationale='The referenced contract is uncertain',uncertainty=['A consequential boundary is not yet understood'])
        run(self.root,self.fake)
        self.assertEqual(load_run(self.root)[1]['tasks'][0]['difficulty'],'complex')
        self.assertEqual(len(self.assessment_calls),1)
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
        self.assertTrue(pending_file(self.root).exists())  # locator for its future reply; no delivery grant
        from .workflow import active_file
        self.assertFalse(active_file(self.root).exists())
        self.assertTrue(receive(self.root,'codex',event|{'prompt':'/oh-deliver 0001'})['pending'])

    def test_unmerged_context_and_unfinished_initiative_dependency_block_delivery(self):
        where,path=self.documents();self.git('switch','-qc','deliver/0001')
        plans.add_initiative(self.root,where,'M1','ledger','Ledger',['auth'])
        n,ledger=plans.write_design(self.root,where,'ledger','Ledger',BODY,'approved');plans.claim(self.root,where,'ledger',n)
        self.git('add','.');self.git('commit','-qm','unmerged context')
        with self.assertRaisesRegex(Refused,"must be main's exactly"):self.start_delivery()
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
        # Non-ASCII text, which Windows would decode with its own codepage unless OH asks for UTF-8.
        (self.root/'output.txt').write_text('changed again on main 📝 Łódź\n',encoding='utf-8',newline='\n');self.git('commit','-qam','Later work 🔍')
        self.git('update-ref','refs/remotes/origin/main','HEAD')  # and main changed those lines again since
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
                    'structured':({'status':'completed','readiness':fixtures.READINESS,'obstacle':None,'summary':'Checked existing code','found_along_way':[]} if args[4]=='implementation'
                                  else {'verdict':'clean','summary':'Checked existing code','findings':[],'evidence':fixtures.EVIDENCE}),'usage_observed':False}
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
        # This fixture deliberately commits CRLF bytes, regardless of the person's global Git policy.
        self.git('config','core.autocrlf','false')
        for location in ('repo','private'):
            with self.subTest(location=location):
                if location=='private':self.setUp()
                where,path=self.documents(location)
                for target in (path,Path(where['roadmap'])):
                    target.write_bytes(target.read_bytes().replace(b'\n',b'\r\n'))
                if location=='private':plans.approve(self.root,where,'0001','human-crlf',False)
                else:
                    self.git('add','.');self.git('commit','-qm','CRLF plans')
                    self.git('update-ref','refs/remotes/origin/main','HEAD')
                    self.assertEqual(len(delivery.selection(self.root,'0001')[0]['tasks']),2)
                    # docs/usage.md: preserve CRLF in the checkout while Git stores the same approved text as LF.
                    self.git('config','core.autocrlf','input')
                    self.git('add','--renormalize','.');self.git('commit','-qm','Normalize plan line endings')
                self.git('update-ref','refs/remotes/origin/main','HEAD')
                self.start_delivery();self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
                self.assertIn(b'- [x] **1.**',path.read_bytes())
                self.assertNotIn(b'\n',path.read_bytes().replace(b'\r\n',b''))
                choose(self.root,'continue',self.event('next','continue'))
                self.assertEqual(run(self.root,self.fake)['status'],'completed')
                self.assertIn(b'status: frozen\r\ndelivered: M1\r\n',path.read_bytes())
                self.assertNotIn(b'\n',path.read_bytes().replace(b'\r\n',b''))
