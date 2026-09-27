"""Private document ownership lives in OH state, never in the document folder."""
from pathlib import Path
import unicodedata
from .storage import Refused, atomic_json, digest, lock, read_json, state_home, state_writer


def canonical(path):
    # Conservative across case-insensitive and Unicode-normalizing filesystems.
    return unicodedata.normalize('NFC', str(Path(path).resolve())).casefold()


def folder_lock(base):
    return state_home() / 'registry/private-plan-locks' / (digest(canonical(base)) + '.lock')


@state_writer
def reserve(base, owner, *, claim=True):
    """A folder remains reserved after rename or checkout deletion; only explicit replacement transfers it."""
    from .config import present_projects
    base=Path(base);key=canonical(base);home=state_home()
    path=home/'registry/private-plans.json'
    with lock(home/'registry/private-plans.lock'):
        records=read_json(path) if path.exists() else {}
        previous=owner.get('private_plans_previous_owner')
        transferable=(previous and owner.get('private_plans_path') and canonical(owner['private_plans_path'])==key
                      and previous not in present_projects())
        for other,record in records.items():
            if Path(key).is_relative_to(Path(other)) or Path(other).is_relative_to(Path(key)):
                if record['project'] != owner['id'] and not (other==key and transferable and record['project']==previous):
                    raise Refused(f'Private plan folder {base} belongs to another project; choose another project name or plans.private_folder')
        legacy=home/'projects'/owner.get('private_plans_legacy',owner['id'])/'plans'
        if key not in records and base.exists() and canonical(legacy)!=key and not transferable:
            raise Refused(f'Private plan folder {base} already exists without ownership; preserve it and choose an empty plans.private_folder')
        if claim and records.get(key,{}).get('project') != owner['id']:
            # A replaced checkout may still have a finishing writer. Never transfer its folder mid-edit.
            if key in records:
                with lock(folder_lock(base),wait=False):
                    records[key]={'project':owner['id'],'path':str(base)}
                    atomic_json(path,records)
                return
            records[key]={'project':owner['id'],'path':str(base)}
            atomic_json(path,records)
