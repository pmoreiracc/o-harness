"""Clickable choices. A menu shows the choices OH is waiting for; the click reaches OH through the host,
never through the model. Claude asks with its own question tool and OH reads the click from Claude's
transcript. Codex asks through OH's MCP server, which records the click itself. Typed words still work."""
import re
from .storage import Refused, checkout_file, digest, lock, state_writer

MARK = 'OH gate '
LABELS = {'continue': ('Continue', ''), 'pr': ('Open a PR', 'Publish the committed work as one pull request.'),
          'stop': ('Stop', 'End this run here.'), 'approve': ('Approve', ''),
          'reconsider': ('Reconsider', 'Undo what OH wrote and write nothing.'),
          'retry': ('Retry', 'Try the unfinished task again within one bounded recovery window.'), 'grant review': ('More reviews', 'Allow another window of reviews; this does not accept any findings.'),
          'fix concerns': ('Fix concerns', 'Send the concerns back to be fixed.'),
          'dismiss scope': ('Dismiss scope', 'Record the finding as dismissed; add no work.'),
          'accept concerns': ('Accept concerns', 'Keep the work as it is; the concerns stay on record.'),
          'route scope': ('Route scope', 'Record future work in the design, or file an issue when no mutable design exists.'),
          'accept concerns and route scope': ('Accept and route', 'Accept concerns and record scope as future work.'),
          'accept concerns and dismiss scope': ('Accept and dismiss', 'Accept concerns and record scope as dismissed.'),
          'fix concerns and route scope': ('Fix and route', 'Record scope as future work, then fix only concerns.'),
          'fix concerns and dismiss scope': ('Fix and dismiss', 'Record scope as dismissed, then fix only concerns.')}
REFINE = {'claude': 'To change it, pick Other and type what to change.', 'codex': 'To change it, pick Refine and say what to change.'}


def finding_text(finding):
    return f"{finding['severity']}: {finding['description']}" + (f" ({finding['path']})" if finding.get('path') else '')


def report_text(attempt):
    # A later failed check must stay visible even when the worker itself reported success.
    if attempt.get('outcome') in ('implemented','clean','blocking','needs_resolution'):
        return attempt.get('human_summary') or attempt.get('summary','')
    return attempt.get('summary','')


def review_history(state, task):
    """Facts retained in the journal, including unsuccessful launches and earlier dispositions."""
    from .workflow import review_limit
    reviews=[a for a in state['attempts'] if a['task']==task and a['role']=='review']
    window=state['config']['review_rounds'];limit=review_limit(state,task)
    lines=[f'Reviews used/granted: {len(reviews)}/{limit}. Round {((len(reviews)-1)%window)+1 if reviews else 0} of {window} in this window.']
    seen=set()
    for number,attempt in enumerate(reviews,1):
        lines.append(f"Review {number}: {attempt.get('outcome','unfinished')}; started {attempt.get('started_at','unknown')}; "
                     + (f"{attempt['duration_ms']/1000:.1f}s." if attempt.get('duration_ms') is not None else 'duration unknown.'))
        for finding in attempt.get('findings',[]):
            family=finding.get('family') or finding['description']
            lines.append(f"- {finding_text(finding)} — {'repeats an earlier finding' if family in seen else 'new finding'}.")
        seen.update(f.get('family') or f['description'] for f in attempt.get('findings',[]))
        resolution=state.get('resolutions',{}).get(attempt['id'])
        scope=state.get('scope_records',{}).get(attempt['id'])
        if resolution:lines.append('Decision: '+resolution['choice']+'.')
        if scope:lines.append('Scope: '+scope['action']+'; '+', '.join(f'{k}: {v}' for k,v in scope['destination'].items())+'.')
        if not attempt.get('findings') and report_text(attempt):lines.append(report_text(attempt))
    substantive=[a for a in reviews if a.get('findings') or a.get('outcome')=='clean']
    if substantive:
        last=substantive[-1];resolved=last['id'] in state.get('resolutions',{})
        scope=state.get('scope_records',{}).get(last['id'],{})
        handled=scope.get('findings',[]) if scope.get('action') in ('route','dismiss') else []
        remaining=[] if resolved else [f for f in last.get('findings',[]) if f not in handled]
        lines.append('Open findings: '+('; '.join(finding_text(f) for f in remaining) if remaining else 'none recorded.'))
    return lines


