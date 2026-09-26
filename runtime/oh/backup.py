from pathlib import Path
import shutil
import sqlite3
import tempfile
import hashlib
import json
import stat
from .storage import Refused, state_home, snapshot_guard,atomic_json,read_json
from .telemetry import connect
from .system import replace, sync_directory, sync_file


def inventory(source):
    result={}
    for path in sorted(source.rglob('*')):
        name=path.relative_to(source).as_posix()
        if name=='backup.json':continue
        mode=path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):raise Refused('Backup contains a symlink or unsupported file type')
        record={'type':'directory' if path.is_dir() else 'file','mode':stat.S_IMODE(mode)}
        if path.is_file():record.update(size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        result[name]=record
    return result


def validate(source,*,manifest=True):
    from .storage import digest
    observed=inventory(source)
    if manifest:
        value=read_json(source/'backup.json')
        if value.get('schema')!=2 or value.get('inventory')!=observed:raise Refused('Backup inventory failed integrity validation')
    for name,item in observed.items():
        if item['type']=='file' and name.endswith('.json'):
            try:read_json(source/name)
            except (ValueError,UnicodeError):raise Refused('Backup contains malformed JSON: '+name)
    for directory in (source/'projects').glob('*/runs/*'):
        previous=None
        for index,path in enumerate(sorted(directory.glob('[0-9]*.json')),1):
            value=read_json(path)
            if (path.name!=f'{index:06}.json' or value.get('sequence')!=index or value.get('previous')!=previous
                or value.get('hash')!=digest({k:v for k,v in value.items() if k!='hash'})):
                raise Refused('Backup run journal is incomplete or altered')
            previous=value['hash']
    database=source/'analytics.sqlite3'
    if not database.is_file():raise Refused('Backup has no analytics database')
    with sqlite3.connect('file:'+str(database)+'?mode=ro&immutable=1',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise Refused('Backup database failed integrity validation')


def sync_parent(path):
    sync_directory(path.parent)


def durable(directory):
    for path in directory.rglob('*'):
        if path.is_file():sync_file(path)
    for path in [p for p in directory.rglob('*') if p.is_dir()]+[directory]:sync_directory(path)


def backup(destination):
    destination=Path(destination).expanduser().resolve();home=state_home()
    if destination.exists() or destination.is_relative_to(home):raise Refused('Choose a new backup directory outside OH data')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with snapshot_guard(exclusive=True):
        temporary=Path(tempfile.mkdtemp(prefix='.oh-backup-',dir=destination.parent))
        try:
            for path in home.rglob('*'):
                if 'versions' not in path.relative_to(home).parts and path.is_symlink():raise Refused('OH state contains a symlink; inspect it before backup')
            with connect() as source:
                target=sqlite3.connect(temporary/'analytics.sqlite3')
                try:source.backup(target);target.execute('PRAGMA journal_mode=DELETE');target.commit()
                finally:target.close()
            for path in home.iterdir():
                if path.is_dir() and path.name not in ('versions','logs'):shutil.copytree(path,temporary/path.name)
            validate(temporary,manifest=False);atomic_json(temporary/'backup.json',{'schema':2,'inventory':inventory(temporary)})
            validate(temporary)
            durable(temporary);temporary.rename(destination);sync_parent(destination)
        finally:
            if temporary.exists():shutil.rmtree(temporary)
    return {'backup':str(destination),'authority':'projects/','analytics':'analytics.sqlite3'}


def restore(source):
    source=Path(source).expanduser().resolve();home=state_home()
    with snapshot_guard(exclusive=True):
        if any(home.iterdir()):raise Refused('Restore requires an empty OH data directory; preserve your existing directory first')
        validate(source)
        temporary=Path(tempfile.mkdtemp(prefix='.oh-restore-',dir=home.parent))
        try:
            shutil.copytree(source,temporary,dirs_exist_ok=True)
            validate(temporary);(temporary/'backup.json').unlink();durable(temporary)
            replace(temporary,home);sync_parent(home)
        finally:
            if temporary.exists():shutil.rmtree(temporary)
    return {'restored':str(home)}
