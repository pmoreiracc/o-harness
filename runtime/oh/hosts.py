from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from .storage import Refused, atomic_json, identifier
from .system import WINDOWS
from .telemetry import best_effort

LENSES=('task-and-design','invariants-and-decisions','affected-surfaces-and-negative-space',
 'correctness-and-failure-paths','security-authorization-and-concurrency',
 'tests-claims-docs-and-generated-artifacts','prior-findings-and-family-closure')
STRINGS={'type':'array','items':{'type':'string'}}
from .handoff import READINESS_LISTS, DISPOSITIONS
READ_ONLY_ROLES=('review','analysis','assessment')
ASSESSMENT_SCHEMA={'type':'object','additionalProperties':False,
 'required':['difficulty','rationale','references','uncertainty'],'properties':{
 'difficulty':{'type':'string','enum':['simple','standard','complex']},
 'rationale':{'type':'string'},'references':STRINGS,'uncertainty':STRINGS}}
REVIEW_SCHEMA={'type':'object','additionalProperties':False,
 'required':['verdict','summary','findings','evidence'],'properties':{
 'verdict':{'type':'string','enum':['clean','blocking','concern','scope']},'summary':{'type':'string'},
 'findings':{'type':'array','items':{'type':'object','additionalProperties':False,
   'required':['severity','description','path','family','relation','anchor','failure','fix'],'properties':{
     **{key:{'type':'string'} for key in ('anchor','failure','fix')},
     'severity':{'type':'string','enum':['blocking','concern','scope']},'description':{'type':'string'},'path':{'type':'string'},'family':{'type':'string'},'relation':{'type':'string','enum':['original','repeat-family','fix-regression','first-round-escape','newly-exposed','scope']}}}},
 'evidence':{'type':'object','additionalProperties':False,'required':['anchors','lenses','attacks','limits'],
   'properties':{'anchors':STRINGS,'attacks':STRINGS,'limits':STRINGS,
     'lenses':{'type':'object','additionalProperties':False,'required':list(LENSES),
       'properties':{lens:{'type':'string'} for lens in LENSES}}}}}}

# Implementation reports keep unrelated observations separate from the authorized change.
WORK_SCHEMA={'type':'object','additionalProperties':False,'required':['status','summary','found_along_way','obstacle','readiness'],
 'properties':{'status':{'type':'string','enum':['completed','unfinished','blocked']},
               'summary':{'type':'string'},'found_along_way':STRINGS,
               'readiness':{'type':['object','null'],'additionalProperties':False,
                 'required':[*READINESS_LISTS,'prior_findings'],
                 'properties':{**{key:STRINGS for key in READINESS_LISTS},
                    'prior_findings':{'type':'array','items':{'type':'object','additionalProperties':False,
                        'required':['id','disposition','proof'],'properties':{'id':{'type':'string'},
                            'disposition':{'type':'string','enum':list(DISPOSITIONS)},'proof':{'type':'string'}}}}}},
               'obstacle':{'type':['object','null'],'additionalProperties':False,
                 'required':['kind','evidence','next_step'],'properties':{
                   'kind':{'type':'string','enum':['missing_authority','external_dependency']},
                   'evidence':{'type':'string'},'next_step':{'type':'string'}}}}}

# A design worker returns prose only; OH adds the number, frontmatter, roadmap link and decision log row.
DESIGN_SCHEMA={'type':'object','additionalProperties':False,
 'required':['kind','title','body','context','alternatives','consequences','summary'],'properties':{
 'kind':{'type':'string','enum':['design','decision']},
 **{key:{'type':'string'} for key in ('title','body','context','alternatives','consequences','summary')}}}
