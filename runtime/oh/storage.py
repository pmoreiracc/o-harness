from __future__ import annotations

import contextlib
import hashlib
import json
import os
from .system import Path
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from .system import WINDOWS, inherit_private_directory, lock_file, replace, sync_directory, unlock_file


NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)  # Windows has no O_NOFOLLOW


class Refused(RuntimeError):
    pass


class Final(Refused):
    """A refusal that is the command's last word: said once, and the waiting command is spent."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def identifier():
    return str(uuid.uuid4())


def validate_id(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise Refused('Invalid durable ID')
    return value


def state_home():
    path = Path(os.environ.get('OH_DATA_HOME', str(Path.home() / '.local/share/o-harness'))).expanduser()
    if not path.exists():path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise Refused('OH data directory must not be a symlink')
    return path.resolve()


def state_path(path, *, directory=False):
    """Repair only legacy directory ACLs on the requested OH path, never a store-wide reset."""
    path=Path(path)
    if not WINDOWS:return path
    home=Path(os.environ.get('OH_DATA_HOME',str(Path.home()/'.local/share/o-harness'))).expanduser().absolute()
    target=(path if directory else path.parent).absolute()
    if not target.is_relative_to(home):return path
    current=home
    for part in ('',*target.relative_to(home).parts):
        if part:current=current/part
        try:info=current.lstat()
        except FileNotFoundError:break
        if info.st_file_attributes&0x400:raise Refused('OH storage path must not traverse a reparse point: '+str(current))
        if current!=home:inherit_private_directory(current)
    return path


def state_mkdir(path):
    path=state_path(path,directory=True)
    home=Path(os.environ.get('OH_DATA_HOME',str(Path.home()/'.local/share/o-harness'))).expanduser().absolute()
    # The root stays private. Descendants inherit its user/host permissions on Windows.
    inherited=WINDOWS and path.absolute()!=home and path.absolute().is_relative_to(home)
    path.mkdir(parents=True,exist_ok=True,mode=0o777 if inherited else 0o700)


import functools
import threading
_snapshot_local=threading.local()


@contextlib.contextmanager
def snapshot_guard(*,exclusive=False):
    home=state_home()
    key=str(home)
    held=getattr(_snapshot_local,'held',{})
    if key in held:
        if exclusive and not held[key]:raise Refused('Finish active OH work before taking a backup')
        yield;return
    path=home.parent/('.oh-snapshot-'+digest(key)+'.lock')
    fd=os.open(path,os.O_RDONLY if path.exists() and not exclusive else os.O_RDWR|os.O_CREAT|NOFOLLOW,0o600)
    try:
        try:lock_file(fd,shared=not exclusive,wait=not exclusive)
        except BlockingIOError:raise Refused('OH is writing state. Finish or stop the active run, then retry the backup or restore.')
        _snapshot_local.held=held|{key:exclusive}
        try:yield
        finally:_snapshot_local.held=held;unlock_file(fd)
    finally:os.close(fd)


def state_writer(function):
    @functools.wraps(function)
    def wrapped(*args,**kwargs):
        with snapshot_guard():return function(*args,**kwargs)
    return wrapped


@state_writer
def atomic_json(path, value, *, immutable=False):
    path = Path(path)
    state_mkdir(path.parent)
    if path.is_symlink():
        raise Refused('State files must not be symlinks')
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encode(value) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            os.link(temporary, path)  # atomic create; never overwrite evidence
            os.unlink(temporary)
        else:
            replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    path = state_path(path)
    if path.is_symlink():
        raise Refused('State files must not be symlinks')
    return json.loads(path.read_text())


@contextlib.contextmanager
def lock(path, *, wait=True):
    path = Path(path)
    state_mkdir(path.parent)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        try:
            lock_file(fd, wait=wait)
        except BlockingIOError:
            raise Refused('This checkout already has an active OH runner')
        try:
            yield
        finally:
            unlock_file(fd)


def git_env():
    """Keep Git configuration and credentials; select the checkout/index explicitly in each child."""
    return {k: v for k, v in os.environ.items() if k not in {
        'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY',
        'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_COMMON_DIR', 'GIT_NAMESPACE', 'GIT_PREFIX'}}


def git(root, *args, raw=False):
    # Input belongs to the host protocol, never Git. Inheriting a live MCP pipe
    # can block Windows Git even for rev-parse, before the tool helper starts.
    output=subprocess.check_output(['git', '-C', str(root), *args], env=git_env(),stdin=subprocess.DEVNULL)
    return output if raw else output.decode().strip()


@contextlib.contextmanager
def git_blobs(root):
    """Read exact blobs through one Git process, retaining only one blob at a time."""
    command=['git','-C',str(root),'cat-file','--batch']
    # File-backed stderr cannot fill a pipe while we read the binary stdout protocol.
    with tempfile.TemporaryFile() as errors, subprocess.Popen(command,env=git_env(),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors) as process:
        def read(oid):
            if len(oid) not in (40,64) or any(c not in '0123456789abcdef' for c in oid):
                raise Refused('Git blob reads require an exact object ID')
            try:
                process.stdin.write(oid.encode('ascii')+b'\n');process.stdin.flush()
            except BrokenPipeError:
                raise Refused('Git stopped before reading the candidate blob') from None
            header=process.stdout.readline(200).split()
            if (len(header)!=3 or header[:2]!=[oid.encode('ascii'),b'blob'] or not header[2].isdigit()):
                raise Refused('Git did not return the requested blob: '+oid)
            size=int(header[2]);data=process.stdout.read(size)
            if len(data)!=size or process.stdout.read(1)!=b'\n':
                raise Refused('Git returned incomplete blob contents: '+oid)
            return data
        try:
            yield read
            process.stdin.close()
            if code:=process.wait():
                errors.seek(0)
                raise subprocess.CalledProcessError(code,command,stderr=errors.read())
        finally:
            if process.poll() is None:process.kill()


def git_root(root):
    """Refuse a checkout redirected by Git configuration, including an inherited core.worktree."""
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != Path(root).resolve():
        raise Refused('Git resolves a different checkout root; select the registered root, correct core.worktree or initialize the child repository before resuming')


def matches_git(root,path,revision):
    """Accept Windows checkout line endings, without applying filters or dropping any other bytes."""
    actual=(Path(root)/path).read_bytes()
    approved=git(root,'cat-file','blob',revision+':'+path,raw=True)
    return actual==approved or actual.replace(b'\r\n',b'\n')==approved


def worktrees(root):
    """This repository's other worktrees that sit inside the checkout, such as those Claude keeps in
    .claude/worktrees, as paths relative to it. Each is its own checkout, never part of this one's changes."""
    here = Path(root).resolve();found = set()
    for line in git(root, 'worktree', 'list', '--porcelain').splitlines():
        if line.startswith('worktree ') and (path := Path(line[9:]).resolve()) != here and path.is_relative_to(here):
            found.add(path.relative_to(here).as_posix())
    return found


