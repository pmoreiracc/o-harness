from __future__ import annotations



from .storage import checkout_file

from .storage import state_writer

from pathlib import Path
from .config import classify, snapshot
from .storage import Journal, Refused, atomic_json, changes, checkout_id, digest, git, identifier, project, read_json, state_home, lock
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


def unfinished(root,event):
    """Whether this checkout has a run, other than the one this very event started, that isn't stopped, published
    or completed. (A replay of the event after a crash finds its own run.)"""
    if not active_file(root).exists():return False
    _,state=load_run(root)
    return state['source']!=digest({k:event[k] for k in ('host','session','turn','prompt')}) and state['status'] not in ('stopped','pr','completed')


def occupied(state):
    """Why a new command can't start while this checkout's run is open, and the person's choice the agent asks."""
    what=f"its {state['workflow']} run {state['id'][:8]}"
    if state['status']=='stopping':
        return Refused(f'OH is stopping {what} in this checkout; run `run` again once `status` says it stopped.')
    return Refused(f'OH is still working on {what} in this checkout. Ask the person with a menu: stop it and start '
        'this command (run `stop`, then `run`), or keep it and cancel this command (run `cancel`).')


def active_file(root):
    return checkout_file(root, 'oh-active-run.json')


NO_RUN=('No OH command is waiting in this checkout. Type /oh-propose <idea>, /oh-design <slug> or /oh-deliver '
        '(in Codex: $oh-propose, $oh-design, $oh-deliver).')


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
        elif kind=='attempt.started':state['attempts'].append(d | {'finished':False,'started_at':record['at']})
        elif kind=='attempt.finished':
            matches=[a for a in state['attempts'] if a['id']==d['id']]
            if len(matches)!=1:raise Refused('Completion without exactly one admitted attempt')
            matches[0].update(d | {'finished':True,'finished_at':record['at']})
        elif kind=='verification':state.setdefault('verification',{})[d['task']]=d
        elif kind=='run.status':
            state['status']=d['status']
            if d['status'] not in ('approval_checkpoint','prepared_checkpoint'):state.pop('refinement',None)
            state.setdefault('status_history',[]).append(d|{'at':record['at']})
            if d['status']=='pausing':state['pause_return_status']=d['return_status']
            if d['status']=='paused':state['pause_snapshot']={'tree':d['tree'],'head':d['head']}
        elif kind=='task.intervention':state['interventions'][d['task']]=state['interventions'].get(d['task'],0)+1
        elif kind=='review.resolution':state['resolutions'][d['attempt']]=d
        elif kind=='run.owner':state['human']=d['human']
        elif kind=='recovery.grant':state.setdefault('recovery_grants',[]).append(d)
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
            matches[0].update(outcome='verification_failed',summary=d['summary'])
        elif kind=='decision':
            state['decisions'].append(d['source'])
            if d['choice']=='pr':state['publication']=d
            if d['choice']=='handoff pr':state['review_handoff']=d
    return state


