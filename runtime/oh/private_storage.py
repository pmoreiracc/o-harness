"""Private document ownership lives in OH state, never in the document folder."""
from pathlib import Path
from contextlib import contextmanager, ExitStack
import unicodedata
from .storage import Refused, atomic_json, digest, lock, read_json, state_home, state_writer


def canonical(path):
    # Conservative across case-insensitive and Unicode-normalizing filesystems.
    return unicodedata.normalize('NFC', str(Path(path).resolve())).casefold()


def folder_lock(base):
    return state_home() / 'registry/private-plan-locks' / (digest(canonical(base)) + '.lock')


@contextmanager
def reservations(candidates, *, claim=True):
    """Reserve a group under one lock; publication errors restore the prior ownership map."""
    from .config import present_projects
    home=state_home();path=home/'registry/private-plans.json'
    with lock(home/'registry/private-plans.lock'), ExitStack() as guards:
        before=read_json(path) if path.exists() else {}
        records=dict(before);transfers=set()
        present=present_projects()
        for base,owner in candidates:
            base=Path(base);key=canonical(base)
            previous=owner.get('private_plans_previous_owner')
            transferable=(previous and owner.get('private_plans_path') and canonical(owner['private_plans_path'])==key
                          and previous not in present)
            for other,record in records.items():
                if Path(key).is_relative_to(Path(other)) or Path(other).is_relative_to(Path(key)):
                    if record['project'] != owner['id'] and not (other==key and transferable and record['project']==previous):
                        raise Refused(f'Private plan folder {base} belongs to another project; choose another project name or plans.private_folder')
            legacy=home/'projects'/owner.get('private_plans_legacy',owner['id'])/'plans'
            if key not in records and base.exists() and canonical(legacy)!=key and not transferable:
                raise Refused(f'Private plan folder {base} already exists without ownership; preserve it and choose an empty plans.private_folder')
            if records.get(key,{}).get('project') != owner['id']:
                if key in records:transfers.add(folder_lock(base))
                records[key]={'project':owner['id'],'path':str(base)}
        for transfer in sorted(transfers):guards.enter_context(lock(transfer,wait=False))
        changed=claim and records!=before
        if changed:atomic_json(path,records)
        try:yield
        except BaseException:
            if changed:atomic_json(path,before)
            raise


def reservation(base,owner,*,claim=True):
    return reservations([(base,owner)],claim=claim)


def configured_folders(data):
    """Effective private folders for all present projects, without loading or migrating settings."""
    from .config import layers,defaults,merge,present_projects
    from .plans import private_base
    top,projects=layers(data);home=state_home();result=[]
    for project in sorted(present_projects()):
        owner=read_json(home/'projects'/project/'profile.json')
        settings=merge(merge(defaults(),top),{k:v for k,v in projects.get(owner['name'],{}).items() if k!='checks'})['plans']
        if settings['location']!='private':continue
        legacy=home/'projects'/owner.get('private_plans_legacy',project)/'plans'
        base=Path(owner['private_plans_path']) if owner.get('private_plans_path') else legacy if legacy.is_dir() else private_base(settings['private_folder'],owner.get('private_plans_name',owner['name']))
        result.append((base,owner))
    return result


@state_writer
def reserve(base, owner, *, claim=True):
    with reservation(base,owner,claim=claim):pass


def owned(base, owner):
    path=state_home()/'registry/private-plans.json'
    with lock(state_home()/'registry/private-plans.lock'):
        return path.exists() and read_json(path).get(canonical(base),{}).get('project')==owner['id']
