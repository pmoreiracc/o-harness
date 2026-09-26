from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from .system import lock_file, replace, sync_directory, unlock_file


NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)  # Windows has no O_NOFOLLOW


class Refused(RuntimeError):
    pass


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
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
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
    path = Path(path)
    if path.is_symlink():
        raise Refused('State files must not be symlinks')
    return json.loads(path.read_text())


@contextlib.contextmanager
def lock(path, *, wait=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
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


def git(root, *args):
    return git_bytes(root, *args).decode().strip()


def git_bytes(root, *args, quiet=False):
    env = {k: v for k, v in os.environ.items() if k not in {
        'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY',
        'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_COMMON_DIR', 'GIT_NAMESPACE', 'GIT_PREFIX'}}
    return subprocess.check_output(['git', '-C', str(root), *args], env=env,
                                   stderr=subprocess.DEVNULL if quiet else None)


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
        self.path = state_home() / 'projects' / validate_id(project_id) / 'runs' / validate_id(run_id)

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
