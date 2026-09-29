"""Branch identity from Git's own reflog; OH writes no marker into a checkout."""
import os
from pathlib import Path
from .storage import Refused,digest,git


def incarnation(root,branch,*,create=False):
    """Read Git's own reflog identity; never write an OH marker in a consumer."""
    path=Path(git(root,'rev-parse','--path-format=absolute','--git-path','logs/refs/heads/'+branch))
    if path.is_symlink() or not path.is_file():raise Refused('Branch reflog is unavailable; enable Git reflogs and start a new run')
    st=path.stat()
    if hasattr(st,'st_birthtime'):
        birth=getattr(st,'st_birthtime_ns',round(st.st_birthtime*1_000_000_000))
    elif os.name=='nt':
        birth=st.st_ctime_ns  # creation time on Windows before Python 3.12 added st_birthtime
    else:
        # Linux statx supplies nanosecond creation identity where ordinary stat does not.
        import ctypes,struct
        libc=ctypes.CDLL(None,use_errno=True);buffer=ctypes.create_string_buffer(256)
        statx=getattr(libc,'statx',None)
        if statx is None or statx(-100,os.fsencode(path),256,0x800,buffer)!=0 or not struct.unpack_from('I',buffer.raw)[0]&0x800:
            raise Refused('This filesystem cannot distinguish a recreated branch safely. Use a filesystem with birth-time support and start a new run.')
        seconds,nanoseconds=struct.unpack_from('qI',buffer.raw,80);birth=seconds*1_000_000_000+nanoseconds
    with path.open('rb') as stream:first=stream.readline().decode()
    return digest({'device':st.st_dev,'inode':st.st_ino,'birth':birth,'first':first})


def trunk(root):
    """The repository's main branch: main, or master where it has no main. None when it has neither."""
    for name in ('main','master'):
        for ref in ('refs/heads/','refs/remotes/origin/'):
            if run_git(root,'rev-parse','--verify','--quiet',ref+name).returncode==0:return name
    return None


def main_ref(root):
    """The ref of the main branch work is measured against: origin's copy when there is one. None without one."""
    name=trunk(root)
    if not name:return None
    return 'origin/'+name if run_git(root,'rev-parse','--verify','--quiet','refs/remotes/origin/'+name).returncode==0 else name


def run_git(root,*args,timeout=None):
    import subprocess
    env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}|{'GIT_TERMINAL_PROMPT':'0'}
    # UTF-8, whatever the platform's default, keeping other bytes (such as a latin-1 file's) exactly.
    try:return subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True,encoding='utf-8',errors='surrogateescape',env=env,timeout=timeout)
    except subprocess.TimeoutExpired:return subprocess.CompletedProcess(args,1,'','timed out')


