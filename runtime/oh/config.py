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
              ('context.compact_at_tokens', number(1000, 100000), 'Context size at which Codex workers compact (Codex only)')]
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
    return 'a model name your subscription offers'


def validate(value):
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise Refused('Unsupported configuration version')
    for key, spec, _ in rules():check(key, spec, lookup_key(value, key))
    return value


def check(key, spec, item):
    if spec['type'] == 'integer':valid = type(item) is int and spec['minimum'] <= item <= spec['maximum']
    elif 'enum' in spec:valid = item in spec['enum']
    else:valid = isinstance(item, str) and bool(re.fullmatch(MODEL, item))
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
    settings in its config folder unless OH_CONFIG_HOME says otherwise."""
    if os.environ.get('OH_CONFIG_HOME'):return Path(os.environ['OH_CONFIG_HOME']).expanduser().absolute()
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
    """The section of settings.json that holds this project's settings: projects.<name>."""
    from .registry import profile
    try:return profile(root)['name']
    except Refused:
        if required:raise
        return None


def registered_names():
    from .storage import state_home
    names = set()
    for path in (state_home() / 'projects').glob('*/profile.json'):
        try:names.add(read_json(path)['name'])
        except (OSError, ValueError, KeyError, Refused):pass
    return names


def read_file(*, upgrade_first=True):
    """settings.json exactly as written, or {} before it exists."""
    if upgrade_first:upgrade()
    path = settings_file()
    if not path.exists():return {}
    try:value = json.loads(path.read_text(encoding='utf-8'))
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
    top, projects = layers(read_file() if data is None else data)
    config = validate(deepcopy(defaults()))
    merge(config, top, origin, 'global')
    section = projects.get(project_name(root), {})
    merge(config, {k: v for k, v in section.items() if k != 'checks'}, origin, 'project')
    return config


def project_checks(root, data=None):
    _, projects = layers(read_file() if data is None else data)
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
    refresh_schema()


def refresh_schema():
    """The schema next to settings.json always describes the OH that is running."""
    text, path = json.dumps(schema(), indent=2) + '\n', config_home() / SCHEMA_NAME
    try:
        if path.read_text(encoding='utf-8') == text:return False
    except OSError:pass
    write_text(path, text)
    return True


def backup_folder(label):
    import time
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for number in range(1, 1000):
        folder = config_home() / 'backups' / (f'{stamp}-{label}' + (f'-{number}' if number > 1 else ''))
        try:folder.mkdir(parents=True);return folder
        except FileExistsError:continue
    raise Refused(f'Too many settings backups in {config_home() / "backups"}')


def legacy_files():
    """Settings files of OH before settings.json: global defaults, and each project's files."""
    from .storage import state_home
    home = state_home()
    found = [home / 'settings/defaults.json'] if (home / 'settings/defaults.json').is_file() else []
    for name in ('config.json', 'config.local.json', 'checks.json'):
        found += sorted((home / 'projects').glob('*/' + name))
    return found


def prune(values, base):
    """Drop values equal to OH's defaults, so a later default still reaches you."""
    result = {}
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            value = prune(value, base[key])
            if value:result[key] = value
        elif base.get(key, object()) != value or type(base.get(key)) is not type(value):result[key] = value
    return result