def _start(root, manifest, event, prepared=None, plan=None, waiting=None):
    tasks=validate_tasks(manifest['tasks']);p=project(root)
    workflow=manifest.get('workflow','deliver')
    if workflow not in ('propose','design','deliver'):raise Refused('Unknown workflow')
    # Plan settings and plan transitions come only from OH's own parsing of a typed /oh-design, never from a
    # manifest file: a prepared file is delivery work, whoever wrote it.
    if {'plans','slug','delivery'}&set(manifest) or (plan is None and any((t.get('transition') or {}).get('profile') in ('plans','intake','delivery') for t in tasks)):
        raise Refused('A manifest cannot choose plan settings or plan transitions')
    if prepared is not None and (workflow!='deliver' or plan is not None):raise Refused('Prepared scope is delivery work only')
    if workflow!='deliver' and len(tasks)!=1:raise Refused('Planning workflows have one bounded artifact task')
    source=digest({k:event[k] for k in ('host','session','turn','prompt')})
    if waiting:source=digest({'human':source,'prepared':waiting})
    if active_file(root).exists():
        journal,state=load_run(root)
        if state['source']==source:return journal,state
        if state['status']=='prepared_checkpoint' and waiting and state['human']['session']==event['session'] and state['host']==event['host']:
            journal.append('run.status',{'status':'stopped','reason':'Replaced by a newer prepared scope; no work was granted.'})
            best_effort('run.status',state['project'],state['id'],status='stopped')
        elif state['status'] not in ('stopped','pr','completed'):raise occupied(state)
    config=prepared['snapshot'] if prepared else snapshot(root)
    from .config import project_checks
    required=prepared['project_checks'] if prepared else project_checks(root)
    if workflow=='deliver' and not required and not manifest.get('checks'):raise Refused("Add this project's checks before starting paid work: oh config set checks '<JSON list>'")
    if changes(root):
        raise Refused('Start from a clean execution checkout; save task manifests in external OH project storage')
    run=identifier();checkout=checkout_id(root)
    from .branches import trunk
    base_name=trunk(root,config['config'])
    original=git(root,'branch','--show-current');base=git(root,'rev-parse','HEAD');created=None
    if plan and workflow in ('design','propose') and committed(plan) and original!=base_name:
        label='designs' if workflow=='design' else 'proposals'
        raise Refused(f'Committed {label} must start from {base_name}; switch to that branch before typing /oh-{workflow} again')
    try:
        if workflow=='deliver' and not waiting and git(root,'branch','--show-current')==base_name:
            from .branches import execution_branch
            target=execution_branch(root,tasks[0]['title'],run)  # numbered designs already have their deliver/ branch
            git(root,'switch','-c',target);created=target
        import re
        current=git(root,'branch','--show-current')
        if plan and committed(plan) and current!=base_name and re.match(r'(design|propose)[/-]',current):
            raise Refused(f'This checkout is on {current}, the branch of another plan; switch to {base_name} first')
        if plan and workflow=='design' and committed(plan) and git(root,'branch','--show-current')==base_name:
            from .plans import branch_for
            target=branch_for(root,plan['slug'],run)
            git(root,'switch','-c',target);created=target
        from .branches import incarnation
        branch_incarnation=incarnation(root,git(root,'branch','--show-current'),create=True)
        for task in tasks:
            # The design or the agent that prepared the tasks decides each task's difficulty; the rubric decides
            # only when they didn't.
            if task.get('difficulty') not in ('simple','standard','complex') or not isinstance(task.get('difficulty_reason'),str) or not task['difficulty_reason'].strip():
                task['difficulty'],task['difficulty_reason']=classify(task)
        data={'id':run,'project':p['id'],'name':p['name'],'work_kind':p['kind'],
              'host':event['host'],'checkout':checkout,'source':source,'human':event,
              'branch':git(root,'branch','--show-current'),'incarnation':branch_incarnation,'base':git(root,'rev-parse','HEAD'),
              'workflow':manifest.get('workflow','deliver'),'design':manifest.get('design'),'track':manifest.get('track'),
              **(plan or {}),
              'tasks':tasks,'checks':manifest.get('checks',[]),'project_checks':required,**config}
        if waiting:data['prepared_request']=waiting
        journal=Journal(p['id'],run)
        journal.append('run.started',data)
        ids=[t['id'] for t in tasks[:data['config']['tasks_per_batch']]]
        if waiting:journal.append('run.status',{'status':'prepared_checkpoint'})
        else:journal.append('grant',{'tasks':ids,'source':source,'kind':'initial','config_hash':data['config_hash']})
        atomic_json(active_file(root),{'project':p['id'],'run':run,'checkout':checkout})
    except Exception:
        # A start that never published its active pointer must not strand the checkout
        # on a plan branch which the next typed command will refuse. Retain its journal.
        active=read_json(active_file(root)) if active_file(root).exists() else {}
        if created and active.get('run')!=run:
            if (git(root,'branch','--show-current')!=created or git(root,'rev-parse','HEAD')!=base
                    or changes(root)):
                raise Refused('Run start failed and the checkout changed; inspect it, then switch back to '+original+' before typing the command again')
            git(root,'switch',original)
            from subprocess import CalledProcessError
            try:git(root,'update-ref','-d','refs/heads/'+created,base)
            except CalledProcessError as exc:
                raise Refused('Run start failed and branch cleanup was refused; inspect '+created+' before starting again') from exc
        raise
    best_effort('run.started',p['id'],run,name=p['name'],work_kind=p['kind'],host=event['host'],
                version=data['harness_version'],config_hash=data['config_hash'])
    if waiting:best_effort('run.status',p['id'],run,status='prepared_checkpoint')
    return journal,reduce(journal.records())


