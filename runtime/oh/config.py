from __future__ import annotations

from copy import deepcopy
import json
import math
import os
import re
from pathlib import Path
from .storage import Refused, digest, git, read_json

HOME = Path(__file__).resolve().parents[2]
ROLES = ('simple', 'standard', 'complex', 'review', 'orchestrator')
EFFORTS = {'codex': {'low', 'medium', 'high', 'xhigh', 'max', 'ultra'},
           'claude': {'low', 'medium', 'high', 'xhigh', 'max'}}


MODEL = r'[A-Za-z0-9][A-Za-z0-9._:/-]*'
FOLDER = r'^(~(?:[/\\].*)?|/.*|[A-Za-z]:[\\/].*)'  # absolute, or in your home folder
PLAN_PATH = r'^(?!.*(^|/)\.\.?(/|$))[A-Za-z0-9_-][A-Za-z0-9._/-]*'  # relative, no . or .. parts
ROLE_MEANING = {'simple': 'small, bounded tasks', 'standard': 'ordinary tasks',
                'complex': 'cross-cutting or safety-sensitive tasks, and retries after a failure',
                'review': 'independent reviews', 'orchestrator': 'the session you talk to (a recommendation only)'}
SCHEMA_NAME = 'settings.schema.json'
MODES = ('review', 'pre-push', 'ci')
# Settings a release renamed or removed, as {old key: new key, or None}. OH rewrites settings.json
# once, after keeping a copy in backups/, so an update never breaks a setting or drops it silently.
RENAMED = {}


def rules():
    """Every setting, once: validation, `oh config` and the editor schema all derive from this."""
    def number(low, high):return {'type': 'integer', 'minimum': low, 'maximum': high}
    result = [('tasks_per_batch', number(1, 100), 'Tasks one approval covers; each "continue" approves this many more'),
              ('review_rounds', number(1, 100), 'Review rounds a task may use before OH asks you'),
              ('max_escalations', number(0, 2), 'Retries on the complex model after a failed attempt, before OH asks you'),
              ('context.handoff_chars', number(1000, 100000), 'Maximum task handoff text sent to a worker'),
              ('context.result_chars', number(1000, 100000), 'Maximum feedback text kept in model prompts'),
              ('context.compact_at_tokens', number(1000, 100000), 'Context size at which Codex workers compact (Codex only)'),
              ('plans.location', {'type': 'string', 'enum': ['ask', 'private', 'repo']},
               'Where roadmaps, design docs and decisions live: repo (committed in the repository), private (OH\'s folder), or ask'),
              ('plans.roadmap', {'type': 'string', 'pattern': PLAN_PATH + r'\.md$'}, 'Roadmap file, relative to where plans live'),
              ('plans.designs', {'type': 'string', 'pattern': PLAN_PATH + '$'}, 'Design docs folder, relative to where plans live'),
              ('plans.decisions', {'type': 'string', 'pattern': PLAN_PATH + '$'}, 'Decision records (ADRs) folder, relative to where plans live'),
              ('plans.private_folder', {'type': 'string', 'pattern': FOLDER},
               'Folder for private plans; each project gets a subfolder named after it')]
    for host in ('claude', 'codex'):
        for role in ROLES:
            result.append((f'models.{host}.{role}.model', {'type': 'string', 'pattern': '^' + MODEL + '$'},
                           f'{host.title()} model for {ROLE_MEANING[role]}'))
            result.append((f'models.{host}.{role}.effort', {'type': 'string', 'enum': sorted(EFFORTS[host])},
                           f'{host.title()} reasoning effort for {ROLE_MEANING[role]}'))
    return result


def check_rules():
    """One project check, as JSON Schema; `validate_checks` enforces the same rules."""
    strings = {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}
    return {'type': 'object', 'additionalProperties': False, 'required': ['name', 'command'], 'properties': {
        'name': {'type': 'string', 'minLength': 1, 'description': 'Shown in results'},
        'command': strings | {'minItems': 1, 'description': 'Program and arguments, run from the repository root without a shell; '
                                                           '{base} and {mode} are replaced'},
        'when': strings | {'description': 'Run only when a changed path matches one of these patterns'},
        'inputs': strings | {'minItems': 1, 'description': 'Repository paths whose contents decide whether a passing result is reused'},
        'toolchain': {'type': 'array', 'items': strings | {'minItems': 1},
                      'description': 'Version commands whose output also decides reuse, such as ["node", "--version"]'},
        'modes': {'type': 'array', 'items': {'enum': list(MODES)}, 'description': 'When the check runs; all of them by default'},
        'timeout_seconds': {'type': 'number', 'exclusiveMinimum': 0, 'description': 'Seconds before the check is stopped; 900 by default'}}}


CHECKS_MEANING = 'Commands that must pass before OH commits a task'