def full_summary(state,root=None):
    """A human gate explains the current task and the effect of waiting, without inventing approval."""
    pending=[t for t in state['tasks'] if t['id'] not in state['done']]
    task=pending[0] if pending else state['tasks'][-1]
    lines=[f"Branch {state['branch']}. Task {task['id']}: {task['title']}.",
           f"Completed: {', '.join(state['done']) or 'none'}. Pending: "+('; '.join(t['id']+': '+t['title'] for t in pending) or 'none')+'.']
    if root is not None:
        from .storage import changes
        lines.append('Uncommitted files: '+(', '.join(changes(root)) or 'none')+'.')
    verification=state.get('verification',{})
    check_task=task['id'] if task['id'] in verification else next(reversed(verification),None)
    checks=verification.get(check_task)
    if checks:
        lines.append(f'Checks: task {check_task}: '+(', '.join(c.get('name','unnamed check')+(': passed' if c['returncode']==0 else ': failed') for c in checks['checks']) or 'none selected')+'.')
    else:lines.append('Checks: not recorded for this task'+(' (planning runs validate document format only).' if state.get('workflow') in ('propose','design') else '.'))
    status=state['status']
    reasons={'checkpoint':'The granted batch is done. No more tasks run until you continue.',
             'prepared_checkpoint':'These tasks are prepared only. Approve grants exactly this list and these limits; waiting runs nothing.',
             'completed':'All selected tasks are done. Publication waits for your PR choice.',
             'approval_checkpoint':'Approval is required before OH continues with this proposal or plan.',
             'review_checkpoint':'The granted review rounds are spent. Work stays here unless you grant more reviews.',
             'findings_checkpoint':'The findings below need a decision. No further work runs until they are resolved.',
             'needs_attention':'The current task could not finish. Retry grants a bounded recovery attempt; waiting starts nothing.'}
    lines.append(reasons[status])
    if status=='prepared_checkpoint':
        from .prepared import limits
        lines.append(limits(len(state['tasks']),state['config']))
        for task in state['tasks']:
            lines.append(f"Task {task['id']}: {task['title']}\n{task['instructions']}\nDependencies: {', '.join(task.get('needs',[])) or 'none'}.")
    if status in ('review_checkpoint','findings_checkpoint','needs_attention'):
        lines.extend(review_history(state,task['id']))
        latest=next((a for a in reversed(state['attempts']) if a['task']==task['id']),None)
        if latest and report_text(latest):lines.append('Latest result: '+report_text(latest))
    return '\n'.join(lines)


