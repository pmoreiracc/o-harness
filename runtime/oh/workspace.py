"""Lossless branch parking in one checkout; state and byte backups stay outside it."""
import hashlib
import os
import stat
import subprocess
from .system import Path
from .storage import Refused, atomic_json, changes, checkout_file, git, git_env, identifier, now, read_json, state_mkdir, worktrees
from .branches import holder, run_git
from .verification import tree


def _path(root):return checkout_file(root,'oh-workspace.json')


def _state(root):
    path=_path(root)
    return read_json(path) if path.exists() else {'version':1,'branches':{}}


def _write(root,state):atomic_json(_path(root),state)


def _index(root):return git(root,'write-tree')


def _ready(root):
    for entry in git(root,'ls-files','--stage','-v','-z',raw=True).split(b'\0'):
        if not entry:continue
        flag=entry[:1].decode()
        if flag.islower() or flag=='S':raise Refused('Clear assume-unchanged/skip-worktree flags before switching; hidden edits must be visible so OH can preserve them.')
        if entry[2:].split(b'\t',1)[0].split()[-1]!=b'0':
            raise Refused('Resolve Git conflicts before switching work; retry the same request after the index is settled.')
    for name in ('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-merge','rebase-apply','sequencer'):
        if Path(git(root,'rev-parse','--path-format=absolute','--git-path',name)).exists():
            raise Refused('Finish or safely abort the current Git operation ('+name+') within the approved outcome, then retry this branch switch. OH has not parked or discarded its work.')


def _exact(root,record):
    if git(root,'rev-parse','HEAD')!=record['head'] or _index(root)!=record['index']:return False
    if any(name.rstrip('/') not in record['files'] for name in changes(root)):return False
    for name,item in record['files'].items():
        path=Path(root)/name;kind=item['kind']
        if kind=='link':
            if not path.is_symlink() or os.readlink(path)!=item['target']:return False
        elif kind=='file':
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:return False
            if os.name!='nt' and stat.S_IMODE(path.stat().st_mode)!=item['mode']:return False
        elif kind=='deleted':
            if path.exists() or path.is_symlink():return False
        elif kind=='directory' and (path.is_symlink() or not path.is_dir()):return False
    return True


def parked(root,branch):
    record=_state(root)['branches'].get(branch)
    return record if record and record['phase']!='restored' else None


def observation(root,branch):
    """Read the saved branch without moving the checkout or borrowing its scope."""
    result=run_git(root,'rev-parse','--verify','--quiet','refs/heads/'+branch+'^{commit}')
    if result.returncode:
        raise Refused('Saved branch '+branch+' is missing. Restore that branch from its retained history before resuming; do not replace it with main.')
    record=parked(root,branch)
    if record and result.stdout.strip()!=record['head']:
        raise Refused('Saved branch '+branch+' moved after its changes were parked. Preserve its newer commits on a named branch, then reconcile whether to return '+branch+' to saved commit '+record['head']+' or integrate both versions. Retry after that resolution; the stash and byte backup at '+record['backup']+' are retained. OH has not reset the branch.')
    return {'branch':branch,'head':result.stdout.strip(),'tree':record['tree'] if record else None,
            'paths':record['paths'] if record else [],'backup':record['backup'] if record else None}


def summary(root):
    return [{'branch':branch,**{k:r[k] for k in ('head','phase','backup','paths')},'stash':r.get('stash')}
            for branch,r in _state(root)['branches'].items() if r['phase']!='restored']