def lookup_key(value, key):
    for part in key.split('.'):
        value = value[part]
    return value


def merge(base, patch, origin=None, source=None, prefix=''):
    if not isinstance(patch, dict):
        raise Refused(f'{prefix.rstrip(".") or "Configuration"} must be an object')
    for key, value in patch.items():
        if key not in base:
            raise Refused(f'Unknown setting: {prefix}{key}. Run oh config to list the settings')
        if isinstance(base[key], dict):
            merge(base[key], value, origin, source, prefix + key + '.')
        else:
            base[key] = value
            if origin is not None:origin[prefix + key] = source
    return base


def allowed(spec):
    if 'enum' in spec:return 'one of: ' + ', '.join(spec['enum'])
    if spec['type'] == 'integer':return f'whole number from {spec["minimum"]} to {spec["maximum"]}'
    if spec['type'] == 'array':return 'a list of checks, each with a name and a command'
    if spec['pattern'] == FOLDER:return 'an absolute folder, or one starting with ~'
    if spec['pattern'].startswith(PLAN_PATH):return 'a relative path with no . or .. parts' + (', ending in .md' if spec['pattern'].endswith(r'\.md$') else '')
    return 'a model name your subscription offers'


def validate(value):
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise Refused('Unsupported configuration version')
    for key, spec, _ in rules():check(key, spec, lookup_key(value, key))
    return value


def check(key, spec, item):
    if spec['type'] == 'integer':valid = type(item) is int and spec['minimum'] <= item <= spec['maximum']
    elif 'enum' in spec:valid = item in spec['enum']
    else:valid = isinstance(item, str) and bool(re.fullmatch(spec['pattern'], item))
    if valid and spec.get('pattern') == FOLDER:
        valid = Path(os.path.expanduser(item)).is_absolute()
    if not valid:raise Refused(f'{key} must be {allowed(spec)}; got {json.dumps(item)}')


def validate_checks(value, label='checks'):
    def strings(items, least=0):
        return isinstance(items, list) and len(items) >= least and all(isinstance(x, str) and x for x in items)
    if not isinstance(value, list):raise Refused(f'{label} must be a list of checks')
    fields = check_rules()['properties']
    for index, item in enumerate(value):
        where = f'{label}[{index}]'
        if not isinstance(item, dict):raise Refused(f'{where} must be an object with a name and a command')
        for field in item:
            if field not in fields:raise Refused(f'Unknown check field: {where}.{field}. Allowed: {", ".join(fields)}')
        if not isinstance(item.get('name'), str) or not item['name'].strip():raise Refused(f'{where}.name must be a nonempty text')
        if not strings(item.get('command'), 1):raise Refused(f'{where}.command must be a nonempty list of nonempty texts')
        if 'when' in item and not strings(item['when']):raise Refused(f'{where}.when must be a list of path patterns')
        if 'inputs' in item and (not strings(item['inputs'], 1) or any(
                Path(x).is_absolute() or x.startswith(('/', '\\')) or '..' in re.split(r'[\\/]', x) for x in item['inputs'])):
            raise Refused(f'{where}.inputs must be a nonempty list of repository-relative paths')
        if 'toolchain' in item and (not isinstance(item['toolchain'], list) or not all(strings(x, 1) for x in item['toolchain'])):
            raise Refused(f'{where}.toolchain must be a list of commands, such as [["node", "--version"]]')
        if 'modes' in item and (not isinstance(item['modes'], list) or any(x not in MODES for x in item['modes'])):
            raise Refused(f'{where}.modes must be a list of: {", ".join(MODES)}')
        if 'timeout_seconds' in item:
            timeout = item['timeout_seconds']
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
                raise Refused(f'{where}.timeout_seconds must be a positive number')
    return value


def defaults():
    return read_json(HOME / 'config/defaults.json')


def config_home():
    """Your settings folder. A separate OH_DATA_HOME (a test, or a second install) keeps its own
    settings in its config folder, so it never reads or changes yours."""
    from .storage import state_home
    if os.environ.get('OH_DATA_HOME') and state_home() != (Path.home() / '.local/share/o-harness').resolve():
        return state_home() / 'config'
    xdg = os.environ.get('XDG_CONFIG_HOME', '')
    return (Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / '.config') / 'o-harness'


def settings_file():
    return config_home() / 'settings.json'


def protected_paths():
    """What workers may never write: the settings folder, and where a dotfiles link points."""
    home = config_home()
    return sorted({str(home), str(home.resolve()), str(settings_file().resolve().parent)})


