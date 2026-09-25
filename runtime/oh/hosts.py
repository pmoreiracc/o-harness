from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from .storage import Refused, atomic_json, identifier
from .telemetry import best_effort

LENSES=('task-and-design','invariants-and-decisions','affected-surfaces-and-negative-space',
 'correctness-and-failure-paths','security-authorization-and-concurrency',
 'tests-claims-docs-and-generated-artifacts','prior-findings-and-family-closure')
STRINGS={'type':'array','items':{'type':'string'}}
REVIEW_SCHEMA={'type':'object','additionalProperties':False,
 'required':['verdict','summary','findings','evidence'],'properties':{
 'verdict':{'type':'string','enum':['clean','blocking','concern','scope']},'summary':{'type':'string'},
 'findings':{'type':'array','items':{'type':'object','additionalProperties':False,
   'required':['severity','description','path','family','relation'],'properties':{
     'severity':{'type':'string','enum':['blocking','concern','scope']},'description':{'type':'string'},'path':{'type':'string'},'family':{'type':'string'},'relation':{'type':'string','enum':['original','repeat-family','fix-regression','first-round-escape','newly-exposed','scope']}}}},
 'evidence':{'type':'object','additionalProperties':False,'required':['anchors','lenses','attacks','limits'],
   'properties':{'anchors':STRINGS,'attacks':STRINGS,'limits':STRINGS,
     'lenses':{'type':'object','additionalProperties':False,'required':list(LENSES),
       'properties':{lens:{'type':'string'} for lens in LENSES}}}}}}


def binary_identity(path,root=None):
    import hashlib
    import stat
    path=Path(path).expanduser().resolve(strict=True)
    if not path.is_file() or not os.access(path,os.X_OK):raise Refused('Host binary is not executable')
    unsafe=[Path('/tmp').resolve(),Path('/private/var/folders'),Path('/var/tmp').resolve()]
    if root:unsafe.append(Path(root).resolve())
    if any(path.is_relative_to(p) for p in unsafe):raise Refused('Host binary must be installed outside temporary and project directories')
    for component in [path,*path.parents]:
        info=component.stat()
        if info.st_uid not in (0,os.getuid()) or info.st_mode & (stat.S_IWGRP|stat.S_IWOTH):
            raise Refused('Host executable has an untrusted owner or shared-writable path component: '+str(component))
    # Execute a native binary directly; a PATH-resolved script interpreter is not part of this trust record.
    with path.open('rb') as stream:
        if stream.read(2)==b'#!':raise Refused('Choose the installed native host binary, not a PATH-resolved wrapper')
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
    with path.open('rb') as stream:script=stream.read(2)==b'#!'
    if script and host=='codex':
        # npm installs a Node wrapper; its native binary is vendored beside it.
        vendored=sorted(path.parent.parent.glob('node_modules/@openai/codex-*/vendor/*/bin/codex'))
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
    path=saved['path'] if pinned else locate(host,root)
    try:same=saved and binary_identity(path,root)=={'path':saved['path'],'sha256':saved['sha256']}
    except FileNotFoundError:raise Refused(f'The {host} binary you pinned is gone: {path}. Run: oh trust-host {host}') from None
    if same:return saved['path']
    current=trust(host,path,root,pinned=pinned)
    if saved:print(f'OH: {host} changed; now using {current["path"]}',file=sys.stderr)
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


def command(host,profile,root,role,schema_path,compact_tokens):
    if host=='codex':
        args=[executable(host,root),'exec','--json','--color','never','--model',profile['model'],
          '--config','features.multi_agent=false','--config','model_provider="openai"','--config','forced_login_method="chatgpt"',
          '--config',f'model_reasoning_effort="{profile["effort"]}"',
          '--config',f'model_auto_compact_token_limit={compact_tokens}',
          '--sandbox','read-only' if role in ('review','analysis') else 'workspace-write',
          '--cd',str(root)]
        if schema_path:args+=['--output-schema',str(schema_path)]
        return args+['-']
    from .storage import state_home
    from .storage import git
    git_paths=[git(root,'rev-parse','--absolute-git-dir'),str(Path(root,git(root,'rev-parse','--git-common-dir')).resolve())]
    protected=git_paths+[str(state_home()),str(Path.home()/'.codex'),str(Path.home()/'.claude'),str(Path(root)/'.oh')]
    if role in ('review','analysis'):protected.append(str(root))
    settings={'sandbox':{'enabled':True,'failIfUnavailable':True,'allowUnsandboxedCommands':False,'excludedCommands':[],
      'filesystem':{'disabled':False,'denyWrite':protected}},'permissions':{'deny':['Agent','Task']+[f'Edit(/{p}/**)' for p in protected]}}
    args=[executable(host,root),'--settings',json.dumps(settings),'--tools','Read,Glob,Grep,Bash' if role in ('review','analysis') else 'Read,Glob,Grep,Bash,Edit,Write','--print','--output-format','stream-json','--verbose',
          '--model',profile['model'],'--effort',profile['effort'],
          '--permission-mode','plan' if role in ('review','analysis') else 'acceptEdits',
          '--permission-prompts','none']
    if schema_path:args+=['--json-schema',schema_path.read_text()]
    return args


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


def invoke(host,root,profile,prompt,role,attempt_dir,context,*,schema=None,timeout=1800):
    authentication(host,root)
    from .capabilities import validate_profile
    validate_profile(host,profile)
    attempt_dir=Path(attempt_dir);attempt_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    schema_path=None
    if schema:
        schema_path=attempt_dir/'output-schema.json';atomic_json(schema_path,schema,immutable=True)
    args=command(host,profile,root,role,schema_path,context['compact_tokens'])
    started=time.monotonic();final='';usage_seen=False;structured=None;failed=False
    with (attempt_dir/'stream.jsonl').open('xb') as raw,(attempt_dir/'stderr.log').open('xb') as error:
        from .processes import launch
        controlled=context.get('controlled',False)
        with launch(root,args,controlled=controlled,timeout=timeout,cwd=root,
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
    if not isinstance(findings,list) or not isinstance(value['summary'],str):return 'failed',[]
    if any(not isinstance(f,dict) or f.get('severity') not in ('blocking','concern','scope')
           or not isinstance(f.get('description'),str) or not isinstance(f.get('path'),str) for f in findings):
        return 'failed',[]
    if value['verdict']=='clean' and not findings:return 'clean',[]
    # Never trust a declared clean count over visible findings.
    if any(f['severity']=='blocking' for f in findings):return 'blocking',findings
    if findings:return 'needs_resolution',findings
    return 'failed',[]