# An intake worker routes one idea and writes its prose; OH writes the row, task or decision record.
PROPOSAL_SCHEMA={'type':'object','additionalProperties':False,
 'required':['route','understanding','reason','evidence','text','slug','milestone','milestone_title','milestone_done_when',
             'depends','design','track','decision_title','decision_context','decision_alternatives','decision_consequences','summary'],
 'properties':{'route':{'type':'string','enum':['roadmap','task','improvement','unclear']},'depends':{'type':'array','items':{'type':'string'}},
   **{key:{'type':'string'} for key in ('understanding','reason','evidence','text','slug','milestone','milestone_title','milestone_done_when',
                                        'design','track','decision_title','decision_context','decision_alternatives','decision_consequences','summary')}}}

def script(stream):
    """A wrapper that needs an interpreter, not a native binary. Windows binaries start with MZ."""
    head=stream.read(2)
    return head!=b'MZ' if WINDOWS else head==b'#!'


def binary_identity(path,root=None):
    import hashlib
    import stat
    import tempfile
    path=Path(path).expanduser().resolve(strict=True)
    if not path.is_file() or not os.access(path,os.X_OK):raise Refused('Host binary is not executable')
    unsafe=[Path('/tmp').resolve(),Path('/private/var/folders'),Path('/var/tmp').resolve()]
    if WINDOWS:unsafe.append(Path(tempfile.gettempdir()).resolve())
    if root:unsafe.append(Path(root).resolve())
    if any(path.is_relative_to(p) for p in unsafe):raise Refused('Host binary must be installed outside temporary and project directories')
    if WINDOWS:
        # The same rule through Windows access lists: only you, the system or administrators may change the
        # program, add files next to it (a planted DLL), or replace a folder above it.
        from .system import untrusted
        for component,kind in [(path,'file'),(path.parent,'folder'),*((p,'above') for p in path.parent.parents)]:
            try:reason=untrusted(component,kind)
            except OSError as exc:raise Refused(f'OH cannot read who may change {component} ({exc}); install the host where you can read its permissions') from None
            if reason:raise Refused(f'Host executable path {component} {reason}; install it where only you or administrators can change it')
    for component in [] if WINDOWS else [path,*path.parents]:
        info=component.stat()
        if info.st_uid not in (0,os.getuid()) or info.st_mode & (stat.S_IWGRP|stat.S_IWOTH):
            raise Refused('Host executable has an untrusted owner or shared-writable path component: '+str(component))
    # Execute a native binary directly; a PATH-resolved script interpreter is not part of this trust record.
    with path.open('rb') as stream:
        if script(stream):raise Refused('Choose the installed native host binary, not a PATH-resolved wrapper')
        stream.seek(0);sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'path':str(path),'sha256':sha}


def locate(host,root=None):
    """Find the native binary behind the host command on PATH, outside the project."""
    import shutil
    search=subscription_env(root)['PATH'] if root else os.environ.get('PATH','')
    found=shutil.which(host,path=search)
    if not found:raise Refused(f'{host} was not found on PATH'+(' outside the project' if root else '')+
        f'. Install it, or name its native binary with: oh trust-host {host} <absolute-path>')
    path=Path(found).resolve()
    with path.open('rb') as stream:wrapper=script(stream)
    if wrapper and host=='codex':
        # npm installs a Node wrapper (on Windows, a .cmd shim beside node_modules); its native binary is vendored.
        package=path.parent/'node_modules/@openai/codex' if WINDOWS else path.parent.parent
        vendored=sorted(package.glob('node_modules/@openai/codex-*/vendor/*/bin/codex'+('.exe' if WINDOWS else '')))
        if len(vendored)==1:path=vendored[0].resolve()
    return path


def trust(host,path=None,root=None,*,pinned=None):
    """Record a host binary after the identity and version checks. A named path stays pinned."""
    from .storage import state_home
    if host not in ('codex','claude'):raise Refused('Unsupported host')
    identity=binary_identity(path or locate(host,root),root)
    probe=subprocess.run([identity['path'],'--version'],capture_output=True,text=True,timeout=10,env=subscription_env(root))
    if probe.returncode or ('codex-cli' if host=='codex' else 'Claude Code') not in probe.stdout:raise Refused('Unrecognized host version')
    record=identity|{'pinned':path is not None if pinned is None else pinned}
    atomic_json(state_home()/'hosts'/(host+'.json'),record)
    return record


