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


def run_git(root,*args,timeout=None):
    import subprocess
    env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}|{'GIT_TERMINAL_PROMPT':'0'}
    try:return subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True,env=env,timeout=timeout)
    except subprocess.TimeoutExpired:return subprocess.CompletedProcess(args,1,'','timed out')


def from_main(root):
    """Put the checkout on its main branch, up to date with origin, as the pre-separation harness did
    (`git checkout main && git pull`) before new work. Offline, the local main serves. Only what needs the
    person stops it: their own uncommitted edits, and a main that can't be brought up to date."""
    from .storage import changes
    if edited:=changes(root):
        shown=', '.join(edited[:5])+(f' and {len(edited)-5} more' if len(edited)>5 else '')
        raise Refused(f'This checkout has uncommitted changes that OH did not make ({shown}). They are yours, so '
                      'OH leaves them alone: commit, stash or discard them, then OH carries on with your command.')
    name=trunk(root)
    if name is None:return
    if run_git(root,'remote','get-url','origin').returncode==0:run_git(root,'fetch','--quiet','origin',name,timeout=60)
    if git(root,'branch','--show-current')!=name:
        switched=run_git(root,'switch','--quiet',name)
        if switched.returncode:
            raise Refused(f'OH starts new work from {name}, but Git could not switch this checkout to it: {switched.stderr.strip()}')
    if run_git(root,'rev-parse','--verify','--quiet','refs/remotes/origin/'+name).returncode==0 and \
            run_git(root,'merge','--ff-only','--quiet','origin/'+name).returncode:
        raise Refused(f'Your local {name} has commits that are not on origin/{name}, so OH cannot bring it up to date. '
                      f'Push them, or reset {name} to origin/{name}, then OH carries on with your command.')
