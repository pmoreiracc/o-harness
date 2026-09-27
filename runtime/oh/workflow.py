from __future__ import annotations



from .storage import checkout_file

from .storage import state_writer

from pathlib import Path
from .config import classify, snapshot
from .storage import Journal, Refused, atomic_json, checkout_id, digest, git, identifier, project, read_json, state_home, lock
from .telemetry import best_effort


def validate_tasks(tasks):
    if not isinstance(tasks,list) or not tasks:
        raise Refused('A run needs an explicit nonempty task list')
    seen=set()
    for task in tasks:
        if not isinstance(task,dict) or not isinstance(task.get('id'),str) or not task['id'] or len(task['id'])>100:
            raise Refused('Every task needs a stable string ID')
        if task['id'] in seen or not isinstance(task.get('title'),str) or not task['title']:
            raise Refused('Task IDs must be unique and titles nonempty')
        if not isinstance(task.get('instructions'),str) or not task['instructions']:
            raise Refused('Each task needs explicit instructions')
        if not isinstance(task.get('needs',[]),list) or not set(task.get('needs',[])) <= seen:
            raise Refused('Tasks must be ordered after their dependencies')
        seen.add(task['id'])
    return tasks


def human_event(payload, host):
    if host not in ('codex','claude') or payload.get('hook_event_name') != 'UserPromptSubmit':
        raise Refused('Only a host UserPromptSubmit event can grant work')
    if any(key in payload for key in ('tool_input','tool_response','tool_name')):
        raise Refused('Tool output cannot grant work')
    session=payload.get('session_id');turn=payload.get('turn_id') or payload.get('prompt_id')
    if not isinstance(session,str) or not session or not isinstance(turn,str) or not turn:
        raise Refused('A host session and unique prompt/turn ID are required; adapter must supply them')
    prompt=payload.get('prompt')
    if not isinstance(prompt,str):
        raise Refused('Missing human prompt')
    return {'host':host,'session':session,'turn':turn,'prompt':prompt.strip()}


def active_file(root):
    return checkout_file(root, 'oh-active-run.json')


def load_run(root):
    active=read_json(active_file(root))
    if active['checkout'] != checkout_id(root) or active['project'] != project(root)['id']:
        raise Refused('This run belongs to another checkout or project')
    journal=Journal(active['project'],active['run'])
    return journal, reduce(journal.records())


def reduce(records):
    if not records or records[0]['kind']!='run.started':
        raise Refused('Missing run start')
    state=dict(records[0]['data']);state.update(done=[],granted=[],attempts=[],status='running',decisions=[],summaries=[],task_started={},commit_intents={},resolutions={},interventions={})
    expanded=[]
    for record in records[1:]:
        if record['kind']=='transition':expanded.extend(e|{'at':record['at']} for e in record['data']['events'])
        else:expanded.append(record)
    for record in expanded:
        kind=record['kind'];d=record['data']
        if kind=='grant':state['granted']=d['tasks'];state['decisions'].append(d['source'])
        elif kind=='commit.intent':state['commit_intents'][d['task']]=d
        elif kind=='task.started':state['task_started'][d['task']]=record['at']
        elif kind=='task.completed':state['done'].append(d['task']);state['summaries'].append(d)
        elif kind=='attempt.started':state['attempts'].append(d | {'finished':False})
        elif kind=='attempt.finished':
            matches=[a for a in state['attempts'] if a['id']==d['id']]
            if len(matches)!=1:raise Refused('Completion without exactly one admitted attempt')
            matches[0].update(d | {'finished':True})
        elif kind=='run.status':
            state['status']=d['status']
            if d['status']=='pausing':state['pause_return_status']=d['return_status']
            if d['status']=='paused':state['pause_snapshot']={'tree':d['tree'],'head':d['head']}
        elif kind=='task.intervention':state['interventions'][d['task']]=state['interventions'].get(d['task'],0)+1
        elif kind=='review.resolution':state['resolutions'][d['attempt']]=d
        elif kind=='recovery.grant':state.setdefault('recovery_grants',[]).append(d)
        elif kind=='review.grant':state.setdefault('review_grants',[]).append(d)
        elif kind=='subject.prepared':
            matches=[a for a in state['attempts'] if a['id']==d['attempt']]
            if len(matches)!=1:raise Refused('Rendered subject without one implementation attempt')
            matches[0]['tree']=d['tree']
        elif kind=='verification.failed':
            matches=[a for a in state['attempts'] if a['id']==d['attempt']]
            if len(matches)!=1:raise Refused('Verification failure without an admitted implementation')
            matches[0].update(outcome='verification_failed',summary=d['summary'])
        elif kind=='decision':
            state['decisions'].append(d['source'])
            if d['choice']=='pr':state['publication']=d
    return state


