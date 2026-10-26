"""The few operating-system differences in OH. Each has one POSIX and one Windows branch."""
import errno
import contextlib
import functools
import os
import shutil
import signal
import subprocess
import sys
import time
import tempfile
import uuid
from pathlib import Path as _Path, WindowsPath as _WindowsPath

WINDOWS=os.name=='nt'


def make_temp_directory(*,prefix='oh-',dir=None):
    """Own a fresh scratch directory without dropping the Windows parent's host access."""
    if not WINDOWS:return tempfile.mkdtemp(prefix=prefix,dir=dir)
    parent=Path(dir if dir is not None else tempfile.gettempdir())
    for _ in range(100):
        path=parent/(prefix+uuid.uuid4().hex)
        try:path.mkdir()
        except FileExistsError:continue
        return str(path.absolute())
    raise FileExistsError('Could not allocate a unique OH scratch directory')


@contextlib.contextmanager
def temporary_directory(*,prefix='oh-',dir=None):
    if not WINDOWS:
        with tempfile.TemporaryDirectory(prefix=prefix,dir=dir) as path:yield path
        return
    path=make_temp_directory(prefix=prefix,dir=dir)
    def readonly(function,name,error):
        if not isinstance(error,PermissionError):raise error
        if not os.path.islink(name) and not os.path.isjunction(name):os.chmod(name,0o700)
        function(name)
    try:yield path
    finally:shutil.rmtree(Path(path),onexc=readonly)


if WINDOWS:
    class Path(_WindowsPath):
        """Keep portable saved identities; use extended Windows paths only for I/O.

        Reopening a path from an old journal must work exactly like a newly built
        path. Do not persist the OS prefix or require a machine-wide policy change.
        """
        def __init__(self, *parts):
            def ordinary(part):
                value=str(part) if isinstance(part, _Path) else os.fspath(part)
                if value[:8].upper()=='\\\\?\\UNC\\':return '\\\\'+value[8:]
                if value.startswith('\\\\?\\'):return value[4:]
                return value
            super().__init__(*(ordinary(part) for part in parts))

        def __fspath__(self):
            value=os.path.abspath(str(self))
            if value.startswith('\\\\.\\'):return value
            return '\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value
else:
    Path=_Path


def file_uri(path):
    """SQLite URI with the native path and literal filename punctuation preserved."""
    from urllib.parse import quote
    return 'file:'+quote(os.fspath(Path(path).absolute()),safe='/:')


def windows_command_words(command):
    """Decode a literal Windows command line using the OS argument parser."""
    if not WINDOWS:return None
    shell32=ctypes.WinDLL('shell32',use_last_error=True)
    split=shell32.CommandLineToArgvW
    split.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)]
    split.restype=ctypes.POINTER(ctypes.c_wchar_p)
    count=ctypes.c_int()
    words=split(command,ctypes.byref(count))
    if not words:raise ctypes.WinError(ctypes.get_last_error())
    try:return [words[i] for i in range(count.value)]
    finally:_kernel32.LocalFree(words)

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
    class _JobLimits(ctypes.Structure):
        _fields_=[('times',ctypes.c_int64*2),('flags',wintypes.DWORD),
                  ('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),
                  ('count',wintypes.DWORD),('affinity',ctypes.c_size_t),
                  ('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]

    class _JobExtended(ctypes.Structure):
        _fields_=[('basic',_JobLimits),('io',ctypes.c_uint64*6),('memory',ctypes.c_size_t*4)]

    _kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
    for _name,_args in (('LockFileEx',[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(_Overlapped)]),
                        ('UnlockFileEx',[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(_Overlapped)]),
                        ('AssignProcessToJobObject',[wintypes.HANDLE,wintypes.HANDLE]),
                        ('TerminateJobObject',[wintypes.HANDLE,wintypes.UINT]),('CloseHandle',[wintypes.HANDLE])):
        getattr(_kernel32,_name).argtypes=_args;getattr(_kernel32,_name).restype=wintypes.BOOL
    _kernel32.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];_kernel32.CreateJobObjectW.restype=wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    _kernel32.OpenJobObjectW.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR]
    _kernel32.OpenJobObjectW.restype=wintypes.HANDLE
    _kernel32.QueryInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p]
    _advapi32=ctypes.WinDLL('advapi32',use_last_error=True)
    _advapi32.GetNamedSecurityInfoW.argtypes=[wintypes.LPCWSTR,ctypes.c_int,wintypes.DWORD]+[ctypes.POINTER(ctypes.c_void_p)]*5
    _advapi32.GetNamedSecurityInfoW.restype=wintypes.DWORD
    _advapi32.GetSecurityDescriptorControl.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ushort),ctypes.POINTER(wintypes.DWORD)]
    _advapi32.GetSecurityDescriptorControl.restype=wintypes.BOOL
    _advapi32.SetNamedSecurityInfoW.argtypes=[ctypes.c_wchar_p,ctypes.c_int,wintypes.DWORD]+[ctypes.c_void_p]*4
    _advapi32.SetNamedSecurityInfoW.restype=wintypes.DWORD
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


