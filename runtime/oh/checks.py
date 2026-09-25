"""Consumer-owned verification contracts; OH never imports a product toolchain."""
import fnmatch
from pathlib import Path
from .storage import Refused,git,project,read_json
from .verification import verify


def selected(root,base='origin/main',mode='review'):
    path=Path(root)/'.oh/checks.json'
    if not path.is_file():raise Refused('Register required checks in .oh/checks.json before executing tasks')
    return resolve(root,read_json(path),base,mode)


def resolve(root,checks,base='origin/main',mode='review'):
    if not isinstance(checks,list) or not checks:raise Refused('At least one project verification check is required')
    ancestor=git(root,'merge-base','HEAD',base)
    changed=set(git(root,'diff','--name-only',ancestor).splitlines()+git(root,'ls-files','--others','--exclude-standard').splitlines())
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


def run(root,base='origin/main',mode='review'):
    checks=selected(root,base,mode)
    return verify(root,checks,project(root)['id'])
