"""Pre-event scope snapshots. Preparation never grants execution authority."""
from datetime import datetime
from pathlib import Path
from .config import project_checks, snapshot
from .storage import Refused,atomic_json,checkout_file,checkout_id,digest,git,now,project,read_json,state_home,state_writer


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
        data=read_json(path)
        if not isinstance(data,dict) or 'tasks' not in data:raise Refused('A prepared task list is a JSON object with tasks')
        validate_tasks(data['tasks']);delivery_only(data)
        value.update(kind='tasks',manifest=data)
    else:
        if project(root).get('design_profile')!='consumer-v1':raise Refused('Design preparation requires a consumer-owned profile')
        from .design_adapter import manifest as project_design
        data=project_design(root,doc,track)
        value.update(kind='design',doc=doc,track=track,manifest=data)
    key=digest(value);atomic_json(directory(root)/(key+'.json'),value,immutable=True)
    trigger=('$o-harness:oh-deliver request:'+key if manifest is not None else '$o-harness:oh-deliver '+doc+(' '+track if track else '')+' request:'+key)
    config=value['snapshot']['config']
    result={'request':key,'trigger':trigger,'tasks_per_batch':config['tasks_per_batch'],'review_rounds':config['review_rounds'],
            'limits':limits(len(data['tasks']),config)}
    if manifest is not None:
        from .authority import materialize,attest
        materialize(root)
        owner=checkout_file(root,'oh-preparation-owner.json')
        if owner.exists():
            human=read_json(owner)
            # Recheck the original native turn, including whether the person has since moved on.
            event=attest(human['host'],human['payload'],root)
            from .workflow import start,checkpoint
            start(root,data,event,prepared=value,waiting=key)
            result|=checkpoint(root)
    return result


def remember(root,host,payload,event):
    """A typed request may open an approval menu; it grants no implementation."""
    atomic_json(checkout_file(root,'oh-preparation-owner.json'),{'host':host,'payload':payload,'event':event})


def activate(root,journal,state,event):
    """Only an approved, unchanged snapshot can become executable. Retain branch creation for crash recovery."""
    from .branches import incarnation,run_git
    from .config import version
    from .storage import changes
    if event['host']!=state['host'] or event['session']!=state['human']['session']:raise Refused('Approve in the conversation that prepared these tasks')
    resolve(root,'request:'+state['prepared_request'],event,'tasks')
    if version()!=state['harness_version']:raise Refused('OH changed after preparation; prepare the task list again')
    if changes(root):raise Refused('Save the uncommitted changes before approving these tasks')
    branch=git(root,'branch','--show-current');intent=state.get('activation')
    if not intent:
        if branch!=state['branch'] or incarnation(root,branch)!=state['incarnation']:raise Refused('Return to the checkout and branch where these tasks were prepared')
        target='codex/oh-'+state['id'][:8] if branch in ('main','master') else branch
        if target!=branch and run_git(root,'show-ref','--verify','--quiet','refs/heads/'+target).returncode==0:raise Refused('The prepared execution branch already exists; prepare again')
        intent={'branch':target,'base':state['base']}
        journal.append('preparation.activating',intent)
    if branch!=intent['branch']:
        if branch!=state['branch']:raise Refused('Return to the preparation branch before approving again')
        if run_git(root,'show-ref','--verify','--quiet','refs/heads/'+intent['branch']).returncode==0:
            if git(root,'rev-parse',intent['branch'])!=intent['base']:raise Refused('The execution branch changed; preserve it and prepare again')
            git(root,'switch',intent['branch'])
        else:git(root,'switch','-c',intent['branch'])
    return {'branch':intent['branch'],'incarnation':incarnation(root,intent['branch'])}


def limits(count,config):
    """The numbers the human approves, said once with every approval."""
    batch,rounds=min(count,config['tasks_per_batch']),config['review_rounds']
    tasks=f'Runs {batch} of {count} tasks, then asks you to continue' if count>batch else f'Runs {count} task'+('s' if count!=1 else '')
    return f'{tasks}, up to {rounds} review round'+('s' if rounds!=1 else '')+' each. Change this with /oh-config.'


def delivery_only(data):
    """A prepared list is delivery work: the workflow, plan settings and document transitions come only from OH."""
    if set(data)-{'tasks','checks'} or any('transition' in task for task in data['tasks']):
        raise Refused('A prepared task list holds only tasks and checks')


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
    if kind=='tasks':delivery_only(value['manifest'])  # also for a file written without prepare
    return value
