"""The few operating-system differences in OH. Each has one POSIX and one Windows branch."""
import errno
import os
import shutil
import signal
import subprocess
import time

WINDOWS=os.name=='nt'

if WINDOWS:
    import ctypes
    from ctypes import wintypes
    import msvcrt
    import weakref

    class _Overlapped(ctypes.Structure):
        _fields_=[('Internal',ctypes.c_size_t),('InternalHigh',ctypes.c_size_t),('Offset',wintypes.DWORD),
                  ('OffsetHigh',wintypes.DWORD),('hEvent',wintypes.HANDLE)]
    _kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
    for _name,_args in (('LockFileEx',[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(_Overlapped)]),
                        ('UnlockFileEx',[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(_Overlapped)]),
                        ('AssignProcessToJobObject',[wintypes.HANDLE,wintypes.HANDLE]),
                        ('TerminateJobObject',[wintypes.HANDLE,wintypes.UINT]),('CloseHandle',[wintypes.HANDLE])):
        getattr(_kernel32,_name).argtypes=_args;getattr(_kernel32,_name).restype=wintypes.BOOL
    _kernel32.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];_kernel32.CreateJobObjectW.restype=wintypes.HANDLE
    _ntdll=ctypes.WinDLL('ntdll');_ntdll.NtResumeProcess.argtypes=[wintypes.HANDLE];_ntdll.NtResumeProcess.restype=ctypes.c_long
else:
    import fcntl


def lock_file(fd,*,shared=False,wait=True):
    """Lock a whole file; without wait, raise BlockingIOError while another holder conflicts."""
    if WINDOWS:
        # msvcrt.locking has no shared mode and stops waiting after ten seconds; LockFileEx has neither limit.
        flags=(0 if shared else 2)|(0 if wait else 1)  # LOCKFILE_EXCLUSIVE_LOCK, LOCKFILE_FAIL_IMMEDIATELY
        if not _kernel32.LockFileEx(msvcrt.get_osfhandle(fd),flags,0,1,0,ctypes.byref(_Overlapped())):
            error=ctypes.get_last_error()
            if error==33:raise BlockingIOError(errno.EAGAIN,'File is locked')  # ERROR_LOCK_VIOLATION
            raise ctypes.WinError(error)
    else:
        fcntl.flock(fd,(fcntl.LOCK_SH if shared else fcntl.LOCK_EX)|(0 if wait else fcntl.LOCK_NB))


def unlock_file(fd):
    if WINDOWS:_kernel32.UnlockFileEx(msvcrt.get_osfhandle(fd),0,1,0,ctypes.byref(_Overlapped()))
    else:fcntl.flock(fd,fcntl.LOCK_UN)


def spawn(command,**kwargs):
    """Start a command that stop() can end together with every descendant."""
    if not WINDOWS:return subprocess.Popen(command,start_new_session=True,**kwargs)
    if not os.path.dirname(command[0]):
        # CreateProcess finds only .exe files; npm and similar tools are .cmd shims found through PATHEXT.
        command=[shutil.which(command[0],path=(kwargs.get('env') or os.environ).get('PATH')) or command[0],*command[1:]]
    # Start suspended and resume only inside a job object, so no descendant can be born outside it.
    child=subprocess.Popen(command,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP|0x4,**kwargs)  # CREATE_SUSPENDED
    job=_kernel32.CreateJobObjectW(None,None)
    if not job or not _kernel32.AssignProcessToJobObject(job,int(child._handle)):
        # Without the job, descendants of an exited leader could outlive stop(); refuse instead.
        if job:_kernel32.CloseHandle(job)
        child.kill();child.wait()
        raise OSError('Could not contain '+str(command[0])+' in a job object')
    child.oh_job=job
    weakref.finalize(child,_kernel32.CloseHandle,job)
    if _ntdll.NtResumeProcess(int(child._handle)):
        stop(child,force=True);child.wait()
        raise OSError('Could not start '+str(command[0]))
    return child


def stop(child,*,force=False):
    """Ask the child's process group to end, or end it and all descendants at once with force."""
    if WINDOWS:
        # CTRL_BREAK to a group whose leader has exited can reach every process on the console, OH included.
        if not force and child.poll() is None:
            try:os.kill(child.pid,signal.CTRL_BREAK_EVENT)
            except OSError:pass
        elif force:_kernel32.TerminateJobObject(child.oh_job,1)
        return
    try:os.killpg(child.pid,signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:pass
    except PermissionError:
        # Darwin reports EPERM for a group containing only unreaped zombies.
        rows=subprocess.check_output(['/bin/ps','-axo','pgid=,stat='],text=True).splitlines()
        live=[row.split() for row in rows if len(row.split())==2 and row.split()[0]==str(child.pid) and not row.split()[1].startswith('Z')]
        if live:raise


def wait_for_exit(child):
    """Observe completion without reaping the process group leader, so its group ID stays valid."""
    import select
    if WINDOWS:
        # The job object, not the leader's ID, holds the descendants here.
        child.wait()
    elif hasattr(os, 'waitid'):
        while os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
            time.sleep(0.05)
    elif hasattr(select, 'kqueue'):
        import contextlib
        with contextlib.closing(select.kqueue()) as queue:
            event=select.kevent(child.pid, filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT)
            try:
                queue.control([event], 0, 0)
                queue.control(None, 1, None)
            except ProcessLookupError:
                # Already exited, still unreaped because this scope owns the Popen object.
                pass
    else:
        raise RuntimeError('OH process ownership requires Linux waitid or macOS kqueue')


def replace(source,target):
    """os.replace. Windows refuses it while a reader briefly holds the target open, so retry."""
    if not WINDOWS:return os.replace(source,target)
    if os.path.isdir(target) and not os.listdir(target):os.rmdir(target)  # POSIX renames onto an empty directory
    for delay in (.05,.1,.2,.4,.8,None):
        try:return os.replace(source,target)
        except PermissionError:
            if delay is None:raise
            time.sleep(delay)


def sync_directory(path):
    # Windows cannot open a directory to flush it; NTFS journals the rename itself.
    if WINDOWS:return
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def sync_file(path):
    # Windows flushes only a handle opened for writing.
    with open(path,'r+b' if WINDOWS else 'rb') as stream:os.fsync(stream.fileno())


def uname():
    if hasattr(os,'uname'):return os.uname()
    import platform
    return tuple(platform.uname())[:5]
