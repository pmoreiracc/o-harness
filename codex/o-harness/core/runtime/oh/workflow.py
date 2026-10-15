"""Durable workflow facts and historical journal reader. Skills own execution."""
from pathlib import Path
from contextlib import contextmanager
from .storage import Journal, Refused, checkout_file, checkout_id, digest, git, project, read_json, lock
NO_RUN = 'No saved OH work in this checkout. Select a design or prepare bounded scope.'


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


def committed(state):
    """Whether this run commits its reviewed tree: delivery, and designs whose plans live in the repository.
    Other planning runs review a saved artifact and leave the product untouched."""
    return state.get('workflow','deliver')=='deliver' or (state.get('plans') or {}).get('location')=='repo'


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
    review=checkout_file(root, 'oh-active-review.json')
    return review if review.exists() else checkout_file(root, 'oh-active-run.json')


def load_run(root):
    if not active_file(root).exists():raise Refused(NO_RUN)
    active=read_json(active_file(root))
    if active['checkout'] != checkout_id(root) or active['project'] != project(root)['id']:
        raise Refused('This run belongs to another checkout or project')
    journal=Journal(active['project'],active['run'])
    return journal, reduce(journal.records())


def reduce(records):
    if not records or records[0]['kind']!='run.started':
        raise Refused('Missing run start')
    state=dict(records[0]['data']);state['tasks']=[dict(t) for t in state['tasks']];state.update(done=[],granted=[],attempts=[],status='running',decisions=[],summaries=[],task_started={},commit_intents={},resolutions={},interventions={})
    expanded=[]
    for record in records[1:]:
        if record['kind']=='transition':expanded.extend(e|{'at':record['at']} for e in record['data']['events'])
        else:expanded.append(record)
    for record in expanded:
        kind=record['kind'];d=record['data']
        if kind=='grant':state['granted']=d['tasks'];state['decisions'].append(d['source'])
        elif kind=='commit.intent':state['commit_intents'][d.get('key',d['task'])]=d
        elif kind=='task.started':state['task_started'][d['task']]=d.get('started_at',record['at'])
        elif kind=='task.assessed':
            if not any(a['id']==d['attempt'] and a['task']==d['task'] and a['role']=='assessment' and a.get('outcome')=='assessed' for a in state['attempts']):
                raise Refused('Difficulty selection requires its retained read-only assessment')
            state.setdefault('assessments',{})[d['task']]=d
            selected=next(t for t in state['tasks'] if t['id']==d['task'])
            selected.update(difficulty=d['difficulty'],difficulty_reason=d['rationale'])
        elif kind=='task.completed':state['done'].append(d['task']);state['summaries'].append(d)
        elif kind=='publication.completed':
            grant=state.get('publication') or {}
            if state['status']!='pr' or d['run']!=state['id'] or (d['grant'],d['approved_head'])!=(grant.get('source'),grant.get('head')):
                raise Refused('Publication receipt does not match this run\'s approval')
            if state.get('published') and state['published']!=d:raise Refused('Publication receipt cannot be replaced')
            state['published']=d
        elif kind=='attempt.started':state['attempts'].append({'host':state['host']} | d | {'finished':False,'started_at':record['at']})
        elif kind=='attempt.admitted':
            admitted=next(a for a in state['attempts'] if a['id']==d['id'])
            admitted['request_hash']=d['hash']
        elif kind=='attempt.finished':
            matches=[a for a in state['attempts'] if a['id']==d['id']]
            if len(matches)!=1:raise Refused('Completion without exactly one admitted attempt')
            matches[0].update(d | {'finished':True,'finished_at':record['at']})
        elif kind=='native.authenticated':state['native_authenticated']=d
        elif kind=='native.adopted':state.update(d)
        elif kind=='native.child.bound':
            child_attempt=next((a for a in state['attempts'] if a['id']==d['attempt']),None)
            if child_attempt is None:raise Refused('Child binding without an admitted attempt')
            child_attempt['native_child']=d['child']
        elif kind=='evidence.attached':state.setdefault('supplementary',[]).append(d)
        elif kind=='native.candidate':state['candidate']=d
        elif kind=='native.private.approved':state['private_native_approval']=d
        elif kind=='verification':state.setdefault('verification',{})[d['task']]=d
        elif kind=='report.submitted':state.setdefault('reports',{})[d['id']]=d
        elif kind=='handoff.normalized':
            author=next(a for a in state['attempts'] if a['id']==d['id'])
            author.update(original_outcome=author['outcome'],outcome='implemented',normalized_report=d['report'])
        elif kind=='run.status':
            state['status']=d['status']
            if d['status'] not in ('approval_checkpoint','prepared_checkpoint'):state.pop('refinement',None)
            state.setdefault('status_history',[]).append(d|{'at':record['at']})
            if d['status']=='pausing':state['pause_return_status']=d['return_status']
            if d['status']=='paused':state['pause_snapshot']={'tree':d['tree'],'head':d['head']}
        elif kind=='task.intervention':state['interventions'][d['task']]=state['interventions'].get(d['task'],0)+1
        elif kind=='review.resolution':state['resolutions'][d['attempt']]=d
        elif kind=='run.owner':state['human']=d['human'];state['host']=d['human']['host']
        elif kind=='delivery.continued':
            state['human']=d['human'];state['host']=d['human']['host'];state['harness_version']=d['version']
            state.setdefault('continuations',[]).append(d|{'at':record['at']})
        elif kind=='recovery.grant':state.setdefault('recovery_grants',[]).append(d)
        elif kind=='review.requested':state['extra_review']=d
        elif kind=='review.checked':state.pop('extra_review',None)
        elif kind=='correction.started':state['correction']=d
        elif kind=='correction.completed':
            state.setdefault('corrections',[]).append(d);state['summaries'].append(d);state.pop('correction',None);state.pop('extra_review',None)
        elif kind=='review.grant':state.setdefault('review_grants',[]).append(d)
        elif kind=='preparation.activating':state['activation']=d
        elif kind=='preparation.activated':state.update(branch=d['branch'],incarnation=d['incarnation'])
        elif kind=='subject.preparing':state['rendered']={'intent':d['intent']}|({'before':d['before']} if 'before' in d else {})
        elif kind=='subject.existing':state['rendered']=d['plan']
        elif kind=='private.approval.intent':state['private_approval']=d
        elif kind=='scope.recorded':
            state.setdefault('scope_records',{})[d['attempt']]=d
            if d.get('render'):state['delivery_render']=d['render']
        elif kind=='delivery.render':state['delivery_render']=d
        elif kind=='delivery.approval.intent':state['delivery_approval']=d
        elif kind=='branch.creating':state['branch_creation']=d
        elif kind=='branch.moving':
            state['branch_move']=d;state.pop('branch_creation',None)
        elif kind=='branch.moved':
            state.update(branch=d['branch'],incarnation=d['incarnation'],moved_from=d['from'])
            state.pop('branch_move',None)
        elif kind=='proposal.discard':state['discard']=d
        elif kind=='proposal.discarded':
            pending=state.pop('discard',{})
            if pending.get('resume'):
                state.update(branch=pending['return_to'],incarnation=pending['return_incarnation'])
                state.pop('moved_from',None)
        elif kind=='proposal':
            state.setdefault('proposals',{})[d['attempt']]=d
            state.setdefault('proposal_answers',[]).append(d)
        elif kind=='refinement.requested':state['refinement']=d
        elif kind=='refinement.feedback':state['refinement']=d
        elif kind=='proposal.preview':state['preview']=d
        elif kind=='subject.cleared':
            state.pop('rendered',None)
            for a in state['attempts']:
                if a['id']==d['attempt']:a['tree']=d['tree']
        elif kind=='subject.prepared':
            matches=[a for a in state['attempts'] if a['id']==d['attempt']]
            if len(matches)!=1:raise Refused('Rendered subject without one implementation attempt')
            matches[0]['tree']=d['tree']
            if d.get('plan'):state['rendered']=d['plan']
        elif kind=='verification.failed':
            matches=[a for a in state['attempts'] if a['id']==d['attempt']]
            if len(matches)!=1:raise Refused('Verification failure without an admitted implementation')
            matches[0].update(outcome='verification_failed',summary=d['summary'],failed_at=record['at'])
        elif kind=='decision':
            state['decisions'].append(d['source'])
            if d['choice']=='pr':state['publication']=d
            if d['choice']=='handoff pr':state['review_handoff']=d
    return state