def _start(root, manifest, event, prepared=None):
    tasks=validate_tasks(manifest['tasks']);p=project(root)
    workflow=manifest.get('workflow','deliver')
    if workflow not in ('propose','design','deliver'):raise Refused('Unknown workflow')
    if workflow!='deliver' and len(tasks)!=1:raise Refused('Planning workflows have one bounded artifact task')
    source=digest({k:event[k] for k in ('host','session','turn','prompt')})
    if active_file(root).exists():
        journal,state=load_run(root)
        if state['source']==source:return journal,state
        if state['status'] not in ('stopped','pr','completed'):
            raise Refused('An unfinished run exists; resume it or explicitly stop first')
    config=prepared['snapshot'] if prepared else snapshot(root)
    from .config import project_checks
    required=prepared['project_checks'] if prepared else project_checks(root)
    if workflow=='deliver' and not required and not manifest.get('checks'):raise Refused("Add this project's checks before starting paid work: oh config set checks '<JSON list>'")
    if git(root,'status','--porcelain'):
        raise Refused('Start from a clean execution checkout; save task manifests in external OH project storage')
    run=identifier();checkout=checkout_id(root)
    if workflow=='deliver' and git(root,'branch','--show-current') in ('main','master'):
        git(root,'switch','-c','codex/oh-'+run[:8])
    from .branches import incarnation
    branch_incarnation=incarnation(root,git(root,'branch','--show-current'),create=True)
    for task in tasks:
        task['difficulty'],task['difficulty_reason']=classify(task)
    data={'id':run,'project':p['id'],'name':p['name'],'work_kind':p['kind'],
          'host':event['host'],'checkout':checkout,'source':source,'human':event,
          'branch':git(root,'branch','--show-current'),'incarnation':branch_incarnation,'base':git(root,'rev-parse','HEAD'),
          'workflow':manifest.get('workflow','deliver'),'design':manifest.get('design'),'track':manifest.get('track'),
          'tasks':tasks,'checks':manifest.get('checks',[]),'project_checks':required,**config}
    journal=Journal(p['id'],run)
    journal.append('run.started',data)
    ids=[t['id'] for t in tasks[:data['config']['tasks_per_batch']]]
    journal.append('grant',{'tasks':ids,'source':source,'kind':'initial','config_hash':data['config_hash']})
    atomic_json(active_file(root),{'project':p['id'],'run':run,'checkout':checkout})
    best_effort('run.started',p['id'],run,name=p['name'],work_kind=p['kind'],host=event['host'],
                version=data['harness_version'],config_hash=data['config_hash'])
    return journal,reduce(journal.records())