def migrate_legacy(data):
    """Moves the old settings files into settings.json. Returns the files to move to backups/."""
    from .storage import state_home
    files, home, base = legacy_files(), state_home(), defaults()
    def read(path):
        try:value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:raise Refused(f'Cannot move {path} into {settings_file()}: {exc}') from None
        return value
    def combine(target, patch):
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):combine(target[key], value)
            else:target[key] = deepcopy(value)
    top, sections = {}, {}
    if home / 'settings/defaults.json' in files:
        value = read(home / 'settings/defaults.json')
        if isinstance(value, dict):top = prune(value, base)
    for folder in sorted({f.parent for f in files if f.parent.parent == home / 'projects'}):
        values = {}
        for name in ('config.json', 'config.local.json'):  # the personal file overrode the shared one
            if (folder / name).is_file():
                value = read(folder / name)
                if isinstance(value, dict):combine(values, value)
        values = prune(values, base) if values else {}
        if (folder / 'checks.json').is_file():values['checks'] = read(folder / 'checks.json')
        try:name = read_json(folder / 'profile.json')['name']
        except (OSError, ValueError, KeyError, Refused):name = folder.name  # an orphan keeps its values under its folder name
        if values and sections.get(name, values) != values:
            raise Refused(f'Two OH projects named "{name}" have different settings. Move what you want into '
                          f'{settings_file()} under projects.{name}, then delete {", ".join(str(f) for f in files)}')
        if values:sections[name] = values
    projects = data.setdefault('projects', {}) if sections else data.get('projects', {})
    if not isinstance(projects, dict):raise Refused(f'{settings_file()}: projects must be an object')
    # A value settings.json already has wins only when both agree; anything else is for you to decide.
    layers = [('', data, top)] + [(f'projects.{n}.', projects.setdefault(n, {}), v) for n, v in sections.items()]
    conflict = [prefix + key for prefix, target, values in layers for key in values
                if not isinstance(target, dict) or target.get(key, values[key]) != values[key]]
    if conflict:
        raise Refused(f'{settings_file()} and older OH settings files both set {", ".join(conflict)}. Keep what you want in '
                      f'{settings_file()}, then delete {", ".join(str(f) for f in files)}')
    for _, target, values in layers:
        for key, value in values.items():target.setdefault(key, value)
    return files


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


def upgrade():
    """After OH changes: move older settings files into settings.json and apply renamed keys, keeping
    a copy of every file it replaces or moves in backups/."""
    import shutil
    from .storage import lock, snapshot_guard, state_home
    def renamed():
        if not RENAMED or not settings_file().exists():return False
        try:return rename_keys(read_file(upgrade_first=False))
        except Refused:return False  # a broken file is reported when it is read
    if not (legacy_files() or renamed()):
        if settings_file().exists():refresh_schema()
        return
    with snapshot_guard(), lock(config_home() / '.lock'):
        files = legacy_files()
        data = read_file(upgrade_first=False)
        before = deepcopy(data)
        if files:migrate_legacy(data)
        rename_keys(data)
        if data != before:
            if settings_file().exists():shutil.copy2(settings_file(), backup_folder('settings') / 'settings.json')
            write_file(data)
        if files:
            folder = backup_folder('moved-into-settings')
            for path in files:
                target = folder / path.relative_to(state_home())
                target.parent.mkdir(parents=True, exist_ok=True)
                os.chmod(path, 0o600)  # retired files were read-only; Windows can't move them otherwise
                shutil.move(str(path), target)
        refresh_schema()


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