def spawn(command,*,on_spawn=None,**kwargs):
    """Start a command that stop() can end together with every descendant."""
    # A filesystem prefix is not a process cwd: cmd treats it as an unsupported UNC folder.
    if kwargs.get('cwd') is not None:kwargs['cwd']=str(Path(kwargs['cwd']))
    if not WINDOWS:
        if on_spawn is None:return subprocess.Popen(command,start_new_session=True,**kwargs)
        # Release execution only after its process identity is durably saved.
        # Owner death closes the gate: EOF exits without executing the command.
        reader,writer=os.pipe()
        gate=('import os,sys;fd=int(sys.argv[1]);ok=os.read(fd,1)==b"1";os.close(fd);'
              'sys.exit(130) if not ok else os.execvpe(sys.argv[2],sys.argv[2:],os.environ)')
        try:
            child=subprocess.Popen([sys.executable,'-I','-c',gate,str(reader),*command],
                start_new_session=True,pass_fds=(*kwargs.pop('pass_fds',()),reader),**kwargs)
            try:
                on_spawn(child)
                os.write(writer,b'1')
                return child
            except BaseException:
                stop(child,force=True);child.wait(timeout=10);raise
        finally:
            os.close(reader);os.close(writer)
    # CreateProcess needs PATHEXT shims and resolves relative executables against OH rather than cwd.
    command=[executable(command[0],env=kwargs.get('env'),cwd=kwargs.get('cwd')),*command[1:]]
    # Start suspended and resume only inside a job object, so no descendant can be born outside it.
    child=subprocess.Popen(command,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP|0x4,**kwargs)  # CREATE_SUSPENDED
    import uuid
    name='Local\\OH-'+str(uuid.uuid4())
    job=_kernel32.CreateJobObjectW(None,name)
    limits=_JobExtended();limits.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not job or not _kernel32.SetInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits))
            or not _kernel32.AssignProcessToJobObject(job,int(child._handle))):
        # Without the job, descendants of an exited leader could outlive stop(); refuse instead.
        if job:_kernel32.CloseHandle(job)
        child.kill();child.wait()
        raise OSError('Could not contain '+str(command[0])+' in a job object')
    child.oh_job=job
    child.oh_job_name=name
    weakref.finalize(child,_kernel32.CloseHandle,job)
    if on_spawn:
        try:on_spawn(child)
        except BaseException:
            stop(child,force=True);child.wait(timeout=10);raise
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
        # /bin/ps cannot execute inside the native macOS sandbox. Read only this
        # owned group's status through libproc instead; denied/unknown remains an error.
        if sys.platform!='darwin' or _darwin_group_live(child.pid):raise