def project_name(root, required=True):
    """The section of settings.json that holds this project's settings: projects.<name>. None only for
    a checkout that was never registered; any other registry problem is reported. A section belongs to
    one project, so a name two projects share is refused until one is renamed."""
    from .registry import index_path, profile
    if not required and not index_path(root).exists():return None
    value = profile(root)
    others = projects_named(value['name']) - {value['id']}
    if others:
        raise Refused(f'More than one OH project is named {value["name"]}, so OH can\'t tell whose settings projects.{value["name"]} '
                      f'holds. Give one of them its own name: oh --root <checkout> rename <new name> (the others: '
                      f'{", ".join(sorted(e["root"] for p in others for e in registrations()[p]))})')
    return value['name']


def project_id(root):
    from .registry import index_path, lookup
    return lookup(root)['project'] if root is not None and index_path(root).exists() else None


def registrations():
    """{project id: [checkout identities]} for current registrations; replaced or moved-away ones are left out."""
    from .storage import state_home
    result = {}
    for path in (state_home() / 'registry/checkouts').glob('*.json'):
        try:value = read_json(path)
        except (OSError, ValueError, Refused):continue
        if isinstance(value, dict) and value.get('checkout') and isinstance(value.get('project'), str) \
                and isinstance(value.get('identity'), dict) and isinstance(value['identity'].get('root'), str):
            result.setdefault(value['project'], []).append(value['identity'])
    return result


def name_of(project):
    from .storage import state_home
    try:return read_json(state_home() / 'projects' / project / 'profile.json')['name']
    except (OSError, ValueError, KeyError, TypeError, Refused):return None


def present_projects(excluding_root=None):
    """Registered projects with a checkout that is still the one registered. A deleted, recreated or
    restored checkout doesn't hold its name, nor does the registration one is replacing (`excluding_root`)."""
    from .registry import verified
    return {p for p, found in registrations().items() if any(e['root'] != excluding_root and verified(e) for e in found)}


def projects_named(name, excluding_root=None):
    return {p for p in present_projects(excluding_root) if name_of(p) == name}


def registered_names():
    return {name for name in map(name_of, present_projects()) if name is not None}


def strict_json(text):
    """JSON where a repeated key is an error, not a silent last-one-wins."""
    def pairs(items):
        seen = {}
        for key, value in items:
            if key in seen:raise ValueError(f'"{key}" appears twice')
            seen[key] = value
        return seen
    return json.loads(text, object_pairs_hook=pairs)


def check_location(*, creating=False):
    """Refuses, rather than falling back to OH's defaults, when this process looks for settings in
    another place than where they are (XDG_CONFIG_HOME set in one shell but not in a host, say), or
    when the file OH recorded is gone. `creating` lets oh config write a new file there."""
    from .storage import atomic_json, state_home
    current, inside = settings_file(), state_home() / 'config/settings.json'
    if inside != current and inside.exists() and not (current.exists() and os.path.samefile(inside, current)):
        raise Refused(f'Your settings are in {inside}, but OH now reads {current}. Move the file there.')
    marker = state_home() / 'config-location.json'
    try:recorded = Path(read_json(marker)['path'])
    except (OSError, ValueError, KeyError, TypeError, Refused):recorded = None
    same = recorded == current or (recorded and recorded.exists() and current.exists() and os.path.samefile(recorded, current))
    if recorded and not same and recorded.exists():
        raise Refused(f'Your settings are in {recorded}, but this OH process reads {current}. Set XDG_CONFIG_HOME '
                      '(and OH_DATA_HOME, if you use it) the same way wherever OH runs, or keep only one of the two files.')
    if recorded and not current.exists() and not creating and (same or not recorded.exists()):
        raise Refused(f'OH\'s settings file {recorded} is missing. If you moved it, set XDG_CONFIG_HOME so every process finds '
                      f'it there; to start again from OH\'s defaults, run oh config open or oh config set.')
    if current.exists() and not same:
        try:atomic_json(marker, {'path': str(current)})
        except (OSError, Refused):pass


def read_file(root=None, *, upgrade_first=True, creating=False):
    """settings.json exactly as written, or {} before it exists. Older settings files that couldn't be
    moved into it stop only the projects they belong to, or every project for the shared one."""
    if upgrade_first:
        stuck = upgrade(creating=creating)
        for key in ('', project_id(root)):
            if key in stuck:raise Refused(stuck[key])
    check_location(creating=creating)
    path = settings_file()
    if not path.exists():return {}
    try:value = strict_json(path.read_text(encoding='utf-8'))
    except ValueError as exc:raise Refused(f'{path} is not valid JSON: {exc}') from None
    except OSError as exc:raise Refused(f'Cannot read {path}: {exc.strerror}') from None
    if not isinstance(value, dict):raise Refused(f'{path} must contain a JSON object')
    return value


