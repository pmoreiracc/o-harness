from __future__ import annotations

import hashlib
import json
import os
import re
from .system import Path
import stat
import subprocess
import time
from .storage import Refused, atomic_json, digest, git, read_json, state_home, whole, worktrees, git_env, git_root
from .system import uname, executable


def tree(root, paths=None):
    root = Path(root)
    if paths and any(p in ('.','./') for p in paths):paths=None
    git_root(root)
    indexed = {};names = set()
    # One NUL-delimited query supplies flags, index stages/modes and nonignored untracked paths.
    inventory = git(root, 'ls-files', '--stage', '-v', '-z', '--cached', '--others', '--exclude-standard', raw=True)
    for entry in inventory.split(b'\0'):
        if not entry:continue
        flag=entry[:1].decode()
        if flag.islower() or flag=='S':raise Refused('Clear assume-unchanged/skip-worktree flags before verification')
        if flag=='?':name=os.fsdecode(entry[2:])
        else:
            metadata, raw_name = entry[2:].split(b'\t', 1)
            mode, _, stage = metadata.decode().split()
            if stage != '0':raise Refused('Resolve Git conflicts before verification')
            name=os.fsdecode(raw_name);indexed[name]=mode
        names.add(name)
    # Git may hide an embedded repository behind the ordinary file still in its index.
    embedded={n.rstrip('/') for n in names if n.endswith('/') or
              ((root/n).is_dir() and ((root/n/'.git').exists() or (root/n/'.git').is_symlink()))}
    inside=worktrees(root) if embedded else set()
    embedded-=inside
    names=sorted({n.rstrip('/') for n in names if n.rstrip('/') not in inside})
    if paths:
        for dependency in paths:
            if not any(name==dependency or name.startswith(dependency.rstrip('/')+'/') for name in names):
                raise Refused(f'Verification dependency matches no files: {dependency}')
    records = []
    for name in names:
        if paths and not any(name == p or name.startswith(p.rstrip('/') + '/') for p in paths):
            continue
        path = root / name
        if not path.is_symlink() and path.is_dir() and (indexed.get(name)=='160000' or name in embedded):
            git_root(path)  # Never mistake the parent's HEAD for an uninitialized child repository.
            if git(path,'status','--porcelain'):raise Refused('Dirty submodules require their own reviewed commit')
            try:head=git(path,'rev-parse','--verify','HEAD')
            except subprocess.CalledProcessError:
                raise Refused(f'Embedded repository {name} has no commit; initialize its reviewed commit before resuming') from None
            records.append((name,'gitlink',head))
        elif path.is_symlink():
            records.append((name,'link',os.readlink(path)))
        elif path.is_file():
            records.append((name, 'executable' if path.stat().st_mode & stat.S_IXUSR else 'file',
                            hashlib.sha256(path.read_bytes()).hexdigest()))
        elif not path.exists():
            records.append((name,'deleted'))
        elif path.is_dir():
            # A former ordinary file is deleted; Git's inventory already includes its new children.
            continue
        else:
            raise Refused(f'Unsupported file type: {name}')
    # Structural HEAD membership, not rename/type-change heuristics, anchors deletions across staging.
    present={record[0] for record in records if record[1]!='deleted'}
    for raw_name in git(root,'ls-tree','-r','--name-only','-z','HEAD',raw=True).split(b'\0'):
        if not raw_name:continue
        name=os.fsdecode(raw_name)
        if name not in present and (not paths or any(name == p or name.startswith(p.rstrip('/')+'/') for p in paths)):
            if (name,'deleted') not in records:records.append((name,'deleted'))
    return digest(sorted(records))


def unavailable(check,command,start,detail,*,returncode=127,cancellation=()):
    return {'name':check['name'],'command':command,'fingerprint':None,'returncode':returncode or 127,
            'duration_ms':round((time.monotonic()-start)*1000),'reused':False,'cancellation':list(cancellation),
            'unavailable':True,'output':detail}


def check_failed(result):
    """A cleanup exit of zero cannot turn a cancelled or unavailable check into success."""
    return result.get('returncode') != 0 or bool(result.get('cancellation') or result.get('unavailable'))


