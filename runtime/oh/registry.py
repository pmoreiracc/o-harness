"""External project profiles and checkout identities; consumers remain untouched."""
from pathlib import Path
from .storage import (Refused, atomic_json, digest, git, identifier, lock, read_json,
                      state_home, state_writer, validate_id)


def identity(root):
    root = Path(root).resolve(strict=True)
    top = Path(git(root, 'rev-parse', '--show-toplevel')).resolve(strict=True)
    if root != top:
        raise Refused('Select the repository root, not a subdirectory')
    admin = Path(git(root, 'rev-parse', '--absolute-git-dir')).resolve(strict=True)
    common = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve(strict=True)
    def stamp(path):
        st = path.stat()
        value = {'device': st.st_dev, 'inode': st.st_ino}
        # Directory mtime/ctime change during normal Git work. Birth time does not.
        if hasattr(st, 'st_birthtime'):
            value['birth'] = st.st_birthtime
        return value
    return {'root': str(root), 'admin': str(admin), 'common': str(common),
            'root_identity': stamp(root), 'admin_identity': stamp(admin),
            'common_identity': stamp(common)}


def index_path(root):
    return state_home() / 'registry' / 'checkouts' / (digest(str(Path(root).resolve())) + '.json')


def lookup(root):
    path = index_path(root)
    if not path.is_file():
        raise Refused('Project is not registered. Run oh init once for this checkout.')
    value = read_json(path)
    if value.get('schema_version') != 1 or value.get('identity') != identity(root):
        raise Refused('Checkout identity changed. Register the new checkout or explicitly reattach the moved checkout; old grants were not reused.')
    validate_id(value['checkout']); validate_id(value['project'])
    return value


def profile_path(root, name='profile.json'):
    if name != 'profile.json':
        raise Refused('Unknown project profile resource')
    return state_home() / 'projects' / lookup(root)['project'] / name


def profile(root):
    entry = lookup(root)
    value = read_json(state_home() / 'projects' / entry['project'] / 'profile.json')
    if value.get('id') != entry['project'] or value.get('kind') not in ('product', 'harness'):
        raise Refused('Invalid external project profile')
    return value


def checkout_state(root):
    return state_home() / 'checkout-state' / lookup(root)['checkout']


@state_writer
def register(root, name, kind='product', *, attach=None, reattach=None, imported=None, replace=False):
    """Onboarding grants no work. Reattachment is explicit and identity-checked."""
    if kind not in ('product', 'harness') or not isinstance(name, str) or not name.strip():
        raise Refused('A project needs a name and product/harness kind')
    current = identity(root)
    home = state_home()
    with lock(home / 'registry' / '.lock'):
        path = index_path(root)
        if imported:
            admin=Path(current['admin'])
            if any((admin/name).exists() for name in ('oh-active-run.json','oh-design-run.json')):
                raise Refused('An old run binding exists. Finish or stop it with its retained runtime and archive its binding before importing this checkout.')
        if replace:
            if attach or reattach or imported:raise Refused('Replacement needs a fresh profile; it cannot import old grants')
            if not path.exists():raise Refused('No prior checkout registration exists to replace')
            previous=read_json(path)
            if previous.get('identity')==current:raise Refused('This checkout has not been replaced; its existing registration remains authoritative')
            archive=home/'registry/retired'/(digest(previous)+'.json')
            if not archive.exists():atomic_json(archive,previous,immutable=True)
            path.unlink()
        if path.exists():
            existing = lookup(root)
            if attach and existing['project'] != attach:
                raise Refused('Checkout is already registered to another project')
            return profile(root)
        if reattach:
            validate_id(reattach)
            matches = [read_json(p) for p in (home / 'registry/checkouts').glob('*.json')
                       if read_json(p).get('checkout') == reattach]
            if len(matches) != 1:
                raise Refused('Moved checkout identity is missing or ambiguous')
            previous = matches[0]
            keys = ('root_identity', 'admin_identity', 'common_identity')
            if any(current[k] != previous['identity'][k] for k in keys):
                raise Refused('This is not the original moved checkout; register it separately')
            if Path(previous['identity']['root']).exists():
                raise Refused('Original checkout still exists; do not alias its active grants')
            entry = previous | {'identity': current}
            atomic_json(path, entry, immutable=True)
            # Old locator becomes a tombstone; it can never silently authorize a replacement.
            old = home / 'registry/checkouts' / (digest(previous['identity']['root']) + '.json')
            atomic_json(old, previous | {'moved_to': str(root), 'checkout': None})
            return profile(root)
        project_id = validate_id(attach) if attach else (validate_id(imported['id']) if imported else identifier())
        destination = home / 'projects' / project_id / 'profile.json'
        if attach:
            value = read_json(destination)
            known = [read_json(p) for p in (home / 'registry/checkouts').glob('*.json')]
            if not any(v.get('project') == attach and v['identity']['common_identity'] == current['common_identity'] for v in known):
                raise Refused('Automatic project attachment is limited to sibling worktrees; clones need separate registration')
        else:
            value = (dict(imported) if imported else {}) | {'schema_version': 1, 'id': project_id, 'name': name, 'kind': kind}
            if destination.exists() and read_json(destination) != value:
                raise Refused('Existing external profile differs; preserve it and resolve the import explicitly')
            if not destination.exists():
                atomic_json(destination, value, immutable=True)
        entry = {'schema_version': 1, 'checkout': identifier(), 'project': project_id, 'identity': current}
        atomic_json(path, entry, immutable=True)
        return value
