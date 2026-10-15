"""The few operating-system differences in OH. Each has one POSIX and one Windows branch."""
import errno
import functools
import os
import shutil
import signal
import subprocess
import time

WINDOWS=os.name=='nt'

if WINDOWS:
    # Windows also looks for a bare command such as git in the current folder, which can be a checkout a
    # worker writes. This variable turns that off for OH and every process it starts (see also cli.main).
    os.environ['NoDefaultCurrentDirectoryInExePath']='1'
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
    _advapi32=ctypes.WinDLL('advapi32',use_last_error=True)
    _advapi32.GetNamedSecurityInfoW.argtypes=[wintypes.LPCWSTR,ctypes.c_int,wintypes.DWORD]+[ctypes.POINTER(ctypes.c_void_p)]*5
    _advapi32.GetNamedSecurityInfoW.restype=wintypes.DWORD
    _advapi32.ConvertSidToStringSidW.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_wchar_p)];_advapi32.ConvertSidToStringSidW.restype=wintypes.BOOL
    _advapi32.GetAce.argtypes=[ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(ctypes.c_void_p)];_advapi32.GetAce.restype=wintypes.BOOL
    _advapi32.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)];_advapi32.OpenProcessToken.restype=wintypes.BOOL
    _advapi32.GetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    _advapi32.GetTokenInformation.restype=wintypes.BOOL
    _advapi32.SetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    _advapi32.SetTokenInformation.restype=wintypes.BOOL
    _kernel32.GetCurrentProcess.restype=wintypes.HANDLE;_kernel32.LocalFree.argtypes=[ctypes.c_void_p];_kernel32.LocalFree.restype=ctypes.c_void_p
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


def executable(program,*,env=None,cwd=None):
    """Resolve native Windows programs; bare Bash must not silently enter WSL."""
    if not WINDOWS:return program
    if os.path.dirname(program):
        return os.path.join(cwd,program) if cwd and not os.path.isabs(program) else program
    env=os.environ if env is None else env
    path=env.get('PATH','')
    found=shutil.which(program,path=path)
    if program.lower() not in ('bash','bash.exe'):return found or program
    windows=env.get('SystemRoot') or os.environ.get('SystemRoot',r'C:\Windows')
    wsl={os.path.normcase(os.path.realpath(os.path.join(windows,folder,'bash.exe')))
         for folder in ('System32','SysWOW64','Sysnative')}
    # The Microsoft Store WSL alias may precede System32 and Git for Windows on PATH.
    local=env.get('LOCALAPPDATA') or os.environ.get('LOCALAPPDATA')
    if local:wsl.add(os.path.normcase(os.path.realpath(os.path.join(local,'Microsoft','WindowsApps','bash.exe'))))
    candidates=[found]+[os.path.join(folder,'bash.exe') for folder in path.split(os.pathsep) if folder]
    git=shutil.which('git',path=path)
    if git:
        base=os.path.dirname(os.path.dirname(git))
        candidates += [os.path.join(base,'bin','bash.exe'),os.path.join(base,'usr','bin','bash.exe')]
    candidates += [os.path.join(env[name],'Git','bin','bash.exe')
                   for name in ('ProgramFiles','ProgramFiles(x86)') if env.get(name)]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.path.normcase(os.path.realpath(candidate)) not in wsl:
            return candidate
    raise FileNotFoundError(errno.ENOENT,
        'Native Windows Bash is unavailable. Install Git for Windows or register an explicit WSL command',program)


def spawn(command,**kwargs):
    """Start a command that stop() can end together with every descendant."""
    if not WINDOWS:return subprocess.Popen(command,start_new_session=True,**kwargs)
    # CreateProcess needs PATHEXT shims and resolves relative executables against OH rather than cwd.
    command=[executable(command[0],env=kwargs.get('env'),cwd=kwargs.get('cwd')),*command[1:]]
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


def stop(child,*,force=False,interrupt=False):
    """Ask the child's process group to end, or end it and all descendants at once with force."""
    if WINDOWS:
        # CTRL_BREAK to a group whose leader has exited can reach every process on the console, OH included.
        if not force and child.poll() is None:
            try:os.kill(child.pid,signal.CTRL_BREAK_EVENT)
            except OSError:pass
        elif force:_kernel32.TerminateJobObject(child.oh_job,1)
        return
    try:os.killpg(child.pid,signal.SIGKILL if force else signal.SIGINT if interrupt else signal.SIGTERM)
    except ProcessLookupError:pass
    except PermissionError:
        # Darwin reports EPERM for a group containing only unreaped zombies.
        rows=subprocess.check_output(['/bin/ps','-axo','pgid=,stat='],text=True).splitlines()
        live=[row.split() for row in rows if len(row.split())==2 and row.split()[0]==str(child.pid) and not row.split()[1].startswith('Z')]
        if live:raise


def wait_for_exit(child, timeout=None):
    """Observe completion without reaping the process group leader, so its group ID stays valid."""
    import select
    if WINDOWS:
        # The job object, not the leader's ID, holds the descendants here.
        try:child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:return False
    elif hasattr(os, 'waitid'):
        deadline=time.monotonic()+timeout if timeout is not None else None
        while os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
            if deadline is not None and time.monotonic()>=deadline:return False
            time.sleep(.05 if deadline is None else min(.05,max(0,deadline-time.monotonic())))
    elif hasattr(select, 'kqueue'):
        import contextlib
        with contextlib.closing(select.kqueue()) as queue:
            event=select.kevent(child.pid, filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT)
            try:
                queue.control([event], 0, 0)
                return bool(queue.control(None, 1, timeout))
            except ProcessLookupError:
                # Already exited, still unreaped because this scope owns the Popen object.
                pass
    else:
        raise RuntimeError('OH process ownership requires Linux waitid or macOS kqueue')
    return True


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


