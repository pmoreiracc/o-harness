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
from .workflow import human_event, load_run, reduce
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
    settings_file().write_text(json.dumps({'projects':{project_name(root):section}}),newline='\n')


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
        (self.root/'product.txt').write_text('fixture',newline='\n')
        self.git('add','.');self.git('commit','-qm','init');self.git('switch','-qc','work')
        self.tasks=[{'id':str(i),'title':f'Task {i}','instructions':'Implement behavior','needs':[] if i==1 else [str(i-1)]} for i in range(1,7)]
        self.calls=[]
        # Production runs use a frozen runtime. Capture its unchanged source version once per fixture;
        # explicit upgrade tests still override this patch, and consumer tree checks remain real.
        from .config import version
        runtime_version=patch('oh.config.version',return_value=version());runtime_version.start();self.addCleanup(runtime_version.stop)
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
        if role!='review':(Path(root)/'output.txt').write_text(str(len(self.calls)),newline='\n')
        return {'failed':False,'returncode':0,'duration_ms':10,'text':'done',
                'structured':({'status':'completed','readiness':READINESS|{'prior_findings':prior},'obstacle':None,'summary':'Checked behavior','found_along_way':[]} if role=='implementation'
                              else {'verdict':'clean','summary':'Checked behavior','findings':[],'evidence':EVIDENCE}),'usage_observed':False}

    def test_config_unknown_fields_fail_closed_and_no_false_zero(self):
        write_settings(self.root,{'taskz':10})
        with self.assertRaises(Refused):load(self.root)
        self.assertEqual(usage_values({}),{'input':None,'cached':None,'output':None,'reasoning':None})
        with self.assertRaises(Refused):usage_values({'input':10,'cached':11})

    def test_verification_cache_invalidates_actual_dependencies(self):
        (self.root/'value').write_text('one',newline='\n')
        checks=[{'name':'read','command':['python3','-c','print("verified")'],'inputs':['value'],'toolchain':[['python3','--version']]}]
        self.assertFalse(verify(self.root,checks,self.project_id)[0]['reused'])
        self.assertTrue(verify(self.root,checks,self.project_id)[0]['reused'])
        (self.root/'value').write_text('two',newline='\n')
        self.assertFalse(verify(self.root,checks,self.project_id)[0]['reused'])

    def test_dot_dependency_tracks_all_files_and_unknown_path_refused(self):
        check={'name':'all','command':['python3','-c','pass'],'inputs':['.'],'toolchain':[['python3','--version']]}
        self.assertFalse(verify(self.root,[check],self.project_id)[0]['reused'])
        self.assertTrue(verify(self.root,[check],self.project_id)[0]['reused'])
        (self.root/'changed').write_text('x',newline='\n')
        self.assertFalse(verify(self.root,[check],self.project_id)[0]['reused'])
        with self.assertRaises(Refused):verify(self.root,[check|{'inputs':['missing']}],self.project_id)

    def test_clean_filter_transformation_rejected_before_review(self):
        from .verification import candidate_tree
        (self.root/'.gitattributes').write_text('*.txt text eol=lf\n*.dat filter=upper\n',newline='\n')  # windows-ok: Git reads either line ending
        (self.root/'data.txt').write_bytes(b'line\r\n')
        candidate_tree(self.root)  # line endings alone: the reviewed text is the committed text
        self.git('config','filter.upper.clean','tr a-z A-Z')
        (self.root/'data.dat').write_bytes(b'lower\n')
        with self.assertRaisesRegex(Refused,'beyond line endings'):candidate_tree(self.root)

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


class NativeFixture:
    """Only the native evidence source is faked; focused helpers and Git remain real."""
    git=WorkflowTest.git
    event=WorkflowTest.event

    def setUp(self):
        WorkflowTest.setUp(self)
        from .authority import native_human
        self.native_human_original=native_human
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        self.native_results={};self.turn=0
        self.parent_path=Path(self.temp.name)/'native-parent.jsonl';self.parent_path.write_text('',newline='\n')
        from .storage import now
        def human(root,locator,**kwargs):
            return {'host':'codex','session':'s','turn':locator.get('turn','human'),
                    'prompt':locator.get('prompt','approve'),'at':now(),'record_hashes':['native-human'],
                    'transcript_path':str(self.parent_path)}|locator
        def coordinator(root,state,locator=None):return human(root,locator) if locator else state['human']
        def child(root,state,attempt,locator):
            return {'child_session':locator.get('child_session','child-'+attempt['id']),
                    'parent_session':state['human']['session'],'profile':attempt['profile'],
                    'transcript_path':str(self.parent_path),'record_hashes':['native-spawn']}
        def result(root,state,attempt,locator):
            value=self.native_results[attempt['id']]
            return {'text':value['text'],'status':value['status'],'profile':attempt['profile'] if attempt.get('native_child') else None,
                    'native_id':attempt.get('native_child',{}).get('child_session'),'record_hashes':['native-result'],'duration_ms':1}|value
        for name,callback in (('native_human',human),('coordinator',coordinator),('native_child',child),('native_result',result)):
            mocked=patch('oh.authority.'+name,side_effect=callback);mocked.start();self.addCleanup(mocked.stop)
        auth=patch('oh.hosts.authentication');auth.start();self.addCleanup(auth.stop)
        catalog=patch('oh.capabilities.codex_models',return_value={
            'gpt-6-luna':{'high'},'gpt-6.1-sol':{'low','medium','high','xhigh'},'gpt-6-astra':{'high'}})
        catalog.start();self.addCleanup(catalog.stop)

    def human(self,prompt='approve',**extra):
        self.turn+=1
        return {'host':'codex','session':'s','turn':str(self.turn),'prompt':prompt,**extra}

    def approve(self,tasks=None,**kwargs):
        from . import native
        prepared=native.prepare_scope(self.root,{'tasks':tasks or self.tasks[:1]},**kwargs)
        native.approve_scope(self.root,prepared['scope_id'],self.human())
        return prepared

    def finish_attempt(self,role,report,*,status='completed',edit=None,child=None):
        from . import native
        admitted=native.admit(self.root,role)
        native.bind(self.root,admitted['id'],{'child_session':child or 'child-'+admitted['id']})
        if edit:edit()
        self.native_results[admitted['id']]={'text':report if isinstance(report,str) else json.dumps(report),'status':status}
        return native.retain(self.root,admitted['id'],{})

    def assess(self):
        return self.finish_attempt('assessment',{'difficulty':'standard','rationale':'Contained behavior change.'})

    def implement(self,report=None,edit=None):
        return self.finish_attempt('implementation',report or {'status':'completed','summary':'Implemented behavior.'},
            edit=edit or (lambda:(self.root/'output.txt').write_text('implemented\n',newline='\n')))

    def reviewed(self,report=None):
        from . import native
        native.candidate(self.root);native.verify(self.root)
        return self.finish_attempt('review',report or {'verdict':'clean','summary':'Checked the candidate.','findings':[]})


