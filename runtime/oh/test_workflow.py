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
READINESS={'rules':['Fixture contract'], 'surfaces':['output.txt and its caller'], 'proof':['Fixture behavior check'],
 'family_closure':[], 'prior_findings':[], 'verification':['Fixture verify passed'], 'requirements':['Fixture requirement -> output.txt -> behavior check'], 'self_review':['Invalid input -> fixture check -> rejected'], 'repairs':['Fixture failure -> required behavior -> implementation correction -> checked'], 'limits':['Synthetic model fixture']}
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


def task_context(prompt):
    from .storage import read_json
    content=json.JSONDecoder().raw_decode(prompt[prompt.index('\n{"task":')+1:])[0]
    return read_json(content['task_context']['path'])


def pull_request(state, *, head=None, number=144, status='open'):
    """GitHub's public PR facts; no model claim of publication is used by the fixture."""
    from .publication import repository
    grant=state['publication'];host,repo=repository(grant)
    return {'id':1000+number,'number':number,'html_url':f'https://{host}/{repo}/pull/{number}',
            'state':'closed' if status=='merged' else status,'merged_at':'2026-10-13T00:00:00Z' if status=='merged' else None,
            'base':{'ref':grant['base_branch'],'repo':{'full_name':repo}},
            'head':{'ref':grant['branch'],'sha':head or grant['head'],'repo':{'full_name':repo}}}


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
        # Production runs use a frozen runtime. Capture its unchanged source version once per fixture;
        # explicit upgrade tests still override this patch, and consumer tree checks remain real.
        from .config import version
        runtime_version=patch('oh.config.version',return_value=version());runtime_version.start();self.addCleanup(runtime_version.stop)
        # Synthetic implementers perform the same last tool call as a real worker, after
        # the test's edits and before returning. Tests of missing/stale evidence disable it.
        from . import runner,hosts
        actual_attempt=runner.attempt
        self.auto_worker_checks=True
        self.auto_reports=True
        self.assessment_calls=[]
        self.assessment_output={'difficulty':'standard','rationale':'A contained fixture change','references':['product.txt'],'uncertainty':[]}
        self.auto_assessment=True
        def attempting(root,journal,state,task,role,profile,feedback='',invoke=hosts.invoke,**options):
            if root!=self.root:return actual_attempt(root,journal,state,task,role,profile,feedback,invoke,**options)
            def working(*args,**kwargs):
                if args[4]=='assessment' and self.auto_assessment:
                    self.assessment_calls.append((args[2],args[3]))
                    return {'failed':False,'returncode':0,'duration_ms':2,'text':'Assessed fixture',
                        'structured':dict(self.assessment_output),'usage_observed':False}
                if args[4]=='review':
                    from .worker_checks import admission
                    admission(args[5])  # all existing repository/private/plan fixtures exercise the real binding check
                result=invoke(*args,**kwargs)
                if (self.auto_worker_checks and args[4]=='implementation' and not result.get('failed')
                        and (result.get('structured') or {}).get('status')=='completed'
                        and load_run(root)[1]['status']=='running'):
                    from .worker_checks import run as checks
                    checked=checks(args[5])
                    if any(c.get('unavailable') for c in checked['checks']):
                        result['structured'].update(status='blocked',obstacle={'kind':'external_dependency',
                            'evidence':checked['failure'],'next_step':'Restore the registered tool, then continue.'})
                if (self.auto_reports and args[4] in ('implementation','review') and result.get('structured') is not None
                        and load_run(root)[1]['status'] in ('running','pausing')):
                    from .worker_checks import submit_report
                    submit_report(args[5],result['structured'])
                return result
            if invoke is hosts.invoke:
                with patch.object(hosts,'invoke',working):return actual_attempt(root,journal,state,task,role,profile,feedback,working,**options)
            return actual_attempt(root,journal,state,task,role,profile,feedback,working,**options)
        instrument=patch.object(runner,'attempt',side_effect=attempting);instrument.start();self.addCleanup(instrument.stop)

    def git(self,*args):return subprocess.check_output(['git','-C',str(self.root),*args],stderr=subprocess.DEVNULL).decode().strip()

    def event(self,turn='1',prompt='oh start .oh/tasks.json'):
        if prompt=='pr':
            # Publication fixtures need a destination; self-fetch remains local and preserves the task base.
            result=subprocess.run(['git','-C',str(self.root),'remote','get-url','origin'],capture_output=True)
            if result.returncode:self.git('remote','add','origin',str(self.root))
        return human_event({'hook_event_name':'UserPromptSubmit','session_id':'s','turn_id':turn,'prompt':prompt},'codex')

    def fake(self,host,root,profile,prompt,role,directory,context,**kw):
        self.calls.append((role,profile,prompt))
        from .storage import read_json
        # Derive references independently from retained receipts, not the validation helper.
        _,state=load_run(root)
        prior=[{'id':f"{a['id']}#{n}",'disposition':'fixed','proof':'Synthetic fixture repair verified'}
               for a in state['attempts'] if a['task']==context['task'] and a['role']=='review'
               for n,_ in enumerate(a.get('findings',[]),1)]
        if role!='review':(Path(root)/'output.txt').write_text(str(len(self.calls)))
        return {'failed':False,'returncode':0,'duration_ms':10,'text':'done',
                'structured':({'status':'completed','readiness':READINESS|{'prior_findings':prior},'obstacle':None,'summary':'Checked behavior','found_along_way':[]} if role=='implementation'
                              else {'verdict':'clean','summary':'Checked behavior','findings':[],'evidence':EVIDENCE}),'usage_observed':False}

    def test_standalone_review_is_fresh_and_preserves_delivery_and_historical_subject(self):
        from . import review
        from .workflow import checkpoint
        from .storage import read_json
        configure(self.root,tasks_per_batch=1)
        original,_=start(self.root,{'tasks':self.tasks[:2]},self.event())
        run(self.root,self.fake)
        before=original.records()
        selected=review.start(self.root,'changes',self.event('review-1','/oh-review changes'))
        self.assertEqual(selected['purpose'],'standalone')
        self.assertEqual(run(self.root,self.fake)['last_review']['outcome'],'clean')
        _,state=load_run(self.root)
        admitted=read_json(Path(state['attempts'][0]['evidence'])/'request.json')
        self.assertEqual(admitted['purpose'],'standalone')
        self.assertEqual(original.records(),before)
        self.assertEqual(review.workflow_reviews(state,'review'),[])
        first=state['id']
        review.start(self.root,'commit HEAD',self.event('review-2','/oh-review commit HEAD'))
        result=run(self.root,self.fake)
        _,state=load_run(self.root)
        self.assertNotEqual(state['id'],first)
        self.assertEqual(len(state['attempts']),1)
        self.assertEqual(result['last_review']['outcome'],'clean')
        admission=read_json(Path(state['attempts'][0]['evidence'])/'request.json')
        self.assertEqual((Path(admission['artifact']['root'])/'output.txt').read_text(),(self.root/'output.txt').read_text())
        self.assertFalse(read_json(Path(state['attempts'][0]['evidence'])/'finding-index.json')['families'])
        self.assertIn('Standalone review',(Path(state['attempts'][0]['evidence'])/'review.md').read_text())
        review.dismiss_finished(self.root)
        self.assertEqual(checkpoint(self.root)['run'],original.path.name)
        # Stop belongs to this review only; resume reports retained incomplete evidence,
        # and cannot silently buy another standalone attempt.
        review.start(self.root,'changes',self.event('stop-review','/oh-review changes'))
        def stopping(*args,**kwargs):
            response=self.fake(*args,**kwargs)
            from .controls import request
            request(self.root,'stop')
            return response
        self.assertEqual(run(self.root,stopping)['status'],'stopped')
        from .cli import host_hook
        event=self.event('resume-review','/oh-resume')|{'host':'claude','session':'new-host'}
        resumed=host_hook(self.root,'claude',{'prompt':'/oh-resume'},verified=event)
        self.assertEqual(resumed['purpose'],'standalone')
        finished=run(self.root,self.fake)
        self.assertEqual(finished['status'],'completed')
        self.assertNotIn('prepare',finished)
        self.assertEqual(len(load_run(self.root)[1]['attempts']),1)
        self.assertEqual(original.records(),before)

    def test_completed_task_rereview_preserves_completion_and_commits_only_reviewed_corrections(self):
        from . import review
        configure(self.root,tasks_per_batch=1)
        journal,_=start(self.root,{'tasks':self.tasks[:2]},self.event())
        def initial(*args,**kwargs):
            if args[4]=='implementation':(self.root/'original-surface.txt').write_text('Original task surface')
            return self.fake(*args,**kwargs)
        run(self.root,initial)
        original=self.git('rev-parse','HEAD');original_intent=load_run(self.root)[1]['commit_intents']['1']
        append=Journal.append
        def saved_then_interrupted(journal,kind,data):
            result=append(journal,kind,data)
            if kind=='transition' and any(e['kind']=='review.requested' for e in data['events']):
                raise OSError('interrupted after saving the review decision')
            return result
        with patch.object(Journal,'append',saved_then_interrupted),self.assertRaisesRegex(OSError,'saving the review decision'):
            review.again(self.root,'1',self.event('again','/oh-review task 1'))
        recovered=review.again(self.root,'1',self.event('again','/oh-review task 1'))
        self.assertEqual(recovered['status'],'running')
        self.assertTrue(recovered['review_request_applied'])
        self.assertTrue(recovered['continue_execution'])
        self.assertEqual(run(self.root,self.fake)['status'],'checkpoint')
        self.assertEqual(self.git('rev-parse','HEAD'),original)
        self.assertEqual(load_run(self.root)[1]['done'],['1'])
        count=len(load_run(self.root)[1]['attempts'])
        self.assertTrue(review.again(self.root,'1',self.event('again','/oh-review task 1'))['review_request_applied'])
        run(self.root,self.fake)
        self.assertEqual(len(load_run(self.root)[1]['attempts']),count)
        from .publication import readable
        state=load_run(self.root)[1]
        prose=readable([{'commit':original,'evidence':original_intent['publication']}],{state['id']:state},self.root)
        self.assertIn('2 rounds',prose)
        review.again(self.root,'1',self.event('find-defect','/oh-review task 1'))
        first=True
        def defect(*args,**kwargs):
            nonlocal first
            result=self.fake(*args,**kwargs)
            if args[4]=='review':
                self.assertIn('original-surface.txt',(args[5]/'change.diff').read_text())
                self.assertEqual(json.loads((args[5]/'request.json').read_text())['head'],original)
            else:
                result['structured']['summary']='Corrected fixture value.\n\nDetailed verification remains in the original report.'
            if args[4]=='review' and first:
                first=False
                result['structured'].update(verdict='blocking',findings=[{'severity':'blocking','description':'Concrete defect',
                    'path':'output.txt','family':'fixture','relation':'first-round-escape','anchor':'none — a defect',
                    'failure':'The fixture produces the wrong value.','fix':'Write the corrected value.'}])
            return result
        boundary=run(self.root,defect)
        if load_run(self.root)[1]['status']=='review_checkpoint':
            self.assertIn('Task 1:',boundary['gate']['details'])
            choose(self.root,'grant review',self.event('more','grant review'))
            run(self.root,defect)
        _,state=load_run(self.root)
        self.assertEqual(state['status'],'checkpoint')
        self.assertEqual(state['done'],['1'])
        self.assertEqual(state['commit_intents']['1'],original_intent)
        self.assertEqual(self.git('rev-parse','HEAD^'),original)
        self.assertEqual(state['summaries'][-1]['correction_of'],original)
        self.assertEqual(len(state['corrections']),1)
        from .publication import verify_record
        verify_record(self.root,state['summaries'][-1]['commit'],state['commit_intents'][state['summaries'][-1]['commit_key']]['publication'])
        prose=readable([{'commit':done['commit'],'evidence':state['commit_intents'][done.get('commit_key',done['task'])]['publication']} for done in state['summaries']],{state['id']:state},self.root)
        self.assertEqual(prose.count('### Task 1:'),1)
        self.assertIn('4 rounds',prose)
        self.assertIn('allowed 3 more reviews',prose)
        self.assertIn('Correction: Corrected fixture value.',prose)
        self.assertNotIn('Detailed verification remains',prose)
        from .handoff import report
        self.assertIn('Detailed verification remains',report(next(a for a in reversed(state['attempts']) if a['role']=='implementation'))['summary'])

    def test_initial_and_continue_same_batch_snapshot_and_idempotent_restart(self):
        from .workflow import checkpoint
        observed=[];clock=[100.0];budgets=[]
        def working(*args,**kwargs):
            from .hosts import worker_focus
            message='Checking the fixture boundary.' if args[4]=='review' else 'Implementing the fixture boundary.'
            worker_focus(args[0],{'type':'item.completed','item':{'type':'agent_message','text':message}},args[5])
            progress=checkpoint(self.root)['progress']
            self.assertEqual(progress['phase'],args[4])
            self.assertEqual(progress['profile'],args[2])
            self.assertEqual(progress['focus']['message'],message)
            if args[4]=='review':
                self.assertEqual(progress['implementation']['summary'],'Checked behavior')
                self.assertIn('attempt',progress['implementation'])
            observed.append((progress['task'],progress['phase']))
            budgets.append(kwargs['timeout'])
            clock[0]+=4000  # each leg fits; the approved workflow exceeds two hours collectively
            return self.fake(*args,**kwargs)
        def checking(*args,**kwargs):
            self.assertEqual(checkpoint(self.root)['progress']['phase'],'implementation')
            return verify(*args,**kwargs)
        journal,_=start(self.root,{'tasks':self.tasks},self.event())
        import time
        with patch('oh.worker_checks.verify',side_effect=checking),patch('oh.runner.time',wraps=time) as timer:
            timer.monotonic.side_effect=lambda:clock[0]
            for _ in range(20):
                before=len(load_run(self.root)[1]['attempts'])
                result=run(self.root,working,one_phase=True)
                self.assertLessEqual(len(load_run(self.root)[1]['attempts'])-before,1)
                if not result['continue_execution']:break
                self.assertNotIn('last_results',result)
                self.assertLessEqual(len(result['phase_result']['summary']),400)
            else:self.fail('The native phase continuation never reached its batch decision')
        self.assertGreater(clock[0],7200)
        self.assertTrue(all(7000<=budget<=7140 for budget in budgets),budgets)
        self.assertFalse(any(a.get('outcome')=='interrupted' for a in load_run(self.root)[1]['attempts']))
        self.assertIn('Delivered: Checked behavior',result['gate']['summary'])
        self.assertIn('clean, no findings',result['gate']['summary'])
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
        self.assertEqual(len(self.assessment_calls),6)
        _,assessed=load_run(self.root)
        self.assertEqual(len(assessed['assessments']),6)
        self.assertTrue(all(p==assessed['config']['models']['codex']['standard'] for p,_ in self.assessment_calls))
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
        messages=io.StringIO()
        with patch('sys.stderr',messages):result=run(self.root,blocked)
        self.assertEqual(result['status'],'review_checkpoint')
        # docs/usage.md: spent review windows show findings and their complete retained history.
        for detail in ('Round 3 of 3','Reviews used/granted: 3/3','Wrong','repeats an earlier finding','Open findings: blocking'):
            self.assertIn(detail,result['gate']['details'])
        reviews=sum(c[0]=='review' for c in self.calls);self.assertEqual(reviews,3)
        self.assertEqual(self.calls[-1][0],'implementation')  # the third receipt's findings were repaired before renewal
        self.assertEqual(messages.getvalue().count('reviewer agent is now challenging'),3)
        self.assertIn('reviewer has not started',messages.getvalue().splitlines()[-1])
        self.assertEqual(result['next_action']['phase'],'review_checkpoint')
        _,ready=load_run(self.root)
        self.assertEqual(ready['verification']['1']['attempt'],ready['attempts'][-1]['id'])
        run(self.root,blocked);self.assertEqual(sum(c[0]=='review' for c in self.calls),3)
        choose(self.root,'grant review',self.event('2','grant review'))
        finished=run(self.root,self.fake)
        self.assertEqual(finished['completed'],1)
        self.assertEqual(finished['last_review']['outcome'],'clean')
        self.assertEqual(finished['last_review']['finding_count'],0)
        self.assertEqual(finished['last_review']['round'],4)
        self.assertNotIn('progress',finished)  # a completed task still reports its final review, not a running phase

    def test_checks_repair_without_escalation_and_only_repeated_review_families_escalate(self):
        # docs/usage.md: both hosts repair checks without a gate; only two
        # independent receipts of one family escalate. Failure history survives run calls.
        from .workflow import checkpoint
        from .runner import repeated_family
        from .verification import failure_summary
        first={'id':'one','outcome':'blocking','findings':[{'severity':'blocking','family':'binding'}]}
        different={'id':'two','outcome':'blocking','findings':[{'severity':'blocking','family':'different'}]}
        self.assertEqual(repeated_family([first,first]),[])  # replaying one receipt never escalates
        self.assertEqual(repeated_family([first,different]),[])
        self.assertEqual(repeated_family([first,different,first|{'id':'three'}]),['binding'])
        for host in ('codex','claude'):
            with self.subTest(host=host):
                self.auto_worker_checks=False
                self.calls=[]
                reviews=[]
                start(self.root,{'tasks':self.tasks[:1]},self.event(host)|{'host':host})
                def implement(*args,**kwargs):
                    value=self.fake(*args,**kwargs)
                    if args[4]=='implementation':
                        expected='complex' if len(reviews)>=2 else load_run(self.root)[1]['tasks'][0]['difficulty']
                        self.assertEqual(args[2],load_run(self.root)[1]['config']['models'][host][expected])
                        self.assertEqual(checkpoint(self.root)['status'],'running')
                        self.assertNotIn('gate',checkpoint(self.root))
                        from .worker_checks import run as checks
                        while not (checked:=checks(args[5]))['passed']:
                            self.assertIn('AssertionError: expected 1, received 2',checked['failure'])
                            self.assertEqual(load_run(self.root)[1]['attempts'][-1]['id'],args[6]['attempt'])
                    else:
                        family='binding'
                        if len(reviews)<2:
                            finding={'severity':'blocking','description':'Fix '+family,'path':'output.txt','family':family,'relation':'original'}
                            value['structured'].update(verdict='blocking',findings=[finding])
                        reviews.append(family)
                    return value
                failure={'name':'tests','returncode':1,'duration_ms':0,'reused':False,
                         'output':'\n'.join(['PASS other test']*80)+'\nFAIL output.test\nAssertionError: expected 1, received 2'}
                self.assertIn('AssertionError: expected 1, received 2',failure_summary([failure],900))
                # Multiple check failures do not consume a repair limit or escalate.
                outcomes=iter([[failure]]*2)
                def check(*args,**kwargs):
                    return next(outcomes,[{'name':'tests','returncode':0,'duration_ms':0,'reused':False}])
                with patch('oh.worker_checks.verify',side_effect=check):result=run(self.root,implement)
                self.assertEqual(result['completed'],1)
                self.assertEqual(result['review_rounds'],3)
                self.assertEqual([c[0] for c in self.calls],['implementation','review']*3)
                journal,state=load_run(self.root)
                self.assertEqual(sum(r['kind']=='grant' for r in journal.records()),1)
                self.assertNotIn('recovery_grants',state)
                self.assertEqual(len(repeated_family([a for a in state['attempts'] if a['role']=='review'])),1)

    def test_review_requires_implementer_checks_for_the_final_unchanged_tree(self):
        from .worker_checks import run as checks,submit_report
        self.auto_worker_checks=False;self.auto_reports=False
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        directories=[]
        def implement(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            if args[4]=='implementation':
                directories.append(args[5])
                self.assertFalse(submit_report(args[5],value['structured'])['accepted'])
                failed=[{'name':'fixture','returncode':1,'duration_ms':0,'reused':False,'output':'Wrong behavior'}]
                with patch('oh.worker_checks.verify',return_value=failed):self.assertFalse(checks(args[5])['passed'])
                def changed_during_checks(*arguments,**options):
                    results=verify(*arguments,**options)
                    (self.root/'during-check.txt').write_text('a late self-review edit',newline='\n')
                    return results
                with patch('oh.worker_checks.verify',side_effect=changed_during_checks):
                    checked=checks(args[5])
                self.assertTrue(all(c['returncode']==0 for c in checked['checks']))
                self.assertFalse(checked['passed'])
                self.assertFalse(submit_report(args[5],value['structured'])['accepted'])
                self.assertTrue(checks(args[5])['passed'])
                self.assertFalse(submit_report(args[5],value['structured']|{'readiness':READINESS|{'repairs':[]}})['accepted'])
                self.assertTrue(submit_report(args[5],value['structured'])['accepted'])
                (self.root/'after-check.txt').write_text('requires verification',newline='\n')
                self.assertFalse(submit_report(args[5],value['structured'])['accepted'])
                self.assertTrue(checks(args[5])['passed'])
            else:
                state=load_run(self.root)[1]
                self.assertEqual(state['verification']['1']['tree'],tree(self.root))
            self.assertTrue(submit_report(args[5],value['structured'])['accepted'])
            return value|{'structured':None}
        self.assertEqual(run(self.root,implement)['completed'],1)
        self.assertEqual([c[0] for c in self.calls],['implementation','review'])
        with self.assertRaises(Refused):checks(directories[-1])
        journal,state=load_run(self.root)
        self.assertEqual(sum(r['kind']=='verification' for r in journal.records()),4)
        self.assertEqual(sum(a['role']=='review' for a in state['attempts']),1)

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
                patch('oh.capabilities.codex_models',return_value=catalog), patch('oh.worker_checks.verify',wraps=verify) as checked:
            completed=run(self.root,native)
        self.assertEqual(checked.call_count,1)  # a failed reviewer cannot trigger another test execution
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
        from .review import again
        head=self.git('rev-parse','HEAD');failed.clear()
        again(self.root,'1',self.event('extra-failure','/oh-review task 1'))
        with patch('oh.worker_checks.verify',wraps=verify) as extra_checks:
            self.assertEqual(run(self.root,review_failure)['status'],'review_checkpoint')
            choose(self.root,'grant review',self.event('extra-window','grant review'))
            self.assertEqual(run(self.root,review_failure)['status'],'completed')
            extra_checks.assert_not_called()
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertEqual(sum(c[0]=='implementation' for c in self.calls),1)
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
        configure(self.root,checks=[
            {'name':'timed check','command':[sys.executable,'-c','pass']},
            {'name':'remaining check','command':[sys.executable,'-c','pass']}])
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        head=self.git('rev-parse','HEAD')
        # The process layer retains both the cleanup exit code and its cancellation reason.
        with patch('oh.processes.capture',return_value=(subprocess.CompletedProcess([],0,'cleanup finished',''),['timeout'])) as capture:
            def blocked_check(*args,**kwargs):
                value=self.fake(*args,**kwargs)
                if len(self.calls)>1:value['structured'].update(status='blocked',summary='The check is timing out; restore its required service.',
                    obstacle={'kind':'external_dependency','evidence':'The required service cannot be reached.',
                              'next_step':'Restore that service.'})
                return value
            result=run(self.root,blocked_check)
        self.assertEqual(capture.call_count,1)  # No remaining check ran after cancellation.
        self.assertEqual(result['status'],'needs_attention')
        self.assertEqual([c[0] for c in self.calls],['implementation','implementation'])
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertTrue((self.root/'output.txt').exists())
        journal,state=load_run(self.root)
        checks=state['verification']['1']['checks']
        self.assertEqual((checks[0]['returncode'],checks[0]['cancellation']),(0,['timeout']))
        self.assertEqual(result['last_failure']['outcome'],'blocked')
        self.assertIn('exit 0, timeout',next(a for a in state['attempts'] if a['role']=='implementation')['summary'])
        self.assertNotIn('gate',result)
        self.assertIn('timed check: failed',full_summary(state))
        # Existing publication histories can contain this falsely accepted result.
        historical={'evidence':{'run':state['id'],'task':'1','title':'Task 1',
            'review':'historical-review','attempts':[{'id':'historical-review','outcome':'clean','findings':[]}],'resolutions':{}}}
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
            if args[4]=='review':
                choose(self.root,'stop',self.event('2','stop'))
                return value|{'failed':True,'returncode':-15,'cancellation':['stopped'],'structured':None}
            return value
        self.assertEqual(run(self.root,stopping)['status'],'stopped')
        self.assertEqual(self.git('rev-parse','HEAD'),before)
        old=load_run(self.root)[1]
        from .cli import host_hook
        event=human_event({'hook_event_name':'UserPromptSubmit','session_id':'claude-resume','turn_id':'resume','prompt':'/oh-resume'},'claude')
        resumed=host_hook(self.root,'claude',{'prompt':'/oh-resume'},verified=event)
        self.assertEqual(resumed['status'],'running')
        self.assertEqual(load_run(self.root)[1]['attempts'],old['attempts'])
        self.assertEqual(run(self.root,self.fake)['status'],'completed')
        current=load_run(self.root)[1]
        self.assertEqual([a['host'] for a in current['attempts'] if a['role']=='review'],['codex','claude'])
        self.assertEqual([c[0] for c in self.calls],['implementation','review','review'])
        self.assertEqual(current['granted'],old['granted'])
        self.assertEqual(current.get('review_grants'),old.get('review_grants'))

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
        from .cli import executable_run
        executable_run(self.root,None)
        with self.assertRaises(Refused):run(self.root,self.fake)

    def test_failed_worker_cause_reaches_status_and_automatic_continuation(self):
        from .workflow import checkpoint
        journal,_=start(self.root,{'tasks':self.tasks[:1]},self.event())
        def recovering(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            if args[4]=='implementation':
                self.assertEqual(args[2],load_run(self.root)[1]['config']['models']['codex']['standard'])
            if len(self.calls)<=2:
                return value|{'failed':True,'returncode':-15,'cancellation':['timeout'],
                              'structured':None,'text':'Still implementing.'}
            if args[4]=='implementation':
                self.assertNotIn('last_failure',checkpoint(self.root))  # a live replacement is not the old failure
                from .storage import read_json
                packet=read_json(args[5]/'task-context.json')
                self.assertIn('execution timeout',packet['remaining_work'])
            return value
        result=run(self.root,recovering)
        self.assertEqual(result['status'],'needs_attention');self.assertNotIn('gate',result)
        self.assertIn('execution timeout',result['blocked']['reason'])
        self.assertEqual(result['last_failure']['returncode'],-15)
        self.assertEqual(result['last_failure']['cancellation'],['timeout'])
        from .cli import executable_run
        executable_run(self.root,None)  # after the external obstacle is fixed; no new human grant
        result=run(self.root,recovering)
        self.assertEqual(result['completed'],1)
        self.assertNotIn('last_failure',result)
        self.assertEqual(sum(r['kind']=='grant' for r in journal.records()),1)
        self.assertNotIn('recovery_grants',load_run(self.root)[1])


    def test_native_pr_evidence_binds_all_commits_and_refuses_tampering(self):
        from .publication import render,validate_event,public_value,START,END
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        def report(*args,**kwargs):
            result=self.fake(*args,**kwargs)
            if args[4]=='implementation':result['structured']={'status':'completed','readiness':READINESS,'obstacle':None,'found_along_way':['Follow-up outside this quick fix --> <tag> & '+str(self.root/'other.py')+' '+('x'*4100)],
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
        for detail in ('### Task 1:', 'Implemented the timeout.', 'Task 1: fixture (passed).', 'Task 1: clean; 1 round.'):
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
        # docs/usage.md: the public summary includes original work and repairs,
        # and final runner checks supersede a worker's local sandbox limitation.
        from .publication import readable
        _,state=load_run(self.root)
        repairs=[{'task':'1','role':'implementation','outcome':'verification_failed',
                  'human_summary':'Preserved staged approvals through FX recovery.\n\nLint failed in the new tests.'},
                 {'task':'1','role':'implementation','outcome':'implemented',
                  'human_summary':'Implemented the timeout and preserved staged approvals through FX recovery; verified the refund query.\n\nDatabase tests could not run in the worker sandbox.'}]
        final=next(i for i,a in enumerate(state['attempts']) if a['id']==packet['records'][0]['evidence']['review'])
        # Repair claims precede their final review; later unreviewed author prose is
        # not the summary of a completed commit.
        short=readable(packet['records'][:1],{state['id']:state|{'attempts':state['attempts'][:final]+repairs+state['attempts'][final:]}},self.root)
        self.assertIn(repairs[-1]['human_summary'].split('\n\n')[0],short)
        self.assertIn('Task 1: fixture (passed).',short)
        self.assertNotIn('Database tests could not run',short);self.assertNotIn('Lint failed',short)
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

    def test_publication_recovery_records_verified_pr_without_reopening_work(self):
        from .publication import reconcile,discover,github
        from .workflow import carry_on,checkpoint
        from .cli import main
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        start(self.root,{'tasks':self.tasks[:1]},self.event());run(self.root,self.fake)
        self.git('remote','add','origin','https://github.com/example/product.git')
        with patch('oh.branches.fetched',return_value='origin/main'):choose(self.root,'pr',self.event('publish','pr'))
        journal,before=load_run(self.root);head=before['publication']['head']
        # Publication interrupted before creation can still move to the other host, retaining its grant.
        with patch('oh.publication.github',return_value=[]):
            transferred=carry_on(self.root,{'host':'claude','session':'publisher','turn':'resume','prompt':'/oh-resume'})
        self.assertEqual(transferred['next_action']['kind'],'publish')
        after_transfer=load_run(self.root)[1]
        self.assertEqual(after_transfer['publication'],before['publication'])
        self.assertEqual(after_transfer['host'],'claude')
        before=after_transfer;original=journal.records()
        # Before push or after push but before creation, the same approved publication remains.
        with patch('oh.publication.github',return_value=[]):
            for _ in range(2):self.assertEqual(reconcile(self.root)['publication_status'],'not published')
        self.assertEqual(journal.records(),original)
        # Real transport failures cannot become an empty successful discovery.
        for failure in (FileNotFoundError(),subprocess.TimeoutExpired('gh',30)):
            with patch('subprocess.run',side_effect=failure):
                with self.assertRaises(Refused):github(self.root,'github.com','repos/example/product/pulls',pages=True)
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,'not JSON','')):
            with self.assertRaises(Refused):github(self.root,'github.com','repos/example/product/pulls',pages=True)
        pr=pull_request(before)
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps([[pr],[]]),'')):
            self.assertEqual(discover(self.root,before)['number'],144)  # paginated gh output
        # A reused branch, different base/repository, or another open PR cannot prove publication.
        for other in (pr|{'base':pr['base']|{'ref':'other'}},pr|{'head':pr['head']|{'repo':{'full_name':'other/repo'}}}):
            with patch('oh.publication.github',return_value=other),self.assertRaises(Refused):reconcile(self.root,144)
        unrelated=pull_request(before,head='f'*40)
        with patch('oh.publication.github',side_effect=lambda r,h,e,**kw:[] if '/commits?' in e else [unrelated]):
            with self.assertRaisesRegex(Refused,'competing PR'):reconcile(self.root)
        with patch('oh.publication.github',return_value=[pr,pull_request(before,number=145)]):
            with self.assertRaisesRegex(Refused,'Several PRs'):reconcile(self.root)
        self.assertEqual(journal.records(),original)
        # HEAD changes prove neither publication nor review coverage.
        self.git('commit','--allow-empty','-qm','Human change after publication')
        later=self.git('rev-parse','HEAD');pr=pull_request(before,head=later)
        with patch('oh.publication.github',return_value=[]),self.assertRaisesRegex(Refused,'later or different work'):reconcile(self.root)
        def response(root,host,endpoint,**kw):
            if '/commits?' in endpoint:return [{'sha':head},{'sha':later}]
            return [pr] if kw.get('pages') else pr
        # A lost response after saving the receipt is recovered without replacing it or transferring control.
        with patch('oh.publication.github',side_effect=response):
            with patch('oh.workflow.checkpoint',side_effect=OSError('lost result')):
                with self.assertRaisesRegex(OSError,'lost result'):reconcile(self.root)
            for host in ('claude','codex'):
                result=carry_on(self.root,{'host':host,'session':'fresh','turn':'resume','prompt':'/oh-resume'})
                self.assertEqual(result['next_action']['kind'],'published');self.assertNotIn('gate',result)
                self.assertEqual(result['published']['approved_head'],head)
                self.assertEqual(result['published']['observed_head'],later)
            receipt=load_run(self.root)[1]['published']
            for status in ('closed','merged'):
                pr=pull_request(before,head=later,status=status)
                self.assertEqual(reconcile(self.root)['published']['state'],status)
                self.assertEqual(load_run(self.root)[1]['published'],receipt)  # observations do not rewrite history
        after=load_run(self.root)[1]
        for key in ('host','human','done','granted','publication','attempts'):self.assertEqual(after[key],before[key])
        self.assertEqual(journal.records()[:-1],original)
        self.assertEqual(journal.records()[-1]['kind'],'publication.completed')
        record=journal.records()[-1]
        with self.assertRaises(Refused):reduce(original+[record|{'data':record['data']|{'approved_head':'f'*40}}])
        # A saved receipt remains terminal after remote changes, dirty files, or a GitHub outage.
        self.git('remote','set-url','origin','https://github.com/other/product.git')
        (self.root/'mine.txt').write_text('unsaved human edit',newline='\n')
        with patch('oh.publication.github',side_effect=Refused('GitHub is offline')):
            result=reconcile(self.root)
        self.assertEqual(result['publication_status'],'last verified');self.assertNotIn('gate',result)
        self.assertEqual(checkpoint(self.root)['next_action']['kind'],'published')
        # Both host entry commands return the finished result before execution's owner check.
        for command in ('resume','run','deliver'):
            with patch('oh.authority.materialize',return_value=result),patch('oh.runner.run') as execute,patch.dict(os.environ,{'CODEX_THREAD_ID':'new-reader'}),patch('sys.stdout',new=io.StringIO()) as out:
                main(['--root',str(self.root),command]+(['0001'] if command=='deliver' else []))
                self.assertEqual(json.loads(out.getvalue())['next_action']['kind'],'published');execute.assert_not_called()
        from .cli import executable_run
        with self.assertRaisesRegex(Refused,'earlier run'):executable_run(self.root,result|{'run':identifier()})
        with self.assertRaises(Refused):choose(self.root,'pr',self.event('again','pr'))


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
        for delivery,extra in (({},{}),({'status':'frozen'},{}),({'status':'approved'},{'extra_review':{'task':'1'}})):
            with patch('oh.delivery.guard'),patch('oh.issues.route',return_value={'url':'https://github.com/example/repo/issues/1'}) as issue:
                value=prepare(None,None,state|{'delivery':delivery}|extra,attempt,'route','human choice')
                self.assertEqual(value['destination'],{'issue':issue.return_value});issue.assert_called_once()
                dismissed=prepare(None,None,state|{'delivery':delivery}|extra,attempt,'dismiss','human choice')
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
            for text in (choice,choice.capitalize(),choice.upper()):
                with patch('oh.cli.choose') as choose,patch('oh.cli.active_file') as active,patch('oh.cli.checkpoint',return_value={'waiting':True}),patch('oh.workflow.load_run',return_value=(None,{'status':'running'})),patch('oh.workflow.carry_on',return_value={'waiting':True}) as resume:
                    active.return_value.exists.return_value=True
                    self.assertEqual(host_hook(Path('/unused'),'codex',{'prompt':text},verified={'prompt':text}),{'waiting':True})
                    if choice=='resume':
                        resume.assert_called_once_with(Path('/unused'),{'prompt':text});choose.assert_not_called()
                    else:
                        choose.assert_called_once_with(Path('/unused'),choice,{'prompt':text});resume.assert_not_called()

    def test_malformed_host_results_cannot_become_review_evidence(self):
        from copy import deepcopy
        from .hosts import review_details,review_result
        from .runner import repeated_family
        finding={'severity':'concern','description':'A claim exceeds its evidence','path':'docs/usage.md',
                 'family':'claims','relation':'original'}
        result={'failed':False,'structured':{'verdict':'concern','summary':'Reviewed','findings':[finding],'evidence':EVIDENCE}}
        parsed=review_details(result)
        self.assertEqual(parsed['outcome'],'needs_resolution')
        self.assertEqual(parsed['findings'][0]['description'],finding['description'])
        # Presentation and missing classification metadata never erase the concrete finding.
        for key,value in [('family',None),('relation','unknown'),('extra','field'),('path',42)]:
            broken=deepcopy(result)
            if value is None:del broken['structured']['findings'][0][key]
            else:broken['structured']['findings'][0][key]=value
            retained=review_details(broken)
            self.assertEqual(retained['findings'][0]['description'],finding['description'])
        broken=deepcopy(result);broken['structured']['verdict']='clean'
        broken['structured']['findings'][0]['severity']='blocking'
        broken['structured']['evidence']={'anchors':[]}
        parsed=review_details(broken)
        self.assertEqual(parsed['outcome'],'blocking');self.assertTrue(parsed['issues'])
        self.assertEqual(len(parsed['findings']),1)
        # A malformed neighbor retains its source position and cannot produce clean.
        broken['structured']['findings'].insert(0,{'severity':'unknown','description':'Unclassified risk'})
        parsed=review_details(broken)
        self.assertEqual(parsed['positions'],[2]);self.assertEqual(parsed['fragments'][0]['number'],1)
        broken['structured']['findings']=[]
        self.assertEqual(review_result(broken)[0],'review_incomplete')
        broken['structured']['evidence']=EVIDENCE
        self.assertEqual(review_result(broken)[0],'clean')
        no_family=dict(parsed['findings'][0],family='')
        self.assertEqual(repeated_family([{'id':str(i),'outcome':'blocking','findings':[no_family]} for i in (1,2)]),[])
        failed=deepcopy(result);failed['failed']=True
        self.assertEqual(review_result(failed)[0],'failed')
        self.assertEqual(len(review_result(failed)[1]),1)