def squashed(root,into,start,end):
    """Whether one commit on `into` since `start` carries exactly the change start..end, as a squash merge does: found
    by Git's patch id, so still found after main changed the same lines again."""
    import subprocess
    def ids(text):
        found=subprocess.run(['git','-C',str(root),'patch-id','--stable'],input=text,capture_output=True,text=True,encoding='utf-8',errors='surrogateescape',
                             env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')})
        return {line.split()[0] for line in found.stdout.splitlines() if line.strip()}
    change=run_git(root,'diff','--no-color','--no-ext-diff',start,end).stdout
    if not change.strip():return False
    return bool(ids(change)&ids(run_git(root,'log','-p','--no-merges','--no-color','--no-ext-diff',start+'..'+into).stdout))


def contained(root,into,commit):
    """Whether `into` holds `commit`'s work: merged, or squashed in one commit."""
    if run_git(root,'merge-base','--is-ancestor',commit,into).returncode==0:return True
    fork=run_git(root,'merge-base',into,commit).stdout.strip()
    return bool(fork) and squashed(root,into,fork,commit)


def untouched(root):
    """Refuse while the checkout holds the person's own uncommitted edits: they decide what happens to them."""
    from .storage import changes
    if edited:=changes(root):
        shown=', '.join(edited[:5])+(f' and {len(edited)-5} more' if len(edited)>5 else '')
        raise Refused(f'This checkout has uncommitted changes that OH did not make ({shown}). They are yours, so '
                      'OH leaves them alone: commit, stash or discard them, then OH carries on with your command.')


def fetched(root,name):
    """Fetch the main branch `name` and return the ref new work starts from: origin/<name>, or the local branch
    when the repository has no origin. Offline, the last fetched origin/<name> serves."""
    if run_git(root,'remote','get-url','origin').returncode==0:run_git(root,'fetch','--quiet','origin',name,timeout=60)
    return 'origin/'+name if run_git(root,'rev-parse','--verify','--quiet','refs/remotes/origin/'+name).returncode==0 else name


def holder(root,branch):
    """The other worktree that has `branch` checked out, or None."""
    here=Path(root).resolve();path=None
    for line in git(root,'worktree','list','--porcelain').splitlines():
        if line.startswith('worktree '):path=Path(line[9:]).resolve()
        elif line=='branch refs/heads/'+branch and path!=here:return path
    return None


def merged_tree(root,ours,theirs):
    """The tree Git makes merging `theirs` into `ours`, or None when they conflict."""
    done=run_git(root,'merge-tree','--write-tree',ours,theirs)
    if done.returncode in (0,1):return done.stdout.split()[0] if done.returncode==0 else None
    raise Refused('OH needs Git 2.38 or newer to resume or publish a delivery branch; update Git, then OH carries on with your command.')


def from_main(root):
    """Put the checkout on its main branch, up to date with origin, as the pre-separation harness did
    (`git checkout main && git pull`) before new plans. Only what needs the person stops it: their own uncommitted
    edits, and a main that differs from origin's."""
    untouched(root)
    name=trunk(root)
    if name is None:return
    base=fetched(root,name)
    if git(root,'branch','--show-current')!=name:
        if elsewhere:=holder(root,name):
            raise Refused(f'OH starts new plans from {name}, which is checked out in {elsewhere}; type the command there.')
        switched=run_git(root,'switch','--quiet',name)
        if switched.returncode:
            raise Refused(f'OH starts new plans from {name}, but Git could not switch this checkout to it: {switched.stderr.strip()}')
    if base!=name and (run_git(root,'merge','--ff-only','--quiet',base).returncode or git(root,'rev-parse','HEAD')!=git(root,'rev-parse',base)):
        raise Refused(f'Your local {name} has commits that are not on {base}, so new work would carry them. '
                      f'Push them, or reset {name} to {base}, then OH carries on with your command.')


def delivery_branch(doc,track=''):
    """deliver/<doc>, or deliver/<doc>-<track> for one track of a design, as the pre-separation harness named them."""
    return f'deliver/{doc}-{track}' if track else f'deliver/{doc}'


def to_delivery(root,name):
    """Put the checkout on the delivery branch `name`, as the pre-separation harness did. A branch whose work main
    already holds (merged, squashed or rebased) is retired and a fresh one starts from origin's main; a branch with
    unmerged work is resumed: the returned base is what `refresh` merges into it. Only the person's own edits, or
    the branch being checked out in another worktree, need them."""
    untouched(root)
    main=trunk(root)
    if main is None:return
    base=fetched(root,main);current=git(root,'branch','--show-current')
    exists=run_git(root,'rev-parse','--verify','--quiet','refs/heads/'+name).returncode==0
    if exists and current!=name and (elsewhere:=holder(root,name)):
        raise Refused(f'{name} is checked out in {elsewhere}; type the command there to carry on with it.')
    if exists and (contained(root,base,name) or merged_tree(root,base,name)==git(root,'rev-parse',base+'^{tree}')):
        if current==name:git(root,'switch','--quiet','--detach',base)  # only while the spent branch is replaced
        git(root,'branch','-D',name);exists=False
    if not exists:
        git(root,'switch','--quiet','--no-track','-c',name,base);return None
    if current!=name:git(root,'switch','--quiet',name)
    return base


def refresh(root,name,base):
    """Merge origin's main into a resumed delivery branch. A conflict is the person's call: start over from main,
    finish without main's changes, or let the agent plan a resolution for them to approve."""
    from .storage import checkout_file,read_json
    try:
        if read_json(checkout_file(root,'oh-without-main.json'))=={'branch':name,'base':git(root,'rev-parse',base)}:return
    except FileNotFoundError:pass
    merging=run_git(root,'merge','--quiet','--no-edit',base)
    if merging.returncode:
        conflicted=git(root,'diff','--name-only','--diff-filter=U').splitlines()
        run_git(root,'merge','--abort')
        if not conflicted:raise Refused(f'Git could not merge {base} into {name}: {merging.stderr.strip()}')
        args=' '.join(name[len('deliver/'):].split('-',1))
        raise Refused(f'{name} holds unfinished work that conflicts with {base} in {", ".join(conflicted[:5])}. Ask the '
            f'person with a menu: start over from {base} and discard this branch (run `conflict fresh {args}`, then '
            f'`run`); finish from here without {base}\'s changes, resolving the conflicts when the pull request merges '
            f'(run `conflict keep {args}`, then `run`); or let you resolve it. For that, study both sides and why each '
            f'changed, show the person your plan with a menu to approve it or handle it themselves, and on approval '
            f'merge {base} into {name}, resolve it as planned, commit the merge and run `run`: the next task\'s review '
            'covers your resolution.')