def _choose(root, choice, event):
    from .runner import approved
    journal,state=load_run(root)
    events=[]
    def append(kind,data):events.append({'kind':kind,'data':data})
    source=digest({k:event[k] for k in ('host','session','turn','prompt')})
    if state.get('discard'):
        discard_proposal(root,journal,state)
        state=reduce(journal.records())
    if source in state['decisions']:return state
    if event['host']!=state['host']:
        raise Refused('Resume through the host that owns this run')
    if choice=='approve' and 'feedback' in state.get('refinement',{}):
        raise Refused('Revise the unapproved task list and call prepare before asking for approval.')
    if choice=='approve' and state['status'] in ('approval_checkpoint','prepared_checkpoint'):
        from .gates import describe
        describe(journal,state,root)  # approval must still refer to the unchanged review copy
    if choice=='refine':
        if state['status'] not in ('approval_checkpoint','prepared_checkpoint'):raise Refused('No preview is waiting for changes')
        append('refinement.requested',{'source':event})
        append('decision',{'source':source,'choice':choice})
    elif state['status']=='prepared_checkpoint' and choice=='cancel':
        append('decision',{'source':source,'choice':choice})
        append('run.status',{'status':'stopped'})
    elif state['status']=='prepared_checkpoint' and choice.startswith('refine:'):
        words=choice[len('refine:'):].strip()
        if not words:raise Refused('Say what to change in the chat.')
        append('refinement.feedback',{'source':event,'feedback':words})
        append('decision',{'source':source,'choice':'refine'})
    elif state['status']=='prepared_checkpoint' and choice=='approve':
        from .prepared import activate
        activation=activate(root,journal,state,event)
        append('preparation.activated',activation)
        append('grant',{'tasks':[t['id'] for t in state['tasks'][:state['config']['tasks_per_batch']]],'source':source,'kind':'initial','config_hash':state['config_hash']})
        append('decision',{'source':source,'choice':choice})
        append('run.status',{'status':'running'})
    elif choice=='continue':
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
            spent=sum(a.get('outcome') in ('failed','interrupted','verification_failed') for a in state['attempts'] if a['task']==task and a['role'] in ('implementation','analysis'))
            append('recovery.grant',{'task':task,'source':source,'spent_before':spent})
        append('decision',{'source':source,'choice':choice})
        append('run.status',{'status':state.get('pause_return_status','running') if choice=='resume' else 'running'})
        append('task.intervention',{'task':task})
    elif choice in ('approve','cancel') or choice.startswith('refine:'):
        if state['status']!='approval_checkpoint':raise Refused('No proposal is waiting for approve, refine or cancel')
        task=state['tasks'][0]['id'];last=[a for a in state['attempts'] if a['task']==task][-1]
        proposing=state.get('workflow')=='propose'
        if choice=='cancel' and proposing and not (state.get('rendered') or {}).get('files'):
            # Nothing is written before approval; cancellation ends this proposal without another question.
            append('decision',{'source':source,'choice':choice})
            append('run.status',{'status':'stopped'})
        elif choice=='cancel':
            # Write nothing: undo what OH wrote and leave the branch it cut, when that branch holds no commit.
            from .plans import undo
            if git(root,'branch','--show-current')!=state['branch'] or git(root,'rev-parse','HEAD')!=state['base']:
                raise Refused('Return to the proposal branch and its recorded base before cancelling')
            from .branches import incarnation
            if incarnation(root,state['branch'])!=state['incarnation']:raise Refused('The proposal branch was recreated; preserve it and stop this run')
            undo(root,state.get('rendered'),check_only=True)
            append('proposal.discard',{'branch':state['branch'],'incarnation':state['incarnation'],
                'base':state['base'],'return_to':state.get('moved_from')})
            append('decision',{'source':source,'choice':choice})
            append('run.status',{'status':'stopped'})
        else:
            words=choice[len('refine:'):].strip() if choice.startswith('refine:') else ''
            if choice.startswith('refine:') and not words:raise Refused('Say what to change: refine: <what to change>')
            decided='refine' if words else 'approve'
            append('proposal',{'attempt':last['id'],'choice':decided,'feedback':words,'source':source}
                   |({'shown':approved(state['preview']['plan'])} if proposing else {}))
            append('decision',{'source':source,'choice':decided})
            append('run.status',{'status':'running'})
            if words:append('task.intervention',{'task':task})
    elif choice=='handoff pr':
        if state['status']!='review_checkpoint' or not committed(state):
            raise Refused('A PR handoff requires a spent review window for repository work')
        from .verification import tree
        append('decision',{'source':source,'choice':choice,'head':git(root,'rev-parse','HEAD'),
                           'tree':tree(root),'reviews':[a['id'] for a in state['attempts'] if a['role']=='review']})
        append('run.status',{'status':'stopped'})
    elif choice in ('pr','stop'):
        if choice=='pr' and not committed(state):raise Refused('Planning does not authorize product publication')
        if choice=='pr' and state['status'] not in ('checkpoint','completed'):
            raise Refused('PR choice requires completed work at a checkpoint')
        decision={'source':source,'choice':choice}
        if choice=='pr':
            from .branches import fetched,trunk
            if main:=trunk(root,state['config']):fetched(root,main)
            from .delivery_verify import verify
            verify(root,state)
            head=git(root,'rev-parse','HEAD');branch=git(root,'branch','--show-current')
            commits=[item['commit'] for item in state['summaries'] if 'commit' in item]
            if not commits:raise Refused('Nothing was committed, so there is nothing to publish')
            if head!=commits[-1] or branch!=state['branch']:
                raise Refused('PR choice must cover the exact completed branch head')
            decision.update(head=head,branch=branch,base_branch=trunk(root,state['config']),commits=adopted(root,state,commits)+commits)
        append('decision',decision)
        append('run.status',{'status':'pr' if choice=='pr' else 'stopped'})
    elif choice in ('accept concerns','route scope','dismiss scope','accept concerns and route scope',
                    'accept concerns and dismiss scope','fix concerns','fix concerns and route scope','fix concerns and dismiss scope'):
        if state['status']!='findings_checkpoint':raise Refused('No unresolved review findings')
        review=state['attempts'][-1];task=review['task'];findings=review.get('findings',[])
        severities={f['severity'] for f in findings}
        expected=({'concern','scope'} if ' and ' in choice else {'scope'} if choice in ('route scope','dismiss scope') else {'concern'})
        if severities!=expected:raise Refused('The choice must resolve every retained finding without dismissing blockers')
        from .verification import candidate_tree,tree
        if tree(root)!=review['tree'] or candidate_tree(root)!=review['git_tree']:raise Refused('Findings no longer describe the current tree; repair and review it again')
        from .delivery import guard
        guard(root,state)
        scope=None
        if 'scope' in severities:
            from .scope import prepare
            scope=prepare(root,journal,state,review,'dismiss' if 'dismiss' in choice else 'route','human choice')
            if scope:append('scope.recorded',scope)
        if not choice.startswith('fix concerns'):
            append('review.resolution',{'attempt':review['id'],'source':source,'choice':choice,
                'issue':((scope or {}).get('destination') or {}).get('issue'),
                'scope':{k:v for k,v in (scope or {}).items() if k!='render'},'tree':review['git_tree']})
        append('decision',{'source':source,'choice':choice})
        append('run.status',{'status':'running'})
        append('task.intervention',{'task':task})
    elif choice=='grant review':
        if state['status']!='review_checkpoint':raise Refused('No spent review window')
        task=next(t['id'] for t in state['tasks'] if t['id'] not in state['done'])
        append('task.intervention',{'task':task})
        append('review.grant',{'task':task,'source':source,'rounds':state['config']['review_rounds']})
        append('decision',{'source':source,'choice':choice})
        append('run.status',{'status':'running'})
    else:raise Refused('Unknown human choice')
    if state['status'] in ('checkpoint','review_checkpoint','findings_checkpoint','approval_checkpoint','needs_attention') and any(item['kind']=='run.status' and item['data']['status']=='running' for item in events):
        pending=next((t['id'] for t in state['tasks'] if t['id'] not in state['done']),None)
        from datetime import datetime,timezone
        waits=[entry for entry in journal.records() if entry['kind']=='run.status' and entry['data']['status'] in ('checkpoint','review_checkpoint','findings_checkpoint','approval_checkpoint','needs_attention')]
        if pending and waits:
            best_effort('phase.finished',state['project'],state['id'],pending,phase='waiting',duration_ms=(datetime.now(timezone.utc)-datetime.fromisoformat(waits[-1]['at'])).total_seconds()*1000)
    journal.append('transition',{'source':event,'events':events})
    for item in events:
        if item['kind']=='run.status':best_effort('run.status',state['project'],state['id'],**item['data'])
        elif item['kind']=='task.intervention':
            best_effort('task.intervention',state['project'],state['id'],item['data']['task'],
                        reason='review_window_renewed' if choice=='grant review' else choice.split(':',1)[0])
    state=reduce(journal.records())
    if choice=='stop':checkout_file(root,'oh-preparation-owner.json').unlink(missing_ok=True)
    if state.get('discard'):discard_proposal(root,journal,state)
    if choice=='cancel':
        from .authority import drop_waiting
        drop_waiting(state['human']['session'])
        checkout_file(root,'oh-preparation-owner.json').unlink(missing_ok=True)
    return reduce(journal.records())