def _choose(root, choice, event):
    journal,state=load_run(root)
    events=[]
    def append(kind,data):events.append({'kind':kind,'data':data})
    source=digest({k:event[k] for k in ('host','session','turn','prompt')})
    if source in state['decisions']:return state
    if event['host']!=state['host']:
        raise Refused('Resume through the host that owns this run')
    if choice=='continue':
        if state['status']!='checkpoint':raise Refused('Continue requires a task checkpoint')
        tasks=[t['id'] for t in state['tasks'] if t['id'] not in state['done']][:state['config']['tasks_per_batch']]
        if not tasks:raise Refused('No remaining tasks')
        append('grant',{'tasks':tasks,'source':source,'kind':'continue','config_hash':state['config_hash']})
        append('run.status',{'status':'running'})
    elif choice in ('resume','retry'):
        expected='paused' if choice=='resume' else 'needs_attention'
        if state['status']!=expected:raise Refused('This choice does not match the current recovery checkpoint')
        task=next((t['id'] for t in state['tasks'] if t['id'] not in state['done']),None)
        if (not task or task not in state['granted']) and choice!='resume':raise Refused('No unfinished task remains in the existing grant')
        if choice=='resume':
            from .verification import tree
            retained=state.get('pause_snapshot') or {}
            if retained.get('head')!=git(root,'rev-parse','HEAD') or retained.get('tree')!=tree(root):
                raise Refused('Files changed while paused; preserve them and reconcile the run before resuming')
        if choice=='retry':
            # A new, explicit human retry grants one bounded recovery window. Restart alone does not.
            spent=sum(a.get('outcome') in ('failed','interrupted','verification_failed') for a in state['attempts'] if a['task']==task and a['role']=='implementation')
            append('recovery.grant',{'task':task,'source':source,'spent_before':spent})
        append('decision',{'source':source,'choice':choice})
        append('run.status',{'status':state.get('pause_return_status','running') if choice=='resume' else 'running'})
        append('task.intervention',{'task':task})
        best_effort('task.intervention',state['project'],state['id'],task,reason=choice)
    elif choice in ('pr','stop'):
        if choice=='pr' and state.get('workflow','deliver')!='deliver':raise Refused('Planning does not authorize product publication')
        if choice=='pr' and state['status'] not in ('checkpoint','completed'):
            raise Refused('PR choice requires completed work at a checkpoint')
        decision={'source':source,'choice':choice}
        if choice=='pr':
            head=git(root,'rev-parse','HEAD');branch=git(root,'branch','--show-current')
            commits=[item['commit'] for item in state['summaries']]
            if not commits or head!=commits[-1] or branch!=state['branch']:
                raise Refused('PR choice must cover the exact completed branch head')
            decision.update(head=head,branch=branch,commits=commits)
        append('decision',decision)
        append('run.status',{'status':'pr' if choice=='pr' else 'stopped'})
    elif choice in ('accept concerns','route scope','accept concerns and route scope'):
        if state['status']!='findings_checkpoint':raise Refused('No unresolved review findings')
        review=state['attempts'][-1];task=review['task'];findings=review.get('findings',[])
        severities={f['severity'] for f in findings}
        expected={'accept concerns':{'concern'},'route scope':{'scope'},'accept concerns and route scope':{'concern','scope'}}[choice]
        if severities!=expected:raise Refused('The choice must resolve every retained finding without dismissing blockers')
        from .verification import candidate_tree,tree
        if tree(root)!=review['tree'] or candidate_tree(root)!=review['git_tree']:raise Refused('Findings no longer describe the current tree; repair and review it again')
        issue=None
        if 'scope' in severities:
            from .issues import route
            issue=route(root,state['project'],state['id'],review['id'],[f for f in findings if f['severity']=='scope'])
        append('review.resolution',{'attempt':review['id'],'source':source,'choice':choice,'issue':issue,'tree':review['git_tree']})
        append('decision',{'source':source,'choice':choice})
        append('run.status',{'status':'running'})
        append('task.intervention',{'task':task})
        best_effort('task.intervention',state['project'],state['id'],review['task'],reason=choice)
    elif choice in ('fix concerns','fix scope','fix findings'):
        if state['status']!='findings_checkpoint':raise Refused('No unresolved review findings')
        append('decision',{'source':source,'choice':choice})
        append('run.status',{'status':'running'})
        task=next(t['id'] for t in state['tasks'] if t['id'] not in state['done'])
        append('task.intervention',{'task':task})
        best_effort('task.intervention',state['project'],state['id'],task,reason=choice)
    elif choice=='grant review':
        if state['status']!='review_checkpoint':raise Refused('No spent review window')
        task=next(t['id'] for t in state['tasks'] if t['id'] not in state['done'])
        append('task.intervention',{'task':task})
        best_effort('task.intervention',state['project'],state['id'],task,reason='review_window_renewed')
        append('review.grant',{'task':task,'source':source,'rounds':state['config']['review_rounds']})
        append('decision',{'source':source,'choice':choice})
        append('run.status',{'status':'running'})
    else:raise Refused('Unknown human choice')
    if state['status'] in ('checkpoint','review_checkpoint','findings_checkpoint','needs_attention') and any(item['kind']=='run.status' and item['data']['status']=='running' for item in events):
        pending=next((t['id'] for t in state['tasks'] if t['id'] not in state['done']),None)
        from datetime import datetime,timezone
        waits=[entry for entry in journal.records() if entry['kind']=='run.status' and entry['data']['status'] in ('checkpoint','review_checkpoint','findings_checkpoint','needs_attention')]
        if pending and waits:
            best_effort('phase.finished',state['project'],state['id'],pending,phase='waiting',duration_ms=(datetime.now(timezone.utc)-datetime.fromisoformat(waits[-1]['at'])).total_seconds()*1000)
    journal.append('transition',{'source':event,'events':events})
    for item in events:
        if item['kind']=='run.status':best_effort('run.status',state['project'],state['id'],**item['data'])
    return reduce(journal.records())


def next_task(state):
    if state['status']!='running':return None
    for task in state['tasks']:
        if task['id'] in state['done']:continue
        if task['id'] not in state['granted']:return None
        if not set(task.get('needs',[]))<=set(state['done']):raise Refused('Unmet task dependency')
        return task
    return None


def review_limit(state,task):
    return state['config']['review_rounds']+sum(g['rounds'] for g in state.get('review_grants',[]) if g['task']==task)


def checkpoint(root):
    journal,state=load_run(root)
    left=len([t for t in state['tasks'] if t['id'] not in state['done']])
    return {'run':state['id'],'status':state['status'],'completed':len(state['done']),
            'authorized_remaining':[t for t in state['granted'] if t not in state['done']],
            'last_results':state['summaries'][-2:],'evidence':str(journal.path),
            'config_hash':state['config_hash'],'version':state['harness_version']}|(
            {'limits':continue_limits(left,state['config'])} if state['status']=='checkpoint' and left else {})


def continue_limits(left,config):
    """What typing continue approves, said at every checkpoint."""
    batch,rounds=min(left,config['tasks_per_batch']),config['review_rounds']
    return (f'Continue runs {batch} of the {left} remaining task'+('s' if left!=1 else '')+f', up to {rounds} review round'
            +('s' if rounds!=1 else '')+' each. This run keeps its settings; /oh-config changes them for the next run.')


@state_writer
def start(root,manifest,event,prepared=None):
    with lock(checkout_file(root, 'oh-control.lock')):
        return _start(root,manifest,event,prepared)


@state_writer
def choose(root,choice,event):
    if choice in ('pause','stop'):
        from .controls import request
        return request(root,choice)
    with lock(checkout_file(root, 'oh-control.lock')):
        return _choose(root,choice,event)
