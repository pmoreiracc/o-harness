from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time
from .storage import Refused, atomic_json, digest, git, read_json, state_home, whole, worktrees
from .system import uname


def tree(root, paths=None):
    root = Path(root)
    if paths and any(p in ('.','./') for p in paths):paths=None
    flags = git(root, 'ls-files', '-v').splitlines()
    if any(line and (line[0].islower() or line[0] == 'S') for line in flags):
        raise Refused('Clear assume-unchanged/skip-worktree flags before verification')
    inventory = subprocess.check_output(['git','-C',str(root),'ls-files','-z','--cached','--others','--exclude-standard'],env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')})
    # Git lists an untracked nested repository as its folder with a trailing slash; this repository's own
    # worktrees are other checkouts, not part of this one.
    names=set(inventory.decode().split('\0'))-{''}
    inside=worktrees(root) if any(n.endswith('/') for n in names) else set()
    names=sorted(n for n in names if n.rstrip('/') not in inside)
    if paths:
        for dependency in paths:
            if not any(name==dependency or name.startswith(dependency.rstrip('/')+'/') for name in names):
                raise Refused(f'Verification dependency matches no files: {dependency}')
    records = []
    for name in names:
        if paths and not any(name == p or name.startswith(p.rstrip('/') + '/') for p in paths):
            continue
        path = root / name
        if path.is_symlink():
            records.append((name,'link',os.readlink(path)))
        elif path.is_file():
            records.append((name, 'executable' if path.stat().st_mode & stat.S_IXUSR else 'file',
                            hashlib.sha256(path.read_bytes()).hexdigest()))
        elif not path.exists():
            records.append((name,'deleted'))
        elif path.is_dir():
            if git(path,'status','--porcelain'):raise Refused('Dirty submodules require their own reviewed commit')
            records.append((name,'gitlink',git(path,'rev-parse','HEAD')))
        else:
            raise Refused(f'Unsupported file type: {name}')
    # Staging a deletion must not make it disappear from the subject.
    deleted = git(root,'diff','--name-only','--diff-filter=D','HEAD').splitlines()
    for name in deleted:
        if not paths or any(name == p or name.startswith(p.rstrip('/')+'/') for p in paths):
            if (name,'deleted') not in records:
                records.append((name,'deleted'))
    return digest(sorted(records))


def verify(root, checks, project_id, *, controlled=False):
    results = []
    for check in checks:
        if controlled:
            from .controls import check as control_check
            control_check(root)
        if not isinstance(check.get('command'), list) or not check['command'] or not all(isinstance(x,str) for x in check['command']):
            raise Refused('Verification commands must be nonempty argument arrays')
        # An omitted dependency list conservatively fingerprints the entire checkout.
        dependencies = check.get('inputs')
        if dependencies is not None and (not dependencies or any(p.startswith('/') or '..' in Path(p).parts for p in dependencies)):
            raise Refused('Verification inputs must be nonempty repository-relative paths')
        toolchain=check.get('toolchain')
        versions=[]
        if isinstance(toolchain,list) and all(isinstance(cmd,list) and cmd and all(isinstance(x,str) for x in cmd) for cmd in toolchain):
            for command in toolchain:
                from .processes import capture
                probe,cancellation=capture(root,command,controlled=controlled,timeout=10,env=check_env())
                if cancellation or probe.returncode:raise Refused('Verification toolchain probe failed or was cancelled: '+probe.stderr[-1000:])
                versions.append(probe.stdout+probe.stderr)
        fingerprint = digest({'tree':tree(root,dependencies),'command':check['command'],
            'environment':dict(os.environ),'platform':uname(), 'toolchain':versions,
            'check':check,'engine':1})
        cache = state_home() / 'verification' / project_id / (fingerprint+'.json')
        # No cache without an explicit dependency AND toolchain contract.
        reusable = bool(dependencies and versions)
        if reusable and cache.exists():
            results.append(read_json(cache) | {'reused':True})
            continue
        start=time.monotonic()
        from .processes import capture
        output,cancellation=capture(root,check['command'],controlled=controlled,timeout=check.get('timeout_seconds',900),env=check_env())
        result={'name':check['name'],'fingerprint':fingerprint,'returncode':output.returncode,
                'duration_ms':round((time.monotonic()-start)*1000),'reused':False,
                'output':(output.stdout+'\n'+output.stderr)[-12000:], 'cancellation':cancellation}
        results.append(result)
        if cancellation or output.returncode:
            return results
        if reusable:
            atomic_json(cache,result)
    return results


def check_env():
    """Checks run the project's own scripts, like cmd /c build.bat, so they keep Windows' search of their folder."""
    return {k:v for k,v in os.environ.items() if k!='NoDefaultCurrentDirectoryInExePath'}


def candidate_tree(root,replacements=None):
    """Build the exact committable subject without modifying the real index."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix='oh-index-') as tmp:
        env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
        env['GIT_INDEX_FILE']=str(Path(tmp)/'index')
        def command(*args):
            return subprocess.check_output(['git','-C',str(root),*args],env=env,stderr=subprocess.PIPE)
        command('read-tree','HEAD');command('add','--all',*whole(root))
        oid=command('write-tree').decode().strip()
        for entry in command('ls-files','--stage','-z').split(b'\0'):
            if not entry:continue
            metadata,name=entry.split(b'\t',1);mode,blob,_=metadata.decode().split()
            path=Path(root)/os.fsdecode(name)
            if mode=='160000':
                if git(path,'status','--porcelain'):raise Refused('Commit submodule changes in their own reviewed repository first')
            elif mode=='120000':continue
            elif (data:=path.read_bytes())!=(stored:=command('cat-file','blob',blob)) and data.replace(b'\r\n',b'\n')!=stored:
                # Only line endings may differ (core.autocrlf, the Git for Windows default): the reviewed text is the committed text.
                raise Refused(f'Git filters transform {os.fsdecode(name)} beyond line endings; normalize it before review so reviewed bytes equal committed bytes')
        for name,replacement in (replacements or {}).items():
            if Path(name).is_absolute() or '..' in Path(name).parts:raise Refused('Invalid final-tree replacement')
            info=command('ls-files','--stage','--',name).decode().split()
            if not info or info[0] not in ('100644','100755'):raise Refused('Final-tree replacement requires an ordinary tracked file')
            blob=command('hash-object','-w','--',str(replacement)).decode().strip()
            command('update-index','--cacheinfo',info[0],blob,name)
        return command('write-tree').decode().strip() if replacements else oid