def discard_proposal(root,journal,state):
    """Finish a durably recorded cancellation; retries never grant work."""
    from .plans import undo
    from .branches import incarnation
    pending=state['discard'];branch=pending['branch'];target=pending['return_to']
    if target and pending.get('return_incarnation') and incarnation(root,target)!=pending['return_incarnation']:
        raise Refused('The original branch was recreated; restore its recorded identity before cleanup')
    current=git(root,'branch','--show-current')
    exists=bool(git(root,'branch','--list',branch))
    if current not in (branch,target) or git(root,'rev-parse','HEAD')!=pending['base']:
        raise Refused('Proposal cleanup is pending; restore its recorded branch/base and run OH again')
    if exists and (git(root,'rev-parse',branch)!=pending['base'] or incarnation(root,branch)!=pending['incarnation']):
        raise Refused('The proposal branch changed; preserve it and restore its recorded identity before cleanup')
    if current==branch:
        undo(root,state.get('rendered'))
        if changes(root):raise Refused('Preserve unrelated edits before retrying proposal cleanup')
        if target:
            if git(root,'rev-parse',target)!=pending['base']:raise Refused('The original branch moved; restore its base before retrying proposal cleanup')
            git(root,'switch',target)
    elif changes(root):
        raise Refused('Preserve new edits before retrying proposal cleanup')
    if target and exists:
        from subprocess import CalledProcessError
        try:git(root,'update-ref','-d','refs/heads/'+branch,pending['base'])
        except CalledProcessError:
            raise Refused('The proposal branch changed during cleanup; preserve it and inspect it before retrying') from None
    journal.append('proposal.discarded',{})


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


