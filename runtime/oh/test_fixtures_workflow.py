"""Disposable Git repositories and synthetic native host records for workflow tests."""
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from .hosts import LENSES
from .registry import register
from .storage import identifier
from .system import Path
from .workflow import human_event, load_run

EVIDENCE={'anchors':['Fixture task'],'attacks':['Fixture gate checked'],'limits':['Synthetic test reviewer'],'lenses':{k:'Fixture checked' for k in LENSES}}
READINESS={'rules':['Fixture contract'], 'surfaces':['output.txt and its caller'], 'proof':['Fixture behavior check'],
 'family_closure':[], 'prior_findings':[], 'verification':['Fixture verify passed'], 'requirements':['Fixture requirement -> output.txt -> behavior check'], 'self_review':['Invalid input -> fixture check -> rejected'], 'repairs':['Fixture failure -> required behavior -> implementation correction -> checked'], 'limits':['Synthetic model fixture']}

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


class WorkflowFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        def cleanup():
            self.temp.name=os.fspath(Path(self.temp.name))
            self.temp.cleanup()
        self.addCleanup(cleanup)
        self.root=Path(self.temp.name)/'project';self.root.mkdir()
        self.env=patch.dict(os.environ,{'OH_DATA_HOME':str(Path(self.temp.name)/getattr(self,'state_folder','state')),
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

class NativeFixture(WorkflowFixture):
    """Only the native evidence source is faked; focused helpers and Git remain real."""
    def setUp(self):
        super().setUp()
        from .authority import native_human
        self.native_human_original=native_human
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        self.native_results={};self.turn=0;self.human_occurrences={}
        self.parent_path=Path(self.temp.name)/'native-parent.jsonl';self.parent_path.write_text('',newline='\n')
        from .storage import now
        def human(root,locator,**kwargs):
            value={'host':'codex','session':'s','turn':'human','prompt':'approve'}|locator
            identity=tuple(value.get(k) for k in ('host','session','turn','prompt','message_id'))+(value.get('question_call') or value.get('tool_use_id'),)
            if locator.get('at'):self.human_occurrences[identity]=locator['at']
            return {'host':'codex','session':'s','turn':locator.get('turn','human'),
                    'prompt':locator.get('prompt','approve'),'at':self.human_occurrences.setdefault(identity,now()),'record_hashes':['native-human'],
                    'transcript_path':str(self.parent_path)}|locator
        def coordinator(root,state,locator=None,**kwargs):return human(root,locator) if locator else state['human']
        def child(root,state,attempt,locator):
            return {'child_session':locator.get('child_session','child-'+attempt['id']),
                    'parent_session':state['human']['session'],'profile':attempt['profile'],
                    'transcript_path':str(self.parent_path),'record_hashes':['native-spawn']}
        def result(root,state,attempt,locator):
            if attempt['id'] not in self.native_results:
                from .authority import Saving
                raise Saving('Native child result is not saved yet')
            value=self.native_results[attempt['id']]
            return {'text':value['text'],'status':value['status'],'profile':attempt['profile'] if attempt.get('native_child') else None,
                    'native_id':attempt.get('native_child',{}).get('child_session'),'record_hashes':['native-result'],'duration_ms':1}|value
        for name,callback in (('native_human',human),('coordinator',coordinator),('native_child',child),('native_result',result),('native_diagnostics',lambda *args:[]),('claude_operations',lambda *args:{})):
            mocked=patch('oh.authority.'+name,side_effect=callback);mocked.start();self.addCleanup(mocked.stop)
        auth=patch('oh.hosts.authentication');auth.start();self.addCleanup(auth.stop)
        catalog=patch('oh.capabilities.codex_models',return_value={
            'gpt-6-luna':{'high'},'gpt-6.1-sol':{'low','medium','high','xhigh'},'gpt-6-astra':{'high'}})
        catalog.start();self.addCleanup(catalog.stop)

    def human(self,prompt='approve',**extra):
        from .storage import now
        self.turn+=1
        if extra.get('decision') and 'prepared_offer' not in extra:
            # Simulated host evidence; transcript parsing is exercised separately.
            extra['prepared_offer']={'decision':extra['decision'],'at':extra.get('question_at') or now()}
        return {'host':'codex','session':'s','turn':str(self.turn),'prompt':prompt,**extra}

    def offer_record(self,host,session,offer,at):
        text=json.dumps(offer)
        if host=='claude':
            return {'sessionId':session,'cwd':str(self.root),'type':'user','timestamp':at,
                    'message':{'content':[{'type':'tool_result','tool_use_id':'prepare','content':text}]}}
        return {'type':'response_item','timestamp':at,'payload':{'type':'function_call_output','call_id':'prepare','output':text}}

    def offered_answer(self,offer,label,*,via='question',**extra):
        from .storage import now
        at=now()
        shown='\n'.join([offer.get('disclosure',''),offer['question'],*offer['options']])
        return self.human(label,decision=offer['decision'],via=via,question=offer['question'] if via=='question' else shown,
                          question_options=offer['options'],question_at=at,
                          question_context=[{'text':shown,'at':at}],**extra)

    def resume_choice(self,*,run=None,**extra):
        from . import native
        state=load_run(self.root,run or native.resume(self.root)['run'])[1]
        question='Resume '+native._saved_subject(state)+' on '+state['branch']+'?'
        return self.human('Resume',question=question,**extra)

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
