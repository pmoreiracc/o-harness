from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
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


def removed(path):
    """Whether a path really no longer exists; an unreadable one is not reported as removed."""
    try:return not path.exists()
    except OSError:return False


def binary_identity(path,root=None,*,removable=False):
    """`removable`: the Windows Codex app may remove this copy while it is checked; a removal is then
    raised as FileNotFoundError, which callers report as a retry."""
    import hashlib
    import stat
    import tempfile
    path=Path(path).expanduser().resolve(strict=True)
    if not path.is_file() or not os.access(path,os.X_OK):
        if removable and removed(path):raise FileNotFoundError(2,'Host binary was removed',str(path))
        raise Refused('Host binary is not executable')
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
            except OSError as exc:
                if removable and isinstance(exc,FileNotFoundError) and removed(component):raise
                raise Refused(f'OH cannot read who may change {component} ({exc}); install the host where you can read its permissions') from None
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


# The Windows Codex app cannot run its CLI from its package, so it copies these files to a per-user folder
# named by their content hash. Each app update copies a new folder and removes the others it can.
CODEX_APP_FILES=('codex.exe','codex-code-mode-host.exe','codex-windows-sandbox-setup.exe','codex-command-runner.exe')
CODEX_PACKAGES=r'Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages'


def codex_app_bin():
    return Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData'/'Local')/'OpenAI'/'Codex'/'bin'


def codex_app_folder(resources):
    """The folder name the Codex app gives the copy of these package resources."""
    stamps=tuple((info.st_size,info.st_mtime_ns) for info in ((resources/name).stat() for name in CODEX_APP_FILES))
    return _codex_app_folder(str(resources),stamps)


@lru_cache(maxsize=4)
def _codex_app_folder(resources,stamps):
    # Hashing the package (hundreds of MB) once per version keeps repeated lookups cheap.
    import hashlib
    whole=hashlib.sha256()
    for name in CODEX_APP_FILES:
        with (Path(resources)/name).open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        whole.update(name.encode()+b'\0'+digest.encode()+b'\0')
    return whole.hexdigest()[:16]


def codex_package():
    """The resources of the one OpenAI-published Codex app package registered for this user, if any."""
    import itertools
    import winreg
    roots=[]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,CODEX_PACKAGES) as packages:
            for index in itertools.count():
                try:name=winreg.EnumKey(packages,index)
                except OSError:break
                if name.startswith('OpenAI.Codex_') and name.endswith('__2p2nqsd0c76g0'):
                    with winreg.OpenKey(packages,name) as package:roots.append(Path(winreg.QueryValueEx(package,'PackageRootFolder')[0]))
    except OSError:return None
    if len(roots)!=1:return None
    # Windows installs packages in Program Files\WindowsApps, or in <volume>\WindowsApps on another drive.
    programs=os.environ.get('ProgramW6432') or os.environ.get('ProgramFiles') or r'C:\Program Files'
    stores=(Path(programs)/'WindowsApps',Path(roots[0].anchor)/'WindowsApps')
    return roots[0]/'app'/'resources' if any(roots[0].parent==store for store in stores) else None


class Undecided(Refused):
    """The Codex app left several CLI copies and OH cannot tell which is current."""


def codex_app():
    """The CLI copy the Codex app made for this user, or None."""
    import re
    try:copies=sorted(d/'codex.exe' for d in codex_app_bin().iterdir() if re.fullmatch('[0-9a-f]{16}',d.name) and (d/'codex.exe').is_file())
    except OSError:return None
    if len(copies)<2:return copies[0] if copies else None
    # A copy still running survives the app's cleanup; the registered package names the current one.
    try:current=(resources:=codex_package()) and codex_app_folder(resources)
    except OSError:current=None
    found=next((copy for copy in copies if copy.parent.name==current),None)
    if not found:raise Undecided(f'The Codex app left several command-line copies in {codex_app_bin()} and its registered '
        'package does not name the current one. Close running Codex sessions, reopen the Codex app and retry, '
        'or name its native binary with: oh trust-host codex <absolute-path>.')
    return found


def in_codex_app(path):
    """Whether a path is one of the Windows Codex app's replaceable CLI copies."""
    if not WINDOWS:return False
    # Recorded paths are resolved, so a profile behind a junction or redirect is compared resolved too.
    bin_dir=codex_app_bin()
    return any(Path(path).resolve().is_relative_to(folder) for folder in (bin_dir,bin_dir.resolve()))


class NotFound(Refused):
    """No usable host binary was found, or a pinned one is gone."""