# Who may change a trusted file on Windows: you, the system, administrators and the installer service.
TRUSTED_SIDS={'S-1-5-18','S-1-5-32-544','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'}
# Rights that let someone replace or change what runs: DELETE, WRITE_DAC, WRITE_OWNER and GENERIC_ALL anywhere;
# writing the file itself; adding a file (a planted DLL) or deleting one in its folder; deleting in any folder above.
_ALWAYS=0x10000|0x40000|0x80000|0x10000000
_RIGHTS={'file':_ALWAYS|0x2|0x4|0x40000000,'folder':_ALWAYS|0x2|0x40|0x40000000,'above':_ALWAYS|0x40}


def _sid_text(sid):
    text=ctypes.c_wchar_p()
    if not _advapi32.ConvertSidToStringSidW(sid,ctypes.byref(text)):raise ctypes.WinError(ctypes.get_last_error())
    try:return text.value
    finally:_kernel32.LocalFree(ctypes.cast(text,ctypes.c_void_p))


@functools.cache
def _current_user():
    token=wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(_kernel32.GetCurrentProcess(),0x0008,ctypes.byref(token)):  # TOKEN_QUERY
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size=wintypes.DWORD()
        _advapi32.GetTokenInformation(token,1,None,0,ctypes.byref(size))  # TokenUser
        buffer=ctypes.create_string_buffer(size.value)
        if not _advapi32.GetTokenInformation(token,1,buffer,size,ctypes.byref(size)):raise ctypes.WinError(ctypes.get_last_error())
        return _sid_text(ctypes.cast(buffer,ctypes.POINTER(ctypes.c_void_p))[0])
    finally:_kernel32.CloseHandle(token)


def _user_owned_objects():
    # Elevated Windows tokens default to Administrators as owner. Python's private directories
    # grant OWNER RIGHTS, so inheriting that owner locks the same account out after elevation ends.
    # Change only this process's default owner, retaining its privileges and all private ACLs.
    token=wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(_kernel32.GetCurrentProcess(),0x0088,ctypes.byref(token)):  # QUERY | ADJUST_DEFAULT
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        values=[]
        for kind in (1,4):  # TokenUser, TokenOwner
            size=wintypes.DWORD()
            _advapi32.GetTokenInformation(token,kind,None,0,ctypes.byref(size))
            buffer=ctypes.create_string_buffer(size.value)
            if not _advapi32.GetTokenInformation(token,kind,buffer,size,ctypes.byref(size)):raise ctypes.WinError(ctypes.get_last_error())
            values.append(buffer)
        user,owner=[ctypes.cast(buffer,ctypes.POINTER(ctypes.c_void_p))[0] for buffer in values]
        if _sid_text(user)!=_sid_text(owner):
            chosen=ctypes.c_void_p(user)  # TOKEN_OWNER contains one SID pointer.
            if not _advapi32.SetTokenInformation(token,4,ctypes.byref(chosen),ctypes.sizeof(chosen)):
                raise ctypes.WinError(ctypes.get_last_error())
    finally:_kernel32.CloseHandle(token)


if WINDOWS:_user_owned_objects()


def untrusted(path,kind):
    """Why someone other than you, the system or administrators can change this Windows file or folder, or
    None. kind: 'file' (the program), 'folder' (the folder holding it) or 'above' (any folder further up)."""
    owner,dacl,descriptor=ctypes.c_void_p(),ctypes.c_void_p(),ctypes.c_void_p()
    error=_advapi32.GetNamedSecurityInfoW(str(path),1,0x1|0x4,ctypes.byref(owner),None,ctypes.byref(dacl),None,ctypes.byref(descriptor))
    if error:raise ctypes.WinError(error)
    try:
        trusted=TRUSTED_SIDS|{_current_user()}
        if _sid_text(owner) not in trusted:return 'is owned by '+_sid_text(owner)
        # OWNER RIGHTS denotes this object's owner, which has just passed the trust check.
        trusted=trusted|{'S-1-3-4'}
        if not dacl.value:return 'has no access list, so everyone can change it'
        count=ctypes.cast(dacl.value+4,ctypes.POINTER(ctypes.c_ushort))[0]  # ACL: revision, padding, size, AceCount
        for index in range(count):
            ace=ctypes.c_void_p()
            if not _advapi32.GetAce(dacl,index,ctypes.byref(ace)):raise ctypes.WinError(ctypes.get_last_error())
            kind_of,flags=ctypes.cast(ace,ctypes.POINTER(ctypes.c_ubyte))[0:2]
            if kind_of in (1,6,10,12) or flags&0x08:continue  # deny entries, and ones only inherited by children
            if kind_of!=0:return 'has an access entry of a kind OH does not read'  # fail closed
            mask=ctypes.cast(ace.value+4,ctypes.POINTER(wintypes.DWORD))[0]
            if mask&_RIGHTS[kind] and (who:=_sid_text(ace.value+8)) not in trusted:return 'lets '+who+' change it'
        return None
    finally:_kernel32.LocalFree(descriptor)


def uname():
    if hasattr(os,'uname'):return os.uname()
    import platform
    return tuple(platform.uname())[:5]