class NativeWorkflowTest(NativeFixture,unittest.TestCase):
    def test_scope_needs_native_approval_and_preserves_its_immutable_task_window(self):
        from . import native
        from .workflow import active_file
        configure(self.root,tasks_per_batch=1)
        original=self.root/'manual.txt';original.write_text('Included original work.',newline='\n')
        prepared=native.prepare_scope(self.root,{'tasks':self.tasks[:2]})
        self.assertFalse(active_file(self.root).exists())
        self.assertIn('manual.txt',Path(prepared['preview']).read_text())
        original.write_text('Changed since the preview.',newline='\n')
        unrelated=self.root/'unrelated.txt';unrelated.write_text('New work.',newline='\n')
        with self.assertRaisesRegex(Refused,'starting contents changed'):
            native.approve_scope(self.root,prepared['scope_id'],self.human())
        self.assertEqual(unrelated.read_text(),'New work.')
        prepared=native.prepare_scope(self.root,{'tasks':self.tasks[:2]})
        for text in ('Discuss the change.','stop','publish','Do not approve this scope.',
                     'Do not approve this scope; revise it.','Approve neither this scope nor publication.'):
            with self.subTest(text=text),self.assertRaises(Refused):
                native.approve_scope(self.root,prepared['scope_id'],self.human(text))
        # An unused preview left by an older plugin is historical evidence, not occupied execution.
        from .storage import checkout_file, checkout_id
        scope=json.loads(Path(prepared['preview']).with_name('scope.json').read_text())
        unused=Journal(self.project_id,identifier())
        unused.append('run.started',{'id':unused.path.name,'project':self.project_id,'name':'Fixture','work_kind':'product',
            'host':'codex','human':{'host':'codex','session':'older-session','turn':'old','prompt':'Prepare the older idea.'},
            'source':'older-native-input','checkout':checkout_id(self.root),'workflow':'deliver',
            'branch':'work','base':self.git('rev-parse','HEAD'),'tasks':[self.tasks[0]],'checks':[],
            **{key:scope[key] for key in ('config','config_hash','harness_version','project_checks')}})
        unused.append('run.status',{'status':'prepared_checkpoint'});prior=unused.records()
        atomic_json(checkout_file(self.root,'oh-active-run.json'),
                    {'project':self.project_id,'run':unused.path.name,'checkout':checkout_id(self.root)})
        native.approve_scope(self.root,prepared['scope_id'],self.human('Approve',session='fresh-parent'))
        journal,state=load_run(self.root);original=journal.records()
        self.assertEqual(state['granted'],['1'])
        self.assertNotEqual(state['id'],unused.path.name)
        self.assertEqual(unused.records()[:len(prior)],prior)
        self.assertEqual((reduce(unused.records())['status'],reduce(unused.records())['granted']),('stopped',[]))
        newer=native.prepare_scope(self.root,{'tasks':[self.tasks[0]|{'instructions':'A different fresh scope.'}]})
        with self.assertRaises(Refused):native.approve_scope(self.root,newer['scope_id'],self.human())
        self.assertEqual(journal.records(),original)
        configure(self.root,tasks_per_batch=4,review_rounds=9)
        self.assertEqual(native.resume(self.root)['granted'],['1'])
        self.assertEqual(load_run(self.root)[1]['config'],state['config'])
        native.approve_scope(self.root,prepared['scope_id'],self.human('Approve'))
        self.assertEqual(journal.records(),original)
        (self.root/'manual.txt').write_text('Authorized implementation after activation.',newline='\n')
        native.approve_scope(self.root,prepared['scope_id'],state['human'])
        self.assertEqual(journal.records(),original)
        path=Path(prepared['preview']).with_name('scope.json');value=json.loads(path.read_text())
        value['tasks'][0]['instructions']='Unapproved expansion';path.write_text(json.dumps(value),newline='\n')
        with self.assertRaises(Refused):native.approve_scope(self.root,prepared['scope_id'],self.human())

    def test_actual_native_plan_cannot_silently_approve_different_prepared_tasks(self):
        from . import native
        prepared=native.prepare_scope(self.root,{'tasks':self.tasks[:1]})
        accepted=Path(prepared['preview']).read_text()+'\nAlso replace authentication.\n'
        with self.assertRaises(Refused):
            native.approve_scope(self.root,prepared['scope_id'],self.human(via='plan',accepted_plan=accepted))
        from .workflow import active_file
        self.assertFalse(active_file(self.root).exists())
        exact=Path(prepared['preview']).read_text()
        native.approve_scope(self.root,prepared['scope_id'],self.human(via='plan',accepted_plan=exact))
        self.assertEqual(load_run(self.root)[1]['accepted_scope'],exact)

    def test_native_admissions_are_sequential_fresh_and_use_explicit_profiles(self):
        from . import native
        configure(self.root,models={'codex':{'standard':{'model':'gpt-6.11-sol','effort':'high'}}},context={'handoff_chars':1000})
        instructions='Implement only the approved bounded behavior and retain its acceptance proof.\n'*400
        title=('Long approved task title '*50)[:1200]
        self.approve([self.tasks[0]|{'title':title,'instructions':instructions},*self.tasks[1:4]])
        with self.assertRaises(Refused):native.admit(self.root,'implementation')
        admission=native.admit(self.root,'assessment')
        self.assertEqual(admission['fork_turns'],'none');self.assertTrue(admission['fresh_context'])
        self.assertEqual(admission['profile'],{'model':'gpt-6.1-sol','effort':'high'})
        self.assertEqual(load_run(self.root)[1]['config']['models']['codex']['standard']['model'],'gpt-6.11-sol')
        self.assertIn('gpt-6.11-sol',json.dumps(admission))
        packet_path=Path(admission['task_context']['path']);packet=json.loads(packet_path.read_text())
        self.assertLessEqual(len(packet_path.read_text()),load_run(self.root)[1]['config']['context']['handoff_chars'])
        details=json.loads((packet_path.parent/packet['details']['path']).read_text())
        self.assertEqual(details['task']['instructions'],instructions)
        self.assertEqual(details['task']['title'],title)
        self.assertEqual(details['scope_snapshot']['hash'],load_run(self.root)[1]['scope_id'])
        self.assertTrue((packet_path.parent/packet['findings']['path']).is_file())
        from .receipts import request
        saved_admission=json.loads(Path(admission['request']).read_text())
        request(Path(admission['request']).parent,saved_admission)
        self.assertIn(instructions,(Path(admission['request']).with_name('request.md')).read_text())
        with self.assertRaises(Refused):native.admit(self.root,'review')
        native.bind(self.root,admission['id'],{'child_session':'first-child'})
        self.native_results[admission['id']]={'text':json.dumps({'difficulty':'standard','rationale':'Contained.'}),'status':'completed'}
        native.retain(self.root,admission['id'],{})
        with self.assertRaises(Refused):native.bind(self.root,admission['id'],{'child_session':'first-child'})
        implement=native.admit(self.root,'implementation')
        with self.assertRaises(Refused):native.bind(self.root,implement['id'],{'child_session':'first-child'})
        self.assertEqual(load_run(self.root)[1]['attempts'][-1]['id'],implement['id'])

    def test_blocked_resume_retains_parent_evidence_and_does_not_spend_review_allowance(self):
        from . import native
        self.approve();self.assess()
        measurement=Path(self.temp.name)/'measurement.txt';measurement.write_text('Required service denied access.\n',newline='\n')
        native.attach_evidence(self.root,{'paths':[str(measurement)],'summary':'Observed required input failure.'})
        reason='Restore access to the service, then finish preview/save binding.'
        blocked=self.implement({'status':'blocked','summary':reason},lambda:(self.root/'partial.txt').write_text('keep this work',newline='\n'))
        initial=load_run(self.root)[1]
        self.assertEqual(blocked['outcome'],'blocked')
        with self.assertRaises(Refused):native.admit(self.root,'review')
        facts=native.resume(self.root)
        self.assertEqual(facts['reviews_used'],0);self.assertEqual(facts['granted'],initial['granted'])
        resumed=native.admit(self.root,'implementation')
        packet=json.loads(Path(resumed['task_context']['path']).read_text())
        self.assertEqual(packet['current_work']['summary'],reason)
        self.assertEqual(packet['current_work']['outcome'],'blocked')
        self.assertEqual(packet['supplementary_evidence'][0]['files'][str(measurement.resolve())],
                         __import__('hashlib').sha256(measurement.read_bytes()).hexdigest())
        self.assertEqual((self.root/'partial.txt').read_text(),'keep this work')
        self.assertNotIn('recovery_grants',load_run(self.root)[1])

    def test_review_requires_completed_work_and_passing_checks_for_the_final_candidate(self):
        from . import native
        configure(self.root,review_rounds=3)
        self.approve();self.assess();self.implement({'status':'unfinished','summary':'Finish the final assertion.'})
        native.candidate(self.root);native.verify(self.root)
        with self.assertRaises(Refused):native.admit(self.root,'review')
        self.implement();native.candidate(self.root)
        cancelled={'name':'fixture','command':['fixture'],'returncode':0,'cancellation':['timeout'],'duration_ms':1}
        with patch('oh.verification.verify',return_value=[cancelled]):native.verify(self.root)
        with self.assertRaises(Refused):native.admit(self.root,'review')
        native.verify(self.root)
        (self.root/'output.txt').write_text('changed after verification',newline='\n')
        with self.assertRaises(Refused):native.admit(self.root,'review')
        native.verify(self.root)
        from . import handoff
        saved_write=handoff.atomic_json;before=load_run(self.root)[1]
        def failed_packet(path,value,**kwargs):
            if Path(path).name=='task-context.json':raise OSError('Simulated packet write failure before native launch.')
            return saved_write(path,value,**kwargs)
        with patch('oh.handoff.atomic_json',side_effect=failed_packet),self.assertRaises(OSError):
            native.admit(self.root,'review')
        self.assertEqual(load_run(self.root)[1]['attempts'],before['attempts'])
        self.assertEqual(native.resume(self.root)['reviews_used'],0)
        failed=native.admit(self.root,'review')
        self.native_results[failed['id']]={'text':'Native spawn failed before returning a child identity.','status':'failed'}
        self.assertEqual(native.retain(self.root,failed['id'],{'tool_use_id':'failed-native-spawn'})['outcome'],'failed')
        self.assertEqual(native.resume(self.root)['reviews_used'],1)
        rejected=native.admit(self.root,'review')
        self.native_results[rejected['id']]={'text':'Terminal child used a different actual profile.','status':'binding_failed',
            'profile':{'model':'actual-other','effort':'low'},'native_id':'rejected-child','admitted_profile':rejected['profile'],
            'terminal_status':'completed','binding_issues':['Actual profile differs from admission.']}
        retained=native.retain(self.root,rejected['id'],{'tool_use_id':'successful-rejected-spawn','child_session':'rejected-child'})
        self.assertEqual(retained['outcome'],'binding_failed')
        self.assertEqual(retained['native_failure']['profile'],{'model':'actual-other','effort':'low'})
        self.assertIn('actual-other / low',(Path(retained['evidence'])/'review.md').read_text())
        self.assertEqual(native.resume(self.root)['reviews_used'],2)
        with self.assertRaises(Refused):native.complete(self.root,rejected['id'])
        review=self.finish_attempt('review',{'verdict':'clean','summary':'Checked.','findings':[]})
        (self.root/'output.txt').write_text('changed after review',newline='\n')
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        self.assertEqual(load_run(self.root)[1]['done'],[])

    def test_reviewer_mutation_preserves_the_report_without_authorizing_completion(self):
        from . import native
        self.approve();self.assess();self.implement();native.candidate(self.root);native.verify(self.root)
        review=self.finish_attempt('review',{'verdict':'clean','summary':'Claimed clean.','findings':[]},
                                   edit=lambda:(self.root/'surprise').write_text('reviewer edit',newline='\n'))
        self.assertEqual(review['outcome'],'binding_failed')
        self.assertTrue((Path(review['evidence'])/'native-result.json').is_file())
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        self.assertEqual(load_run(self.root)[1]['done'],[])

    def test_review_attempts_and_findings_survive_repairs_and_spent_window(self):
        from . import native
        from .handoff import finding_index
        configure(self.root,review_rounds=2)
        self.approve();self.assess();self.implement()
        finding={'severity':'blocking','description':'Timeout still leaks its session.','path':'output.txt','family':'session-leak','relation':'original'}
        scope={'severity':'scope','description':'Logout cleanup belongs to later work.','path':'logout.py','family':'logout','relation':'original'}
        original_report='[BLOCKING] '+finding['description']+'\nPath: output.txt\nFamily: session-leak. Relation: original.\n\n[SCOPE] '+scope['description']+'\nPath: logout.py\nFamily: `logout`. Relation: original.'
        first=self.reviewed(original_report)
        self.assertEqual(first['findings'],[finding,scope])
        with self.assertRaises(Refused):native.complete(self.root,first['id'])
        repaired=self.implement()
        self.assertEqual(repaired['profile'],load_run(self.root)[1]['config']['models']['codex']['standard'])
        second=self.reviewed('[BLOCKING] '+finding['description']+'\nPath: output.txt\nFamily: session-leak. Relation: repeat-family.')
        repair=native.admit(self.root,'implementation')
        state=load_run(self.root)[1]
        self.assertEqual(repair['profile'],state['config']['models']['codex']['complex'])
        historical={'attempts':[dict(a,findings=[dict(f,family='session-leak. Relation: '+f.get('relation','original')+'.') for f in a.get('findings',[])]) for a in state['attempts']]}
        self.assertTrue(native._repeated_family(historical,'1'))
        native.bind(self.root,repair['id'],{})
        self.native_results[repair['id']]={'text':json.dumps({'status':'completed','summary':'Closed the family.'}),'status':'completed'}
        native.retain(self.root,repair['id'],{});native.candidate(self.root);native.verify(self.root)
        with self.assertRaises(Refused):native.admit(self.root,'review')
        before=native.resume(self.root)
        self.assertEqual((before['reviews_used'],before['reviews_allowed']),(2,2))
        for text in ('Discuss the findings.','Do not grant another review window.'):
            with self.assertRaises(Refused):native.decision(self.root,'grant-review',self.human(text))
        locator=self.human('Grant another review window.')
        native.decision(self.root,'grant-review',locator)
        native.decision(self.root,'grant-review',locator)
        self.assertEqual(native.resume(self.root)['reviews_allowed'],4)
        clean=self.finish_attempt('review',{'verdict':'clean','summary':'Independently checked repairs.','findings':[]})
        with self.assertRaises(Refused):native.complete(self.root,clean['id'])
        native.decision(self.root,'route-scope',self.human('Route scope'),attempt=first['id'],
                        destination={'issue':'https://github.com/example/product/issues/20'})
        with self.assertRaises(Refused):
            native.decision(self.root,'accept-concerns',self.human('Accept concerns'),attempt=first['id'])
        families=finding_index(load_run(self.root)[1],'1')['families']
        self.assertEqual(len(families[0]['occurrences']),2)
        self.assertTrue(all(item['reviewed_by']==clean['id'] for item in families[0]['occurrences']))
        self.assertEqual(json.loads((Path(first['evidence'])/'native-result.json').read_text())['text'],original_report)
        self.assertEqual(families[1]['occurrences'][0]['disposition'],'routed')
        native.complete(self.root,clean['id'])

    def test_imperfect_report_preserves_every_recognizable_finding(self):
        from . import native
        self.approve();self.assess();self.implement()
        headings=self.reviewed('Clean. No findings.\n\n## Scope examined\nThe changed route and its callers were inspected.')
        self.assertEqual(headings['outcome'],'clean');self.assertEqual(headings['findings'],[])
        report={'verdict':'clean','summary':'Imperfect report.','findings':[
            {'severity':'unknown','description':'Unclassified neighboring risk.'},
            {'severity':'blocking','description':'Concrete retained defect.','family':'retained','path':'output.txt'}]}
        review=self.reviewed(report)
        self.assertEqual(review['findings'][0]['description'],'Concrete retained defect.')
        self.assertNotEqual(review['outcome'],'clean')
        retained=json.loads((Path(review['evidence'])/'result.json').read_text())
        self.assertEqual(retained,report)
        from .handoff import finding_index
        index=finding_index(load_run(self.root)[1],'1')
        self.assertEqual(index['families'][0]['occurrences'][0]['id'],review['id']+'#2')
        self.assertEqual(index['incomplete_reviews'][0]['fragments'],[{'position':1,'finding':report['findings'][0]}])
        self.assertIn('Unclassified neighboring risk.',(Path(review['evidence'])/'review.md').read_text())
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        readable='''[UNKNOWN] Unclassified neighboring risk.
Location: sibling.py:1
Why: Accepted input X loses its output.

**[BLOCKING] Concrete retained defect.**
- **Family:** retained
- **Location:** output.txt
- **Why:** The output is lost.

```text
[BLOCKING] A fenced example is not another finding.
Family: example
```
'''
        second=self.reviewed(readable)
        self.assertEqual(len(second['findings']),1)
        self.assertEqual(second['findings'][0]['family'],'retained')
        self.assertEqual(second['findings'][0]['failure'],'The output is lost.')
        self.assertEqual(second['finding_positions'],[2])
        self.assertEqual(second['review_fragments'][0]['finding']['severity'],'unknown')
        self.assertTrue(second['report_issues'])
        self.assertEqual(native._report('````text\n'+readable+'````')['findings'],native._report(readable)['findings'])
        self.assertNotEqual(native._report('Example only:\n```text\nClean.\n```').get('verdict'),'clean')
        self.assertEqual(native._report('```text\nClean.\n```')['verdict'],'clean')
        index=finding_index(load_run(self.root)[1],'1')
        self.assertEqual(index['families'][0]['occurrences'][-1]['id'],second['id']+'#2')
        self.assertEqual(len(index['incomplete_reviews']),2)
        self.assertEqual(json.loads((Path(second['evidence'])/'native-result.json').read_text())['text'],readable)
        with self.assertRaises(Refused):native.complete(self.root,second['id'])
        repair=native.admit(self.root,'implementation')
        packet=json.loads(Path(repair['task_context']['path']).read_text())
        self.assertEqual(json.loads(Path(packet['findings']['path']).read_text()),index)

    def test_completion_commits_exact_reviewed_tree_once_and_task_grants_do_not_expand(self):
        from . import native
        configure(self.root,tasks_per_batch=1)
        self.approve(self.tasks[:2]);self.assess();self.implement()
        review=self.reviewed();head=self.git('rev-parse','HEAD')
        completed=native.complete(self.root,review['id'])
        self.assertEqual(self.git('rev-parse','HEAD^'),head)
        self.assertEqual(self.git('rev-parse','HEAD^{tree}'),review['git_tree'])
        self.assertEqual(native.complete(self.root,review['id']),completed)
        self.assertEqual(native.resume(self.root)['status'],'checkpoint')
        collect()
        with connect() as db:
            observations=analytics(db,{'from':'2000','to':'2100'})['summary']
        self.assertGreaterEqual(observations['attempts'],3)
        self.assertIsNone(observations['input'])
        self.assertIsNone(observations['output'])
        with self.assertRaises(Refused):native.admit(self.root,'assessment')
        locator=self.human('Continue with the next task window.')
        native.decision(self.root,'continue',locator)
        native.decision(self.root,'continue',locator)
        state=load_run(self.root)[1]
        self.assertEqual(state['granted'],['2']);self.assertEqual(state['done'],['1'])
        self.assertEqual(native.resume(self.root)['task']['id'],'2')
        self.assess();self.implement(edit=lambda:(self.root/'second.txt').write_text('Task two is complete.',newline='\n'))
        second=self.reviewed();native.complete(self.root,second['id'])
        second_commit=self.git('rev-parse','HEAD');original_summaries=load_run(self.root)[1]['summaries']
        native.review(self.root,['task','1']);native.verify(self.root)
        self.git('remote','add','origin','https://github.com/example/product.git')
        publication_choice=lambda:native.decision(self.root,'publish',self.human('publish',question='Publish the reviewed work branch to example/product?'))
        with self.assertRaisesRegex(Refused,'requested task review'):publication_choice()
        blocker=self.finish_attempt('review',{'verdict':'blocking','summary':'Task one needs a scoped correction.','findings':[
            {'severity':'blocking','description':'Task one leaves stale timeout state.','family':'earlier-task','path':'output.txt'}]})
        with self.assertRaises(Refused):native.complete(self.root,blocker['id'])
        with self.assertRaisesRegex(Refused,'requested task review'):publication_choice()
        from . import publication
        unresolved=load_run(self.root)[1]
        with patch('oh.publication.made',return_value=unresolved|{'status':'pr'}),self.assertRaisesRegex(Refused,'requested task review'):
            publication.render(self.root)
        self.implement(edit=lambda:(self.root/'output.txt').write_text('Corrected task one after task two.',newline='\n'))
        fixed=self.reviewed();correction=native.complete(self.root,fixed['id'])
        self.assertEqual(self.git('rev-parse','HEAD^'),second_commit)
        self.assertEqual(correction['correction_of'],completed['commit'])
        state=load_run(self.root)[1]
        self.assertEqual(state['summaries'][:2],original_summaries)
        self.assertEqual(state['done'],['1','2'])
        evidence=state['commit_intents'][correction['commit_key']]['publication']
        self.assertEqual(evidence['parent'],second_commit)
        self.assertEqual(evidence['correction_of'],completed['commit'])
        publication_choice()
        self.assertIn('Correction:',publication.render(self.root))

    def test_interrupted_commit_recovers_without_another_review_or_duplicate_commit(self):
        from . import native
        self.approve();self.assess()
        author=native.admit(self.root,'implementation');native.bind(self.root,author['id'],{})
        (self.root/'output.txt').write_text('Retain this implementation once.\n',newline='\n')
        self.native_results[author['id']]={'text':json.dumps({'status':'completed','summary':'Implementation is ready.'}),'status':'completed'}
        save=native.atomic_json
        def interrupted_result(path,value,**kwargs):
            result=save(path,value,**kwargs)
            if Path(path).name=='native-result.json':raise OSError('Interrupted after retaining the original native result.')
            return result
        with patch('oh.native.atomic_json',side_effect=interrupted_result),self.assertRaises(OSError):
            native.retain(self.root,author['id'],{})
        source_path=Path(author['request']).with_name('native-result.json');source=source_path.read_bytes()
        self.assertFalse(load_run(self.root)[1]['attempts'][-1]['finished'])
        native.retain(self.root,author['id'],{})
        self.assertEqual(source_path.read_bytes(),source)
        self.assertEqual(len(load_run(self.root)[1]['attempts']),2)
        review=self.reviewed()
        journal,state=load_run(self.root);original=Journal.append
        def interrupted(this,kind,data):
            if kind=='task.completed':raise OSError('Interrupted after exact commit.')
            return original(this,kind,data)
        with patch.object(Journal,'append',interrupted),self.assertRaises(OSError):native.complete(self.root,review['id'])
        committed=self.git('rev-parse','HEAD');attempts=len(load_run(self.root)[1]['attempts'])
        recovered=native.complete(self.root,review['id'])
        self.assertEqual(recovered['commit'],committed)
        self.assertEqual(self.git('rev-parse','HEAD'),committed)
        self.assertEqual(len(load_run(self.root)[1]['attempts']),attempts)
        self.assertEqual(load_run(self.root)[1]['done'],['1'])

    def test_stop_refuses_unsettled_native_child_and_resume_never_renews_allowance(self):
        from . import native
        self.approve();self.assess();attempt=native.admit(self.root,'implementation')
        before=load_run(self.root)[1]
        with self.assertRaises(Refused):native.decision(self.root,'stop',self.human('stop'))
        self.assertEqual(native.resume(self.root)['granted'],before['granted'])
        native.bind(self.root,attempt['id'],{})
        self.native_results[attempt['id']]={'text':'Host confirms the child was cancelled.','status':'interrupted'}
        native.retain(self.root,attempt['id'],{})
        native.decision(self.root,'stop',self.human('stop'))
        with self.assertRaises(Refused):native.admit(self.root,'implementation')
        native.resume(self.root,self.human('Resume the approved work.',session='new-session',host='claude'))
        after=load_run(self.root)[1]
        self.assertEqual(after['granted'],before['granted']);self.assertEqual(after['config'],before['config'])
        self.assertEqual(len(after['attempts']),len(before['attempts']))
        self.assertEqual(after['attempts'][-1]['outcome'],'interrupted')

    def test_journal_tampering_cannot_rewrite_task_authority(self):
        self.approve();journal,state=load_run(self.root)
        grant=next(record for record in journal.records() if record['kind']=='grant')
        path=journal.path/f"{grant['sequence']:06}.json";value=json.loads(path.read_text());value['data']['tasks']=['unauthorized']
        path.write_text(json.dumps(value),newline='\n')
        with self.assertRaises(Refused):journal.records()

    def test_scope_routing_and_concern_acceptance_are_separate_exact_subject_decisions(self):
        from . import native
        self.approve();self.assess();self.implement()
        concern={'severity':'concern','description':'Optional timeout wording.','family':'wording','path':'output.txt'}
        scope={'severity':'scope','description':'Logout cleanup belongs to later work.','family':'logout','path':'logout.py'}
        review=self.reviewed({'verdict':'concern','summary':'Two distinct dispositions.','findings':[concern,scope]})
        with self.assertRaises(Refused):
            native.decision(self.root,'accept-concerns',self.human('Do not accept concerns; fix them.'),attempt=review['id'])
        issue='https://github.com/example/product/issues/19'
        native.decision(self.root,'route-scope',self.human('route scope'),attempt=review['id'],destination={'issue':issue})
        with self.assertRaises(Refused):native.complete(self.root,review['id'])
        native.decision(self.root,'accept-concerns',self.human('accept concerns'),attempt=review['id'])
        state=load_run(self.root)[1]
        self.assertEqual(state['scope_records'][review['id']]['findings'],[scope])
        self.assertIn(issue,json.dumps(state['resolutions'][review['id']]))
        self.assertEqual(state['attempts'][-1]['findings'],[concern,scope])
        native.complete(self.root,review['id'])
        self.assertEqual(load_run(self.root)[1]['done'],['1'])
        from . import publication
        self.git('remote','add','origin','https://github.com/example/product.git')
        native.decision(self.root,'publish',self.human('publish',question='Publish the reviewed work branch to example/product?'))
        self.assertIn(issue,publication.render(self.root))
        from copy import deepcopy
        state=load_run(self.root)[1];evidence=state['commit_intents']['1']['publication']
        for issue_reference in (issue,{'url':issue}):
            for scope_record in (True,False):
                historical=deepcopy(state);portable=deepcopy(evidence)
                historical['resolutions'][review['id']]['issue']=issue_reference
                portable['resolutions'][review['id']]['issue']=issue_reference
                if scope_record:
                    historical['scope_records'][review['id']]['destination']['issue']=issue_reference
                    portable['scope'][review['id']]['destination']['issue']=issue_reference
                else:
                    historical['scope_records']={};portable.pop('scope',None)
                with self.subTest(issue_reference=issue_reference,historical_scope=scope_record):
                    rendered=publication.readable([{'commit':self.git('rev-parse','HEAD'),'evidence':portable}],{state['id']:historical})
                    self.assertIn(issue,rendered)
        historical=deepcopy(evidence)
        record=historical['scope'][review['id']]
        record.update(action='dismiss',destination={'design':'docs/design/0900-fixture.md','section':'## Scope decisions'})
        resolution=historical['resolutions'][review['id']]
        resolution.update(choice='accept concerns and dismiss scope',scope=record)
        resolution.pop('issue',None)
        publication.validate_evidence(historical)
        record['destination']['section']='## Unrecorded decisions'
        with self.assertRaises(Refused):publication.validate_evidence(historical)

    def test_standalone_review_after_stop_is_feedback_and_preserves_the_original_run(self):
        from . import native
        self.approve();self.assess();self.implement()
        native.decision(self.root,'stop',self.human('stop'))
        original_journal,original=load_run(self.root);records=original_journal.records();head=self.git('rev-parse','HEAD')
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'s'}):
            standalone=native.review(self.root,['tree'])
            reviewed=self.finish_attempt('review',{'verdict':'clean','summary':'Feedback on the stopped changes.','findings':[]})
            packet=json.loads((Path(reviewed['evidence'])/'task-context.json').read_text())
            self.assertEqual(packet['purpose'],'standalone')
            self.assertTrue(packet['standalone_subject'])
            self.assertNotIn('human_scope_approval',packet)
            self.assertNotIn('original_scope_provenance',packet)
            with self.assertRaises(Refused):native.complete(self.root,reviewed['id'])
            with self.assertRaises(Refused):native.admit(self.root,'implementation')
        self.assertNotEqual(standalone['run'],original['id'])
        self.assertEqual(original_journal.records(),records)
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertEqual(original['granted'],['1'])
        feedback=Journal(self.project_id,standalone['run']);feedback_records=feedback.records()
        resumed=native.resume(self.root,self.human('Resume the approved work.',session='delivery-parent'))
        self.assertEqual(resumed['run'],original['id'])
        self.assertEqual(resumed['granted'],original['granted'])
        self.assertEqual(load_run(self.root)[1]['attempts'],original['attempts'])
        self.assertEqual(feedback.records(),feedback_records)
        continuation=native.admit(self.root,'implementation')
        self.assertEqual(continuation['task'],'1')

    def test_legacy_resume_preserves_original_findings_and_consumed_review_allowance(self):
        from . import native
        from .storage import checkout_file, checkout_id, read_json
        configure(self.root,review_rounds=2)
        self.approve();self.assess();self.implement()
        first=self.reviewed({'verdict':'blocking','summary':'Original blocker.','findings':[
            {'severity':'blocking','description':'Retain this original defect.','family':'legacy','path':'output.txt'}]})
        journal,state=load_run(self.root);legacy=Journal(self.project_id,identifier())
        data=dict(journal.records()[0]['data']);data['id']=legacy.path.name
        for key in ('native_version','scope_id','scope_snapshot'):data.pop(key,None)
        legacy.append('run.started',data)
        for record in journal.records()[1:]:legacy.append(record['kind'],record['data'])
        legacy.append('run.status',{'status':'stopped'})
        atomic_json(checkout_file(self.root,'oh-active-run.json'),
                    {'project':self.project_id,'run':legacy.path.name,'checkout':checkout_id(self.root)})
        original=legacy.records();before=reduce(original);result=read_json(Path(first['evidence'])/'result.json')
        resumed=native.resume(self.root,self.human('resume',session='fresh-session'))
        self.assertEqual(resumed['granted'],state['granted'])
        self.assertEqual((resumed['reviews_used'],resumed['reviews_allowed']),(1,2))
        after=load_run(self.root)[1]
        self.assertEqual(after['config'],state['config']);self.assertEqual(after['attempts'],before['attempts'])
        self.assertEqual(legacy.records()[:len(original)],original)
        self.assertEqual(read_json(Path(first['evidence'])/'result.json'),result)
        self.assertNotIn('recovery_grants',after)
        live=native.admit(self.root,'implementation')
        packet=read_json(live['task_context']['path'])
        self.assertNotIn('human_scope_approval',packet)
        provenance=Path(packet['original_scope_provenance']['path'])
        self.assertEqual(provenance,legacy.path/'000001.json')
        self.assertEqual(read_json(provenance),original[0])
        with self.assertRaises(Refused):native.resume(self.root,self.human('resume',session='other-session'))
        self.assertEqual(load_run(self.root)[1]['attempts'][-1]['id'],live['id'])

    def test_publication_reuses_the_existing_pr_and_unknown_discovery_does_not_reopen_work(self):
        from . import native, publication
        self.git('remote','add','origin','https://github.com/example/product.git')
        (self.root/'manual.txt').write_text('Existing manual PR work to review.',newline='\n')
        self.git('add','.');self.git('commit','-qm','manual PR starting work')
        manual=self.git('rev-parse','HEAD');base=self.git('rev-parse','origin/main')
        pr=pull_request({'publication':{'destination':'https://github.com/example/product.git',
            'base_branch':'main','branch':'work','head':manual}})
        from . import branches, prepared
        run_git=branches.run_git
        def local_fetch(root,*args,**kwargs):
            if args[:3]==('fetch','--quiet','origin'):
                return run_git(root,'fetch','--quiet',str(self.root),*args[3:],**kwargs)
            return run_git(root,*args,**kwargs)
        manifest=Path(self.temp.name)/'correction-tasks.json'
        atomic_json(manifest,{'tasks':self.tasks[:1]})
        with patch('oh.publication.github',return_value=pr),patch('oh.branches.run_git',side_effect=local_fetch):
            selected=prepared.prepare(self.root,manifest=manifest,pr=144)
        scope=json.loads(Path(selected['preview']).with_name('scope.json').read_text())
        self.assertNotIn('repair_source',scope)
        self.assertEqual(scope['pr_target']['covers'],[manual])
        self.assertEqual(scope['pr_target']['review_base'],base)
        self.assertIn(manual,Path(selected['preview']).read_text())
        native.approve_scope(self.root,selected['scope_id'],self.human())
        self.assess();self.implement();review=self.reviewed()
        packet=json.loads((Path(review['evidence'])/'task-context.json').read_text())
        self.assertEqual(packet['included_original_work']['covers'],[manual])
        native.complete(self.root,review['id'])
        for text in ('approve','Do not publish. Keep the work local.','No, publish nothing.'):
            with self.assertRaises(Refused):native.decision(self.root,'publish',self.human(text))
        question='Publish the reviewed work branch to example/product?'
        with self.assertRaises(Refused):
            native.decision(self.root,'publish',self.human('publish',question=question,question_at='2000-01-01T00:00:00+00:00'))
        native.decision(self.root,'publish',self.human('publish',question=question))
        journal,state=load_run(self.root);grant=state['publication'];attempts=state['attempts']
        with patch('oh.publication.github',side_effect=Refused('GitHub temporarily unavailable.')):
            with self.assertRaises(Refused):publication.reconcile(self.root)
        self.assertEqual(load_run(self.root)[1]['publication'],grant)
        body=publication.render(self.root)
        self.assertIn(manual,body)
        pr=pull_request(state)|{'body':body}
        def github(root,host,path,**kwargs):return [pr] if kwargs.get('pages') else pr
        with patch('oh.publication.github',side_effect=github):
            saved=publication.reconcile(self.root)
            repeated=publication.reconcile(self.root)
        self.assertEqual(saved['published']['number'],144)
        self.assertEqual(repeated['published']['number'],144)
        self.assertEqual(load_run(self.root)[1]['attempts'],attempts)
        with self.assertRaises(Refused):native.admit(self.root,'implementation')
        history=journal.records()
        self.approve([self.tasks[0]|{'instructions':'A separate bounded follow-up.'}])
        self.assertNotEqual(load_run(self.root)[1]['id'],state['id'])
        self.assertEqual(journal.records(),history)


if __name__=='__main__':unittest.main()