class Vanished(Refused):
    """A found binary was removed before it could be used."""


def vanished(host,path):
    return Vanished(f'{path} was removed while {host} updated itself. Retry the command.')


def replaceable(host):
    """Whether the host's binary can be removed under OH by its own app: only the Windows Codex app."""
    return WINDOWS and host=='codex'


def installed(host):
    """A host binary its own installer placed outside PATH: the Codex app's CLI on Windows."""
    if host!='codex' or not WINDOWS:return None
    named=os.environ.get('CODEX_CLI_PATH','').strip()
    return Path(named) if named and Path(named).is_absolute() and Path(named).is_file() else codex_app()


def locate(host,root=None):
    """Find the native binary behind the host command on PATH, outside the project, or its app's own copy."""
    import shutil
    search=subscription_env(root)['PATH'] if root else os.environ.get('PATH','')
    found=shutil.which(host,path=search) or installed(host)
    if not found:raise NotFound(f'{host} was not found on PATH'+(' outside the project' if root else '')+
        ('. Install it or open the Codex app once so it installs its command-line binary' if host=='codex' and WINDOWS else '. Install it')+
        f', or name its native binary with: oh trust-host {host} <absolute-path>')
    path=Path(found).resolve()
    try:
        with path.open('rb') as stream:wrapper=script(stream)
    except FileNotFoundError:
        if not replaceable(host):raise
        raise vanished(host,path) from None
    if wrapper and host=='codex':
        # npm installs a Node wrapper (on Windows, a .cmd shim beside node_modules); its native binary is vendored.
        package=path.parent/'node_modules/@openai/codex' if WINDOWS else path.parent.parent
        vendored=sorted(package.glob('node_modules/@openai/codex-*/vendor/*/bin/codex'+('.exe' if WINDOWS else '')))
        if len(vendored)==1:path=vendored[0].resolve()
    return path