def edit(root, scope, apply):
    """Read, change and check settings.json as one step; nothing invalid is ever written."""
    from .storage import lock
    upgrade()
    with lock(config_home() / '.lock'):
        data = read_file(upgrade_first=False)
        before = deepcopy(data)
        try:layers(data);valid = True
        except Refused:valid = False  # a broken file is repaired one setting at a time
        if scope == 'global':layer = data
        else:
            projects = data.setdefault('projects', {})
            if not isinstance(projects, dict):raise Refused(f'{settings_file()}: projects must be an object')
            layer = projects.setdefault(project_name(root), {})
        result = apply(layer)
        if valid:layers(data)  # a valid file stays valid
        if data != before or not settings_file().exists():write_file(data)
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
    name = project_name(root, required=False)
    scope = scope or ('project' if name else 'global')
    if scope == 'project' and not name:raise Refused('This checkout is not an OH project yet; use --global, or run oh init first')
    if key == 'checks' and scope == 'global':raise Refused('checks belong to one project; run this in the project, without --global')
    known = key == 'checks' or key in {k for k, _, _ in rules()}
    parts = key.split('.')
    if raw is not None and not known:raise Refused(f'Unknown setting: {key}. Run oh config to list the settings')
    value = parse(key, raw) if raw is not None else None
    where = f'projects.{name}' if scope == 'project' else 'your settings for every project'
    def current():
        try:return project_checks(root) if key == 'checks' else lookup_key(load(root) if scope == 'project' else load_global(), key)
        except (Refused, KeyError):pass
        # While another setting is still broken, report what this layer holds, or the default.
        data = read_file()
        layer = data if scope == 'global' else data.get('projects', {}).get(name, {})
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
    if raw is None and not known and not present_anywhere(root, scope, parts):
        raise Refused(f'Unknown setting: {key}. Run oh config to list the settings')
    changed = edit(root, scope, apply)
    result = {'setting': key, 'scope': where, 'file': str(settings_file())}
    if changed is False:
        return result | {'unchanged': True, 'note': f'Not set in {where}' if raw is None else 'Already set to this value'}
    after = current()
    note = 'Applies to the next run you start; a run in progress keeps the settings it was approved with.'
    if scope == 'global' and name and key != 'checks' and present(read_file().get('projects', {}).get(name, {}), parts):
        note += f' projects.{name} sets its own value, which wins in this project.'
    return result | {'from': before, 'to': after, 'note': note}


def present_anywhere(root, scope, parts):
    data = read_file()
    layer = data if scope == 'global' else data.get('projects', {}).get(project_name(root), {})
    return isinstance(layer, dict) and present(layer, parts)


def load_global():
    top, _ = layers(read_file())
    return merge(validate(deepcopy(defaults())), top)


def ensure_project(root):
    """Creates settings.json with this project's section, so there is always a file to open."""
    edit(root, 'project', lambda layer: False)
    return {'settings': str(settings_file()), 'section': f'projects.{project_name(root)}'}


def open_settings(root):
    """Creates settings.json when needed and opens it in the app that edits JSON files."""
    if project_name(root, required=False):ensure_project(root)
    elif not settings_file().exists():edit(root, 'global', lambda layer: False)
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


def describe(root):
    base, origin = defaults(), {}
    name = project_name(root, required=False)
    data = read_file()
    effective = load(root, origin=origin, data=data) if name else merge(validate(deepcopy(base)), layers(data)[0], origin, 'global')
    result = {'file': str(settings_file()), 'schema': str(config_home() / SCHEMA_NAME), 'project': name,
              'settings': [{'key': key, 'value': lookup_key(effective, key), 'default': lookup_key(base, key),
                            'source': origin.get(key, 'default'), 'allowed': allowed(spec), 'meaning': meaning}
                           for key, spec, meaning in rules()],
              'effective': effective, 'version': version(),
              'precedence': ['OH defaults', 'settings.json: your settings for every project'] + (
                  [f'settings.json: projects.{name}'] if name else [])}
    notes = [] if name else ['This checkout is not an OH project yet: register it with oh init --name <name>.']
    if name:
        result['checks'] = project_checks(root, data)
        if not result['checks']:notes.append(f'{name} has no checks yet: add them with oh config set checks \'<JSON list>\'')
    unknown = sorted(set(data.get('projects', {})) - registered_names())
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
    text = (task['title'] + ' ' + task.get('instructions', '')).lower()
    critical = ('authorization', 'migration', 'concurrency', 'security boundary', 'cryptograph', 'transaction')
    if any(word in text for word in critical) or len(task.get('paths', [])) > 6:
        return 'complex', 'Cross-cutting or safety-sensitive change (rubric 1)'
    if len(task.get('paths', [])) <= 2 and any(word in text for word in ('typo', 'copy edit', 'rename', 'documentation')):
        return 'simple', 'Small bounded editorial change (rubric 1)'
    return 'standard', 'Ordinary implementation or unspecified scope (rubric 1)'