def executable(host,root=None):
    """Resolve the host binary on every use. Host CLIs update themselves, so a changed binary is
    checked and recorded again automatically instead of waiting for a manual trust step."""
    from .storage import state_home,read_json
    import sys
    if host not in ('codex','claude'):raise Refused('Unsupported host')
    record=state_home()/'hosts'/(host+'.json')
    saved=read_json(record) if record.exists() else None
    pinned=bool(saved and saved.get('pinned'))
    legacy=bool(saved) and 'pinned' not in saved
    path=saved['path'] if pinned else None
    if not pinned:
        try:path=locate(host,root);binary_identity(path,root)
        except Refused:
            # A record from before automatic trust keeps working where PATH has no usable host.
            if not legacy:raise
            path=saved['path'];pinned=True
    try:same=saved and binary_identity(path,root)=={'path':saved['path'],'sha256':saved['sha256']}
    except FileNotFoundError:raise Refused(f'The {host} binary you pinned is gone: {path}. Run: oh trust-host {host}') from None
    if same:
        if legacy:atomic_json(record,saved|{'pinned':pinned})
        return saved['path']
    current=trust(host,path,root,pinned=pinned)
    if legacy and current['path']!=saved['path']:
        print(f'OH: {host} now follows your PATH: {current["path"]}. To keep using {saved["path"]}, '
              f'run: oh trust-host {host} {saved["path"]}',file=sys.stderr)
    elif saved:print(f'OH: {host} changed; now using {current["path"]}',file=sys.stderr)
    return current['path']


def subscription_env(root=None):
    # Do not read, copy, or print secrets. Force the installed first-party CLI's subscription path.
    forbidden={'OPENAI_API_KEY','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','OPENAI_BASE_URL',
      'ANTHROPIC_BASE_URL','CLAUDE_CODE_USE_BEDROCK','CLAUDE_CODE_USE_VERTEX','CLAUDE_CODE_USE_FOUNDRY',
      'CODEX_API_KEY','CODEX_ACCESS_TOKEN','NODE_OPTIONS','NODE_PATH','PYTHONPATH','PYTHONHOME','LD_PRELOAD','DYLD_INSERT_LIBRARIES','BASH_ENV','ENV'}
    env={k:v for k,v in os.environ.items() if k not in forbidden}
    project=Path(root or Path.cwd()).resolve()
    env['PATH']=os.pathsep.join(str(Path(p).resolve()) for p in env.get('PATH','').split(os.pathsep)
      if p and Path(p).is_absolute() and not Path(p).resolve().is_relative_to(project))
    return env


def authentication(host,root):
    binary=executable(host,root)
    command=[binary,'login','status'] if host=='codex' else [binary,'auth','status']
    result=subprocess.run(command,cwd=root,env=subscription_env(root),capture_output=True,text=True,timeout=20)
    if host=='codex':
        valid=result.returncode==0 and 'Logged in using ChatGPT' in result.stdout+result.stderr
    else:
        try:
            data=json.loads(result.stdout)
            valid=data.get('loggedIn') is True and data.get('authMethod')=='claude.ai' and data.get('apiProvider')=='firstParty'
        except ValueError:valid=False
    if not valid:
        raise Refused(f'{host}: subscription login could not be confirmed. Sign in with the installed CLI; no API fallback was attempted.')


def codex_home():
    """Codex's own folder: CODEX_HOME when set, as Codex itself reads it."""
    import os
    return Path(os.environ['CODEX_HOME']).expanduser() if os.environ.get('CODEX_HOME') else Path.home()/'.codex'


def oh_plugins():
    """OH's plugin as installed in Codex, under each marketplace that provides it."""
    import re
    import tomllib
    import os
    home=codex_home()
    try:plugins=tomllib.loads((home/'config.toml').read_text()).get('plugins',{})
    except (OSError,ValueError):return []
    return sorted(k for k in plugins if isinstance(k,str) and re.fullmatch(r'o-harness@[A-Za-z0-9_.-]+',k))