def reopen(root,state,event):
    """Make a finished run this checkout's run again, so its pull request can be chosen: the person typing the
    delivery again after stopping it at completion wants that choice back. It grants no new work."""
    journal=Journal(state['project'],state['id'])
    with lock(checkout_file(root,'oh-control.lock')):
        owned(journal,state,event)
        if state['status']=='stopped':
            journal.append('decision',{'source':digest({k:event[k] for k in ('host','session','turn','prompt')}),'choice':'reopen'})
            journal.append('run.status',{'status':'completed'})
        atomic_json(active_file(root),{'project':state['project'],'run':state['id'],'checkout':checkout_id(root)})
    return checkpoint(root)


def carry_on(root,event):
    """The person typed the checkout's open run's command again: carry on with it, from this conversation."""
    with lock(checkout_file(root,'oh-control.lock')):
        journal,state=load_run(root)
        owned(journal,state,event)
    return checkpoint(root)


def owned(journal,state,event):
    """A verified command typed in another conversation of the run's host makes that conversation the run's owner,
    so its menus are answered there. The host stays: its workers and transcripts are that host's."""
    if state['human'].get('session')==event['session']:return
    from .storage import Final
    if state['host']!=event['host']:raise Final(f"This run belongs to {state['host'].title()}; carry on with it there")
    journal.append('run.owner',{'human':event})