def validate_layer(values, prefix, *, project):
    """Every key known and every value allowed, each named by its full path in settings.json."""
    specs = {key: spec for key, spec, _ in rules()}
    def walk(node, path):
        for key, value in node.items():
            name = path + key
            if name in specs:check(prefix + name, specs[name], value)
            elif any(k.startswith(name + '.') for k in specs):
                if not isinstance(value, dict):raise Refused(f'{prefix}{name} must be an object')
                walk(value, name + '.')
            elif name == 'checks' and project:validate_checks(value, prefix + name)
            elif name == 'checks':raise Refused('checks belong to one project: put them under projects.<project name>.checks')
            else:raise Refused(f'Unknown setting: {prefix}{name}. Run oh config to list the settings')
    walk(values, '')


def layers(data):
    """The settings for every project, and each project's own section, checked as a whole."""
    path = settings_file()
    try:
        top = {k: v for k, v in data.items() if k not in ('$schema', 'projects')}
        validate_layer(top, '', project=False)
        projects = data.get('projects', {})
        if not isinstance(projects, dict):raise Refused('projects must be an object: {"<project name>": {...}}')
        for name, section in projects.items():
            if not isinstance(section, dict):raise Refused(f'projects.{name} must be an object')
            validate_layer(section, f'projects.{name}.', project=True)
    except Refused as exc:raise Refused(f'{path}: {exc}') from None
    return top, projects


def load(root, *, origin=None, data=None):
    """Effective settings: OH's defaults, then yours for every project, then this project's section."""
    top, projects = layers(read_file(root) if data is None else data)
    config = validate(deepcopy(defaults()))
    merge(config, top, origin, 'global')
    section = projects.get(project_name(root), {})
    merge(config, {k: v for k, v in section.items() if k != 'checks'}, origin, 'project')
    return config


def project_checks(root, data=None):
    _, projects = layers(read_file(root) if data is None else data)
    return deepcopy(projects.get(project_name(root), {}).get('checks', []))


def schema():
    """JSON Schema for settings.json, so editors explain each setting and flag mistakes."""
    base = defaults()
    def settings(project):
        node = {'type': 'object', 'additionalProperties': False, 'properties': {}}
        for key, spec, meaning in rules():
            parent = node
            for part in key.split('.')[:-1]:
                parent = parent['properties'].setdefault(part, {'type': 'object', 'additionalProperties': False, 'properties': {}})
            parent['properties'][key.split('.')[-1]] = spec | {'description': meaning, 'default': lookup_key(base, key)}
        if project:node['properties']['checks'] = {'type': 'array', 'items': check_rules(), 'description': CHECKS_MEANING}
        return node
    root = {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'title': 'OH settings',
            'description': 'Your OH settings. Top-level values apply to every project; projects.<name> overrides them for '
                           'one project. Run `oh config` to list them, or change them with /oh-config.'} | settings(False)
    root['properties'] = {'$schema': {'type': 'string', 'description': 'Lets editors show these descriptions'}} | root['properties'] | {
        'projects': {'type': 'object', 'description': 'Settings for one project, by the name you gave it at oh init',
                     'additionalProperties': settings(True)}}
    return root


def write_text(path, text):
    """Replace a file atomically. A symlink (a dotfiles manager, say) keeps pointing at the updated file."""
    import stat
    import tempfile
    from .system import replace
    target = Path(path).resolve() if Path(path).is_symlink() else Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.oh-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        if target.exists():os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))
        replace(temporary, target)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def render(value, indent=0):
    """JSON as people write it: two-space indents, and lists without objects on one line."""
    pad = '  ' * indent
    if isinstance(value, dict) and value:
        return '{\n' + ',\n'.join(f'{pad}  {json.dumps(k, ensure_ascii=False)}: {render(v, indent + 1)}'
                                  for k, v in value.items()) + '\n' + pad + '}'
    if isinstance(value, list) and any(isinstance(x, dict) for x in value):
        return '[\n' + ',\n'.join(f'{pad}  {render(x, indent + 1)}' for x in value) + '\n' + pad + ']'
    return json.dumps(value, ensure_ascii=False)


def write_file(data):
    body = {'$schema': data.get('$schema', './' + SCHEMA_NAME)} | {k: v for k, v in data.items() if k not in ('$schema', 'projects')}
    if 'projects' in data:body['projects'] = data['projects']  # per-project sections read best last
    write_text(settings_file(), render(body) + '\n')
    check_location(creating=True)  # records where the settings are
    refresh_schema()


def refresh_schema():
    """The schema next to settings.json describes the OH that is running. Only an editor aid: a folder
    OH can't write (one a dotfiles tool manages, say) never stops OH."""
    text, path = json.dumps(schema(), indent=2) + '\n', config_home() / SCHEMA_NAME
    try:
        if path.read_text(encoding='utf-8') == text:return False
    except OSError:pass
    try:write_text(path, text)
    except OSError:return False
    return True


def backup_folder(label):
    import time
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for number in range(1, 1000):
        folder = config_home() / 'backups' / (f'{stamp}-{label}' + (f'-{number}' if number > 1 else ''))
        try:folder.mkdir(parents=True);return folder
        except FileExistsError:continue
    raise Refused(f'Too many settings backups in {config_home() / "backups"}')