def _darwin_group_live(group):
    """libproc.h / sys/proc_info.h: PROC_PGRP_ONLY, PROC_PIDT_SHORTBSDINFO."""
    import ctypes
    class ShortInfo(ctypes.Structure):
        _fields_=[('pid',ctypes.c_uint32),('ppid',ctypes.c_uint32),
                  ('pgid',ctypes.c_uint32),('status',ctypes.c_uint32),
                  ('command',ctypes.c_char*16),('identity',ctypes.c_uint32*8)]
    lib=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True)
    lib.proc_listpids.argtypes=[ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_int]
    lib.proc_listpids.restype=ctypes.c_int
    lib.proc_pidinfo.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_uint64,ctypes.c_void_p,ctypes.c_int]
    lib.proc_pidinfo.restype=ctypes.c_int
    capacity=64
    while capacity<=65536:
        pids=(ctypes.c_int*capacity)()
        ctypes.set_errno(0)
        size=lib.proc_listpids(2,group,pids,ctypes.sizeof(pids))
        if size<=0:
            if error:=ctypes.get_errno():raise OSError(error,os.strerror(error))
            return False
        if size>=ctypes.sizeof(pids):
            capacity*=2
            continue
        for pid in pids[:size//ctypes.sizeof(ctypes.c_int)]:
            if not pid:continue
            info=ShortInfo()
            ctypes.set_errno(0)
            read=lib.proc_pidinfo(pid,13,0,ctypes.byref(info),ctypes.sizeof(info))
            if read!=ctypes.sizeof(info):
                error=ctypes.get_errno()
                if error==errno.ESRCH:continue
                raise OSError(error or errno.EPERM,'Cannot verify the owned process group')
            if info.pgid==group and info.status!=5:return True  # SZOMB
        return False
    raise OSError(errno.EAGAIN,'Owned process group changed while checking cleanup')


def process_identity(pid):
    """Kernel creation identity, not a process name or a reusable PID alone."""
    import ctypes
    if WINDOWS:
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        handle=kernel.OpenProcess(0x1000,False,pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            if ctypes.get_last_error()==87:return None
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            times=[wintypes.FILETIME() for _ in range(4)]
            kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
            if not kernel.GetProcessTimes(handle,*(ctypes.byref(t) for t in times)):
                raise ctypes.WinError(ctypes.get_last_error())
            return [times[0].dwHighDateTime,times[0].dwLowDateTime]
        finally:_kernel32.CloseHandle(handle)
    if sys.platform=='darwin':
        import ctypes
        class Info(ctypes.Structure):
            _fields_=[('ids',ctypes.c_uint32*12),('names',ctypes.c_char*48),
                      ('other',ctypes.c_uint32*6),('seconds',ctypes.c_uint64),('micros',ctypes.c_uint64)]
        lib=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True)
        lib.proc_pidinfo.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_uint64,ctypes.c_void_p,ctypes.c_int]
        lib.proc_pidinfo.restype=ctypes.c_int
        info=Info();size=lib.proc_pidinfo(pid,3,0,ctypes.byref(info),ctypes.sizeof(info))
        if size==ctypes.sizeof(info):return [info.seconds,info.micros]
        error=ctypes.get_errno()
        if error==errno.ESRCH:return None
        raise OSError(error or errno.EPERM,'Cannot read the owned process identity')
    from pathlib import Path
    try:return [Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]]
    except FileNotFoundError:return None


def group_live(pid):
    if sys.platform=='darwin':return _darwin_group_live(pid)
    if WINDOWS:raise OSError('Process-group recovery is unavailable on Windows')
    from pathlib import Path
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:fields=path.read_text().rsplit(')',1)[1].split()
        except FileNotFoundError:continue
        if int(fields[2])==pid and fields[0]!='Z':return True
    return False


def recover_process(record):
    """Clean a saved POSIX group only while its original leader is identifiable."""
    process=record.get('process')
    if not process:
        if record.get('gated'):return {'source':'command-never-released'}
        from datetime import datetime
        started=datetime.fromisoformat(record['started'].replace('Z','+00:00')).timestamp()
        try:boot=boot_time()
        except OSError:return None  # A restricted host cannot establish reboot cleanup.
        return {'source':'kernel-reboot','boot_time':boot} if boot>started else None
    if WINDOWS:
        name=process.get('job')
        if not name:return None
        job=_kernel32.OpenJobObjectW(0x0004|0x0008,False,name)  # QUERY | TERMINATE
        if not job:
            if ctypes.get_last_error()==2:return {'source':'kernel-job-absent','job':name}
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not _kernel32.TerminateJobObject(job,130):raise ctypes.WinError(ctypes.get_last_error())
            counters=(ctypes.c_uint64*6)()  # BASIC_ACCOUNTING_INFORMATION, 48 bytes
            until=time.monotonic()+2
            while True:
                if not _kernel32.QueryInformationJobObject(job,1,ctypes.byref(counters),48,None):
                    raise ctypes.WinError(ctypes.get_last_error())
                active=ctypes.cast(ctypes.byref(counters),ctypes.POINTER(wintypes.DWORD))[10]
                if not active:return {'source':'owned-job-cleaned','job':name}
                if time.monotonic()>=until:return None
                time.sleep(.02)
        finally:_kernel32.CloseHandle(job)
    pid=process['pid']
    if not group_live(pid):return {'source':'kernel-process-group-absent','pid':pid}
    if process.get('identity') is None or process_identity(pid)!=process['identity']:return None
    # No signal is sent to an unidentified/reused PID or group.
    # The owner has already died and Stop revoked the attempt. End the group
    # together; a graceful leader exit here would lose its identity before we
    # could end a descendant that ignores SIGTERM.
    try:os.killpg(pid,signal.SIGKILL)
    except ProcessLookupError:pass
    until=time.monotonic()+2
    while group_live(pid) and time.monotonic()<until:time.sleep(.02)
    return {'source':'owned-process-group-cleaned','pid':pid} if not group_live(pid) else None