def review_progress(state,task):
    """Keep a finished review available at approval and completion checkpoints."""
    from .gates import report_text
    reviews=[a for a in state['attempts'] if a['task']==task and a['role']=='review' and a.get('finished')]
    if not reviews:return None
    review=reviews[-1];findings=review.get('findings',[])
    return {'attempt':review['id'],'task':task,'round':len(reviews),'outcome':review['outcome'],
            'summary':report_text(review)[:600],'finding_count':len(findings),
            'decision':state.get('resolutions',{}).get(review['id'],{}).get('choice'),
            'findings':[{k:str(f.get(k,''))[:250] for k in ('severity','description','path','family')} for f in findings[:5]]}


def running_progress(state):
    """Describe the current task from retained execution evidence, without inspecting worker transcripts."""
    if state['status']!='running':return {}
    task=next((t for t in state['tasks'] if t['id'] in state['granted'] and t['id'] not in state['done']),None)
    if not task:return {}
    attempts=[a for a in state['attempts'] if a['task']==task['id']]
    last=attempts[-1] if attempts else None
    phase='preparing'
    if last:
        if not last['finished']:
            phase=last['role']
        elif last['role']=='review':
            phase='completing' if last.get('outcome')=='clean' or last['id'] in state['resolutions'] else 'preparing'
        elif last.get('outcome')=='implemented':phase='checks'
    from .gates import report_text
    worker=next((a for a in reversed(attempts) if a['role'] in ('implementation','analysis') and a.get('outcome')=='implemented'),None)
    progress={'task':task['id'],'title':' '.join(task['title'].split())[:200], 'phase':phase}
    if last and not last['finished']:progress|={'attempt':last['id'],'profile':last['profile']}
    if worker:progress['implementation']={'attempt':worker['id'],'summary':report_text(worker)[:900]}
    if review:=review_progress(state,task['id']):progress['review']=review
    return {'progress':progress}


def checkpoint(root):
    journal,state=load_run(root)
    from .prepared import limits
    left=len([t for t in state['tasks'] if t['id'] not in state['done']])
    reviewed=next((a['task'] for a in reversed(state['attempts']) if a['role']=='review' and a.get('finished')),None)
    last_review=review_progress(state,reviewed) if reviewed else None
    model_notices=list(dict.fromkeys(a['model_fallback']['notice'] for a in state['attempts'] if a.get('model_fallback')))[-5:]
    private_diff={}
    if state['status']=='approval_checkpoint' and state.get('plans',{}).get('location')=='private' and state.get('rendered',{}).get('files'):
        from .plans import changed_text,validate_outputs
        validate_outputs(root,state['rendered'],state['plans']['base'])
        private_diff={'private_diff':changed_text(root,state['rendered'])}
    return {'run':state['id'],'status':state['status'],'completed':len(state['done']),
            'authorized_remaining':[t for t in state['granted'] if t not in state['done']],
            'last_results':state['summaries'][-2:],'evidence':str(journal.path),
            'review_rounds':sum(a['role']=='review' and a['task'] in state['done'] for a in state['attempts']),
            'config_hash':state['config_hash'],'version':state['harness_version']} | (
            {'model_notices':model_notices} if model_notices else {}) | (
            {'last_review':last_review} if last_review else {}) | running_progress(state) | (
            {'publication':state['publication']|{'next':'Execution is finished. Use pr_summary, push the approved branch and open one PR targeting publication.base_branch. Report its number, link and a short summary. Do not ask for PR approval again, call run or repeat implementation/review.'}}
            if state['status']=='pr' and state.get('publication') else {}) | (
            {'handoff':state['review_handoff']|{'next':'OH stopped with unresolved work for human PR triage. No task completion, review renewal or publication approval was granted.'}}
            if state.get('review_handoff') else {})|(
            {'plan':{k:v for k,v in state['rendered'].items() if k in ('kind','number','title','path','tasks','summary')}
                    |({'choices':['approve','refine: <what to change>','cancel']} if state['status']=='approval_checkpoint' else {})}
             if state.get('rendered',{}).get('files') and state.get('workflow')=='design' else {})|(
            {'proposal':{k:v for k,v in state['preview']['plan'].items() if k in ('route','understanding','reason','evidence','text','summary','lines','intent','writes')}
                        |({'choices':['approve','refine: <what to change>','cancel']} if state['status']=='approval_checkpoint' else {})}
             if state.get('workflow')=='propose' and state.get('preview') else {})|(
            {'limits':continue_limits(left,state['config'])} if state['status']=='checkpoint' and left else
            {'limits':limits(left,state['config'])} if state['status']=='running' and left else {}) | private_diff | menu(root,journal,state) | waiting(root,state)


