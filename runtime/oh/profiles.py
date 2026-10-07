"""Portable configuration only: never sessions, host credentials, evidence or grants."""
from copy import deepcopy
from pathlib import Path
import math
import re
import stat
from .config import HOME, merge, validate, rename_keys
from .registry import lookup, profile, register
from .storage import Refused, git, atomic_json, identifier, read_json, state_writer

FIELDS={'schema_version','profile','config','checks'}


def validate_document(value,root):
    if not isinstance(value,dict) or set(value)!=FIELDS or value['schema_version']!=1:
        raise Refused('Unsupported portable profile format')
    p=value['profile']
    if not isinstance(p,dict) or set(p)-{'name','kind','design_profile'} or not isinstance(p.get('name'),str) or not p['name'].strip() or p.get('kind') not in ('product','harness'):
        raise Refused('Profile contains identity/private fields or lacks its name and kind')
    if p.get('design_profile') not in (None,'consumer-v1'):raise Refused('Unsupported document profile')
    value=deepcopy(value)
    if isinstance(value['config'],dict):rename_keys(value['config'])
    validate(merge(deepcopy(read_json(HOME/'config/defaults.json')),value['config']))
    checks=value['checks']
    if not isinstance(checks,list):raise Refused('Profile checks must be a list')
    for check in checks:
        if not isinstance(check,dict) or set(check)-{'name','command','inputs','toolchain','when','modes','timeout_seconds'}:
            raise Refused('Only portable check definitions can be exported; environment/secrets are excluded')
        if not isinstance(check.get('name'),str) or not check['name'].strip():
            raise Refused('Checks require a nonempty name')
        portable_command(check.get('command'),root)
        for field in ('inputs','when','modes'):
            if field not in check:continue
            items=check[field]
            if not isinstance(items,list) or any(not isinstance(x,str) or not x for x in items):
                raise Refused(f'Check {field} must be an array of nonempty strings')
            if field=='inputs' and (not items or any(Path(x).is_absolute() or '..' in Path(x).parts for x in items)):
                raise Refused('Check inputs must be nonempty repository-relative paths')
            if field=='modes' and any(x not in ('review','pre-push','ci') for x in items):
                raise Refused('Unsupported check mode')
        if 'timeout_seconds' in check:
            timeout=check['timeout_seconds']
            if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout<=0:
                raise Refused('Check timeout must be a finite positive number')
        if 'toolchain' in check:
            if not isinstance(check['toolchain'],list):raise Refused('Toolchain must be an array of probes')
            for command in check['toolchain']:portable_command(command,root,probe=True)
    return value


# An allowlist, not a secret-name detector: arbitrary literals, inline programs,
# environment assignments, URLs and flags cannot cross this export boundary.
# Local checks remain unrestricted. Projects can wrap complex checks in a script
# that reads credentials from their usual local environment/credential store.
PORTABLE_MODES={'{base}','{mode}','review','pre-push','ci','native','syntax','affected','guards','adapters','delivery'}
PROBE_TOOLS={'python3','node','git','bash','sh','jq','pnpm','npm'}


def portable_command(command,root,probe=False):
    if not isinstance(command,list) or not command or any(not isinstance(x,str) or not x for x in command):
        raise Refused('Checks require nonempty command argument arrays')
    if probe:
        if len(command)==2 and command[0] in PROBE_TOOLS and command[1]=='--version':return
    else:
        parts=command[1:] if command[0] in ('bash','sh','python3','node') else command
        if parts:
            path=parts[0]
            if (re.fullmatch(r'(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:sh|py|js|mjs|cjs)',path)
                    and '..' not in Path(path).parts and not path.startswith('-')
                    and all(x in PORTABLE_MODES for x in parts[1:])):
                if parts is command and '/' not in path:
                    raise Refused('Direct portable scripts require an explicit relative path, for example ./checks.sh')
                root=Path(root).resolve();script=root/path
                # Bind the reference to a tracked ordinary file, including every parent.
                # A syntactically plausible filename alone can still be a secret literal.
                if any(part.is_symlink() for part in (script,*script.parents) if part!=root and root in part.parents):
                    raise Refused('Portable script references cannot contain symlinks')
                if not script.is_file() or not script.resolve().is_relative_to(root):
                    raise Refused('Portable checks require an existing repository script')
                entry=git(root,'ls-files','--stage','--',path).split('\t',1)[0].split()
                if len(entry)!=3 or entry[0] not in ('100644','100755') or entry[2]!='0':
                    raise Refused('Portable checks require a tracked ordinary repository script')
                if parts is command and (entry[0]!='100755' or not script.stat().st_mode & stat.S_IXUSR):
                    raise Refused('Directly invoked portable scripts must be executable')
                return
    raise Refused('Portable checks require repository script references with only {base}, {mode}, or standard OH check modes; '
                  'toolchain probes allow known tools with --version only. Wrap other commands in a repository script '
                  'and read credentials locally; arbitrary arguments and inline programs are not exported or imported.')


@state_writer
def export_profile(root,destination):
    from .config import load,project_checks
    destination=Path(destination).expanduser().resolve()
    if destination.exists() or destination.is_relative_to(Path(root).resolve()):
        raise Refused('Export to a new file outside the product checkout')
    source=profile(root)
    value={'schema_version':1,'profile':{k:source[k] for k in ('name','kind','design_profile') if k in source},
           'config':load(root),'checks':project_checks(root)}
    validate_document(value,root);atomic_json(destination,value,immutable=True)
    return {'exported':str(destination),'contents':'profile, effective non-secret settings and check definitions only; private plan documents and their approvals are excluded, as are identities, authority, host trust and transcripts'}


@state_writer
def import_profile(root,source,name=None):
    from .registry import index_path
    value=validate_document(read_json(Path(source).expanduser().resolve()),root)
    if index_path(root).exists():raise Refused('Import requires an unregistered checkout; it never replaces an existing profile or its grants')
    from .config import edit,load_global,prune,section_differences,settings_file
    from .registry import free
    name=name or value['profile']['name'];mine=load_global();free(name)
    # Settings are saved before the checkout is registered: a failure leaves an unused section, never a
    # registered project without its checks. Only what differs from your own settings is kept, so later
    # OH defaults and your changes still apply. A section left by an earlier project of this name is
    # reused only when it already holds the same settings.
    def apply(data):
        projects=data.setdefault('projects',{})
        section=prune(value['config'],mine)|({'checks':value['checks']} if value['checks'] else {})
        existing=projects.get(name) or {}
        if existing and section_differences(existing,section,mine):
            raise Refused(f'{settings_file()} already has different settings under projects.{name}; remove them, '
                          f'or import with --name <another name>')
        if not existing:projects[name]=section
    edit(root,'global',apply)
    result=register(root,name,value['profile']['kind'],imported=value['profile']|{'id':identifier(),'name':name})
    return {'profile':result,'checkout':lookup(root)['checkout'],'authorized':False,'settings':f'{settings_file()} (projects.{name})'}