def command(host,profile,root,role,schema_path,artifact_dir=None,*,standalone=False,read_only_paths=(),verification_dir=None):
    if standalone and role!='analysis':raise Refused('Standalone execution is only for read-only insights analysis')
    if host=='codex':
        args=[executable(host,root),'exec','--json','--color','never','--model',profile['model'],
          '--config','features.multi_agent=false','--config','features.apps=false','--config','model_provider="openai"','--config','forced_login_method="chatgpt"',
          '--config',f'model_reasoning_effort="{profile["effort"]}"',
          '--cd',str(root)]
        if role=='implementation' and read_only_paths:
            from .storage import state_home
            from .config import protected_paths
            args+=['--strict-config',*codex_document_permissions([*read_only_paths,state_home(),*protected_paths()])]
        else:args+=['--sandbox','read-only' if role in READ_ONLY_ROLES else 'workspace-write']
        if standalone:args+=['--skip-git-repo-check']
        # Workers never load OH itself: its menu server would run outside their sandbox.
        for name in oh_plugins():args+=['--config',f'plugins."{name}".enabled=false']
        if verification_dir:
            from .storage import read_json
            server=verification_server(verification_dir)
            # Fixed commands and an argument-free tool; no arbitrary execution or state access.
            config=','.join(key+'='+json.dumps(value) for key,value in server.items() if key!='env')
            env=','.join(key+'='+json.dumps(value) for key,value in server['env'].items())
            timeout=read_json(Path(verification_dir)/'request.json').get('verification_timeout',60)
            operation='admission' if role=='review' else 'verify'
            args+=['--config','mcp_servers.oh_checks={'+config+',env={'+env+'},enabled_tools=["'+operation+'"],tool_timeout_sec='+str(timeout)+'}']
        if schema_path:args+=['--output-schema',str(schema_path)]
        return args+['-']
    from .storage import state_home
    from .storage import git
    git_paths=[] if standalone else [git(root,'rev-parse','--absolute-git-dir'),str(Path(root,git(root,'rev-parse','--git-common-dir')).resolve())]
    from .config import protected_paths
    protected=git_paths+[str(state_home()),*protected_paths(),str(Path.home()/'.codex'),str(codex_home()),str(Path.home()/'.claude'),str(Path(root)/'.oh')]
    if artifact_dir:protected.append(str(artifact_dir))
    if role in READ_ONLY_ROLES:protected.append(str(root))
    private=None if standalone else private_plans(root)
    if private:protected.append(str(private))  # workers read private plans; only OH writes them
    deny=['Agent','Task']+[f'{tool}({rule_path(p)}/**)' for p in protected for tool in ('Edit','Write')]
    documents=sorted({str(Path(p).resolve()) for p in read_only_paths})
    protected+=documents
    deny += [f'{tool}({rule_path(p)})' for p in documents for tool in ('Edit','Write')]
    if WINDOWS:
        # Claude Code's sandbox doesn't run on native Windows, so workers there get no shell at all: they read
        # and edit files. Their argument-free verify tool runs configured checks without granting a shell.
        settings={'sandbox':{'enabled':False},'permissions':{'deny':deny+['Bash','PowerShell']}}
        tools='Read,Glob,Grep' if role in READ_ONLY_ROLES else 'Read,Glob,Grep,Edit,Write'
    else:
        settings={'sandbox':{'enabled':True,'failIfUnavailable':True,'allowUnsandboxedCommands':False,'excludedCommands':[],
          'filesystem':{'disabled':False,'denyWrite':protected}},'permissions':{'deny':deny}}
        tools='Read,Glob,Grep,Bash' if role in READ_ONLY_ROLES else 'Read,Glob,Grep,Bash,Edit,Write'
    if verification_dir:settings['permissions']['allow']=['mcp__oh_checks__'+('admission' if role=='review' else 'verify')]
    args=[executable(host,root),'--settings',json.dumps(settings),'--tools',tools,'--print','--output-format','stream-json','--verbose',
          '--model',profile['model'],'--effort',profile['effort'],
          '--permission-mode','plan' if role in READ_ONLY_ROLES else 'acceptEdits',
          '--permission-prompts','none','--strict-mcp-config','--disable-slash-commands']
    if schema_path:args+=['--json-schema',schema_path.read_text()]
    # Every role reads OH's project inputs, admissions and repair feedback. The existing protected
    # paths still deny edits there: adding a readable directory never grants authority to change it.
    if artifact_dir:args+=['--add-dir',str(artifact_dir)]
    if private:args+=['--add-dir',str(private)]
    if verification_dir:args+=['--mcp-config',json.dumps({'mcpServers':{'oh_checks':verification_server(verification_dir)}})]
    return args


