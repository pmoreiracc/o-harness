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