def boot_time():
    """A reboot is conclusive cleanup even for old receipts without a process ID."""
    import ctypes
    if WINDOWS:
        _kernel32.GetTickCount64.restype=ctypes.c_uint64
        return time.time()-_kernel32.GetTickCount64()/1000
    if sys.platform=='darwin':
        import ctypes
        class Timeval(ctypes.Structure):
            _fields_=[('seconds',ctypes.c_long),('micros',ctypes.c_int)]
        value=Timeval();size=ctypes.c_size_t(ctypes.sizeof(value))
        lib=ctypes.CDLL(None,use_errno=True)
        if lib.sysctlbyname(b'kern.boottime',ctypes.byref(value),ctypes.byref(size),None,0):
            error=ctypes.get_errno();raise OSError(error,os.strerror(error))
        return value.seconds+value.micros/1_000_000
    from pathlib import Path
    return float(next(line.split()[1] for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime ')))


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
    source,target=Path(source),Path(target)
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
    with Path(path).open('r+b' if WINDOWS else 'rb') as stream:os.fsync(stream.fileno())


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


def copy_directory_access(source,target):
    """Preserve the empty data root's existing Windows policy across atomic restore."""
    if not WINDOWS:return
    dacl,descriptor=ctypes.c_void_p(),ctypes.c_void_p()
    error=_advapi32.GetNamedSecurityInfoW(os.fspath(source),1,4,None,None,ctypes.byref(dacl),None,ctypes.byref(descriptor))
    if error:raise ctypes.WinError(error)
    try:
        control=ctypes.c_ushort();revision=wintypes.DWORD()
        if not _advapi32.GetSecurityDescriptorControl(descriptor,ctypes.byref(control),ctypes.byref(revision)):raise ctypes.WinError(ctypes.get_last_error())
        flags=0x80000004 if control.value&0x1000 else 0x20000004
        error=_advapi32.SetNamedSecurityInfoW(os.fspath(target),1,flags,None,None,dacl,None)
        if error:raise ctypes.WinError(error)
    finally:_kernel32.LocalFree(descriptor)


def inherit_private_directory(path):
    """Let a legacy Python-0700 directory inherit its parent's existing access.

    Called only for directories below OH's data root. Never change the root, a
    different owner, or a custom ACL; no users or access rights are invented here.
    """
    if not WINDOWS:return False
    owner,dacl,descriptor=ctypes.c_void_p(),ctypes.c_void_p(),ctypes.c_void_p()
    error=_advapi32.GetNamedSecurityInfoW(os.fspath(path),1,0x1|0x4,ctypes.byref(owner),None,ctypes.byref(dacl),None,ctypes.byref(descriptor))
    if error==5:return False  # No ACL authority: leave it alone and let the actual I/O enforce access.
    if error:raise ctypes.WinError(error)
    try:
        control=ctypes.c_ushort();revision=wintypes.DWORD()
        get_control=_advapi32.GetSecurityDescriptorControl
        if not get_control(descriptor,ctypes.byref(control),ctypes.byref(revision)):raise ctypes.WinError(ctypes.get_last_error())
        if not control.value&0x1000 or not dacl.value or _sid_text(owner)!=_current_user():return False  # SE_DACL_PROTECTED
        count=ctypes.cast(dacl.value+4,ctypes.POINTER(ctypes.c_ushort))[0]
        if count!=3:return False
        entries=set()
        for index in range(count):
            ace=ctypes.c_void_p()
            if not _advapi32.GetAce(dacl,index,ctypes.byref(ace)):raise ctypes.WinError(ctypes.get_last_error())
            kind,flags=ctypes.cast(ace,ctypes.POINTER(ctypes.c_ubyte))[0:2]
            mask=ctypes.cast(ace.value+4,ctypes.POINTER(wintypes.DWORD))[0]
            if (kind,flags,mask)!=(0,3,0x1f01ff):return False  # allow, object/container inherit, full control
            entries.add(_sid_text(ace.value+8))
        if entries!={'S-1-3-4','S-1-5-18','S-1-5-32-544'}:return False
        set_security=_advapi32.SetNamedSecurityInfoW
        # Keep the exact explicit DACL and enable inheritance; do not request SACL/owner privileges.
        error=set_security(os.fspath(path),1,0x20000004,None,None,dacl,None)
        if error:raise ctypes.WinError(error)
        return True
    finally:_kernel32.LocalFree(descriptor)


def untrusted(path,kind):
    """Why someone other than you, the system or administrators can change this Windows file or folder, or
    None. kind: 'file' (the program), 'folder' (the folder holding it) or 'above' (any folder further up)."""
    owner,dacl,descriptor=ctypes.c_void_p(),ctypes.c_void_p(),ctypes.c_void_p()
    error=_advapi32.GetNamedSecurityInfoW(os.fspath(Path(path)),1,0x1|0x4,ctypes.byref(owner),None,ctypes.byref(dacl),None,ctypes.byref(descriptor))
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
