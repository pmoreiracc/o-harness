"""Shared next-action policy. Execution supplies validated facts; views cannot grant work."""


def external_failures(attempts, state):
    resumed = max([s['at'] for s in state.get('status_history', []) if s['status'] == 'running']+[''])
    failed = 0
    for attempt in reversed(attempts):
        if attempt['started_at'] < resumed or attempt.get('outcome') not in ('failed', 'interrupted'):break
        failed += 1
    return failed >= 2


def next_action(state, current_tree=None, *, verified=False):
    from .workflow import next_task, review_limit
    status = state['status']
    if state.get('published'):return {'kind':'published','phase':'publication'}
    if status in ('stopping', 'pausing', 'stopped', 'paused'):
        return {'kind': 'stopped' if status in ('stopping', 'stopped') else 'paused', 'phase': status}
    if status == 'pr':return {'kind': 'publish' if state.get('publication',{}).get('destination') and not state.get('publication_changed') else 'decision', 'phase': 'publication'}
    if status == 'needs_attention':return {'kind': 'blocked', 'phase': 'needs_attention'}
    if status == 'review_checkpoint' and state.get('workflow', 'deliver') == 'deliver':
        continuation = next_action(state | {'status': 'running'}, current_tree)
        if continuation['kind'] in ('implement', 'route_scope'):
            return continuation | {'resume': True}
    if status != 'running':
        return {'kind': 'finished' if status == 'completed' and not choices(state) else 'decision', 'phase': status}
    task = next_task(state)
    if not task:
        return {'kind': 'boundary', 'phase': 'completed' if len(state['done']) == len(state['tasks']) else 'checkpoint'}
    task_id = task['id']
    history = [a for a in state['attempts'] if a['task'] == task_id]
    def result(kind, **extra):
        phases = {'assess': 'assessment', 'implement': 'implementation' if state.get('workflow', 'deliver') == 'deliver' else 'analysis',
                  'verify': 'checks', 'complete': 'completing', 'complete_proposal': 'completing',
                  'preview': 'preparing', 'route_scope': 'preparing', 'review': 'review',
                  'review_allowance': 'review_checkpoint', 'approve_plan': 'approval_checkpoint', 'blocked': 'needs_attention'}
        return {'kind': kind, 'task': task_id, 'phase': phases.get(kind, kind)} | extra
    if history and not history[-1].get('finished'):
        pending=state.get('reports',{}).get(history[-1]['id'],{})
        return result('working', phase='report_correction' if pending.get('issues') else history[-1]['role'], attempt=history[-1]['id'])
    if state.get('workflow', 'deliver') == 'deliver' and task_id not in state['task_started'] and task_id not in state.get('assessments', {}):
        attempts = [a for a in history if a['role'] == 'assessment']
        return result('blocked' if external_failures(attempts, state) else 'assess')
    from .runner import intake, designing, gated, accepted
    previous = [a for a in history if a['role'] != 'assessment']
    last = previous[-1] if previous else None
    authors = [a for a in previous if a['role'] in ('implementation', 'analysis')]
    work = authors[-1] if authors else None
    from .handoff import legacy_pending
    if legacy_pending(work):return result('restore_report',work=work['id'])
    reviews = [a for a in previous if a['role'] == 'review']
    decided = state.get('proposals', {}).get(last['id']) if last and gated(state, task) else None
    if intake(task) and last and last['role'] == 'analysis' and last.get('outcome') == 'implemented':
        if (state.get('preview') or {}).get('attempt') != last['id']:return result('preview')
        answer = accepted(state)
        if not answer:return result('approve_plan')
        if answer == 'refine':decided = state['proposal_answers'][-1]
        elif not state['preview']['plan']['lines']:return result('complete_proposal')
    resolved = last and (last.get('outcome') == 'clean' or last['id'] in state.get('resolutions', {}))
    if gated(state, task) and resolved and not decided:return result('approve_plan')
    rerendered = bool(last and state.get('scope_records', {}).get(last['id'], {}).get('render'))
    if decided and decided['choice'] == 'approve' or resolved and not gated(state, task) and not rerendered:
        return result('complete', review=last['id'])
    if (last and last.get('outcome') == 'blocking' and last['id'] not in state.get('scope_records', {}) and
            any(f['severity'] == 'scope' for f in last.get('findings', []))):
        return result('route_scope', review=last['id'])
    if work and work.get('outcome')=='report_invalid':return result('blocked',attempt=work['id'])
    if external_failures(authors, state):return result('blocked')
    refined = bool(decided and decided['choice'] == 'refine')
    reusable = bool(work and work.get('outcome') == 'implemented' and
                    (current_tree is None or work.get('tree') == current_tree) and
                    (last is work or last.get('outcome') in ('failed', 'interrupted','review_incomplete')) and not refined)
    if rerendered and last['id'] in state.get('resolutions', {}) and work and work.get('outcome') == 'implemented':reusable = True
    existing = bool(designing(task) and task['transition'].get('existing') and not refined and
                    (not previous or all(a['role'] == 'review' and a.get('outcome') in ('failed', 'interrupted','review_incomplete') for a in previous)))
    if verified:
        return result('review_allowance' if len(reviews) >= review_limit(state, task_id) else 'review')
    return result('verify' if reusable or existing else 'implement',
                  work=work['id'] if work else None, reuse=reusable, existing=existing, refined=refined)