def summary(state,root=None,journal=None):
    """Bound the menu even for large valid task lists; save complete details outside the handoff."""
    text=full_summary(state,root)
    # Claude receives both summary and question, so reserve room for both and the menu controls.
    budget=min(8000,max(1000,state['config']['context']['handoff_chars']//3))
    if len(text)<=budget:return text
    reference='the retained run journal (run OH status for a details file)'
    if journal is not None:
        from .storage import atomic_json,read_json
        value={'report':text};path=journal.path/'menus'/(digest(value)+'.json')
        try:atomic_json(path,value,immutable=True)
        except FileExistsError:
            if read_json(path)!=value:raise Refused('Saved menu details changed; restore the run backup before choosing')
        reference=str(path)
    notice=f'Short preview. Complete details: {reference}\nRead the saved report before choosing. '
    if state['status']=='prepared_checkpoint':
        from .prepared import limits
        notice+=f"Approve covers all {len(state['tasks'])} saved tasks, including those omitted here. "+limits(len(state['tasks']),state['config'])
    notice+='\n\n'
    return notice+text[:max(0,budget-len(notice)-18)]+'\n[Preview ends.]'


def options(state):
    """The choices this run is waiting for, as (choice, description) pairs; None when it waits for none."""
    from .workflow import committed, continue_limits
    status = state['status']
    if status=='prepared_checkpoint':
        from .prepared import limits
        return [('approve',limits(len(state['tasks']),state['config'])),('stop','Discard this preparation without running any task.')]
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
            return [('approve', f'OH writes exactly these lines, has them reviewed and commits them. {REFINE[state["host"]]}'),
                    ('reconsider', 'Write nothing; OH asks what you meant.')]
        return [('approve', f'Accept this plan exactly as reviewed. {REFINE[state["host"]]}'), ('reconsider', '')]
    if status == 'review_checkpoint':return [('grant review', f"Allow {state['config']['review_rounds']} more review rounds for this task; findings still require repair or a decision."), ('stop', '')]
    if status == 'needs_attention':
        task = next((t['id'] for t in state['tasks'] if t['id'] not in state['done']), None)
        return ([('retry', '')] if task and task in state['granted'] else []) + [('stop', '')]
    if status == 'findings_checkpoint':
        severities = {f['severity'] for f in state['attempts'][-1].get('findings', [])}
        pairs = {frozenset({'concern'}): ('fix concerns', 'accept concerns'), frozenset({'scope'}): ('route scope', 'dismiss scope'),
                 frozenset({'concern', 'scope'}): ('fix concerns and route scope', 'fix concerns and dismiss scope', 'accept concerns and route scope', 'accept concerns and dismiss scope')}
        found = pairs.get(frozenset(severities), ())
        return [(choice, '') for choice in found] + ([('stop', '')] if len(found)<4 else [])
    return None


def describe(journal, state, root=None):
    """The menu for the current choice, or None. Its id binds the run, its status and the journal head, so a
    click on an older menu never applies to a later state."""
    found = options(state)
    if not found or len(found) < 2:return None
    head = journal.records()[-1]['hash']
    ident = digest({'run': state['id'], 'status': state['status'], 'head': head})[:12]
    title = {'checkpoint': 'This batch is done. What next?', 'completed': 'The run is complete. Open a pull request?',
             'prepared_checkpoint':'Approve these tasks and limits?',
             'approval_checkpoint': 'Approve the proposal?' if state.get('workflow') == 'propose' else 'Approve this plan?',
             'review_checkpoint': 'The review rounds are spent. Allow more?', 'needs_attention': 'A task needs attention. Retry it?',
             'findings_checkpoint': 'How should OH handle the review findings?'}[state['status']]
    menu = [{'choice': choice, 'label': LABELS[choice][0]+(' (Recommended)' if index==0 else ''), 'description': text or LABELS[choice][1] or LABELS[choice][0]}
            for index,(choice, text) in enumerate(found)]
    explanation=summary(state,root,journal)
    return {'id': ident, 'run': state['id'], 'status': state['status'], 'host': state['host'],
            'summary':explanation,'question': f'{explanation}\n\n{title} [{MARK}{ident}]', 'options': menu, 'words': state['status'] == 'approval_checkpoint'}


def current(root):
    from .workflow import active_file, load_run
    if not active_file(root).exists():return None
    journal, state = load_run(root)
    return describe(journal, state,root)


def ask(gate):
    """Claude's AskUserQuestion input for this menu, exactly as OH will compare it."""
    return {'questions': [{'question': gate['question'], 'header': 'OH', 'multiSelect': False,
                           'options': [{'label': o['label'], 'description': o['description']} for o in gate['options']]}]}


def how(gate, root):
    typed = ', '.join(o['choice'] for o in gate['options']) + (', or refine: <what to change>' if gate['words'] else '')
    if gate['host'] == 'claude':
        return ('Ask the person with AskUserQuestion, passing exactly `gate.ask` and never an `answers` field. '
                'After they answer, run OH `run`; OH reads the click from the saved transcript of the conversation that '
                'owns this run, so ask only there. '
                f'Typing works too: {typed}.')
    return (f'Call the o-harness `choose` tool with root "{root}". It shows these choices as a menu and records the click '
            f'itself. Then run OH `run`. If it says the menu could not be shown, ask the person to type one of: {typed}.')


def pick(gate, answer):
    """The choice a click names. Only an offered label counts; free text is a change request where one is allowed."""
    if not isinstance(answer, str) or not answer.strip():raise Refused('The menu came back without a choice; ask again.')
    answer = answer.strip()
    for option in gate['options']:
        if answer.casefold() in (option['label'].casefold(), option['label'].removesuffix(' (Recommended)').casefold(), option['choice'].casefold()):return option['choice']
    from .entry import CHOICES, command
    parsed = command(answer)
    if answer.casefold() in CHOICES | {'pause'} or parsed and parsed[0] != 'choice':
        raise Refused(f'"{answer}" is an OH command, not a change to make, and it is not on this menu. Type it in the chat instead.')
    if gate['words']:
        words = re.sub(r'^refine:\s*', '', answer, flags=re.I).strip()
        if words:return 'refine: ' + words
    raise Refused('OH takes only one of the offered choices here; the text was not treated as a choice. Ask again.')


@state_writer
def apply(root, event, gate_id):
    """Carry out a click on the menu `gate_id` after checking it is still the current menu of this run."""
    from .workflow import _choose, checkpoint, load_run
    with lock(checkout_file(root, 'oh-control.lock')):
        journal, state = load_run(root)
        if event['host'] != state['host'] or event['session'] != state['human']['session']:
            raise Refused('This choice came from another conversation than the one that owns this run.')
        gate = describe(journal, state,root)
        if not gate or gate['id'] != gate_id:
            raise Refused('That menu is out of date: the run moved on after it was shown. Run OH `status` and ask again.')
        # Every menu waits on a run that isn't executing, so Stop is recorded as this person's decision
        # directly, and a finished run offered Open a PR / Stop closes instead of asking again.
        _choose(root, event['prompt'], event)
    return checkpoint(root)