def trust(host,path=None,root=None,*,pinned=None,removable=None):
    """Record a host binary after the identity and version checks. A named path stays pinned.
    A binary OH found itself (`removable`, by default when no path is named) can be removed by the
    Windows Codex app before it is checked; that is reported as a retry."""
    from .storage import state_home
    if host not in ('codex','claude'):raise Refused('Unsupported host')
    removable=replaceable(host) and (path is None if removable is None else removable)
    try:
        identity=binary_identity(found:=path or locate(host,root),root,removable=removable)
        probe=subprocess.run([identity['path'],'--version'],capture_output=True,text=True,timeout=10,env=subscription_env(root))
    except FileNotFoundError:
        if not removable:raise
        raise vanished(host,found) from None
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
        try:path=locate(host,root);binary_identity(path,root,removable=replaceable(host))
        except FileNotFoundError:
            # On Windows the Codex app can remove a found copy between lookup and use.
            if not replaceable(host):raise
            raise vanished(host,path) from None
        except Refused:
            # A record from before automatic trust keeps working where PATH has no usable host.
            # A Windows Codex app copy is replaced on update, so it is kept unpinned and only while it exists.
            # A removed Windows Codex record keeps the lookup's own reason instead of a pinned-gone message.
            if not legacy:raise
            app=in_codex_app(saved['path'])
            if (app or replaceable(host)) and not Path(saved['path']).is_file():raise
            path=saved['path'];pinned=not app
    racing=replaceable(host) and not pinned
    try:same=saved and binary_identity(path,root,removable=racing)=={'path':saved['path'],'sha256':saved['sha256']}
    except FileNotFoundError:
        if racing:raise vanished(host,path) from None
        raise NotFound(f'The {host} binary you pinned is gone: {path}. Run: oh trust-host {host}') from None
    if same:
        if legacy:atomic_json(record,saved|{'pinned':pinned})
        return saved['path']
    try:current=trust(host,path,root,pinned=pinned,removable=racing)
    except FileNotFoundError:
        if not racing:raise
        raise vanished(host,path) from None
    if legacy and current['path']!=saved['path']:
        # Do not offer to pin a removed binary or a Codex app copy the app will replace.
        if replaceable(host) and (not Path(saved['path']).is_file() or in_codex_app(saved['path'])):
            print(f'OH: {host} now uses {current["path"]}.',file=sys.stderr)
        else:print(f'OH: {host} now follows your PATH: {current["path"]}. To keep using {saved["path"]}, '
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
    # Native children inherit this host environment; do not mask API authentication for the probe.
    result=subprocess.run(command,cwd=root,env=os.environ.copy(),capture_output=True,text=True,timeout=20)
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
        return 'report_invalid','The implementation report needs status, summary, found_along_way, obstacle and readiness. Preserve the implementation and finish the handoff.'
    obstacle=value['obstacle']
    if obstacle is not None and (not isinstance(obstacle,dict) or set(obstacle)!= {'kind','evidence','next_step'} or
            obstacle.get('kind') not in ('missing_authority','external_dependency') or
            any(not isinstance(obstacle.get(k),str) or not obstacle[k].strip() for k in ('evidence','next_step'))):
        return 'report_invalid','An obstacle needs its kind, concrete evidence and the external action or authority needed. Otherwise continue the approved work.'
    if value['status']=='blocked' and obstacle:
        return 'blocked','Obstacle: '+obstacle['evidence']+'\nNext: '+obstacle['next_step']+'\n\n'+value['summary']
    if value['status']!='completed' or obstacle:
        return 'unfinished',value['summary']
    from .handoff import validate_readiness
    if problem:=validate_readiness(value['readiness']):
        return 'report_invalid',value['summary']+'\nCorrect the implementation report: '+problem
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


def review_details(result):
    """Keep findings independently of presentation; only complete evidence can authorize clean."""
    value=result.get('structured');issues=[];fragments=[];findings=[];positions=[]
    if not isinstance(value,dict):
        import re
        fragments=[{'line':n,'value':line,'problem':'Unstructured finding; inspect the original report.'}
                   for n,line in enumerate(result.get('text','').splitlines(),1)
                   if re.search(r'\b(BLOCKING|CONCERN|SCOPE)\b',line,re.IGNORECASE)]
        return {'outcome':'failed' if result.get('failed') else 'review_incomplete','findings':[],
                'positions':[], 'fragments':fragments, 'issues':['No structured review report was retained.']}
    items=value.get('findings')
    if not isinstance(items,list):
        issues.append('Review findings must be a list, including [] for no findings.')
        if items is not None:fragments.append({'number':0,'value':items,'problem':'Unclassified findings field.'})
        items=[]
    shape=REVIEW_SCHEMA['properties']['findings']['items']['properties']
    for number,item in enumerate(items,1):
        if not isinstance(item,dict) or item.get('severity') not in shape['severity']['enum']:
            fragments.append({'number':number,'value':item,'problem':'Finding severity is missing or unknown.'})
            continue
        finding={key:item[key] for key in shape if isinstance(item.get(key),str)}
        for key in ('severity','description','path','family','relation'):finding.setdefault(key,'')
        if finding['relation'] not in shape['relation']['enum']:finding['relation']=''
        findings.append(finding);positions.append(number)
        if not finding['description'].strip():
            fragments.append({'number':number,'value':item,'problem':'Finding claim is missing.'})
    if fragments:issues.append('Clarify incomplete findings: '+', '.join(str(f['number']) for f in fragments)+'.')
    evidence=value.get('evidence')
    if not isinstance(evidence,dict):issues.append('Review evidence is missing.')
    else:
        for key in ('anchors','attacks','limits'):
            items=evidence.get(key)
            if (not isinstance(items,list) or any(not isinstance(x,str) or not x.strip() for x in items)
                    or key!='limits' and not items):issues.append('Complete review evidence.'+key+'.')
        lenses=evidence.get('lenses')
        missing=[lens for lens in LENSES if not isinstance(lenses,dict) or not isinstance(lenses.get(lens),str) or not lenses[lens].strip()]
        if missing:issues.append('Complete review lenses: '+', '.join(missing)+'.')
    if not isinstance(value.get('summary'),str) or not value['summary'].strip():issues.append('Provide a review summary.')
    if value.get('verdict') not in REVIEW_SCHEMA['properties']['verdict']['enum']:issues.append('Provide an explicit review verdict.')
    if result.get('failed'):outcome='failed'
    elif any(f['severity']=='blocking' and f['description'].strip() for f in findings):outcome='blocking'
    elif issues:outcome='review_incomplete'
    elif findings:outcome='needs_resolution'
    elif value.get('verdict')=='clean':outcome='clean'
    else:
        outcome='review_incomplete';issues.append('A non-clean verdict needs its findings; absence of findings is not a clean verdict.')
    return {'outcome':outcome,'findings':findings,'positions':positions,'fragments':fragments,'issues':issues}


def review_result(result):
    parsed=review_details(result)
    return parsed['outcome'],parsed['findings']


def invoke(*args, **kwargs):
    raise Refused('OH no longer launches host subprocesses. Use a fresh native host agent.')