def _archive(root,branch):
    # Reject conflicts, hidden index flags and dirty submodules before any mutation.
    fingerprint=tree(root);index=_index(root)
    untracked={os.fsdecode(p) for p in git(root,'ls-files','--others','--exclude-standard','-z',raw=True).split(b'\0') if p}
    paths=set(untracked)
    for args in (('diff','--name-only','--no-renames','-z'),
                 ('diff','--cached','--name-only','--no-renames','-z','HEAD')):
        paths.update(os.fsdecode(p) for p in git(root,*args,raw=True).split(b'\0') if p)
    nested=worktrees(root) if any(p.endswith('/') for p in paths) else set()
    paths={p for p in paths if p.rstrip('/') not in nested}
    untracked={p for p in untracked if p.rstrip('/') not in nested}
    if any(p.endswith('/') for p in paths):
        raise Refused('An untracked nested repository cannot be parked safely. Preserve or finish its work separately, then retry this same branch switch; OH will not create another checkout.')
    # A tracked file/link replaced by a directory can contain ignored files that
    # stash's cleanup would otherwise remove. Preserve just those ignored paths,
    # without sweeping unrelated ignored dependencies/configuration into a stash.
    directories=[p for p in paths if not (Path(root)/p).is_symlink() and (Path(root)/p).is_dir()]
    if any(n==p or n.startswith(p+'/') for p in directories for n in nested):
        raise Refused('A changed path contains another worktree. Preserve and reconcile that path in place before switching; OH will not remove the nested checkout.')
    ignored=set()
    for name in directories:
        ignored.update(os.fsdecode(p) for p in git(root,'ls-files','--others','--ignored','--exclude-standard','-z','--',':(literal)'+name,raw=True).split(b'\0') if p)
    paths|=ignored
    untracked|=ignored
    token=identifier();backup=_path(root).parent/'workspace'/token
    state_mkdir(backup)
    patch=git(root,'diff','--binary','--full-index','--no-ext-diff','--no-renames','HEAD',raw=True)
    with (backup/'worktree.patch').open('xb') as stream:
        stream.write(patch);stream.flush();os.fsync(stream.fileno())
    files={}
    for number,name in enumerate(sorted(paths)):
        path=Path(root)/name
        if path.is_symlink():files[name]={'kind':'link','target':os.readlink(path)}
        elif path.is_file():
            data=path.read_bytes();blob=str(number)
            with (backup/blob).open('xb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            files[name]={'kind':'file','blob':blob,'sha256':hashlib.sha256(data).hexdigest(),'mode':stat.S_IMODE(path.stat().st_mode)}
        elif path.is_dir():files[name]={'kind':'directory'}
        elif not path.exists():files[name]={'kind':'deleted'}
        else:raise Refused('Cannot preserve unsupported file '+name+'; resolve its type before retrying the same branch switch.')
    record={'id':token,'branch':branch,'head':git(root,'rev-parse','HEAD'),'index':index,
            'tree':fingerprint,'paths':sorted(paths),'backup':str(backup),'files':files,
            'phase':'saving','created_at':now(),'stash':None,'include_ignored':bool(ignored),
            'untracked':sorted(untracked),'patch_sha256':hashlib.sha256(patch).hexdigest()}
    if ignored:
        with (backup/'pathspec').open('xb') as stream:
            stream.write(b''.join(os.fsencode(':(literal)'+name)+b'\0' for name in sorted(paths)))
            stream.flush();os.fsync(stream.fileno())
    atomic_json(backup/'snapshot.json',record,immutable=True)
    if not _exact(root,record) or tree(root)!=fingerprint:
        raise Refused('Local work changed while it was being saved. The byte backup is at '+str(backup)+'; inspect the current edits and retry without discarding them.')
    return record


def _find_stash(root,record):
    tag='OH workspace '+record['id']
    found=run_git(root,'stash','list','--format=%H:%gs')
    if found.returncode:raise Refused('Could not inspect saved Git stashes; preserve the backup at '+record['backup']+' and retry the same switch.')
    for line in found.stdout.splitlines():
        oid,_,message=line.partition(':')
        if message.endswith(': '+tag) and git(root,'rev-parse',oid+'^1')==record['head'] and git(root,'rev-parse',oid+'^2^{tree}')==record['index']:
            return oid


def _save(root,state,branch):
    record=state['branches'].get(branch)
    if record and record['phase']=='saving':
        record['stash']=record.get('stash') or _find_stash(root,record)
        if record['stash'] and not changes(root):
            record['phase']='parked';_write(root,state);return record
        if not _exact(root,record):
            raise Refused('The interrupted save is incomplete. Saved bytes remain at '+record['backup']+'. Inspect its snapshot and current Git changes before resolving the partial save; do not reset or clean the checkout.')
    elif changes(root):
        record=_archive(root,branch);state['branches'][branch]=record;_write(root,state)
    else:return None
    selection=(['--all','--pathspec-from-file='+str(Path(record['backup'])/'pathspec'),'--pathspec-file-nul']
               if record.get('include_ignored') else ['--include-untracked'])
    saved=run_git(root,'stash','push',*selection,'--message','OH workspace '+record['id'])
    record['stash']=_find_stash(root,record)
    if not record['stash'] or changes(root):
        remaining=changes(root)
        _write(root,state)
        if record['stash']:_restore(root,state,branch,rollback=True)
        reason=(saved.stderr.strip() or ('Parking the branch exposed remaining paths: '+', '.join(remaining[:5])+'. Keep ambient files ignored on the destination or reconcile their preservation before retrying.' if remaining else 'Git did not retain the expected stash; inspect its error and restore stash access before retrying.'))
        raise Refused('Git could not finish saving '+branch+': '+reason+' Original bytes remain at '+record['backup']+'. Retry the same branch switch after resolving that prerequisite; no discard is authorized.')
    record['phase']='parked';_write(root,state)
    return record


def _raw_bytes(root,record):
    """Stash can normalize filters/line endings; retain and restore the original bytes."""
    backup=Path(record['backup'])
    # Reverse patch applicability proves only that the saved hunks are present.
    # Before replacing whole files, reject bytes or executable modes outside the
    # saved raw or Git representations, including edits outside those hunks. Validate
    # every file first so a later collision does not partly replace earlier files.
    for name,item in record['files'].items():
        if item['kind']=='file':
            value=(backup/item['blob']).read_bytes()
            if hashlib.sha256(value).hexdigest()!=item['sha256']:
                raise Refused('Saved byte backup changed at '+str(backup)+'. Restore its original archive before continuing; the Git stash is retained.')
            path=Path(root)/name
            if path.is_symlink() or not path.is_file():
                raise Refused('Git restored an unexpected file type at '+name+'. Inspect the retained snapshot at '+str(backup)+' before resolving it; the stash is retained.')
            current=path.read_bytes()
            if ((current!=value and not _matches_git_bytes(root,record,name,current)) or
                    (os.name!='nt' and not _matches_git_mode(root,record,name,path.stat().st_mode))):
                raise Refused('Cannot restore '+name+' over new edits. Preserve and reconcile its current bytes and executable mode with snapshot.json at '+str(backup)+', then retry the same resume; the saved stash '+record['stash']+' and byte backup are retained. OH has not overwritten this file.')
    for name,item in record['files'].items():
        if item['kind']=='file':
            path=Path(root)/name;value=(backup/item['blob']).read_bytes()
            if path.read_bytes()!=value:path.write_bytes(value)
            if os.name!='nt':path.chmod(item['mode'])


def _matches_git_bytes(root,record,name,current):
    """Compare full bytes, never cleaned hashes that could discard a new edit."""
    for options in (('blob',),('--filters','--path='+name)):
        saved=subprocess.run(['git','-C',str(root),'cat-file',*options,record['stash']+':'+name],
                             stdin=subprocess.DEVNULL,capture_output=True,env=git_env())
        if saved.returncode==0 and saved.stdout==current:return True
    return False


def _matches_git_mode(root,record,name,current):
    """Git tracks owner execute only; other permission bits can differ by umask."""
    executable=bool(current & stat.S_IXUSR)
    if executable==bool(record['files'][name]['mode'] & stat.S_IXUSR):return True
    # Untracked files are recreated with open('xb'), hence without execute bits.
    if name in record['untracked']:return not executable
    entry=run_git(root,'ls-tree','-z',record['stash'],'--',':(literal)'+name)
    mode=entry.stdout.split(' ',1)[0]
    return entry.returncode==0 and mode in ('100644','100755') and executable==(mode=='100755')


def _same_file(path,item):
    if item['kind']=='link':return path.is_symlink() and os.readlink(path)==item['target']
    return item['kind']=='file' and not path.is_symlink() and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']


def _directory_collision(root,path,record):
    """Only recorded tracked deletions may clear a directory for a saved file."""
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():_directory_collision(root,child,record)
        elif record['files'].get(child.relative_to(root).as_posix(),{}).get('kind')!='deleted':
            raise Refused('Cannot restore '+record['branch']+' over '+str(child)+'. Preserve and reconcile this extra file, then retry the same resume; its saved stash and byte backup are retained.')


def _empty_directory(path):
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():_empty_directory(child)
        else:raise Refused('A new file prevents restoring '+str(path)+'. Preserve and reconcile '+str(child)+' before retrying; OH will not remove it.')
    path.rmdir()


def _untracked(root,record):
    found=run_git(root,'ls-tree','-r','--name-only','-z',record['stash']+'^3')
    names=record['untracked']
    saved={p for p in found.stdout.split('\0') if p} if found.returncode==0 else set()
    if saved-set(names):
        raise Refused('Git saved additional files after the byte snapshot. Inspect stash '+record['stash']+' and '+record['backup']+' before reconciling both versions; neither has been discarded.')
    for name in names:
        if name not in record['files']:
            raise Refused('Git saved additional files after the byte snapshot. Inspect stash '+record['stash']+' and '+record['backup']+' before reconciling both versions; neither has been discarded.')
        blocked=False
        for parent in Path(name).parents:
            if str(parent)=='.':continue
            path=Path(root)/parent
            if path.is_symlink() or path.is_file():
                if record['files'].get(parent.as_posix(),{}).get('kind')=='directory':blocked=True;break
                raise Refused('Cannot restore '+name+' through existing parent '+str(parent)+'. Preserve and reconcile that path, then retry; the stash and byte backup are retained.')
        path=Path(root)/name
        directory=path.is_dir() and not path.is_symlink() and any(p.startswith(name+'/') and i['kind']=='deleted' for p,i in record['files'].items())
        if not blocked and not directory and (path.exists() or path.is_symlink()) and not _same_file(path,record['files'][name]):
            raise Refused('Git could not restore '+record['branch']+' because '+name+' already exists. Preserve and reconcile that file, then retry the same resume. The stash '+record['stash']+' and byte backup '+record['backup']+' are retained; no saved edits were applied.')
    return names


def _restore(root,state,branch,*,rollback=False):
    record=state['branches'].get(branch)
    if not record or record['phase']=='restored':return None
    observation(root,branch)
    if _exact(root,record):
        record['phase']='restored';_write(root,state);return record
    residual=changes(root)
    overlapping=any(a==b or a.startswith(b.rstrip('/')+'/') or b.startswith(a.rstrip('/')+'/')
                    for a in residual for b in record['paths'])
    partial=record['phase']=='restoring' and all(p.rstrip('/') in record['files'] for p in residual)
    if residual and not partial and (not rollback or overlapping):
        raise Refused('Cannot restore '+branch+' over new or partially restored edits. The stash '+str(record.get('stash'))+' and byte backup '+record['backup']+' are retained. Compare current changes with snapshot.json and resolve them before retrying the same resume; OH will not overwrite them.')
    if record['phase']=='saving':
        record['stash']=record.get('stash') or _find_stash(root,record)
    if not record.get('stash'):
        raise Refused('The saved Git stash is unavailable. Restore it using the retained snapshot at '+record['backup']+' before retrying; OH will not replace saved work with an empty checkout.')
    # Check the archive before applying anything. This also keeps missing/corrupt
    # archives from turning a recoverable prerequisite into a partial restore.
    try:
        patch=(Path(record['backup'])/'worktree.patch').read_bytes()
        if hashlib.sha256(patch).hexdigest()!=record['patch_sha256']:
            raise Refused('The saved working-tree patch changed; restore '+record['backup']+' before retrying. The Git stash remains retained.')
        for item in record['files'].values():
            if item['kind']=='file' and hashlib.sha256((Path(record['backup'])/item['blob']).read_bytes()).hexdigest()!=item['sha256']:
                raise Refused('The saved byte backup changed; restore '+record['backup']+' before retrying. The Git stash remains retained.')
    except OSError as exc:
        raise Refused('The saved byte backup is unavailable: '+str(exc)+'. Restore access to '+record['backup']+' and retry the same resume; its Git stash is retained.') from None
    for name,item in record['files'].items():
        path=Path(root)/name
        if item['kind'] in ('file','link') and path.is_dir() and not path.is_symlink():_directory_collision(Path(root),path,record)
    names=_untracked(root,record)
    index=_index(root);baseline=git(root,'rev-parse','HEAD^{tree}')
    tracked=not patch
    if record['phase']=='restoring' and patch:
        checked=subprocess.run(['git','-C',str(root),'apply','--reverse','--check','--binary','-'],input=patch,capture_output=True,env=git_env())
        tracked=checked.returncode==0
    clean=run_git(root,'diff','--quiet','--no-ext-diff','HEAD','--').returncode==0
    if index not in (baseline,record['index']) or not (tracked or clean):
        raise Refused('Tracked files or staged state differ from both the saved work and its original base. Compare them with '+record['backup']+'/snapshot.json and reconcile the new edits before retrying; the stash is retained.')
    record['phase']='restoring';_write(root,state)
    # Apply tracked changes atomically before creating untracked directories.
    # A stash's tree/restore ordering can miss file-to-directory transitions.
    # Use the pre-save patch and keep the saved index independent of it.
    if not tracked:
        if patch:
            applied=subprocess.run(['git','-C',str(root),'apply','--binary','--whitespace=nowarn','-'],input=patch,capture_output=True,env=git_env())
            if applied.returncode:
                raise Refused('Git could not restore tracked changes: '+applied.stderr.decode('utf-8','replace').strip()+'. Resolve that filesystem/path prerequisite and retry the same resume; stash '+record['stash']+' and backup '+record['backup']+' remain retained.')
    indexed=run_git(root,'read-tree',record['index'])
    if indexed.returncode:raise Refused('Git could not restore the saved index: '+indexed.stderr.strip()+'. Resolve the index prerequisite and retry the same resume; its working-tree patch and byte backup are retained.')
    for name in names:
        path=Path(root)/name;item=record['files'][name]
        if _same_file(path,item):continue
        if path.is_dir() and not path.is_symlink():_empty_directory(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        if item['kind']=='link':path.symlink_to(item['target'])  # windows-ok: restore a recorded native link; missing privileges leave its stash and backup retained.
        else:
            with path.open('xb') as stream:stream.write((Path(record['backup'])/item['blob']).read_bytes())
    _raw_bytes(root,record)
    if not _exact(root,record):
        raise Refused('Restoration did not match the saved contents and index. Compare current changes with '+record['backup']+'/snapshot.json; the original stash and byte backup are retained.')
    record['phase']='restored';_write(root,state)
    return record


def switch(root,branch,base=None):
    """Caller holds native control lock and has verified authority and writer settlement."""
    if not isinstance(branch,str) or not branch or branch.startswith('-') or run_git(root,'check-ref-format','refs/heads/'+branch).returncode:
        raise Refused('Select a valid named Git branch before switching work.')
    current=git(root,'branch','--show-current')
    if not current:
        raise Refused('This checkout has a detached HEAD. First name its current work with a lossless branch creation, then retry the requested switch in this folder.')
    state=_state(root)
    record=state['branches'].get(branch)
    if current==branch and (not record or record['phase']=='restored'):
        return {'branch':branch,'saved':None,'restored':None}
    _ready(root)
    if elsewhere:=holder(root,branch):
        raise Refused('Branch '+branch+' is already checked out at '+str(elsewhere)+'. Release that branch there after preserving its work, then retry here; OH will not move this task to another checkout.')
    existing=run_git(root,'rev-parse','--verify','--quiet','refs/heads/'+branch+'^{commit}').returncode==0
    if not existing and not base:observation(root,branch)
    if parked(root,branch):observation(root,branch)
    commit=None
    if not existing:
        resolved=run_git(root,'rev-parse','--verify','--quiet','--end-of-options',str(base)+'^{commit}')
        if resolved.returncode:raise Refused('The selected branch base is unavailable. Fetch or restore '+str(base)+' and retry this same switch; local work is unchanged.')
        commit=resolved.stdout.strip()
    if current==branch:
        restored=_restore(root,state,branch)
        return {'branch':branch,'saved':None,'restored':restored['backup'] if restored else None}
    # A crash after parking but before switching must not restore/re-stash the
    # same work. A partial restoration, however, must settle before leaving.
    record=state['branches'].get(current)
    if record and record['phase']=='parked' and not changes(root):saved=record
    else:
        if record and record['phase'] in ('parked','restoring'):_restore(root,state,current)
        saved=_save(root,state,current)
    args=['switch','--quiet','--no-overwrite-ignore']
    args+=['--no-track','-c',branch,commit] if not existing else [branch]
    switched=run_git(root,*args)
    if switched.returncode:
        # Git normally leaves the source selected. Restore it without another
        # human question; an interrupted rollback is recovered by the same record.
        if git(root,'branch','--show-current')==current:_restore(root,state,current)
        raise Refused('Git could not switch to '+branch+': '+switched.stderr.strip()+'. Source work is retained. Resolve the reported branch/path prerequisite and retry the same request in this checkout.')
    restored=_restore(root,state,branch)
    return {'branch':branch,'saved':saved['backup'] if saved else None,'restored':restored['backup'] if restored else None}