def verification_server(directory):
    import sys
    from .config import HOME
    from .storage import state_home
    return {'command':sys.executable,'args':['-I',str(HOME/'oh'),'worker-checks',str(directory)],
            'env':{'OH_DATA_HOME':str(state_home())}}


def codex_document_permissions(paths):
    """Invocation-local profile: keep the host's workspace protections, narrow only approved files."""
    entries=','.join(json.dumps(path)+'="read"' for path in sorted({str(Path(p).resolve()) for p in paths}))
    # CLI dotted-key parsing does not preserve quoted path segments. Put paths in
    # a TOML inline table so dots, spaces and Windows separators retain their meaning.
    return ['--config','default_permissions="oh-delivery"','--config',
            'permissions.oh-delivery={extends=":workspace",filesystem={'+entries+'}}']


def rule_path(path):
    """An absolute path the way Claude's permission rules write it: //c/Users/me for C:\\Users\\me, //Users/me on POSIX."""
    path=str(path)
    if len(path)>2 and path[1]==':' and path[2] in '\\/':return '//'+path[0].lower()+path[2:].replace('\\','/')
    return '/'+path


def private_plans(root):
    """This project's private plans folder, or None when its plans live in the repository or aren't chosen yet."""
    from .plans import layout
    try:where=layout(root)
    except Refused:return None
    return where['base'] if where['location']=='private' else None


def parse_usage(host,event,attempt):
    if host=='codex' and event.get('type')=='turn.completed':
        u=event.get('usage') or {}
        return [{'response_id':attempt+':'+str(event.get('turn_id','final')),
          'input':u.get('input_tokens'),'cached':u.get('cached_input_tokens'),
          'output':u.get('output_tokens'),'reasoning':u.get('reasoning_output_tokens'),
          'source':'codex.turn.completed'}]
    if host=='claude' and event.get('type')=='result':
        result=[]
        # modelUsage is the aggregate for this fresh CLI conversation, including cache fields.
        # Do not also add per-message usage or forwarded child messages.
        for model,u in (event.get('modelUsage') or {}).items():
            parts=[u.get('inputTokens'),u.get('cacheReadInputTokens'),u.get('cacheCreationInputTokens')]
            total=sum(parts) if all(type(x) is int for x in parts) else None
            result.append({'response_id':attempt+':'+model,'model':model,'input':total,
              'cached':u.get('cacheReadInputTokens'),'output':u.get('outputTokens'),
              'reasoning':None,'source':'claude.result.modelUsage'})
        return result
    return []


def public_message(host,event):
    """Only public assistant text, never reasoning, tool output or a structured final report."""
    if host=='codex' and event.get('type')=='item.completed':
        item=event.get('item',{})
        text=item.get('text') if item.get('type')=='agent_message' else None
    elif host=='claude' and event.get('type')=='assistant':
        text=' '.join(part.get('text','') for part in event.get('message',{}).get('content',[])
                      if part.get('type')=='text')
    else:return None
    if not isinstance(text,str) or not text.strip():return None
    try:json.loads(text)
    except ValueError:return ' '.join(text.split())[:600]
    return None