def verify(root, checks, project_id):
    results = []
    for check in checks:
        if not isinstance(check.get('command'), list) or not check['command'] or not all(isinstance(x,str) for x in check['command']):
            raise Refused('Verification commands must be nonempty argument arrays')
        # An omitted dependency list conservatively fingerprints the entire checkout.
        dependencies = check.get('inputs')
        if dependencies is not None and (not dependencies or any(p.startswith('/') or '..' in Path(p).parts for p in dependencies)):
            raise Refused('Verification inputs must be nonempty repository-relative paths')
        start=time.monotonic()
        command=check['command']
        try:command=[executable(command[0],cwd=root,env=check_env()),*command[1:]]
        except FileNotFoundError as exc:
            return results+[unavailable(check,command,start,str(exc))]
        toolchain=check.get('toolchain')
        versions=[]
        if isinstance(toolchain,list) and all(isinstance(cmd,list) and cmd and all(isinstance(x,str) for x in cmd) for cmd in toolchain):
            for probe_command in toolchain:
                from .processes import capture
                try:
                    probe_command=[executable(probe_command[0],cwd=root,env=check_env()),*probe_command[1:]]
                    probe,cancellation=capture(root,probe_command,timeout=10,env=check_env())
                except FileNotFoundError as exc:
                    return results+[unavailable(check,probe_command,start,str(exc))]
                if cancellation or probe.returncode:
                    detail='Toolchain probe '+repr(probe_command)+' failed: '+(probe.stdout+probe.stderr)[-1000:]
                    return results+[unavailable(check,probe_command,start,detail,returncode=probe.returncode,cancellation=cancellation)]
                versions.append({'command':probe_command,'output':probe.stdout+probe.stderr})
        fingerprint = digest({'tree':tree(root,dependencies),'command':check['command'],'resolved_command':command,
            'environment':dict(os.environ),'platform':uname(), 'toolchain':versions,
            'check':check,'engine':2})
        cache = state_home() / 'verification' / project_id / (fingerprint+'.json')
        # No cache without an explicit dependency AND toolchain contract.
        reusable = bool(dependencies and versions)
        if reusable and cache.exists():
            results.append(read_json(cache) | {'reused':True})
            continue
        start=time.monotonic()
        from .processes import capture
        try:output,cancellation=capture(root,command,timeout=check.get('timeout_seconds',900),env=check_env())
        except FileNotFoundError as exc:
            return results+[unavailable(check,command,start,str(exc))]
        result={'name':check['name'],'command':command,'fingerprint':fingerprint,'returncode':output.returncode,
                'duration_ms':round((time.monotonic()-start)*1000),'reused':False,
                'output':(output.stdout+'\n'+output.stderr)[-12000:], 'cancellation':cancellation}
        results.append(result)
        if check_failed(result):
            return results
        if reusable:
            atomic_json(cache,result)
    return results


def failure_summary(results, limit):
    """Readable bounded repair feedback; complete check evidence stays in the journal."""
    failed=[r for r in results if check_failed(r)]
    header='\n'.join(f"{r['name']} failed (exit {r.get('returncode', 'unknown')}"+
                     (', '+', '.join(r['cancellation']) if r.get('cancellation') else '')+').' for r in failed)
    output='\n'.join(r.get('output','') for r in failed)
    output=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',output)
    # A tail can start with hundreds of passing tests and hide the actual assertion
    # when status further bounds it. Put error locations/messages first, retaining
    # surrounding context and the original full output in the journal.
    lines=output.splitlines()
    errors=[i for i,line in enumerate(lines) if re.search(
        r'\b(?:FAIL|ERROR|AssertionError|Traceback|error TS\d+|error:)|^\s*Error:|\d+:\d+\s+error\b',line)]
    if errors:
        indices=sorted({j for i in errors[:5] for j in range(max(0,i-1),min(len(lines),i+8))})
        output='\n'.join(lines[i] for i in indices)+'\n\n'+output
    header=(header+'\n')[:limit]
    remaining=limit-len(header)
    return header+(output[:remaining] if errors else output[-remaining:] if remaining else '')


def check_env():
    """Checks run the project's own scripts, like cmd /c build.bat, so they keep Windows' search of their folder."""
    return {k:v for k,v in os.environ.items() if k!='NoDefaultCurrentDirectoryInExePath'}


def candidate_tree(root,replacements=None):
    """Build the exact committable subject without modifying the real index."""
    import tempfile
    git_root(root)
    with tempfile.TemporaryDirectory(prefix='oh-index-') as tmp:
        env=git_env()
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
                git_root(path)
                if git(path,'status','--porcelain'):raise Refused('Commit submodule changes in their own reviewed repository first')
            elif mode=='120000':continue
            elif (data:=path.read_bytes())!=(stored:=command('cat-file','blob',blob)) and data.replace(b'\r\n',b'\n')!=stored:
                # Only line endings may differ (core.autocrlf, the Git for Windows default): the reviewed text is the committed text.
                raise Refused(f'Git filters transform {os.fsdecode(name)} beyond line endings; normalize it before review so reviewed bytes equal committed bytes')
        for name,replacement in (replacements or {}).items():
            if Path(name).is_absolute() or '..' in Path(name).parts:raise Refused('Invalid final-tree replacement')
            info=command('ls-files','--stage','--',name).decode().split()
            if not info or info[0] not in ('100644','100755'):raise Refused('Final-tree replacement requires an ordinary tracked file')
            # Apply this tracked path's Git attributes to the proposed bytes, just as
            # staging the published file will (including core.autocrlf on Windows).
            blob=command('hash-object','-w','--path='+name,'--',str(replacement)).decode().strip()
            data=Path(replacement).read_bytes();stored=command('cat-file','blob',blob)
            if data!=stored and data.replace(b'\r\n',b'\n')!=stored:
                raise Refused(f'Git filters transform proposed {name} beyond line endings')
            command('update-index','--cacheinfo',info[0],blob,name)
        return command('write-tree').decode().strip() if replacements else oid