class WorkerCompletionTest(unittest.TestCase):
    setUp=WorkflowTest.setUp
    git=WorkflowTest.git
    event=WorkflowTest.event

    def test_blocked_or_missing_worker_completion_never_spends_a_review(self):
        """docs/usage.md: blocked work preserves edits, evidence and review allowance."""
        from .storage import read_json
        from .hosts import work_result
        _,initial=start(self.root,{"tasks":self.tasks[:1]},self.event())
        reason="Required input is inaccessible; restore its read access before retrying."
        report={"failed":False,"returncode":0,"duration_ms":1,"text":"host succeeded",
            "structured":{"status":"blocked","readiness":READINESS,"summary":reason,"found_along_way":[],
                "obstacle":{"kind":"external_dependency","evidence":"Read access to the required input is denied.","next_step":"Restore read access to that input."}},"usage_observed":False}
        def blocked(*args,**kwargs):
            self.assertEqual(args[4],"implementation")
            (self.root/"partial.txt").write_text("keep this work")
            return report
        with patch("oh.worker_checks.verify") as checks:
            result=run(self.root,blocked)
            checks.assert_not_called()
            self.assertEqual(result["status"],"needs_attention")
            self.assertNotIn("gate",result)
            self.assertIn(reason,result["blocked"]["reason"])
            self.assertIn('Restore read access to that input.',result['blocked']['reason'])
            journal,state=load_run(self.root)
            self.assertEqual(state["granted"],initial["granted"]);self.assertEqual(state["done"],[])
            self.assertEqual([a["outcome"] for a in state["attempts"] if a['role']=='implementation'],["blocked"])
            self.assertEqual(state["config"],initial["config"])
            self.assertEqual((self.root/"partial.txt").read_text(),"keep this work")
            self.assertEqual(read_json(Path(state["attempts"][-1]["evidence"])/"result.json")["structured"],report["structured"])
            before=len(journal.records());run(self.root,blocked)
            self.assertEqual(len(journal.records()),before)
        with self.assertRaisesRegex(Refused,"No Retry approval is needed"):
            choose(self.root,"retry",self.event("2","retry"))
        from .cli import executable_run
        executable_run(self.root,None)
        _,state=load_run(self.root)
        self.assertNotIn("recovery_grants",state)
        self.assertFalse(any(a["role"]=="review" for a in state["attempts"]))
        self.assertEqual(work_result(report)[0],"blocked")
        completed=report|{"structured":report["structured"]|{"status":"completed","obstacle":None}}
        self.assertEqual(work_result(completed),("implemented",reason))  # no tree-change requirement
        for key,value in (("status",None),("status","unknown"),("summary",""),("summary"," \n"),("found_along_way",[42])):
            broken=report["structured"]|{key:value}
            self.assertEqual(work_result(report|{"structured":broken})[0],"report_invalid")

    def test_unfinished_work_continues_with_edits_and_remaining_steps_on_both_hosts(self):
        """docs/usage.md: incomplete work is continued, never a blocker, escalation or review grant."""
        from .hosts import work_result
        for host in ('codex','claude'):
            with self.subTest(host=host):
                configure(self.root,tasks_per_batch=1)
                event=self.event(host,'deliver fixture');event['host']=host
                _,initial=start(self.root,{'tasks':self.tasks[:1]},event)
                self.calls=[]
                remaining='Selection rows are implemented; finish preview/save binding and its tests.'
                def continuing(*args,**kwargs):
                    if args[4]=='implementation' and not self.calls:
                        self.calls.append((args[4],args[2],args[3]))
                        (self.root/'partial.txt').write_text('selection rows')
                        return {'failed':False,'returncode':0,'duration_ms':1,'text':remaining,
                          'structured':{'status':'unfinished','readiness':None,'summary':remaining,'found_along_way':[],'obstacle':None},
                          'usage_observed':False}
                    if args[4]=='implementation':
                        self.assertEqual((self.root/'partial.txt').read_text(),'selection rows')
                        self.assertIn(remaining,task_context(args[3])['remaining_work'])
                    return WorkflowTest.fake(self,*args,**kwargs)
                result=run(self.root,continuing)
                self.assertEqual(result['status'],'completed');self.assertEqual(result['review_rounds'],1)
                self.assertEqual([c[0] for c in self.calls],['implementation','implementation','review'])
                self.assertEqual(self.calls[0][1],self.calls[1][1])
                journal,state=load_run(self.root)
                self.assertEqual([a['outcome'] for a in state['attempts']],['assessed','unfinished','implemented','clean'])
                self.assertEqual(state['granted'],initial['granted']);self.assertEqual(state['config'],initial['config'])
                self.assertFalse(any(r['kind']=='run.status' and r['data']['status']=='needs_attention' for r in journal.records()))
                self.assertNotIn('recovery_grants',state)
                report={'failed':False,'structured':{'status':'unfinished','readiness':None,'summary':remaining,'found_along_way':[],'obstacle':None}}
                self.assertEqual(work_result(report),('unfinished',remaining))
                self.git('switch','main');self.git('switch','-C','work')

    def test_post_worker_fingerprint_failure_retains_result_and_spent_attempt(self):
        """docs/architecture.md: unknown post-worker state preserves raw evidence without a new allowance."""
        from .runner import attempt
        from .storage import read_json
        from .workflow import review_limit
        journal,initial=start(self.root,{'tasks':self.tasks[:1]},self.event())
        report={'failed':False,'returncode':0,'duration_ms':1,'text':'usable worker result',
                'structured':{'status':'completed','readiness':READINESS,'obstacle':None,'summary':'Kept work','found_along_way':['retained finding']},'usage_observed':False}
        calls=[]
        def worker(*args,**kwargs):
            calls.append(args[4]);(self.root/'output').write_text('keep this')
            return report
        before=tree(self.root)
        with patch('oh.runner.tree',side_effect=[before,Refused('fingerprint unavailable')]):
            with self.assertRaisesRegex(Refused,'repair the checkout and resume'):
                attempt(self.root,journal,initial,self.tasks[0],'implementation',initial['config']['models']['codex']['simple'],invoke=worker)
        _,state=load_run(self.root);saved=read_json(Path(state['attempts'][0]['evidence'])/'result.json')
        for key,value in report.items():self.assertEqual(saved['final_text' if key=='text' else key],value)
        self.assertIsNone(saved['tree']);self.assertIn('fingerprint unavailable',saved['fingerprint_error'])
        self.assertEqual(state['status'],'needs_attention');self.assertEqual(state['granted'],initial['granted'])
        self.assertEqual(state['done'],[]);self.assertEqual(len(state['attempts']),1)
        self.assertTrue(state['attempts'][0]['finished']);self.assertEqual(state['attempts'][0]['outcome'],'failed')
        self.assertIsNone(state['attempts'][0]['tree']);self.assertEqual(review_limit(state,'1'),review_limit(initial,'1'))
        previous=len(journal.records());run(self.root,worker)
        self.assertEqual(calls,['implementation']);self.assertEqual(len(journal.records()),previous)
        from .cli import executable_run
        executable_run(self.root,None)
        _,state=load_run(self.root);self.assertNotIn('recovery_grants',state)
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
