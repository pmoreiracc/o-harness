import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from .storage import atomic_json,identifier,Refused
from .initial import record,bind,covers,load
from .legacy import execute
from .workflow import human_event

class InitialGrantTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'unrelated';self.root.mkdir()
        env=patch.dict(os.environ,{'OH_DATA_HOME':str(Path(self.tmp.name)/'state')});env.start();self.addCleanup(env.stop)
        self.git('init','-qb','main');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        atomic_json(self.root/'.oh/project.json',{'id':identifier(),'name':'Independent consumer','kind':'product','design_profile':'consumer-v1'})
        (self.root/'.gitignore').write_text('.oh/*.local.json\n.deliver/\n')
        (self.root/'docs/design').mkdir(parents=True)
        (self.root/'docs/design/0900-fixture.md').write_text('---\ntype: design\nstatus: approved\nlast-verified: 2026-09-25\n---\n# Fixture\n## Tasks\n### Code track\n'+''.join(f'- [ ] **{n}.** Implement behavior {n}.\n' for n in range(1,8)))
        self.git('add','.');self.git('commit','-qm','approved');self.git('update-ref','refs/remotes/origin/main','HEAD')
        self.event=human_event({'hook_event_name':'UserPromptSubmit','session_id':'s','prompt_id':'p','prompt':'/deliver 0900'},'claude')
    def git(self,*args):return subprocess.check_output(['git','-C',str(self.root),*args],stderr=subprocess.DEVNULL).decode().strip()
    def test_external_initial_grant_batch_and_recreated_branch(self):
        grant=record(self.root,'0900','',self.event)
        self.assertEqual(grant['tasks'],['1','2','3','4','5'])
        result=execute(self.root,'scripts/start.sh',['0900']);self.assertEqual(result.returncode,0,result.stderr)
        bind(self.root)
        self.assertTrue(covers(self.root,'0900','5'));self.assertFalse(covers(self.root,'0900','6'))
        result=execute(self.root,'scripts/next.sh',['0900']);self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(result.stdout.startswith('1  '))
        atomic_json(self.root/'.oh/config.local.json',{'tasks_per_batch':9})
        self.assertEqual(record(self.root,'0900','',self.event)['tasks'],grant['tasks'])
        self.git('switch','main');self.git('branch','-D','deliver/0900');self.git('switch','-c','deliver/0900')
        with self.assertRaises(Refused):covers(self.root,'0900','1')
    def test_replayed_trigger_on_main_keeps_snapshot(self):
        first=record(self.root,'0900','',self.event)
        atomic_json(self.root/'.oh/config.local.json',{'tasks_per_batch':9})
        second=record(self.root,'0900','',self.event)
        self.assertEqual(first['run'],second['run'])
        self.assertEqual(second['tasks'],first['tasks'])

    def test_two_task_external_design_delivery(self):
        from .design_runner import run
        atomic_json(self.root/'.oh/checks.json',[{'name':'fixture','command':['python3','-c','pass']}])
        atomic_json(self.root/'.oh/config.json',{'tasks_per_batch':2})
        self.git('add','.');self.git('commit','-qm','verification');self.git('update-ref','refs/remotes/origin/main','HEAD')
        record(self.root,'0900','',self.event)
        calls=[];self.design_calls=calls
        original=atomic_json;crashed=[]
        def interrupted(path,value,**kwargs):
            if Path(path).name=='done.json' and not crashed:
                crashed.append(True);raise RuntimeError('Simulated loss after commit')
            return original(path,value,**kwargs)
        with patch('oh.design_runner.atomic_json',interrupted):
            with self.assertRaises(RuntimeError):run(self.root,'0900',call=self.fake)
        result=run(self.root,'0900',call=self.fake)
        self.assertEqual(result['status'],'checkpoint',result)
        self.assertEqual([x['task'] for x in result['completed_now']],['1','2'])
        self.assertEqual(calls,['implementation','review','implementation','review'])

    def fake(self,host,root,profile,prompt,role,directory,context,**kwargs):
        self.design_calls.append(role);Path(directory).mkdir(parents=True,exist_ok=True)
        if role=='implementation':
            (root/('output-'+context['task']+'.txt')).write_text('implemented')
            headings='Requirements covered|Rules checked|Affected surfaces|Claims and proof|Adversarial self-review|Defect-family closure|Prior finding dispositions|Verification|Limits'.split('|')
            ready='\n\n'.join('## '+h+'\n'+('- none — first review' if h=='Prior finding dispositions' else '- Checked fixture behavior.') for h in headings)
            structured={'summary':'Implemented fixture task','readiness':ready};text='Implemented'
        else:
            structured=None
            lenses='task-and-design invariants-and-decisions affected-surfaces-and-negative-space correctness-and-failure-paths security-authorization-and-concurrency tests-claims-docs-and-generated-artifacts prior-findings-and-family-closure'.split()
            text='## Evidence\n\n### Anchors read\n- The fixture design and required verification.\n\n### Scope examined\n'+''.join('- Lens: '+x+' — fixture behavior checked.\n' for x in lenses)+'\n### Adversarial attacks\n- Attack: wrong task authority. Outcome: rejected.\n- Attack: mutated review tree. Outcome: rejected.\n\n### Limits\n- Deterministic fixture; no production integration claimed.\n\nVERDICT: clean — 0 blocking, 0 concerns, 0 scope'
        return {'failed':False,'returncode':0,'text':text,'structured':structured,'duration_ms':1,'usage_observed':False}

    def test_completed_design_can_finalize_from_main(self):
        design=self.root/'docs/design/0900-fixture.md'
        design.write_text(design.read_text().replace('- [ ]','- [x]'))
        (self.root/'docs/roadmap.md').write_text('### M1 — Fixture\n\n| Slug | Initiative | Depends | Design |\n|---|---|---|---|\n| `fixture` | Fixture | — | [0900](./design/0900-fixture.md) |\n')
        atomic_json(self.root/'.oh/checks.json',[{'name':'fixture','command':['python3','-c','pass']}])
        self.git('add','.');self.git('commit','-qm','converged');self.git('update-ref','refs/remotes/origin/main','HEAD')
        grant=record(self.root,'0900','',self.event);self.assertEqual(grant['tasks'],['finalize'])
        self.design_calls=[]
        from .design_runner import run
        result=run(self.root,'0900',call=self.fake)
        self.assertEqual(result['status'],'completed',result)
        self.assertIn('status: frozen',design.read_text())
        self.assertEqual(self.design_calls,['implementation','review'])

    def test_accepted_concern_resumes_without_new_worker_or_review(self):
        import json
        from .design_runner import run
        from .legacy import environment
        from .config import HOME
        atomic_json(self.root/'.oh/checks.json',[{'name':'fixture','command':['python3','-c','pass']}])
        atomic_json(self.root/'.oh/config.json',{'tasks_per_batch':1,'review_rounds':1})
        self.git('add','.');self.git('commit','-qm','checks');self.git('update-ref','refs/remotes/origin/main','HEAD')
        record(self.root,'0900','',self.event);self.design_calls=[]
        def concern(*args,**kwargs):
            result=self.fake(*args,**kwargs)
            if args[4]=='review':result['text']='[CONCERN] Retain this optional improvement.\nAnchor: none — optional improvement\nWhere: output-1.txt\nWhy: Fixture concern.\nResolve: Accept or fix.\n\n'+result['text'].replace('VERDICT: clean — 0 blocking, 0 concerns, 0 scope','VERDICT: findings — 0 blocking, 1 concerns, 0 scope')
            return result
        first=run(self.root,'0900',call=concern);self.assertEqual(first['status'],'findings_checkpoint',first)
        attempt=Path(first['evidence']);tree=json.loads((attempt/'start.json').read_text())['tree']
        chosen=subprocess.run(['/bin/bash','-c','source "$1/core/review-workflow.sh"; review_resolution_record "$2" "$3" accept-concerns fixture-human "$4"','fixture',str(HOME),str(self.root),str(attempt),tree],cwd=self.root,env=environment(self.root),capture_output=True,text=True)
        self.assertEqual(chosen.returncode,0,chosen.stderr)
        result=run(self.root,'0900',call=lambda *a,**k:self.fail('accepted review must not start another model'))
        self.assertEqual(result['status'],'checkpoint',result);self.assertEqual(len(result['completed_now']),1)

    def test_branch_nonce_survives_appends_and_rejects_recreation_with_identical_creation_record(self):
        from .initial import incarnation
        self.git('switch','-c','work');path=self.root/'.git/logs/refs/heads/work'
        first=path.read_text().splitlines()[0]
        original=incarnation(self.root,'work',create=True)
        self.git('commit','--allow-empty','-qm','ordinary commit')
        self.assertEqual(incarnation(self.root,'work'),original)
        self.git('switch','main');self.git('branch','-D','work');self.git('switch','-c','work')
        # Force the exact timestamp/identity bytes that made the Linux failure possible.
        path.write_text(first+'\n')
        with self.assertRaises(Refused):incarnation(self.root,'work')
        self.assertNotEqual(incarnation(self.root,'work',create=True),original)

    def _binding_failure_recovery(self,phase):
        from . import initial
        from .design_runner import run
        atomic_json(self.root/'.oh/checks.json',[{'name':'fixture','command':['python3','-c','pass']}])
        atomic_json(self.root/'.oh/config.json',{'tasks_per_batch':1})
        self.git('add','.');self.git('commit','-qm','checks');self.git('update-ref','refs/remotes/origin/main','HEAD')
        grant=record(self.root,'0900','',self.event);self.design_calls=[]
        original_git=initial.git;original_json=initial.atomic_json
        def unavailable(root,*args):
            if args[:2]==('reflog','write'):raise subprocess.CalledProcessError(1,args)
            return original_git(root,*args)
        def interrupted(path,value,**kwargs):
            if Path(path).name=='branch.json':raise RuntimeError('binding interrupted')
            return original_json(path,value,**kwargs)
        with patch('oh.initial.git',side_effect=unavailable if phase=='marker' else original_git),patch('oh.initial.atomic_json',side_effect=interrupted if phase=='binding' else original_json):
            with self.assertRaises(Refused if phase=='marker' else RuntimeError):run(self.root,'0900',call=self.fake)
        self.assertEqual(self.design_calls,[]);self.assertEqual(self.git('branch','--show-current'),'deliver/0900')
        result=run(self.root,'0900',call=self.fake)
        self.assertEqual(result['status'],'checkpoint',result)
        self.assertEqual(self.design_calls,['implementation','review'])
        self.assertEqual(load(self.root)[1]['hash'],grant['hash'])
        self.assertEqual(load(self.root)[1]['tasks'],['1'])

    def test_missing_marker_recovers_after_git_capability_is_restored(self):
        self._binding_failure_recovery('marker')

    def test_crash_after_marker_recovers_without_replenishing_scope(self):
        self._binding_failure_recovery('binding')
