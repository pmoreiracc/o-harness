from __future__ import annotations

from .storage import state_writer

from pathlib import Path
import re
import subprocess
import os
from .config import HOME,snapshot
from .storage import Refused,atomic_json,checkout_id,digest,git,identifier,project,read_json,state_home


def pointer(root):return Path(git(root,'rev-parse','--absolute-git-dir'))/'oh-design-run.json'


def load(root):
    binding=read_json(pointer(root));p=project(root)
    if binding['project']!=p['id'] or binding['checkout']!=checkout_id(root):raise Refused('Design run belongs to another checkout')
    directory=state_home()/'projects'/p['id']/'design-runs'/binding['run']
    grant=read_json(directory/'initial.json')
    if grant['hash']!=digest({k:v for k,v in grant.items() if k!='hash'}):raise Refused('Initial grant was altered')
    return directory,grant


@state_writer
def record(root,doc,track,event,prepared=None,require_prepared=False):
    if pointer(root).exists():
        directory,grant=load(root)
        if grant['human']==event:
            if grant['doc']!=doc or grant['track']!=track:raise Refused('Replayed trigger changed its design scope')
            return grant
        if grant['doc']==doc and grant['track']==track and git(root,'branch','--show-current')==grant['branch']:
            covers(root,doc,grant['tasks'][0])
            return grant
    if require_prepared and prepared is None:raise Refused('Prepare this design scope before its human trigger')
    if prepared and (prepared['doc']!=doc or prepared['track']!=track):raise Refused('Prepared design scope differs from the trigger')
    if git(root,'branch','--show-current')!='main' or git(root,'rev-parse','HEAD')!=git(root,'rev-parse','origin/main'):
        raise Refused('Start a new design run from refreshed main; resume an existing run on its branch')
    if git(root,'status','--porcelain'):raise Refused('Initial design grant requires a clean checkout')
    files=list((Path(root)/'docs/design').glob(doc+'-*.md'))
    if len(files)!=1:raise Refused('Design does not resolve uniquely')
    relative=str(files[0].relative_to(root));approved=git(root,'show','origin/main:'+relative)
    if not re.search(r'^status:\s*approved\s*$',approved,re.M):raise Refused('Design is not approved on main')
    config=prepared['snapshot'] if prepared else snapshot(root)
    plan=subprocess.check_output([str(HOME/'core/scripts/plan.sh'),doc],env=os.environ|{'CLAUDE_PROJECT_DIR':str(root)},text=True)
    finalizing=not any(line.split('\x1f')[1]=='pending' for line in plan.splitlines() if line)
    command='''set -e
. "$1/core/task-ledger.sh"
TASK_US=$(printf '\\037')
TSV=$(CLAUDE_PROJECT_DIR="$2" "$1/core/scripts/plan.sh" "$3")
OWNER="$5"
if [ -z "$OWNER" ]; then
 OWNER=$(printf '%s\\n' "$TSV" | cut -d"$TASK_US" -f3 | sort -u)
 [ "$(printf '%s\\n' "$OWNER" | wc -l | tr -d ' ')" = 1 ] || exit 2
fi
task_project_ids "$TSV" "$OWNER" "$4"
'''
    result=subprocess.run(['/bin/bash','-c',command,'initial',str(HOME),str(root),doc,
        str(config['config']['tasks_per_batch']),track],capture_output=True,text=True)
    ids=result.stdout.strip().split(',')
    if finalizing:ids=['finalize']
    elif result.returncode or not ids or not all(i.isdigit() for i in ids):raise Refused('Cannot project an exact runnable task window: '+result.stderr[-1000:])
    p=project(root);run=identifier();checkout=checkout_id(root)
    # A single-track design keeps its canonical suffixless branch spelling.
    owners={line.split('\x1f')[2] for line in plan.splitlines() if line}
    branch='deliver/'+doc+('-'+track if len(owners)>1 and not finalizing else '')
    grant={'run':run,'doc':doc,'track':track,'branch':branch,'base':git(root,'rev-parse','HEAD'),
      'design_blob':git(root,'rev-parse','origin/main:'+relative),'tasks':ids,'project':p['id'],
      'checkout':checkout,'human':event,'checks':prepared['project_checks'] if prepared else (read_json(Path(root)/'.oh/checks.json') if (Path(root)/'.oh/checks.json').exists() else []),**config}
    grant['hash']=digest(grant)
    directory=state_home()/'projects'/p['id']/'design-runs'/run
    atomic_json(directory/'initial.json',grant,immutable=True)
    atomic_json(pointer(root),{'run':run,'project':p['id'],'checkout':checkout})
    return grant


def incarnation(root,branch,*,create=False):
    path=Path(git(root,'rev-parse','--path-format=absolute','--git-path','logs/refs/heads/'+branch))
    if path.is_symlink():raise Refused('Branch reflog cannot be a symlink')
    lines=path.read_text().splitlines()
    markers=[line for line in lines if re.search(r'\tOH incarnation: [0-9a-f-]{36}$',line)]
    if not markers and create:
        head=git(root,'rev-parse','refs/heads/'+branch)
        try:git(root,'reflog','write','refs/heads/'+branch,head,head,'OH incarnation: '+identifier())
        except subprocess.CalledProcessError as exc:
            raise Refused('OH requires Git with reflog write support (Git 2.55 is verified). Upgrade Git before starting this run; the retained scope is unchanged and no task execution started.') from exc
        return incarnation(root,branch)
    if not markers:raise Refused('Branch incarnation marker is missing; a recreated branch cannot reuse the old grant')
    # A retained nonce survives ordinary appends but disappears with branch deletion.
    # Filesystem inode reuse and Git timestamps at one-second resolution are irrelevant.
    return digest({'first':lines[0],'marker':markers[0]})


@state_writer
def bind(root):
    directory,grant=load(root)
    branch=git(root,'branch','--show-current')
    if branch!=grant['branch']:
        raise Refused('Initial grant belongs to another delivery branch')
    path=directory/'branch.json'
    if not path.exists() and git(root,'rev-parse','HEAD')!=grant['base']:
        raise Refused('Initial grant does not match the newly created delivery branch')
    value={'incarnation':incarnation(root,branch,create=not path.exists()),'grant':grant['hash']}
    if path.exists():
        if read_json(path)!=value:raise Refused('The delivery branch was recreated; its old grant cannot be reused')
    else:atomic_json(path,value,immutable=True)


def covers(root,doc,task):
    directory,grant=load(root)
    if doc!=grant['doc'] or git(root,'branch','--show-current')!=grant['branch']:
        raise Refused('Initial grant belongs to another delivery context')
    binding=read_json(directory/'branch.json')
    if binding!={'incarnation':incarnation(root,grant['branch']),'grant':grant['hash']}:
        raise Refused('Stale initial grant: branch incarnation changed')
    return task in grant['tasks']
