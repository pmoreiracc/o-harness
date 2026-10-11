from .registry import register, profile_path
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .config import load
from .hosts import LENSES
EVIDENCE={'anchors':['Fixture task'],'attacks':['Fixture gate checked'],'limits':['Synthetic test reviewer'],'lenses':{k:'Fixture checked' for k in LENSES}}
from .storage import Refused, atomic_json, identifier, Journal
from .workflow import human_event, start, choose, load_run, reduce
from .runner import run
from .telemetry import collect, connect, analytics, emit, usage_values
from .verification import tree, verify
# POSIX users run OH's scripts directly, so tests do too; Windows needs the interpreter.
RUN=[sys.executable,'-I'] if os.name=='nt' else []


def configure(root,**values):
    """Saves this project's settings the way oh config does, checked."""
    from .config import edit
    edit(root,'project',lambda layer:layer.update(values))


def write_settings(root,section):
    """Writes this project's section as a hand edit would, unchecked."""
    from .config import project_name,settings_file
    settings_file().parent.mkdir(parents=True,exist_ok=True)
    settings_file().write_text(json.dumps({'projects':{project_name(root):section}}))


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'project';self.root.mkdir()
        self.env=patch.dict(os.environ,{'OH_DATA_HOME':str(Path(self.temp.name)/'state'),
            'CODEX_THREAD_ID':'','CODEX_SESSION_ID':'','OH_CODEX_TURN_ID':''});self.env.start();self.addCleanup(self.env.stop)
        self.git('init','-q','-b','main');self.git('config','user.name','OH Test');self.git('config','user.email','test@example.invalid')
        self.project_id=identifier()
        register(self.root,'Fixture',imported={'id':self.project_id})
        configure(self.root,checks=[{'name':'fixture','command':['python3','-c','pass']}])
        (self.root/'product.txt').write_text('fixture')
        self.git('add','.');self.git('commit','-qm','init');self.git('switch','-qc','work')
        self.tasks=[{'id':str(i),'title':f'Task {i}','instructions':'Implement behavior','needs':[] if i==1 else [str(i-1)]} for i in range(1,7)]
        self.calls=[]

    def git(self,*args):return subprocess.check_output(['git','-C',str(self.root),*args],stderr=subprocess.DEVNULL).decode().strip()

    def event(self,turn='1',prompt='oh start .oh/tasks.json'):
        return human_event({'hook_event_name':'UserPromptSubmit','session_id':'s','turn_id':turn,'prompt':prompt},'codex')

    def fake(self,host,root,profile,prompt,role,directory,context,**kw):
        self.calls.append((role,profile,prompt))
        if role!='review':(Path(root)/'output.txt').write_text(str(len(self.calls)))
        return {'failed':False,'returncode':0,'duration_ms':10,'text':'done',
                'structured':({'status':'completed','summary':'Checked behavior','found_along_way':[]} if role=='implementation'
                              else {'verdict':'clean','summary':'Checked behavior','findings':[],'evidence':EVIDENCE}),'usage_observed':False}

    def test_initial_and_continue_same_batch_snapshot_and_idempotent_restart(self):
        from .workflow import checkpoint
        observed=[]
        def working(*args,**kwargs):
            progress=checkpoint(self.root)['progress']
            self.assertEqual(progress['phase'],args[4])
            self.assertEqual(progress['profile'],args[2])
            if args[4]=='review':
                self.assertEqual(progress['implementation']['summary'],'Checked behavior')
                self.assertIn('attempt',progress['implementation'])
            observed.append((progress['task'],progress['phase']))
            return self.fake(*args,**kwargs)
        def checking(*args,**kwargs):
            self.assertEqual(checkpoint(self.root)['progress']['phase'],'checks')
            return verify(*args,**kwargs)
        journal,_=start(self.root,{'tasks':self.tasks},self.event())
        with patch('oh.runner.verify',side_effect=checking):result=run(self.root,working)
        self.assertEqual((result['completed'],result['status']),(5,'checkpoint'))
        self.assertTrue(result['limits'].startswith('Continue runs 1 of the 1 remaining task, up to 3 review rounds each.'))
        self.assertEqual(len(self.calls),10)
        self.assertEqual(observed,[(str(i),role) for i in range(1,6) for role in ('implementation','review')])
        self.assertNotIn('progress',result)  # a spent batch never claims a specialist is still working
        configure(self.root,tasks_per_batch=1,review_rounds=10)
        run(self.root,self.fake);self.assertEqual(len(self.calls),10)
        choose(self.root,'continue',self.event('2','continue'))
        waiting=[json.loads(p.read_text()) for p in (Path(self.temp.name)/'state/spool').glob('*.json') if json.loads(p.read_text())['kind']=='phase.finished' and json.loads(p.read_text())['payload'].get('phase')=='waiting']
        self.assertEqual(len(waiting),1);self.assertGreaterEqual(waiting[0]['payload']['duration_ms'],0)
        _,state=load_run(self.root)
        self.assertEqual(state['config']['tasks_per_batch'],5)
        self.assertEqual(state['granted'],['6'])
        self.assertEqual(run(self.root,self.fake)['completed'],6)
        # Replaying the same host response cannot create another grant.
        before=len(journal.records());choose(self.root,'continue',self.event('2','continue'))
        self.assertEqual(len(journal.records()),before)
        from .config import HOME
        contract_size=len((HOME/'prompts/invariant-reviewer.md').read_text())
        self.assertTrue(all(len(c[2])<contract_size+14000 for c in self.calls))

    def test_review_budget_survives_failures_and_restart(self):
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        def blocked(*args,**kw):
            from .workflow import checkpoint
            progress=checkpoint(self.root)['progress']
            if args[4]=='implementation' and progress.get('review'):
                self.assertEqual(progress['review']['outcome'],'blocking')
                self.assertEqual(progress['review']['findings'][0]['description'],'Wrong')
                self.assertEqual(progress['review']['finding_count'],1)
            value=self.fake(*args,**kw)
            if args[4]=='review':value['structured']={'verdict':'blocking','summary':'Fix it','findings':[{'severity':'blocking','description':'Wrong','path':'output.txt','family':'wrong-output','relation':'original'}],'evidence':EVIDENCE}
            return value
        result=run(self.root,blocked)
        self.assertEqual(result['status'],'review_checkpoint')
        # docs/usage.md: spent review windows show findings and their complete retained history.
        for detail in ('Round 3 of 3','Reviews used/granted: 3/3','Wrong','repeats an earlier finding','Open findings: blocking'):
            self.assertIn(detail,result['gate']['details'])
        reviews=sum(c[0]=='review' for c in self.calls);self.assertEqual(reviews,3)
        run(self.root,blocked);self.assertEqual(sum(c[0]=='review' for c in self.calls),3)
        choose(self.root,'grant review',self.event('2','grant review'))
        finished=run(self.root,self.fake)
        self.assertEqual(finished['completed'],1)
        self.assertEqual(finished['last_review']['outcome'],'clean')
        self.assertEqual(finished['last_review']['finding_count'],0)
        self.assertEqual(finished['last_review']['round'],4)
        self.assertNotIn('progress',finished)  # a completed task still reports its final review, not a running phase

    def test_failed_review_does_not_repeat_successful_implementation(self):
        # A host keeps its own worktrees inside the checkout: they are never its changes, reviewed or committed.
        self.git('worktree','add','-q','-b','side','.claude/worktrees/side')
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        failed=[]
        def review_failure(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            if args[4]=='review' and not failed:
                failed.append(True);value['failed']=True
            return value
        # The native executor resolves fallback before admission, including a retried review.
        from . import hosts
        catalog={'gpt-6-luna':{'high'},'gpt-6-sol':{'medium','high'},'gpt-6-astra':{'high'}}
        with patch.object(hosts,'invoke',side_effect=review_failure) as native,patch('sys.stderr',new_callable=io.StringIO) as messages, \
                patch('oh.capabilities.codex_models',return_value=catalog):
            completed=run(self.root,native)
        self.assertEqual(completed['completed'],1)
        self.assertEqual(len(completed['model_notices']),2)  # implementation/medium and review/high
        self.assertEqual(messages.getvalue().count('Continuing with'),2)  # review retry never repeats the notice
        journal,state=load_run(self.root)
        self.assertEqual(state['config']['models']['codex']['review']['model'],'gpt-6.1-sol')
        for review in (a for a in state['attempts'] if a['role']=='review'):
            admission=json.loads((journal.path/'attempts'/review['id']/'request.json').read_text())
            self.assertEqual(admission['profile'],{'model':'gpt-6-sol','effort':'high'})
            self.assertEqual(admission['model_fallback']['requested'],state['config']['models']['codex']['review'])
        collect()
        with connect() as db:
            self.assertEqual([r[0] for r in db.execute("SELECT model FROM attempts WHERE role='review'")],['gpt-6-sol','gpt-6-sol'])
        self.assertEqual([c[0] for c in self.calls],['implementation','review','review'])
        self.assertEqual(self.git('show','--name-only','--format=','HEAD'),'output.txt')
        subprocess.run(['git','init','-q',str(self.root/'vendor')],check=True)  # any other repository is a change
        from .storage import changes
        self.assertEqual(changes(self.root),['vendor/'])

    def test_changed_tree_cannot_borrow_review_and_tool_output_cannot_grant(self):
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        def mutation(*args,**kw):
            value=self.fake(*args,**kw)
            if args[4]=='review':(self.root/'surprise').write_text('edit')
            return value
        self.assertEqual(run(self.root,mutation)['status'],'needs_attention')
        _,state=load_run(self.root);self.assertEqual(state['done'],[])
        with self.assertRaises(Refused):human_event({'hook_event_name':'PostToolUse','session_id':'s','turn_id':'x','prompt':'continue'},'codex')

    def test_journal_rejects_missing_or_altered_authority(self):
        journal,_=start(self.root,{'tasks':self.tasks[:1]},self.event())
        path=journal.path/'000002.json';value=json.loads(path.read_text());value['data']['tasks']=['unauthorized']
        path.write_text(json.dumps(value))
        with self.assertRaises(Refused):journal.records()

    def test_config_unknown_fields_fail_closed_and_no_false_zero(self):
        write_settings(self.root,{'taskz':10})
        with self.assertRaises(Refused):load(self.root)
        self.assertEqual(usage_values({}),{'input':None,'cached':None,'output':None,'reasoning':None})
        with self.assertRaises(Refused):usage_values({'input':10,'cached':11})

    def test_verification_cache_invalidates_actual_dependencies(self):
        (self.root/'value').write_text('one')
        checks=[{'name':'read','command':['python3','-c','print("verified")'],'inputs':['value'],'toolchain':[['python3','--version']]}]
        self.assertFalse(verify(self.root,checks,self.project_id)[0]['reused'])
        self.assertTrue(verify(self.root,checks,self.project_id)[0]['reused'])
        (self.root/'value').write_text('two')
        self.assertFalse(verify(self.root,checks,self.project_id)[0]['reused'])

    def test_zero_exit_cancelled_check_blocks_delivery_and_is_reported_failed(self):
        # docs/configuration.md: cancellation is failure even when cleanup exits zero.
        from .cli import main
        from .gates import describe, full_summary
        from .publication import readable
        configure(self.root,max_escalations=0,checks=[
            {'name':'timed check','command':[sys.executable,'-c','pass']},
            {'name':'remaining check','command':[sys.executable,'-c','pass']}])
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        head=self.git('rev-parse','HEAD')
        # The process layer retains both the cleanup exit code and its cancellation reason.
        with patch('oh.processes.capture',return_value=(subprocess.CompletedProcess([],0,'cleanup finished',''),['timeout'])) as capture:
            result=run(self.root,self.fake)
        self.assertEqual(capture.call_count,1)  # No remaining check ran after cancellation.
        self.assertEqual(result['status'],'needs_attention')
        self.assertEqual([c[0] for c in self.calls],['implementation'])
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertTrue((self.root/'output.txt').exists())
        journal,state=load_run(self.root)
        checks=state['verification']['1']['checks']
        self.assertEqual((checks[0]['returncode'],checks[0]['cancellation']),(0,['timeout']))
        self.assertEqual(result['last_failure']['outcome'],'verification_failed')
        self.assertIn('exit 0, timeout',result['last_failure']['summary'])
        self.assertIn('timed check: failed',full_summary(state))
        # Existing publication histories can contain this falsely accepted result.
        historical={'evidence':{'run':state['id'],'task':'1','title':'Task 1',
            'attempts':[{'outcome':'clean','findings':[]}],'resolutions':{}}}
        self.assertIn('timed check (failed)',readable([historical],{state['id']:state}))
        for status in ('completed','checkpoint'):
            legacy=state|{'status':status,'done':['1'],'summaries':[{'task':'1','commit':head}],
                          'tasks':self.tasks[:2] if status=='checkpoint' else self.tasks[:1]}
            self.assertIn('Checks failed',describe(journal,legacy)['summary'])
        with patch('oh.checks.run',return_value=checks),patch('sys.stdout',new_callable=io.StringIO), \
             self.assertRaises(SystemExit) as exited:
            main(['--root',str(self.root),'verify'])
        self.assertEqual(exited.exception.code,1)

    def test_recover_clean_review_after_commit_without_new_model_calls(self):
        # docs/architecture.md: a supported file/folder replacement survives an interrupted commit without paid reruns.
        journal,_=start(self.root,{'tasks':self.tasks[:1]},self.event())
        def replacement(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            if args[4]=='implementation':
                (self.root/'product.txt').unlink();(self.root/'product.txt').mkdir()
                (self.root/'product.txt/child').write_text('refactored')
            return value
        original=Journal.append
        def crash(obj,kind,data):
            if kind=='task.completed':raise RuntimeError('simulated crash after commit')
            return original(obj,kind,data)
        with patch.object(Journal,'append',crash):
            with self.assertRaises(RuntimeError):run(self.root,replacement)
        self.assertEqual(len(self.calls),2)
        self.assertEqual(run(self.root,replacement)['completed'],1)
        self.assertEqual(len(self.calls),2)

    def test_duplicate_concurrent_renewals_count_once(self):
        from concurrent.futures import ThreadPoolExecutor
        journal,_=start(self.root,{'tasks':self.tasks[:1]},self.event())
        journal.append('run.status',{'status':'review_checkpoint'})
        event=self.event('2','grant review')
        with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:choose(self.root,'grant review',event),range(2)))
        self.assertEqual(len(load_run(self.root)[1]['review_grants']),1)
        # The reference's third option is a stop/handoff, never review or publication authority.
        journal.append('run.status',{'status':'review_checkpoint'})
        choose(self.root,'handoff pr',self.event('handoff','handoff pr'))
        state=load_run(self.root)[1]
        self.assertEqual(state['status'],'stopped');self.assertEqual(state['done'],[])
        self.assertEqual(len(state['review_grants']),1);self.assertNotIn('publication',state)
        self.assertEqual(state['review_handoff']['choice'],'handoff pr')
        with self.assertRaises(Refused):choose(self.root,'pr',self.event('publish','pr'))

    def test_stop_during_review_prevents_commit(self):
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        before=self.git('rev-parse','HEAD')
        def stopping(*args,**kw):
            value=self.fake(*args,**kw)
            if args[4]=='review':choose(self.root,'stop',self.event('2','stop'))
            return value
        self.assertEqual(run(self.root,stopping)['status'],'stopped')
        self.assertEqual(self.git('rev-parse','HEAD'),before)

    def test_dot_dependency_tracks_all_files_and_unknown_path_refused(self):
        check={'name':'all','command':['python3','-c','pass'],'inputs':['.'],'toolchain':[['python3','--version']]}
        self.assertFalse(verify(self.root,[check],self.project_id)[0]['reused'])
        self.assertTrue(verify(self.root,[check],self.project_id)[0]['reused'])
        (self.root/'changed').write_text('x')
        self.assertFalse(verify(self.root,[check],self.project_id)[0]['reused'])
        with self.assertRaises(Refused):verify(self.root,[check|{'inputs':['missing']}],self.project_id)

    def test_clean_filter_transformation_rejected_before_review(self):
        from .verification import candidate_tree
        (self.root/'.gitattributes').write_text('*.txt text eol=lf\n*.dat filter=upper\n')  # windows-ok: Git reads either line ending
        (self.root/'data.txt').write_bytes(b'line\r\n')
        candidate_tree(self.root)  # line endings alone: the reviewed text is the committed text
        self.git('config','filter.upper.clean','tr a-z A-Z')
        (self.root/'data.dat').write_bytes(b'lower\n')
        with self.assertRaisesRegex(Refused,'beyond line endings'):candidate_tree(self.root)

    def test_fabricated_native_user_choice_is_only_pending(self):
        from .authority import stage,materialize
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        payload={'hook_event_name':'UserPromptSubmit','session_id':'invented','turn_id':'invented','prompt':'stop'}
        stage(self.root,'codex',payload)
        with self.assertRaises(Refused):materialize(self.root)
        self.assertEqual(load_run(self.root)[1]['status'],'running')

    def test_collection_is_idempotent_and_subsets_are_not_added_twice(self):
        run_id=identifier();attempt=identifier()
        emit('run.started',self.project_id,run_id,name='Fixture',work_kind='product',host='codex',version='v1',config_hash='c')
        emit('task.started',self.project_id,run_id,'1',title='Task',difficulty='standard',rubric=1)
        emit('attempt.started',self.project_id,run_id,'1',attempt,role='implementation',phase='implementation',host='codex',model='model',effort='medium')
        u={'response_id':'response','input':100,'cached':80,'output':20,'reasoning':10,'source':'test'}
        emit('usage',self.project_id,run_id,'1',attempt,**u);emit('usage',self.project_id,run_id,'1',attempt,**u)
        emit('task.finished',self.project_id,run_id,'1',status='completed',wall_ms=100)
        collect();self.assertEqual(collect(),0)
        with connect() as db:
            summary=analytics(db,{'from':'2000','to':'2100'})['summary']
        self.assertEqual(summary['input'],100);self.assertEqual(summary['tokens_per_completed'],120)
        self.assertEqual(summary['cached'],80);self.assertEqual(summary['reasoning'],10)


    def test_worker_commit_is_not_accepted_as_task_parent(self):
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        def committing(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            self.git('add','.');self.git('commit','-qm','unauthorized worker commit')
            return value
        with self.assertRaises(Refused):run(self.root,committing)
        _,state=load_run(self.root)
        self.assertEqual(state['status'],'needs_attention');self.assertEqual(state['done'],[])
        choose(self.root,'retry',self.event('2','retry'))
        with self.assertRaises(Refused):run(self.root,self.fake)

    def test_failed_review_then_verification_failure_consumes_worker_allowance(self):
        configure(self.root,max_escalations=0)
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        def failed_review(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            if args[4]=='review':value['failed']=True
            return value
        checks=[[{'name':'tests','returncode':0,'duration_ms':0,'reused':False}],
                [{'name':'tests','returncode':1,'duration_ms':0,'reused':False,
                  'output':'\x1b[31mExpected refund_links.SELECT\x1b[0m\nFix the privilege expectation.'}]]
        with patch('oh.runner.verify',side_effect=checks):result=run(self.root,failed_review)
        self.assertEqual(result['status'],'needs_attention')
        _,state=load_run(self.root)
        self.assertEqual(state['attempts'][0]['outcome'],'verification_failed')
        self.assertEqual(state['attempts'][1]['outcome'],'failed')
        self.assertEqual(result['last_failure']['outcome'],'verification_failed')
        self.assertEqual(result['last_failure']['summary'],
                         'tests failed (exit 1).\nExpected refund_links.SELECT\nFix the privilege expectation.')
        before=len(self.calls);run(self.root,failed_review);self.assertEqual(len(self.calls),before)
        choose(self.root,'retry',self.event('2','retry'))
        def repaired(*args,**kwargs):
            if args[4]=='implementation':self.assertIn('Expected refund_links.SELECT',args[3])
            return self.fake(*args,**kwargs)
        self.assertEqual(run(self.root,repaired)['completed'],1)

    def test_failed_worker_cause_reaches_status_and_retry(self):
        from .workflow import checkpoint
        journal,_=start(self.root,{'tasks':self.tasks[:1]},self.event())
        def recovering(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            if len(self.calls)==1:
                return value|{'failed':True,'returncode':-15,'cancellation':['timeout'],
                              'structured':None,'text':'Still implementing.'}
            if args[4]=='implementation':
                failure=checkpoint(self.root)['last_failure']
                self.assertEqual(failure['returncode'],-15)
                self.assertEqual(failure['cancellation'],['timeout'])
                self.assertIn('execution timeout',failure['summary'])
                self.assertIn('execution timeout',args[3])
            return value
        result=run(self.root,recovering)
        self.assertEqual(result['completed'],1)
        self.assertNotIn('last_failure',result)
        self.assertEqual(sum(r['kind']=='grant' for r in journal.records()),1)


    def test_native_pr_evidence_binds_all_commits_and_refuses_tampering(self):
        from .publication import render,validate_event,public_value,START,END
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        def report(*args,**kwargs):
            result=self.fake(*args,**kwargs)
            if args[4]=='implementation':result['structured']={'status':'completed','found_along_way':['Follow-up outside this quick fix --> <tag> & '+str(self.root/'other.py')+' '+('x'*4100)],
                'summary':f'Implemented the timeout. See [output.txt]({self.root}/output.txt).'}
            result['text']=json.dumps(result['structured'])  # actual Codex structured output, not the fixture's plain 'done'
            return result
        def checkout_redaction(root,state,value):
            # Model a checkout outside home/temp: those incidental prefixes must not
            # mask a missing checkout root in the real completion -> sealing path.
            with patch('pathlib.Path.home',return_value=self.root.parent/'other-home'), \
                    patch('tempfile.gettempdir',return_value=str(self.root.parent/'other-temp')):
                return public_value(root,state,value)
        with patch('oh.publication.public_value',side_effect=checkout_redaction):
            start(self.root,{'tasks':self.tasks[:2]},self.event());run(self.root,report)
        with self.assertRaises(Refused):render(self.root)
        choose(self.root,'pr',self.event('2','pr'))
        from .workflow import checkpoint
        publication=checkpoint(self.root)['publication']
        self.assertEqual(publication['head'],self.git('rev-parse','HEAD'))
        self.assertEqual(publication['branch'],'work')
        self.assertEqual(len(publication['commits']),2)
        self.assertIn('Execution is finished',publication['next'])
        self.assertEqual(checkpoint(self.root)['review_rounds'],2)
        self.assertEqual(checkpoint(self.root)['last_review']['task'],'2')
        self.assertEqual(checkpoint(self.root)['last_review']['finding_count'],0)
        body=render(self.root)
        self.assertIn('Found along the way (task 1)',body)  # docs/usage.md: quick-fix observations reach the PR
        self.assertIn('Follow-up outside this quick fix',body)
        prose=body.split(START)[0]  # docs/usage.md: work and outcomes, not execution logs or machine JSON
        for detail in ('### Task 1:', 'Implemented the timeout.', 'Verification: fixture (passed).', 'Independent invariant review: clean; 1 round.'):
            self.assertIn(detail,prose)
        for detail in ('Run history:', 'Task history:', 'Reviews used/granted:', '```json', '\"verdict\":'):
            self.assertNotIn(detail,prose)
        block=body.split(START)[1].split(END)[0].strip()
        self.assertTrue(block.startswith('<!--\n```json\n') and block.endswith('\n```\n-->'))
        self.assertNotIn('-->',block[:-3])  # reported text cannot close the hidden evidence comment
        self.assertNotIn(str(self.root),body)
        self.assertIn('[output.txt](output.txt)',body)
        event={'pull_request':{'head':{'ref':'work','sha':self.git('rev-parse','HEAD')},'body':body}}
        self.assertEqual(validate_event(self.root,event,'origin/main')['commits'],2)
        packet=json.loads(body.split('```json\n')[1].split('\n```')[0])
        published_note=next(iter(packet['records'][0]['evidence']['scope'].values()))['findings'][0]['description']
        self.assertIn('--> <tag> &',published_note)
        self.assertNotIn(str(self.root),published_note)  # decoded Windows paths cannot hide behind JSON escaping
        legacy=START+'\n```json\n'+json.dumps(packet)+'\n```\n'+END
        self.assertEqual(validate_event(self.root,{'pull_request':event['pull_request']|{'body':legacy}},'origin/main')['commits'],2)
        packet['records'][0]['evidence']['attempts'][0]['duration_ms']=999
        altered='```json\n'+json.dumps(packet)+'\n```'
        for retained in (altered,'<!--\n'+altered+'\n-->'):
            tampered=START+'\n'+retained+'\n'+END
            with self.assertRaises(Refused):validate_event(self.root,{'pull_request':event['pull_request']|{'body':tampered}},'origin/main')
        with self.assertRaises(Refused):validate_event(self.root,{'pull_request':event['pull_request']|{'body':prose}},'origin/main')
        self.git('commit','--allow-empty','-qm','unreviewed extra')
        with self.assertRaises(Refused):render(self.root)
        with self.assertRaises(Refused):validate_event(self.root,event,'origin/main')

    def test_a_pr_choice_works_where_the_main_branch_is_master(self):
        from .publication import render
        self.git('branch','-m','main','master');self.git('update-ref','refs/remotes/origin/master','master')
        start(self.root,{'tasks':self.tasks[:1]},self.event());run(self.root,self.fake)
        choose(self.root,'pr',self.event('2','pr'))
        self.assertEqual(load_run(self.root)[1]['status'],'pr')
        packet=json.loads(render(self.root,'origin/master').split('```json\n')[1].split('\n```')[0])
        self.assertEqual(packet['grants'][load_run(self.root)[1]['id']]['choice'],'pr')


    def test_publication_stopped_and_mixed_cli_paths_refuse(self):
        from .publication import render
        from .config import HOME
        self.git('branch','-m','deliver/release')
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        start(self.root,{'tasks':self.tasks[:1]},self.event());run(self.root,self.fake)
        choose(self.root,'stop',self.event('2','stop'))
        with self.assertRaises(Refused):render(self.root)
        self.git('commit','--allow-empty','-qm','unreviewed extra')
        event=Path(self.temp.name)/'pr.json';event.write_text(json.dumps({'pull_request':{'head':{'sha':self.git('rev-parse','HEAD'),'ref':'deliver/release'},'body':''}}))
        for args in [[],['--validate-event',str(event)]]:
            result=subprocess.run([*RUN,str(HOME/'oh'),'--root',str(self.root),'pr-summary',*args],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertNotIn('Review history',result.stdout)

class ReviewResultTest(unittest.TestCase):
    def test_scope_without_a_mutable_design_routes_or_dismisses_but_never_grants_work(self):
        """docs/usage.md: frozen designs and quick fixes retain scope in an issue or a dismissal."""
        from .scope import prepare
        from .gates import options
        from .publication import validate_evidence,readable,public_value
        self.assertEqual(public_value(r'C:\Users\Fixture\repo',{},r'See c:\users\fixture\repo\smoke.py'),'See smoke.py')
        finding={'severity':'scope','description':'Unrelated logout','path':'logout.py','family':'logout','relation':'original'}
        attempt={'id':'review','task':'1','role':'review','finished':True,'findings':[finding],'git_tree':'tree','head':'parent','outcome':'needs_resolution'}
        state={'id':'run','project':'project','status':'findings_checkpoint','attempts':[attempt]}
        for delivery in ({},{'status':'frozen'}):
            with patch('oh.delivery.guard'),patch('oh.issues.route',return_value={'url':'https://github.com/example/repo/issues/1'}) as issue:
                value=prepare(None,None,state|{'delivery':delivery},attempt,'route','human choice')
                self.assertEqual(value['destination'],{'issue':issue.return_value});issue.assert_called_once()
                dismissed=prepare(None,None,state|{'delivery':delivery},attempt,'dismiss','human choice')
                self.assertEqual(dismissed['destination'],{'pr':True});self.assertNotIn('render',dismissed)
        evidence={'schema':1,'attempts':[attempt],'review':'review','parent':'parent','git_tree':'tree','resolutions':{
            'review':{'choice':'dismiss scope','tree':'tree','source':'human','scope':dismissed}}}
        validate_evidence(evidence)
        from .workflow import review_progress
        final_review=review_progress(state,'1')
        self.assertEqual(final_review['outcome'],'needs_resolution')
        self.assertEqual(final_review['finding_count'],1)  # accepted findings must never become a clean/no-findings claim
        # The readable PR retains actual finding decisions and destinations, without raw dictionaries.
        for choice,scope in (('dismiss scope',dismissed),('route scope',value)):
            published=evidence|{'run':'run','task':'1','title':'Logout scope','scope':{'review':scope},
                'resolutions':{'review':{'choice':choice,'tree':'tree','source':'human','scope':scope,
                                       'issue':scope['destination'].get('issue')}}}
            validate_evidence(published)
            self.assertEqual(review_progress(state|{'resolutions':published['resolutions']},'1')['decision'],choice)
            prose=readable([{'commit':'commit','evidence':published}],{'run':state})
            self.assertIn('Unrelated logout',prose);self.assertIn('Decision: '+choice,prose)
            self.assertIn('this PR' if choice=='dismiss scope' else 'https://github.com/example/repo/issues/1',prose)
            self.assertNotIn("{'url':",prose)
        dismissed['findings']=[]
        with self.assertRaises(Refused):validate_evidence(evidence)
        attempt['findings'].append(finding|{'severity':'concern'})
        choices=[c for c,_ in options(state)]
        self.assertEqual(choices,['fix concerns and route scope','fix concerns and dismiss scope',
                                  'accept concerns and route scope','accept concerns and dismiss scope'])
        self.assertNotIn('fix scope',choices)
        from .cli import host_hook
        from .entry import CHOICES
        for choice in CHOICES:
            with patch('oh.cli.choose') as choose,patch('oh.cli.active_file') as active,patch('oh.cli.checkpoint',return_value={'waiting':True}):
                active.return_value.exists.return_value=True
                self.assertEqual(host_hook(Path('/unused'),'codex',{'prompt':choice},verified={'prompt':choice}),{'waiting':True})
                choose.assert_called_once_with(Path('/unused'),choice,{'prompt':choice})

    def test_malformed_host_results_cannot_become_review_evidence(self):
        from copy import deepcopy
        from .hosts import review_result
        finding={'severity':'concern','description':'A claim exceeds its evidence','path':'docs/usage.md',
                 'family':'claims','relation':'original'}
        result={'failed':False,'structured':{'verdict':'concern','summary':'Reviewed','findings':[finding],'evidence':EVIDENCE}}
        self.assertEqual(review_result(result),('needs_resolution',[finding]))
        mutations=[('family',None),('relation','unknown'),('relation',None),('extra','field'),('path',42)]
        for key,value in mutations:
            broken=deepcopy(result)
            if value is None:del broken['structured']['findings'][0][key]
            else:broken['structured']['findings'][0][key]=value
            with self.subTest(key=key,value=value):self.assertEqual(review_result(broken),('failed',[]))
        broken=deepcopy(result);broken['structured']['verdict']='accepted'
        self.assertEqual(review_result(broken),('failed',[]))
        # A declared clean result never erases a visible, valid blocker.
        result['structured']['verdict']='clean';finding['severity']='blocking'
        self.assertEqual(review_result(result),('blocking',[finding]))


class WorkerCompletionTest(unittest.TestCase):
    setUp=WorkflowTest.setUp
    git=WorkflowTest.git
    event=WorkflowTest.event

    def test_blocked_or_missing_worker_completion_never_spends_a_review(self):
        """docs/usage.md: blocked work preserves edits, evidence and review allowance."""
        from .storage import read_json
        from .hosts import work_result
        configure(self.root,max_escalations=0)
        _,initial=start(self.root,{"tasks":self.tasks[:1]},self.event())
        reason="Required input is inaccessible; restore its read access before retrying."
        report={"failed":False,"returncode":0,"duration_ms":1,"text":"host succeeded",
            "structured":{"status":"blocked","summary":reason,"found_along_way":[]},"usage_observed":False}
        def blocked(*args,**kwargs):
            self.assertEqual(args[4],"implementation")
            (self.root/"partial.txt").write_text("keep this work")
            return report
        with patch("oh.runner.verify") as checks:
            result=run(self.root,blocked)
            checks.assert_not_called()
            self.assertEqual(result["status"],"needs_attention")
            self.assertIn(reason,result["gate"]["details"])
            journal,state=load_run(self.root)
            self.assertEqual(state["granted"],initial["granted"]);self.assertEqual(state["done"],[])
            self.assertEqual([a["outcome"] for a in state["attempts"]],["blocked"])
            self.assertEqual(state["config"],initial["config"])
            self.assertEqual((self.root/"partial.txt").read_text(),"keep this work")
            self.assertEqual(read_json(Path(state["attempts"][0]["evidence"])/"result.json")["structured"],report["structured"])
            before=len(journal.records());run(self.root,blocked)
            self.assertEqual(len(journal.records()),before)
        choose(self.root,"retry",self.event("2","retry"))
        _,state=load_run(self.root)
        self.assertEqual(state["recovery_grants"][0]["spent_before"],1)
        self.assertFalse(any(a["role"]=="review" for a in state["attempts"]))
        self.assertEqual(work_result(report),("blocked",reason))
        completed=report|{"structured":report["structured"]|{"status":"completed"}}
        self.assertEqual(work_result(completed),("implemented",reason))  # no tree-change requirement
        for key,value in (("status",None),("status","unknown"),("summary",""),("summary"," \n"),("found_along_way",[42])):
            broken=report["structured"]|{key:value}
            self.assertEqual(work_result(report|{"structured":broken})[0],"failed")

    def test_post_worker_fingerprint_failure_retains_result_and_spent_attempt(self):
        """docs/architecture.md: unknown post-worker state preserves raw evidence without a new allowance."""
        from .runner import attempt
        from .storage import read_json
        from .workflow import review_limit
        journal,initial=start(self.root,{'tasks':self.tasks[:1]},self.event())
        report={'failed':False,'returncode':0,'duration_ms':1,'text':'usable worker result',
                'structured':{'status':'completed','summary':'Kept work','found_along_way':['retained finding']},'usage_observed':False}
        calls=[]
        def worker(*args,**kwargs):
            calls.append(args[4]);(self.root/'output').write_text('keep this')
            return report
        before=tree(self.root)
        with patch('oh.runner.tree',side_effect=[before,Refused('fingerprint unavailable')]):
            with self.assertRaisesRegex(Refused,'repair the checkout and resume'):
                attempt(self.root,journal,initial,self.tasks[0],'implementation',initial['config']['models']['codex']['simple'],invoke=worker)
        _,state=load_run(self.root);saved=read_json(Path(state['attempts'][0]['evidence'])/'result.json')
        for key,value in report.items():self.assertEqual(saved[key],value)
        self.assertIsNone(saved['tree']);self.assertIn('fingerprint unavailable',saved['fingerprint_error'])
        self.assertEqual(state['status'],'needs_attention');self.assertEqual(state['granted'],initial['granted'])
        self.assertEqual(state['done'],[]);self.assertEqual(len(state['attempts']),1)
        self.assertTrue(state['attempts'][0]['finished']);self.assertEqual(state['attempts'][0]['outcome'],'failed')
        self.assertIsNone(state['attempts'][0]['tree']);self.assertEqual(review_limit(state,'1'),review_limit(initial,'1'))
        previous=len(journal.records());run(self.root,worker)
        self.assertEqual(calls,['implementation']);self.assertEqual(len(journal.records()),previous)
        choose(self.root,'retry',self.event('retry','retry'))
        _,state=load_run(self.root);self.assertEqual(state['recovery_grants'][0]['spent_before'],1)
        self.assertEqual((self.root/'output').read_text(),'keep this')
        # The same failure during review retains every returned finding and spends that review round.
        finding={'severity':'blocking','description':'Retained defect','path':'output','family':'kept-defect','relation':'original'}
        report=report|{'structured':{'verdict':'blocking','summary':'Fix retained defect','findings':[finding],'evidence':EVIDENCE}}
        with patch('oh.runner.tree',side_effect=[tree(self.root),Refused('review fingerprint unavailable')]):
            with self.assertRaises(Refused):
                attempt(self.root,journal,state,self.tasks[0],'review',state['config']['models']['codex']['review'],invoke=worker)
        _,state=load_run(self.root);review=state['attempts'][-1]
        self.assertEqual(review['findings'],[finding]);self.assertIsNone(review['tree']);self.assertTrue(review['finished'])
        saved=read_json(Path(review['evidence'])/'result.json')
        self.assertEqual(saved['structured'],report['structured']);self.assertEqual(saved['findings'],[finding])
        self.assertEqual(len([a for a in state['attempts'] if a['role']=='review']),1)
        self.assertEqual(review_limit(state,'1'),review_limit(initial,'1'));self.assertEqual(state['status'],'needs_attention')

    def test_host_schemas_avoid_string_length_keywords(self):
        """Codex strict structured output rejects string length rules; work_result enforces a non-blank summary."""
        from . import hosts
        def keys(value):
            if isinstance(value,dict):return set(value)|{k for v in value.values() for k in keys(v)}
            if isinstance(value,list):return {k for v in value for k in keys(v)}
            return set()
        for schema in (hosts.WORK_SCHEMA,hosts.REVIEW_SCHEMA,hosts.DESIGN_SCHEMA,hosts.PROPOSAL_SCHEMA):
            self.assertFalse(keys(schema)&{"minLength","maxLength"})


if __name__=='__main__':unittest.main()