def legacy_groups():
    """Settings files of OH before settings.json: (None, [settings/defaults.json]) first, then
    (project folder, its files)."""
    from .storage import state_home
    home = state_home()
    groups = [(None, [home / 'settings/defaults.json'])] if (home / 'settings/defaults.json').is_file() else []
    for folder in sorted(p for p in (home / 'projects').glob('*') if p.is_dir()):
        files = [folder / n for n in ('config.json', 'config.local.json', 'checks.json') if (folder / n).is_file()]
        if files:groups.append((folder, files))
    return groups


def legacy_files():
    return [path for _, files in legacy_groups() for path in files]


def prune(values, base):
    """Drop values equal to the ones that apply anyway, so a later default or change still reaches you."""
    result = {}
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            value = prune(value, base[key])
            if value:result[key] = value
        elif base.get(key, object()) != value or type(base.get(key)) is not type(value):result[key] = value
    return result


def combine(target, patch):
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):combine(target[key], value)
        else:target[key] = deepcopy(value)
    return target


def clashes(target, values, prefix=''):
    found = []
    for key, value in values.items():
        if key not in target:continue
        if isinstance(value, dict) and isinstance(target[key], dict):found += clashes(target[key], value, prefix + key + '.')
        elif target[key] != value:found.append(prefix + key)
    return found


def fill(target, values):
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):fill(target[key], value)
        else:target.setdefault(key, deepcopy(value))


