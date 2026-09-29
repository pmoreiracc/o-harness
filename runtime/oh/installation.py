"""Explicit, local plugin packaging and shared-core installation. No consumer writes."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from .config import HOME, version
from .storage import Refused, atomic_json, lock, read_json, state_home
from .system import replace


# The launcher finds Python through these: python.sh from sh and Git Bash, oh.cmd from PowerShell and cmd,
# and get-python.ps1 fetches the official Python on Windows during setup when none is installed.
HELPERS=('python.sh','python.cmd','oh.cmd','hook.cmd','get-python.ps1')
LAUNCHERS=(b'#!/usr/bin/env -S python3 -I\n"""Resolve bundled setup',b'#!/bin/sh\n""":"\nself=$0\n')


def inventory(root):
    files={}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():raise Refused('Package resources must not be symlinks')
        if path.is_file() and path!=root/'package.json':
            files[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def build(destination, host):
    if host not in ('codex','claude'):raise Refused('Unsupported plugin host')
    destination=Path(destination).expanduser().resolve()
    if destination.name!='o-harness':raise Refused('The plugin directory must be named o-harness')
    if destination.exists() or destination.is_relative_to(HOME):
        raise Refused('Build into a new directory outside the OH source checkout')
    source=HOME/'plugins/o-harness'
    revision=version()
    shutil.copytree(source,destination)
    core=destination/'core';core.mkdir()
    shutil.copy2(HOME/'oh',core/'oh')
    shutil.copy2(source/'scripts/oh',core/'launcher')
    for helper in HELPERS:shutil.copy2(source/'scripts'/helper,core/helper)
    for directory in ('runtime','config','prompts','workflows','dashboard'):
        shutil.copytree(HOME/directory,core/directory,ignore=shutil.ignore_patterns('__pycache__','test_*.py'))
    atomic_json(core/'revision.json',{'revision':revision,'version':read_json(source/'.claude-plugin/plugin.json')['version']})
    atomic_json(core/'package.json',{'schema_version':1,'revision':revision,'files':inventory(core)})
    hooks=read_json(destination/'hooks/hooks.json')
    for group in hooks['hooks']['UserPromptSubmit']:
        for hook in group['hooks']:
            hook['command']=hook['command'].rsplit(' ',1)[0]+' '+host
            # Codex's default Windows runner supplies cmd /C and its outer quote pair.
            # Keep the quoted executable first, avoiding a redundant nested shell.
            if host=='codex':hook['commandWindows']='"%PLUGIN_ROOT%\\scripts\\hook.cmd" codex'
    menus=destination/'codex-mcp.json'
    if host=='codex':
        # Codex shows OH menus through OH's MCP server; Claude asks with its own question tool and hooks.
        for event in ('PreToolUse','PostToolUse'):hooks['hooks'].pop(event,None)
        menus.replace(destination/'.mcp.json')
        manifest=read_json(destination/'.codex-plugin/plugin.json')
        atomic_json(destination/'.codex-plugin/plugin.json',manifest|{'mcpServers':'./.mcp.json'})
    else:menus.unlink()
    atomic_json(destination/'hooks/hooks.json',hooks)
    if host=='codex':
        for path in (destination/'skills').glob('*/SKILL.md'):
            path.write_text(path.read_text().replace('disable-model-invocation: true\n',''))
    return {'plugin':str(destination),'host':host,'revision':revision}


def refresh_python(core):
    """On Windows, move a Python that OH fetched earlier to the version this release pins (best effort)."""
    from .system import WINDOWS
    if not WINDOWS or not (state_home()/'python'/'current').is_file():return {}
    import os,subprocess
    powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    done=subprocess.run([str(powershell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(core/'get-python.ps1'),'-Refresh'],
                        capture_output=True,text=True,env=os.environ|{'OH_DATA_HOME':str(state_home())})
    return {} if done.returncode==0 else {'python':'Could not update the Python OH fetched: '+done.stderr.strip()[-500:]}


def verify_package(root):
    manifest=read_json(root/'package.json')
    revision=manifest.get('revision')
    if manifest.get('schema_version')!=1 or not isinstance(revision,str) or Path(revision).name!=revision:
        raise Refused('Invalid packaged core revision')
    if inventory(root)!=manifest.get('files'):
        raise Refused('Packaged core changed or is incomplete; rebuild/reinstall before setup')
    return revision


def version_key(value):
    try:return tuple(int(part) for part in str(value).split('.'))
    except ValueError:return ()


def setup(*, development=False, if_newer=False):
    revision=verify_package(HOME)
    if '+worktree.' in revision and not development:
        raise Refused('This is an unreviewed development build. Use setup --development only for an explicit local test; install a reviewed revision for normal work.')
    home=state_home();destination=home/'versions'/revision
    version=read_json(HOME/'revision.json').get('version')
    with lock(home/'runtime/install.lock'):
        active=home/'runtime/active.json'
        # Automatic activation re-checks under the lock, so concurrent hosts never downgrade.
        if if_newer and active.exists() and version_key(version)<=version_key(read_json(active).get('version')):
            return {'revision':read_json(active)['revision'],'activated':False}
        if destination.exists():
            if destination.is_symlink() or verify_package(destination)!=revision:
                raise Refused('Existing shared core is inconsistent; preserve it and reinstall into a clean version directory')
        else:
            destination.parent.mkdir(parents=True,exist_ok=True)
            staging=Path(tempfile.mkdtemp(prefix='.install-',dir=destination.parent))
            try:
                shutil.copytree(HOME,staging,dirs_exist_ok=True)
                verify_package(staging)
                staging.rename(destination)
            finally:
                if staging.exists():shutil.rmtree(staging)
        launcher=home/'bin/oh';launcher.parent.mkdir(parents=True,exist_ok=True)
        content=(destination/'launcher').read_bytes()
        if launcher.exists() and not launcher.read_bytes().startswith(LAUNCHERS):
            raise Refused('Existing OH CLI conflicts with setup; preserve it and select a clean OH data home')
        # Helpers first: a new launcher must never run without the python.sh it calls.
        for name,data in [*((h,(destination/h).read_bytes()) for h in HELPERS),('oh',content)]:
            target=launcher.parent/name;temporary=target.with_name(name+'.pending')
            temporary.write_bytes(data);temporary.chmod(0o755);replace(temporary,target)
        atomic_json(active,{'revision':revision,'version':version,'schema_version':1})
    refreshed=refresh_python(destination)
    return refreshed|{'core':str(destination),'revision':revision,'cli':str(home/'bin/oh'),'next':'Register the project with oh init, then configure its external checks. Existing runs keep their recorded runtime.'}
