"""Consumer-owned verification contracts; OH never imports a product toolchain."""
import fnmatch
from pathlib import Path
from .storage import Refused,changes,git,project
from .verification import verify


def selected(root,base=None,mode='review'):
    from .config import project_checks
    checks=project_checks(root)
    if not checks:raise Refused("Add this project's checks first: oh config set checks '<JSON list>'")
    return resolve(root,checks,base,mode)


def resolve(root,checks,base=None,mode='review'):
    if not isinstance(checks,list) or not checks:raise Refused('At least one project verification check is required')
    from .branches import main_ref
    base=base or main_ref(root)
    if not base:raise Refused('No base branch found; set base_branch with oh config')
    ancestor=git(root,'merge-base','HEAD',base)
    changed=set(git(root,'diff','--name-only',ancestor).splitlines()+changes(root))
    result=[]
    for check in checks:
        if not isinstance(check,dict) or not isinstance(check.get('name'),str):raise Refused('Invalid project check')
        modes=check.get('modes',['review','pre-push','ci'])
        if mode not in modes:continue
        patterns=check.get('when')
        if patterns and not any(fnmatch.fnmatchcase(path,pattern) for path in changed for pattern in patterns):continue
        resolved=dict(check)
        resolved['command']=[part.replace('{base}',base).replace('{mode}',mode) for part in check['command']]
        result.append(resolved)
    return result


def run(root,base=None,mode='review'):
    checks=selected(root,base,mode)
    return verify(root,checks,project(root)['id'])
