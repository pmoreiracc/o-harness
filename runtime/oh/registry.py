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
    return {'root': str(root), 'admin': str(admin), 'common': str(common),
            'root_identity': stamp(root), 'admin_identity': stamp(admin),
            'common_identity': stamp(common)}


def stamp(path):
    st = Path(path).stat()
    value = {'device': st.st_dev, 'inode': st.st_ino}
    # Directory mtime/ctime change during normal Git work. Birth time does not.
    if hasattr(st, 'st_birthtime'):
        value['birth'] = st.st_birthtime
    return value


def verified(recorded):
    """Whether a recorded checkout is still there, with the same folder and Git folders (no Git call)."""
    try:return all(stamp(recorded[key]) == recorded[key + '_identity'] for key in ('root', 'admin', 'common'))
    except (OSError, KeyError, TypeError, ValueError):return False


def index_path(root):
    return state_home() / 'registry' / 'checkouts' / (digest(str(Path(root).resolve())) + '.json')


def lookup(root):
    path = index_path(root)
    if not path.is_file():
        raise Refused('Project is not registered. Run oh init once for this checkout.')
    value = read_json(path)
    if value.get('schema_version') != 1 or value.get('identity') != identity(root):
        raise Refused('Checkout identity changed. For a new checkout at this path, run oh init --name <name> --replace; '
                      'for a moved one, reattach it. Old grants were not reused.')
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
        note, joined = None, False
        if not (attach or reattach) and (replace or not path.exists()):
            # A new project needs a free name, checked before anything changes so a refusal changes nothing.
            # A checkout of the Git repository of the project that has the name (a worktree, or one recreated
            # at an old path) joins that project, as --attach would, with a fresh checkout id and no grants.
            # Without birth times (Linux), a folder id can be reused, so only a registration still in place counts.
            from .config import name_of, projects_named, registrations
            here = str(Path(root).resolve())
            holders = projects_named(name, excluding_root=here)
            same = {p for p, found in registrations().items() if name_of(p) == name and any(
                    e.get('common_identity') == current['common_identity'] and e['root'] != here
                    and (verified(e) or 'birth' in current['common_identity']) for e in found)}
            if len(same) == 1 and holders <= same and not imported:
                attach, joined = next(iter(same)), True
                note = f'This checkout belongs to the Git repository of {name}, so it joined that project: its settings and checks apply here.'
            else:free(name, excluding_root=here)
        if replace:
            if (attach and not joined) or reattach or imported:raise Refused('Replacement needs a fresh profile; it cannot import old grants')
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
            from .config import name_of, projects_named
            taken = projects_named(name_of(previous['project'])) - {previous['project']}
            if taken:
                raise Refused(f'Another project took the name {name_of(previous["project"])} while this checkout was away. '
                              'Rename that project first (oh --root <its checkout> rename <new name>), then reattach.')
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
        return value | ({'note': note, 'joined': name} if joined else {})


def free(name, project=None, excluding_root=None):
    """A project name picks its section of the settings file, so no two present projects share one."""
    from .config import projects_named, registrations
    others = projects_named(name, excluding_root) - {project}
    if others:
        where = ', '.join(sorted(e['root'] for p in others for e in registrations()[p] if e['root'] != excluding_root))
        raise Refused(f'Another OH project is already named {name} ({where}); choose another name')


@state_writer
def rename(root, name):
    """Gives a project a new name, and its section of the settings file with it. Refuses to take over a
    section that already holds other settings; when another project still has the old name (from before
    names were unique), the section stays theirs and this project starts from an empty one."""
    from .config import edit, load_global, projects_named, section_differences
    if not isinstance(name, str) or not name.strip() or name != name.strip():raise Refused('A project name needs text without surrounding spaces')
    with lock(state_home() / 'registry' / '.lock'):
        value = profile(root)
        if value['name'] == name:return value
        free(name, value['id'])
        old, base, outcome, path = value['name'], load_global(), {}, state_home() / 'projects' / value['id'] / 'profile.json'
        def move(data):
            projects = data.setdefault('projects', {})
            if not isinstance(projects, dict):raise Refused('projects in the settings file must be an object; fix it with oh config open')
            shared = bool(projects_named(old) - {value['id']})
            mine, theirs = ({} if shared else projects.get(old) or {}), projects.get(name) or {}
            if theirs and (not mine or section_differences(theirs, mine, base)):
                raise Refused(f'projects.{name} already holds settings of an earlier project named {name}'
                              + (f' ({", ".join(section_differences(theirs, mine, base))} differ)' if mine else '')
                              + '; remove them with oh config open, or choose another name')
            if mine or not shared:projects.pop(old, None)
            projects[name] = theirs or mine
            outcome['section'] = (f'projects.{old} stays with the other project named {old}; projects.{name} starts empty'
                                  if shared else f'projects.{old} is now projects.{name}')
            atomic_json(path, value | {'name': name})  # under the settings lock, so no change lands in between
        try:edit(root, 'global', move)
        except BaseException:
            if read_json(path).get('name') == name:atomic_json(path, value)  # the settings weren't written
            raise
    return profile(root) | outcome
