"""Pre-event scope snapshots. Preparation never grants execution authority."""
from datetime import datetime
from pathlib import Path
from .config import project_checks, snapshot
from .storage import Refused,atomic_json,checkout_id,digest,git,now,project,read_json,state_home,state_writer


def directory(root):return state_home()/'projects'/project(root)['id']/'prepared'


@state_writer
def prepare(root,manifest=None,doc=None,track=''):
    if (manifest is None)==(doc is None):raise Refused('Prepare either tasks or one design')
    value={'created':now(),'project':project(root)['id'],'checkout':checkout_id(root),'base':git(root,'rev-parse','HEAD'),
           'snapshot':snapshot(root),'project_checks':project_checks(root)}
    if manifest is not None:
        from .workflow import validate_tasks
        path=(Path(root)/manifest).resolve()
        if not path.is_relative_to(directory(root).parent):raise Refused('Save task manifests in this project’s external OH storage')
        data=read_json(path);validate_tasks(data['tasks'])
        value.update(kind='tasks',manifest=data)
    else:
        if project(root).get('design_profile')!='consumer-v1':raise Refused('Design preparation requires a consumer-owned profile')
        from .design_adapter import manifest as project_design
        data=project_design(root,doc,track)
        value.update(kind='design',doc=doc,track=track,manifest=data)
    key=digest(value);atomic_json(directory(root)/(key+'.json'),value,immutable=True)
    trigger=('$o-harness:oh-deliver request:'+key if manifest is not None else '$o-harness:oh-deliver '+doc+(' '+track if track else '')+' request:'+key)
    config=value['snapshot']['config']
    return {'request':key,'trigger':trigger,'tasks_per_batch':config['tasks_per_batch'],'review_rounds':config['review_rounds'],
            'limits':limits(len(data['tasks']),config)}


def limits(count,config):
    """The numbers the human approves, said once with every approval."""
    batch,rounds=min(count,config['tasks_per_batch']),config['review_rounds']
    tasks=f'Runs {batch} of {count} tasks, then asks you to continue' if count>batch else f'Runs {count} task'+('s' if count!=1 else '')
    return f'{tasks}, up to {rounds} review round'+('s' if rounds!=1 else '')+' each. Change this with /oh-config.'


def resolve(root,name,event,kind):
    import re
    if not re.fullmatch(r'request:[0-9a-f]{64}',name or ''):raise Refused('Prepare the agreed scope first, then use the exact request trigger returned by OH')
    key=name.split(':',1)[1];value=read_json(directory(root)/(key+'.json'))
    if digest(value)!=key:raise Refused('Prepared scope was changed')
    if value['kind']!=kind or value['project']!=project(root)['id'] or value['checkout']!=checkout_id(root):raise Refused('Prepared scope belongs to another workflow or checkout')
    try:before=datetime.fromisoformat(value['created']);human=datetime.fromisoformat(event['at'].replace('Z','+00:00'))
    except (KeyError,ValueError,TypeError):raise Refused('A timestamped native human event is required for prepared scope')
    if before.tzinfo is None or human.tzinfo is None or before>=human:raise Refused('Scope must be prepared before the human trigger; use the new request in a new human turn')
    if value['base']!=git(root,'rev-parse','HEAD'):raise Refused('Prepared scope is stale: prepare against the current committed base')
    return value