def absorb(data, folder, files):
    """Adds one group of older settings files to settings.json. Refuses, changing nothing, a value OH
    doesn't accept or one settings.json already sets differently."""
    label = ', '.join(str(path) for path in files)
    def read(path, kind):
        try:value = strict_json(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:raise Refused(f'Cannot move {path} into {settings_file()}: {exc}') from None
        if not isinstance(value, kind):
            raise Refused(f'Cannot move {path} into {settings_file()}: it must contain a JSON {"object" if kind is dict else "list"}')
        return value
    if folder is None:values = prune(read(files[0], dict), defaults())
    else:
        values = {}
        for name in ('config.json', 'config.local.json'):  # the personal file overrode the shared one
            if folder / name in files:combine(values, read(folder / name, dict))
        # Compared with what every project gets, so a project's own value survives even when it equals OH's default.
        top = {k: v for k, v in data.items() if k not in ('$schema', 'projects')}
        values = prune(values, combine(deepcopy(defaults()), top))
        if folder / 'checks.json' in files:values['checks'] = read(folder / 'checks.json', list)
        try:name = read_json(folder / 'profile.json')['name']
        except (OSError, ValueError, KeyError, TypeError, Refused):raise Refused(f'Cannot read {folder / "profile.json"}') from None
        projects = data.setdefault('projects', {})
        if not isinstance(projects, dict) or not isinstance(projects.get(name, {}), dict):
            raise Refused(f'Cannot move {label} into {settings_file()}: its projects section is not an object')
        try:validate_layer(values, f'projects.{name}.', project=True)
        except Refused as exc:raise Refused(f'Cannot move {label} into {settings_file()}: {exc}') from None
        # The section may already hold this project's values (an older OH wrote the files again, say).
        section = projects.get(name) or {}
        found = section_differences(section, values, combine(deepcopy(defaults()), top))
        if section and found:
            raise Refused(f'projects.{name} in {settings_file()} differs from {label} in '
                          f'{", ".join("projects." + name + "." + key for key in found)}. Keep what you want in projects.{name}, '
                          f'then delete {"that file" if len(files) == 1 else "those files"}.')
        if not section:projects[name] = values
        return
    try:validate_layer(values, '', project=False)
    except Refused as exc:raise Refused(f'Cannot move {label} into {settings_file()}: {exc}') from None
    found = clashes(data, values)
    if found:
        raise Refused(f'{settings_file()} already sets {", ".join(found)} differently from {label}. Keep the value you '
                      f'want in settings.json, then delete {"that file" if len(files) == 1 else "those files"}.')
    fill(data, values)


def leaves(value, prefix=''):
    result = {}
    for key, item in value.items():
        if isinstance(item, dict) and item:result |= leaves(item, prefix + key + '.')
        else:result[prefix + key] = item
    return result


def differences(first, second):
    a, b = leaves(first), leaves(second)
    return sorted(k for k in set(a) | set(b) if a.get(k, a) != b.get(k, b))


def section_differences(section, values, base):
    """Keys where a project section differs from `values` (both compared with `base`, the settings
    every project gets, so a value pinned to what applies anyway is no difference)."""
    def checks(value):return {'checks': value['checks']} if value.get('checks') else {}  # an empty list is no checks
    own = prune({k: v for k, v in section.items() if k != 'checks'}, base) | checks(section)
    return differences(own, {k: v for k, v in values.items() if k != 'checks'} | checks(values))


def rename_keys(data):
    """Applies RENAMED to every layer. Returns whether anything changed."""
    changed = False
    projects = data.get('projects')
    for layer in [data] + (list(projects.values()) if isinstance(projects, dict) else []):
        if not isinstance(layer, dict):continue
        for old, new in RENAMED.items():
            parts = old.split('.')
            if not present(layer, parts):continue
            value = get(layer, parts);remove(layer, parts);changed = True
            if new and not present(layer, new.split('.')):put(layer, new.split('.'), value)
    return changed


def upgrade(*, creating=False):
    """After OH changes: move older settings files into settings.json and apply renamed keys, keeping a
    copy of every file it replaces or moves in backups/. Returns {'' or project id: why} for older
    files that stay where they are until you resolve them."""
    import shutil
    from .storage import lock, snapshot_guard, state_home
    def renamed():
        if not RENAMED or not settings_file().exists():return False
        try:return rename_keys(read_file(upgrade_first=False))
        except Refused:return False  # a broken file is reported when it is read
    if not (legacy_groups() or renamed()):
        if settings_file().exists():refresh_schema()
        return {}
    with snapshot_guard(), lock(config_home() / '.lock'):
        data = read_file(upgrade_first=False, creating=creating)
        record = state_home() / 'settings-moved.json'  # what is already in settings.json, if a move was interrupted
        try:done = set(read_json(record))
        except (OSError, ValueError, TypeError, Refused):done = set()
        before, moved, unused, stuck, registered, present = deepcopy(data), {}, [], {}, registrations(), present_projects()
        for folder, files in legacy_groups():
            key = folder.name if folder else ''
            if key in done:moved[key] = files;continue
            name = name_of(key) if folder else None
            # A replaced or removed registration, or a deleted checkout whose name a present project now uses.
            if folder is not None and (key not in registered or (key not in present and projects_named(name))):
                unused += files;continue
            try:
                if folder is not None and len(projects_named(name) | {key}) > 1:
                    raise Refused(f'More than one OH project is named {name}, so OH can\'t tell which one {", ".join(map(str, files))} '
                                  f'belongs in. Give one of them its own name: oh --root <checkout> rename <new name>')
                candidate = deepcopy(data);absorb(candidate, folder, files)
                data = candidate;moved[key] = files
            except Refused as exc:
                stuck[key] = str(exc)
                if folder is None:break  # projects are compared with the shared settings, so they wait for them
        rename_keys(data)
        if data != before:
            if settings_file().exists():shutil.copy2(settings_file(), backup_folder('settings') / 'settings.json')
            write_file(data)
        if moved:
            from .storage import atomic_json
            atomic_json(record, sorted(done | set(moved)))
        for label, paths in (('moved-into-settings', [p for files in moved.values() for p in files]), ('unused-project-settings', unused)):
            if not paths:continue
            folder = backup_folder(label)
            for path in paths:
                target = folder / path.relative_to(state_home())
                target.parent.mkdir(parents=True, exist_ok=True)
                os.chmod(path, 0o600)  # retired files were read-only; Windows can't move them otherwise
                shutil.move(str(path), target)
        record.unlink(missing_ok=True)
        refresh_schema()
    return stuck


def present(data, parts):
    for part in parts:
        if not isinstance(data, dict) or part not in data:return False
        data = data[part]
    return True


def get(data, parts):
    for part in parts:data = data[part]
    return data


def put(data, parts, value):
    for part in parts[:-1]:
        if not isinstance(data.get(part), dict):data[part] = {}
        data = data[part]
    data[parts[-1]] = value


def remove(data, parts):
    trail = []
    for part in parts[:-1]:trail.append((data, part));data = data[part]
    data.pop(parts[-1])
    for parent, part in reversed(trail):
        if not parent[part]:parent.pop(part)


def edit(root, scope, apply, *, creating=False):
    """Read, change and check settings.json as one step; nothing invalid is ever written. Only a
    change you ask for (`creating`) may start a new file where a recorded one went missing."""
    from .storage import lock
    upgrade(creating=creating)
    with lock(config_home() / '.lock'):
        data = read_file(upgrade_first=False, creating=creating)
        before = deepcopy(data)
        try:layers(data);valid = True
        except Refused:valid = False  # a broken file is repaired one setting at a time
        if scope == 'global':layer = data
        else:
            projects = data.setdefault('projects', {})
            if not isinstance(projects, dict):raise Refused(f'{settings_file()}: projects must be an object')
            name = project_name(root)
            layer = projects.setdefault(name, {})
            if not isinstance(layer, dict):raise Refused(f'{settings_file()}: projects.{name} must be an object; fix it with oh config open')
        result = apply(layer)
        if valid:layers(data)  # a valid file stays valid
        if data != before or not settings_file().exists():
            try:write_file(data)
            except OSError as exc:raise Refused(f'Cannot write {settings_file()}: {exc.strerror or exc}') from None
    return result


def parse(key, raw):
    if key == 'checks':
        try:value = json.loads(raw)
        except ValueError:raise Refused('checks must be a JSON list, such as [{"name": "tests", "command": ["npm", "test"]}]') from None
        return validate_checks(value)
    spec = {k: s for k, s, _ in rules()}[key]
    try:value = json.loads(raw)
    except ValueError:value = raw
    if value is None:raise Refused(f'Use oh config unset {key} to go back to the default')
    if spec['type'] == 'string' and not isinstance(value, str):value = raw
    check(key, spec, value)
    return value


def change(root, key, raw=None, *, scope=None):
    """The only writer: an unknown key or invalid value never reaches settings.json."""
    scope = scope or 'project'
    if scope == 'global':
        try:name = project_name(root, required=False)
        except Refused:name = None  # only used to point out this project's own value
    else:name = project_name(root, required=False)
    if scope == 'project' and not name:
        raise Refused('This checkout is not an OH project: add --global to change your settings for every project, '
                      'or register it with oh init')
    keys, parts, creating = {k for k, _, _ in rules()}, key.split('.'), raw is not None  # only a set may start a new file
    known = key in keys or (key == 'checks' and scope == 'project')
    if raw is not None and key == 'checks' and scope == 'global':raise Refused('checks belong to one project; run this in the project, without --global')
    if raw is not None and not known:raise Refused(f'Unknown setting: {key}. Run oh config to list the settings')
    if raw is None and scope == 'global' and parts[0] in ('projects', '$schema'):
        raise Refused(f'{key} is not a setting; change a project\'s settings from inside it, or edit the file with oh config open')
    if raw is None and not known:
        # Unsetting what isn't a setting repairs a broken file: allowed only for what is there, one value at a time.
        upgrade()
        data = read_file(upgrade_first=False)
        layer = data if scope == 'global' else sections(data).get(name, {})
        if not isinstance(layer, dict) or not present(layer, parts):
            raise Refused('checks belong to one project; run this in the project, without --global' if key == 'checks'
                          else f'Unknown setting: {key}. Run oh config to list the settings')
        if isinstance(get(layer, parts), dict) and any(k.startswith(key + '.') for k in keys):
            raise Refused(f'{key} groups several settings; unset them one at a time (oh config lists them)')
    value = parse(key, raw) if raw is not None else None
    where = f'projects.{name}' if scope == 'project' else 'your settings for every project'
    def current():
        try:return project_checks(root) if key == 'checks' else lookup_key(load(root) if scope == 'project' else load_global(), key)
        except (Refused, KeyError):pass
        # While another setting is still broken, report what this layer holds, or the default.
        data = read_file(upgrade_first=False, creating=creating)
        layer = data if scope == 'global' else sections(data).get(name, {})
        if isinstance(layer, dict) and present(layer, parts):return get(layer, parts)
        try:return [] if key == 'checks' else lookup_key(defaults(), key)
        except KeyError:return None
    before = current()
    def apply(layer):
        if raw is None:
            if not present(layer, parts):return False
            remove(layer, parts);return True
        if present(layer, parts) and type(get(layer, parts)) is type(value) and get(layer, parts) == value:return False
        put(layer, parts, value);return True
    changed = edit(root, scope, apply, creating=creating)
    result = {'setting': key, 'scope': where, 'file': str(settings_file())}
    if changed is False:
        return result | {'unchanged': True, 'note': f'Not set in {where}' if raw is None else 'Already set to this value'}
    after = current()
    note = 'Applies to the next run you start; a run in progress keeps the settings it was approved with.'
    if scope == 'global' and name and key != 'checks' and present(sections(read_file(upgrade_first=False)).get(name, {}), parts):
        note += f' projects.{name} sets its own value, which wins in this project.'
    return result | {'from': before, 'to': after, 'note': note}


def sections(data):
    value = data.get('projects', {})
    return value if isinstance(value, dict) else {}


def load_global():
    top, _ = layers(read_file())
    return merge(validate(deepcopy(defaults())), top)


def ensure_project(root):
    """Creates settings.json with this project's section, so there is always a file to open. Says which
    settings the section already holds (left by an earlier project of this name, say): they apply here."""
    found = {}
    def apply(layer):found.update(layer);return False
    edit(root, 'project', apply)
    return {'settings': str(settings_file()), 'section': f'projects.{project_name(root)}'} | (
        {'applies': sorted(found), 'note': f'projects.{project_name(root)} already sets {", ".join(sorted(found))}; '
                                           'those settings apply to this project (oh config shows them)'} if found else {})


def open_settings(root):
    """Opens settings.json in the app that edits JSON files, even a broken one, which is what you'd fix
    there. Only when there is no file yet does it create one, with this project's section."""
    check_location(creating=True)
    if not settings_file().exists():
        edit(root, 'project' if project_name(root, required=False) else 'global', lambda layer: False, creating=True)
    path = str(settings_file())
    try:launch(path);opened = True
    except OSError:opened = False
    return {'file': path, 'opened': opened} | ({} if opened else {'note': f'Open {path} in your editor'})


def launch(path):
    import subprocess
    import sys
    if sys.platform == 'darwin':subprocess.Popen(['open', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif os.name == 'nt':os.startfile(path)  # type: ignore[attr-defined]
    else:subprocess.Popen(['xdg-open', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def new_project_note(root):
    """What oh init would name an unregistered checkout with no OH project in its repository."""
    import subprocess
    from .registry import identity, repository_name
    try:name = repository_name(identity(root))
    except (Refused, OSError, ValueError, subprocess.CalledProcessError):name = None
    taken = sorted(e['root'] for p in projects_named(name) for e in registrations()[p]) if name else []
    if taken:return (f'This checkout is not an OH project yet. Its repository\'s name, {name}, is used by another project '
                     f'({", ".join(taken)}): oh init --name <another name> registers it.')
    return 'This checkout is not an OH project yet: oh init registers it' + (f' as {name}.' if name else '.')


def repository_names(root):
    """Names of the OH projects of an unregistered checkout's Git repository, which oh init can join."""
    import subprocess
    from .registry import joinable
    try:return joinable(root)
    except (Refused, OSError, ValueError, subprocess.CalledProcessError):return []


def describe(root):
    base, origin = defaults(), {}
    name = project_name(root, required=False)
    data = read_file(root if name else None)
    effective = load(root, origin=origin, data=data) if name else merge(validate(deepcopy(base)), layers(data)[0], origin, 'global')
    result = {'file': str(settings_file()), 'schema': str(config_home() / SCHEMA_NAME), 'project': name,
              'settings': [{'key': key, 'value': lookup_key(effective, key), 'default': lookup_key(base, key),
                            'source': origin.get(key, 'default'), 'allowed': allowed(spec), 'meaning': meaning}
                           for key, spec, meaning in rules()],
              'effective': effective, 'version': version(),
              'precedence': ['OH defaults', 'settings.json: your settings for every project'] + (
                  [f'settings.json: projects.{name}'] if name else [])}
    known = [] if name else repository_names(root)
    notes = [] if name else [
        f'This checkout is not registered yet. It belongs to the Git repository of the OH project {known[0]}: '
        f'oh init joins it.' if len(known) == 1 else
        f'This checkout is not registered yet. OH projects of its Git repository: {", ".join(known)}; '
        'oh init --name <one of them> joins it.' if known else new_project_note(root)]
    if len(known) == 1:result['join'] = known[0]
    if name:
        result['checks'] = project_checks(root, data)
        if not result['checks']:notes.append(f'{name} has no checks yet: add them with oh config set checks \'<JSON list>\'')
    unknown = sorted(set(sections(data)) - registered_names())
    if unknown:notes.append(f'No OH project on this machine is named {", ".join(unknown)}; those sections do nothing. '
                            f'Projects: {", ".join(sorted(registered_names())) or "none yet"}')
    if notes:result['note'] = ' '.join(notes)
    return result


def version():
    if (HOME/'revision.json').is_file():
        return read_json(HOME/'revision.json')['revision']
    revision=git(HOME, 'rev-parse', 'HEAD')
    if git(HOME,'status','--porcelain'):
        from .verification import tree
        return revision+'+worktree.'+tree(HOME)[:16]
    return revision


def snapshot(root):
    config = load(root)
    return {'config': config, 'config_hash': digest(config), 'harness_version': version(), 'rubric_version': 1}


def classify(task):
    # Stable pre-execution signals; spend and outcome never change the assigned cohort.
    if (task.get('transition') or {}).get('profile') == 'plans':
        return 'complex', 'A design decides how a whole initiative is built (rubric 1)'
    text = (task['title'] + ' ' + task.get('instructions', '')).lower()
    critical = ('authorization', 'migration', 'concurrency', 'security boundary', 'cryptograph', 'transaction')
    if any(word in text for word in critical) or len(task.get('paths', [])) > 6:
        return 'complex', 'Cross-cutting or safety-sensitive change (rubric 1)'
    if len(task.get('paths', [])) <= 2 and any(word in text for word in ('typo', 'copy edit', 'rename', 'documentation')):
        return 'simple', 'Small bounded editorial change (rubric 1)'
    return 'standard', 'Ordinary implementation or unspecified scope (rubric 1)'