def status(root):
    """Git's changed and untracked paths, as (changes, nested). `nested` are this repository's worktrees inside the
    checkout: they are never its changes and OH never commits them. Any other repository inside it, such as one a
    worker cloned, is a change like any new folder."""
    env = git_env() | {'GIT_OPTIONAL_LOCKS':'0'}
    output = subprocess.run(['git', '-C', str(root), 'status', '--porcelain=v1', '-z', '--untracked-files=all'],
                            capture_output=True, check=True, env=env).stdout.decode().split('\0')
    paths, skip = [], False
    for entry in output:
        if skip or not entry:skip = False;continue
        paths.append(entry[3:]);skip = entry[0] in 'RC'  # a rename or copy is followed by its old path
    # Git lists an untracked nested repository as its folder, with a trailing slash.
    inside = worktrees(root) if any(p.endswith('/') for p in paths) else set()
    return [p for p in paths if p.rstrip('/') not in inside], [p.rstrip('/') for p in paths if p.rstrip('/') in inside]


def changes(root):
    """Paths Git sees as changed or untracked in the checkout, without the repositories nested in it."""
    return status(root)[0]


def whole(root):
    """The pathspec for the whole checkout except the repositories nested in it."""
    return ['--', '.', *(':(exclude,top)' + p for p in status(root)[1])]


def checkout_id(root):
    from .registry import lookup
    return lookup(root)['checkout']


def checkout_file(root, name):
    from .registry import checkout_state
    if not name or Path(name).name != name:
        raise Refused('Invalid checkout state filename')
    return checkout_state(root) / name


def project(root):
    from .registry import profile
    return profile(root)


class Journal:
    """Authoritative immutable records. SQLite is deliberately not used here."""
    def __init__(self, project_id, run_id):
        self.path = state_path(state_home() / 'projects' / validate_id(project_id) / 'runs' / validate_id(run_id),directory=True)

    def records(self):
        previous = None
        records = []
        for index, path in enumerate(sorted(self.path.glob('*.json')), 1):
            record = read_json(path)
            if path.name != f'{index:06}.json' or record['sequence'] != index or record['previous'] != previous:
                raise Refused('Incomplete or altered run journal; restore its backup')
            if record['hash'] != digest({k: v for k, v in record.items() if k != 'hash'}):
                raise Refused('Run journal digest mismatch')
            records.append(record)
            previous = record['hash']
        return records

    @state_writer
    def append(self, kind, data):
        with lock(self.path / '.lock'):
            records = self.records()
            record = {'sequence': len(records) + 1, 'previous': records[-1]['hash'] if records else None,
                      'id': identifier(), 'at': now(), 'kind': kind, 'data': data}
            record['hash'] = digest(record)
            atomic_json(self.path / f'{record["sequence"]:06}.json', record, immutable=True)
            return record