def intent_key(state,task):
    correction=state.get('correction') or {}
    return correction['key'] if correction.get('task')==task else task


def next_task(state):
    if state['status']!='running':return None
    if selected:=state.get('extra_review') or state.get('correction'):
        return next(t for t in state['tasks'] if t['id']==selected['task'])
    for task in state['tasks']:
        if task['id'] in state['done']:continue
        if task['id'] not in state['granted']:return None
        if not set(task.get('needs',[]))<=set(state['done']):raise Refused('Unmet task dependency')
        return task
    return None


def display_task(state):
    return (next_task(state|{'status':'running','granted':state.get('granted',[])}) or
            next((t for t in state['tasks'] if t['id'] not in state['done']),state['tasks'][-1]))


def review_limit(state,task):
    return state['config']['review_rounds']+sum(g['rounds'] for g in state.get('review_grants',[]) if g['task']==task)


def adopted(root,state,own):
    """The reviewed commits a stopped run, or a completed one nobody chose to publish, left on this branch before
    this run resumed it. They were never published, so this run's PR choice publishes them with its own."""
    import subprocess
    from .branches import main_ref
    from .publication import commits,made
    base=main_ref(root,state['config'])
    if not base:raise Refused('No base branch found; set base_branch with oh config')
    try:mine=commits(root,base,reviewed=None)  # render checks the merges
    except subprocess.CalledProcessError as exc:raise Refused(f'OH could not list this branch\'s commits since {base}') from exc
    runs={commit:other for commit in mine if (other:=made(root,state['project'],commit))}
    # Commits OH didn't make (the person's own, or OH's they amended or rebased) belong to no run: a review covered
    # them, or render refuses the PR.
    covers={c for other in runs.values() for intent in other['commit_intents'].values() for c in (intent.get('publication') or {}).get('covers',[])}
    found=[]
    for commit in mine:
        if commit in own:break
        if commit in covers:continue
        if not (other:=runs.get(commit)):raise Refused(f'Commit {commit[:12]} on this branch was neither made nor reviewed by OH')
        if other['status']=='pr' and commit in (other.get('publication') or {}).get('commits',[]):found=[];continue
        if other['status'] not in ('stopped','completed') or other['branch']!=state['branch']:raise Refused('This branch holds commits of another unfinished run')
        found.append(commit)
    return found


def checkpoint(root):
    from .native import select
    return select(root)


@contextmanager
def settled_owner(root):
    with lock(checkout_file(root, 'oh-control.lock')):
        yield


def review_progress(state, task):
    reviews=[a for a in state['attempts'] if a['task']==task and a['role']=='review']
    return {'used':len(reviews),'allowed':review_limit(state,task)}


def running_progress(state, directory=None):
    return {'attempts':[{'id':a['id'],'role':a['role'],'finished':a.get('finished',False)} for a in state['attempts']]}