def worker_focus(host,event,directory,previous=None):
    """A bounded latest public update for status; informational, never execution authority."""
    message=public_message(host,event)
    if not message or previous and message==previous['message']:return previous
    from .storage import digest
    focus={'message':message,'id':digest(message),'updated_at':datetime.now(timezone.utc).isoformat()}
    try:atomic_json(Path(directory)/'focus.json',focus)
    except OSError:pass  # a visibility failure cannot interrupt implementation or review
    return focus


def invoke(host,root,profile,prompt,role,attempt_dir,context,*,schema=None,timeout=None):
    authentication(host,root)
    from .capabilities import validate_profile
    validate_profile(host,profile,root)
    attempt_dir=Path(attempt_dir);attempt_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    schema_path=None
    if schema:
        schema_path=attempt_dir/'output-schema.json';atomic_json(schema_path,schema,immutable=True)
    from .storage import state_home
    artifact_dir=(state_home()/'projects'/context['project'] if not context.get('standalone')
                  else attempt_dir.parent.parent)
    args=command(host,profile,root,role,schema_path,artifact_dir,
                 standalone=context.get('standalone',False),read_only_paths=context.get('read_only_paths',()),
                 verification_dir=attempt_dir if role in ('implementation','review') else None)
    started=time.monotonic();final='';usage_seen=False;structured=None;failed=False;focus=None
    reported=set();last_progress=started
    with (attempt_dir/'stream.jsonl').open('xb') as raw,(attempt_dir/'stderr.log').open('xb') as error:
        from .processes import launch
        controlled=context.get('controlled',False)
        from contextlib import nullcontext
        from .worker_checks import service
        with service(attempt_dir) if role in ('implementation','review') else nullcontext():
            with launch(root,args,controlled=controlled,timeout=timeout,interrupt=True,cwd=root,
                        env=subscription_env(root)|{'OH_CHILD_ATTEMPT':context['attempt']},
                        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=error) as (child,cancelled,reason):
                try:
                    child.stdin.write(prompt.encode());child.stdin.close()
                except BrokenPipeError:
                    failed=True
                turn=0
                for line in child.stdout:
                    raw.write(line)
                    try:event=json.loads(line)
                    except ValueError:continue
                    focus=worker_focus(host,event,attempt_dir,focus)
                    now=time.monotonic()
                    if focus and focus['id'] not in reported and now-last_progress>=210:
                        import sys
                        label='independent reviewer' if role=='review' else 'implementation' if role=='implementation' else 'assessment' if role=='assessment' else 'planning'
                        print(f"The {label} agent: {focus['message']}",file=sys.stderr,flush=True)
                        reported.add(focus['id']);last_progress=now
                    if event.get('type')=='turn.completed':turn+=1;event['turn_id']=event.get('turn_id',str(turn))
                    for usage in parse_usage(host,event,context['attempt']):
                        usage_seen=True
                        best_effort('usage',context['project'],context['run'],context.get('task'),context['attempt'],**usage)
                    if event.get('type')=='item.completed':
                        item=event.get('item',{})
                        if item.get('type')=='agent_message':final=item.get('text','')
                    if event.get('type')=='result':
                        final=event.get('result','');structured=event.get('structured_output')
                        failed=bool(event.get('is_error'))
                    if event.get('type') in ('turn.failed','error'):failed=True
                raw.flush();os.fsync(raw.fileno())
            status=child.returncode
    if schema and structured is None:
        try:structured=json.loads(final)
        except ValueError:pass
    return {'returncode':status,'text':final,'structured':structured,'usage_observed':usage_seen,
            'duration_ms':round((time.monotonic()-started)*1000),'failed':failed or status!=0 or cancelled.is_set(),'cancellation':reason}


def failure_text(result):
    reasons=result.get('cancellation',[])
    reason=('Worker stopped by request.' if 'stopped' in reasons else
            'Worker reached its execution timeout.' if 'timeout' in reasons else
            f"Worker failed (exit status {result.get('returncode', 'unknown')}).")
    return reason+('\nLast worker output:\n'+result['text'] if result.get('text') else '')