def choices(state):
    """The choices this run is waiting for, as (choice, description) pairs; None when it waits for none."""
    from .workflow import committed, continue_limits
    from .gates import approval_effect
    status = state['status']
    if state.get('published'):return None
    if status=='pr' and (not state.get('publication',{}).get('destination') or state.get('publication_changed')):
        return [('pr','Confirm the destination for the already-reviewed work.'),('stop','Keep the work locally.')]
    if status=='prepared_checkpoint':
        from .prepared import limits
        return [('approve',limits(len(state['tasks']),state['config'])),('refine',''),('cancel','Discard this preparation without running any task.')]
    if status == 'checkpoint':
        left = len([t for t in state['tasks'] if t['id'] not in state['done']])
        found = ([('continue', continue_limits(left, state['config']))] if left else [])
        found += [('pr', '')] if committed(state) and any('commit' in s for s in state['summaries']) else []
        return found + [('stop', '')]
    if status == 'completed':
        if not committed(state) or not any('commit' in s for s in state['summaries']):return None
        return [('pr', ''), ('stop', '')]
    if status == 'approval_checkpoint':
        if state.get('workflow') == 'propose':
            return [('approve', approval_effect(state)), ('refine',''),
                    ('cancel', 'End this proposal without saving it.')]
        return [('approve', approval_effect(state)), ('refine',''), ('cancel', 'Discard this unapproved draft and end the run.')]
    if status == 'review_checkpoint':
        if next_action(state).get('resume'):return None
        found=[('grant review', f"Allow up to {state['config']['review_rounds']} fresh independent reviews for this task; approved scope stays the same."),
               ('stop', 'End OH here and keep the work for you to finish manually.')]
        return found+[('handoff pr','')] if committed(state) else found
    if status == 'paused':return [('resume',''),('stop','')]
    if status == 'needs_attention':return None
    if status == 'findings_checkpoint':
        severities = {f['severity'] for f in state['attempts'][-1].get('findings', [])}
        pairs = {frozenset({'concern'}): ('fix concerns', 'accept concerns'), frozenset({'scope'}): ('route scope', 'dismiss scope'),
                 frozenset({'concern', 'scope'}): ('fix concerns and route scope', 'fix concerns and dismiss scope', 'accept concerns and route scope', 'accept concerns and dismiss scope')}
        found = pairs.get(frozenset(severities), ())
        return [(choice, '') for choice in found] + ([('stop', '')] if len(found)<4 else [])
    return None