def refinement_for(root,host,session):
    from .registry import index_path
    if not index_path(root).is_file() or not active_file(root).exists():return None
    _,state=load_run(root)
    if state['host']==host and state['human']['session']==session:
        return state.get('refinement')
    return None


def waiting(root,state):
    """The question the agent asks while collecting conversational input."""
    if refinement:=state.get('refinement'):
        if 'feedback' in refinement:
            return {'prepare':True,'authorized':False,'feedback':refinement['feedback'],'tasks':state['tasks'],
                    'next':'Revise the unapproved task list using this feedback, then call prepare to show a fresh approval. No tasks have been granted.'}
        return {'waiting':{'command':'refine','ask':'What would you like to change?',
                           'next':'Ask in plain chat and end your turn; do not open another question form. After the human replies, call OH run to read their message and update the preview.'}}
    from .authority import waiting_for
    found=waiting_for(root,state['human']['host'],state['human']['session'])
    return {'waiting':found|{'next':WAIT_NEXT}} if found else {}


WAIT_NEXT=('Ask the person exactly `ask` in plain chat and end your turn. Their next message is the argument of the '
           'command: OH starts it when you run OH `run` after they answer. Another OH command replaces it; /oh-stop drops it.')


def menu(root,journal,state):
    """The current choice as a clickable menu, with how to show it on this run's host."""
    from .gates import ask,describe,how,native_ask
    if state.get('refinement'):return {}
    gate=describe(journal,state,root)
    if not gate:return {}
    return {'gate':{'id':gate['id'],'summary':gate['summary'],'details':gate['details'],'choices':[o['choice'] for o in gate['options']]}
            |({'preview':gate['preview']} if gate.get('preview') else {})
            |({'ask':ask(gate)} if gate['host']=='claude' else {'native_ask':native_ask(gate)})
            |{'how':how(gate,root)}}


def continue_limits(left,config):
    """What typing continue approves, said at every checkpoint."""
    batch,rounds=min(left,config['tasks_per_batch']),config['review_rounds']
    return (f'Continue runs {batch} of the {left} remaining task'+('s' if left!=1 else '')+f', up to {rounds} review round'
            +('s' if rounds!=1 else '')+' each. This run keeps its settings; /oh-config changes them for the next run.')


@state_writer
def start(root,manifest,event,prepared=None,plan=None,waiting=None):
    with lock(checkout_file(root, 'oh-control.lock')):
        return _start(root,manifest,event,prepared,plan,waiting)


@state_writer
def choose(root,choice,event):
    # A stop typed at completion declines the pull request, as the menu's Stop does; controls only reduce a run's work.
    if choice=='pause' or choice=='stop' and load_run(root)[1]['status']!='completed':
        from .controls import request
        return request(root,choice)
    with lock(checkout_file(root, 'oh-control.lock')):
        return _choose(root,choice,event)