def work_result(result):
    """Host success means the report arrived, not that the assigned implementation finished."""
    if result['failed']:return 'failed',failure_text(result)
    value=result.get('structured')
    if (not isinstance(value,dict) or set(value)!=set(WORK_SCHEMA['required']) or
            value.get('status') not in ('completed','unfinished','blocked') or
            not isinstance(value.get('summary'),str) or not value['summary'].strip() or
            not isinstance(value.get('found_along_way'),list) or
            any(not isinstance(note,str) for note in value['found_along_way'])):
        return 'unfinished','The implementation report needs status, summary, found_along_way, obstacle and readiness. Preserve the implementation and finish the handoff.'
    obstacle=value['obstacle']
    if obstacle is not None and (not isinstance(obstacle,dict) or set(obstacle)!= {'kind','evidence','next_step'} or
            obstacle.get('kind') not in ('missing_authority','external_dependency') or
            any(not isinstance(obstacle.get(k),str) or not obstacle[k].strip() for k in ('evidence','next_step'))):
        return 'unfinished','An obstacle needs its kind, concrete evidence and the external action or authority needed. Otherwise continue the approved work.'
    if value['status']=='blocked' and obstacle:
        return 'blocked','Obstacle: '+obstacle['evidence']+'\nNext: '+obstacle['next_step']+'\n\n'+value['summary']
    if value['status']!='completed' or obstacle:
        return 'unfinished',value['summary']
    from .handoff import validate_readiness
    if problem:=validate_readiness(value['readiness']):
        return 'unfinished',value['summary']+'\nFinish self-review before requesting independent review: '+problem
    return 'implemented',value['summary']


def assessment_result(result):
    if result['failed']:return 'failed',failure_text(result)
    value=result.get('structured')
    if (not isinstance(value,dict) or set(value)!=set(ASSESSMENT_SCHEMA['required']) or
            value.get('difficulty') not in ('simple','standard','complex') or
            not isinstance(value.get('rationale'),str) or not value['rationale'].strip() or
            any(not isinstance(value.get(k),list) or any(not isinstance(x,str) or not x.strip() for x in value[k])
                for k in ('references','uncertainty')) or not value['references']):
        return 'unfinished','Difficulty assessment needs a level, scope-based rationale, examined references and remaining uncertainty.'
    return 'assessed',value['rationale']


def review_result(result):
    value=result.get('structured')
    if result['failed'] or not isinstance(value,dict) or set(value)!={'verdict','summary','findings','evidence'}:
        return 'failed',[]
    evidence=value['evidence']
    if not isinstance(evidence,dict) or set(evidence)!={'anchors','attacks','limits','lenses'}:return 'failed',[]
    if any(not isinstance(evidence[k],list) or any(not isinstance(x,str) or not x.strip() for x in evidence[k]) for k in ('anchors','attacks','limits')):return 'failed',[]
    if not evidence['anchors'] or not evidence['attacks']:return 'failed',[]
    if not isinstance(evidence['lenses'],dict) or set(evidence['lenses'])!=set(LENSES) or any(not isinstance(v,str) or not v.strip() for v in evidence['lenses'].values()):return 'failed',[]
    findings=value['findings']
    if value['verdict'] not in REVIEW_SCHEMA['properties']['verdict']['enum']:return 'failed',[]
    if not isinstance(findings,list) or not isinstance(value['summary'],str):return 'failed',[]
    shape=REVIEW_SCHEMA['properties']['findings']['items']
    if any(not isinstance(f,dict) or set(f) not in (set(shape['required']),set(shape['required'])-{'anchor','failure','fix'})
           or any(not isinstance(v,str) for v in f.values())
           or f['severity'] not in shape['properties']['severity']['enum']
           or f['relation'] not in shape['properties']['relation']['enum'] for f in findings):
        return 'failed',[]
    if value['verdict']=='clean' and not findings:return 'clean',[]
    # Never trust a declared clean count over visible findings.
    if any(f['severity']=='blocking' for f in findings):return 'blocking',findings
    if findings:return 'needs_resolution',findings
    return 'failed',[]
