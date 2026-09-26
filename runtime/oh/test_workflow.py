from .registry import register, profile_path
import json
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


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'project';self.root.mkdir()
        self.env=patch.dict(os.environ,{'OH_DATA_HOME':str(Path(self.temp.name)/'state')});self.env.start();self.addCleanup(self.env.stop)
        self.git('init','-q','-b','main');self.git('config','user.name','OH Test');self.git('config','user.email','test@example.invalid')
        self.project_id=identifier()
        register(self.root,'Fixture',imported={'id':self.project_id})
        atomic_json(profile_path(self.root,'checks.json'),[{'name':'fixture','command':['python3','-c','pass']}])
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
                'structured':{'verdict':'clean','summary':'Checked behavior','findings':[],'evidence':EVIDENCE},'usage_observed':False}

    def test_initial_and_continue_same_batch_snapshot_and_idempotent_restart(self):
        journal,_=start(self.root,{'tasks':self.tasks},self.event())
        result=run(self.root,self.fake)
        self.assertEqual((result['completed'],result['status']),(5,'checkpoint'))
        self.assertEqual(len(self.calls),10)
        atomic_json(profile_path(self.root,'config.local.json'),{'tasks_per_batch':1,'review_rounds':10})
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
        self.assertTrue(all(len(c[2])<14000 for c in self.calls))

    def test_review_budget_survives_failures_and_restart(self):
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        def blocked(*args,**kw):
            value=self.fake(*args,**kw)
            if args[4]=='review':value['structured']={'verdict':'blocking','summary':'Fix it','findings':[{'severity':'blocking','description':'Wrong','path':'output.txt'}],'evidence':EVIDENCE}
            return value
        self.assertEqual(run(self.root,blocked)['status'],'review_checkpoint')
        reviews=sum(c[0]=='review' for c in self.calls);self.assertEqual(reviews,3)
        run(self.root,blocked);self.assertEqual(sum(c[0]=='review' for c in self.calls),3)
        choose(self.root,'grant review',self.event('2','grant review'))
        self.assertEqual(run(self.root,self.fake)['completed'],1)

    def test_failed_review_does_not_repeat_successful_implementation(self):
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        failed=[]
        def review_failure(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            if args[4]=='review' and not failed:
                failed.append(True);value['failed']=True
            return value
        self.assertEqual(run(self.root,review_failure)['completed'],1)
        self.assertEqual([c[0] for c in self.calls],['implementation','review','review'])

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
        atomic_json(profile_path(self.root,'config.local.json'),{'taskz':10})
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

    def test_recover_clean_review_after_commit_without_new_model_calls(self):
        journal,_=start(self.root,{'tasks':self.tasks[:1]},self.event())
        original=Journal.append
        def crash(obj,kind,data):
            if kind=='task.completed':raise RuntimeError('simulated crash after commit')
            return original(obj,kind,data)
        with patch.object(Journal,'append',crash):
            with self.assertRaises(RuntimeError):run(self.root,self.fake)
        self.assertEqual(len(self.calls),2)
        self.assertEqual(run(self.root,self.fake)['completed'],1)
        self.assertEqual(len(self.calls),2)

    def test_duplicate_concurrent_renewals_count_once(self):
        from concurrent.futures import ThreadPoolExecutor
        journal,_=start(self.root,{'tasks':self.tasks[:1]},self.event())
        journal.append('run.status',{'status':'review_checkpoint'})
        event=self.event('2','grant review')
        with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:choose(self.root,'grant review',event),range(2)))
        self.assertEqual(len(load_run(self.root)[1]['review_grants']),1)

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
        (self.root/'.gitattributes').write_text('*.txt text eol=lf\n')
        (self.root/'data.txt').write_bytes(b'line\r\n')
        with self.assertRaises(Refused):candidate_tree(self.root)

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
        atomic_json(profile_path(self.root,'config.local.json'),{'max_escalations':0})
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        def failed_review(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            if args[4]=='review':value['failed']=True
            return value
        checks=[[{'returncode':0,'duration_ms':0,'reused':False}], [{'returncode':1,'duration_ms':0,'reused':False}]]
        with patch('oh.runner.verify',side_effect=checks):result=run(self.root,failed_review)
        self.assertEqual(result['status'],'needs_attention')
        _,state=load_run(self.root)
        self.assertEqual(state['attempts'][0]['outcome'],'verification_failed')
        self.assertEqual(state['attempts'][1]['outcome'],'failed')
        before=len(self.calls);run(self.root,failed_review);self.assertEqual(len(self.calls),before)
        choose(self.root,'retry',self.event('2','retry'))
        self.assertEqual(run(self.root,self.fake)['completed'],1)


    def test_native_pr_evidence_binds_all_commits_and_refuses_tampering(self):
        from .publication import render,validate_event,START,END
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        start(self.root,{'tasks':self.tasks[:2]},self.event());run(self.root,self.fake)
        with self.assertRaises(Refused):render(self.root)
        choose(self.root,'pr',self.event('2','pr'))
        body=render(self.root)
        event={'pull_request':{'head':{'ref':'work','sha':self.git('rev-parse','HEAD')},'body':body}}
        self.assertEqual(validate_event(self.root,event,'origin/main')['commits'],2)
        packet=json.loads(body.split('```json\n')[1].split('\n```')[0]);packet['records'][0]['evidence']['attempts'][0]['duration_ms']=999
        tampered=START+'\n```json\n'+json.dumps(packet)+'\n```\n'+END
        with self.assertRaises(Refused):validate_event(self.root,{'pull_request':event['pull_request']|{'body':tampered}},'origin/main')
        self.git('commit','--allow-empty','-qm','unreviewed extra')
        with self.assertRaises(Refused):render(self.root)
        with self.assertRaises(Refused):validate_event(self.root,event,'origin/main')


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

if __name__=='__main__':unittest.main()
