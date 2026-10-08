"""Clickable choices. A menu shows the choices OH is waiting for; the click reaches OH through the host,
never through the model. Claude asks with its own question tool and OH reads the click from Claude's
transcript. Codex asks through OH's MCP server, which records the click itself. Typed words still work."""
import re
from pathlib import Path
from .storage import Refused, checkout_file, digest, lock, state_writer

MARK = 'OH gate '
LABELS = {'continue': ('Continue', ''), 'pr': ('Open a PR', 'Publish the committed work as one pull request.'),
          'stop': ('Stop and take over', 'End OH here and keep the work for you to continue; do not push or open a PR.'), 'resume': ('Resume', 'Continue with the existing task and review allowances.'),
          'handoff pr': ('Stop and hand off to a PR', 'End OH and retain unresolved work for human PR triage; this does not approve completion or publication.'), 'approve': ('Approve', ''),
          'refine': ('Refine', 'Tell OH what to change in the chat.'),
          'cancel': ('Cancel', 'Discard this unapproved proposal and end the run.'),
          'retry': ('Retry', 'Try the unfinished task again within one bounded recovery window.'), 'grant review': ('More reviews', 'Allow another window of reviews; this does not accept any findings.'),
          'fix concerns': ('Fix concerns', 'Send the concerns back to be fixed.'),
          'dismiss scope': ('Dismiss scope', 'Record the finding as dismissed; add no work.'),
          'accept concerns': ('Accept concerns', 'Keep the work as it is; the concerns stay on record.'),
          'route scope': ('Route scope', 'Record future work in the design, or file an issue when no mutable design exists.'),
          'accept concerns and route scope': ('Accept and route', 'Accept concerns and record scope as future work.'),
          'accept concerns and dismiss scope': ('Accept and dismiss', 'Accept concerns and record scope as dismissed.'),
          'fix concerns and route scope': ('Fix and route', 'Record scope as future work, then fix only concerns.'),
          'fix concerns and dismiss scope': ('Fix and dismiss', 'Record scope as dismissed, then fix only concerns.')}


def approval_effect(state):
    if state['status']=='prepared_checkpoint':
        from .prepared import limits
        return limits(len(state['tasks']),state['config'])
    if state.get('workflow')!='propose':return 'Approve this reviewed plan for later delivery. Implementation does not start here.'
    plan=(state.get('preview') or {}).get('plan',{})
    if plan.get('route') in ('improvement','unclear'):return 'Accept this assessment. No files are written and no implementation starts.'
    if state.get('plans',{}).get('location')=='private':return 'Save and review this private proposal. No Git commit or implementation.'
    return 'Write, review and commit this proposal. Implementation comes later.'


def review_document(state):
    """The complete approval subject, written for a reader rather than as a runner status dump."""
    effect=approval_effect(state)
    if state['status']=='prepared_checkpoint':
        lines=['# Quick-fix task list',effect,'## Tasks']
        for task in state['tasks']:
            lines.extend([f"### Task {task['id']}: {task['title']}",task['instructions'],
                          'Dependencies: '+(', '.join(task.get('needs',[])) or 'none')+'.'])
    elif state.get('workflow')=='propose':
        plan=state['preview']['plan']
        lines=['# Proposal',plan['understanding'],'## What you are approving',effect,'## Proposed change',plan.get('summary') or plan['text'],
               '## Why this route',plan['route'].capitalize()+': '+plan['reason'],'## Evidence',plan.get('evidence') or 'None recorded.']
        if plan.get('intent'):lines.extend(['## Files to change',*('- '+p for p in plan['intent'])])
        if plan.get('lines'):
            lines.append('## Exact additions')
            for line in plan['lines']:
                lines.append(('| Initiative | Description | Dependencies | Design |\n| --- | --- | --- | --- |\n' if line.startswith('|') else '')+line)
        writes=plan.get('writes',{})
        labels={'milestone':'Milestone','milestone_title':'Milestone title','done_when':'Done when',
                'slug':'Initiative','design':'Design','track':'Track','depends':'Dependencies'}
        for key,label in labels.items():
            if key in writes:
                value=writes[key]
                if isinstance(value,list):value=', '.join(value) or 'none'
                lines.append(f'**{label}:** {value}')
        if decision:=writes.get('decision'):
            lines.append('## Proposed decision')
            lines.extend(f'**{key.capitalize()}:**\n\n{value}' for key,value in decision.items())
        if not plan.get('lines'):lines.append(plan['text'])
    else:
        plan=state['rendered']
        from hashlib import sha256
        content=Path(plan['path']).read_bytes()
        if sha256(content).hexdigest()!=plan['files'][plan['path']]:
            raise Refused('The plan changed after review. Your edits are preserved; stop this run, then use oh-design on its initiative to review them.')
        lines=['# Review: '+plan['title'],plan.get('summary',''),'## What you are approving',effect,f"Tasks: {plan['tasks']}.",
               '## Reviewed document',f"Source: {plan['path']}",content.decode('utf-8')]
    lines.append('Use the accompanying question to choose. This document is a review copy; request revisions through the conversation.')
    return '\n\n'.join(lines)+'\n'


def preview(journal,state,ident):
    """A stable view of this exact checkpoint, outside the consumer checkout."""
    text=review_document(state)
    path=journal.path/'menus'/f'preview-{ident}.md'
    if path.is_symlink() or path.exists() and path.read_bytes()!=text.encode():
        raise Refused('The review preview was edited. Use refine: <what to change> in the chat, or restore the preview before approving.')
    if not path.exists():
        from .plans import write
        write(path,text)
    return str(path)


def native_ask(gate):
    """Codex Desktop's small, persistent question; its native answer is verified by authority."""
    choices=[o['label'] for o in gate['options']]
    # The host supplies no hidden checkpoint field: retain the existing marker so a
    # delayed old payload cannot be displayed later and approve a replacement scope.
    return {'questions':[{'title':gate['question'], 'options':choices}]}


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
    reasons={'checkpoint':'This batch is complete. Continue with the next tasks, open a PR, or finish here.',
             'prepared_checkpoint':'The task preview is ready. Review its scope and limits, then choose Approve, Refine or Cancel.',
             'completed':'The selected work is complete. Open a PR or keep the completed commits locally.',
             'approval_checkpoint':'The proposal or plan is ready to review. Choose Approve, Refine or Cancel.',
             'review_checkpoint':'This review window is used. Choose more reviews or take over the retained work.',
             'findings_checkpoint':'Review found the issues below. Choose how to handle them.',
             'needs_attention':'The task did not finish. Review the problem below, then retry or take over.',
             'paused':'The work is paused. Resume continues from here.'}
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
        found=[('grant review', f"Allow up to {state['config']['review_rounds']} fresh independent reviews for this task; approved scope stays the same."),
               ('stop', 'End OH here and keep the work for you to finish manually.')]
        return found+[('handoff pr','')] if committed(state) else found
    if status == 'paused':return [('resume',''),('stop','')]
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


def decision_summary(state):
    """Short chat context; complete findings and history remain in the returned details."""
    pending=[t for t in state['tasks'] if t['id'] not in state['done']]
    task=pending[0] if pending else state['tasks'][-1]
    status=state['status']
    if status=='review_checkpoint':
        from .workflow import review_limit
        used=sum(a['role']=='review' and a['task']==task['id'] for a in state['attempts'])
        reason=('Your requested revision still needs an independent review.'
                if (state.get('proposal_answers') or [{}])[-1].get('choice')=='refine' else
                'The current task still needs a completed review or a repair.')
        return f"OH has used {used} of {review_limit(state,task['id'])} allowed reviews. {reason}"
    if status=='checkpoint':
        return (f"{len(state['done'])} of {len(state['tasks'])} tasks completed. Checks passed; independent review completed. Next: "
                +(' '.join(task['title'].split())[:200] if pending else 'none')+'.')
    if status=='completed':
        count=len(state['done'])
        checks='Checks' if state.get('workflow','deliver')=='deliver' else 'Document validation'
        return f"{count} task"+('s' if count!=1 else '')+f" completed. {checks} passed; independent review completed."
    if status=='paused':return 'The run is paused. Resume continues the approved work with its remaining allowances.'
    last=next((a for a in reversed(state['attempts']) if a['task']==task['id']),{})
    text=last.get('human_summary') or ('A task needs your attention before OH can continue.' if status=='needs_attention' else 'Review findings need your decision.')
    return ' '.join(text.split())[:320]


def menu_record(journal,state):
    """A pending branch activation retains its original approval subject across a crash."""
    record=state.get('activation',{}).get('gate_record') if state['status']=='prepared_checkpoint' else None
    return record or journal.records()[-1]


def describe(journal, state, root=None):
    """The menu for the current choice, or None. Its id binds the run, its status and the journal head, so a
    click on an older menu never applies to a later state."""
    found = options(state)
    if not found or len(found) < 2:return None
    head = menu_record(journal,state)['hash']
    ident = digest({'run': state['id'], 'status': state['status'], 'head': head})[:12]
    title = {'checkpoint': 'What would you like to do next?', 'completed': 'Open a pull request?',
             'prepared_checkpoint':'Approve this task list?',
             'approval_checkpoint': 'Approve the proposal?' if state.get('workflow') == 'propose' else 'Approve this plan?',
             'review_checkpoint': f"Allow {state['config']['review_rounds']} more reviews for this task?",
             'paused':'Resume this paused run?', 'needs_attention': 'Retry this task after resolving the problem?',
             'findings_checkpoint': 'Fix the concerns or accept the current work?'}[state['status']]
    if state['status']=='findings_checkpoint':
        severities={f['severity'] for f in state['attempts'][-1].get('findings',[])}
        if severities=={'scope'}:title='Record the scope as future work or dismiss it?'
        elif 'scope' in severities:title='How should OH handle the concerns and future work?'
    menu = [{'choice': choice, 'label': LABELS[choice][0], 'description': ('Run this approved task list.' if choice=='approve' and state['status']=='prepared_checkpoint' else
                            'Approve this proposal or plan.' if choice=='approve' else text or LABELS[choice][1] or LABELS[choice][0])}
            for choice,text in found]
    if state['status']=='checkpoint':
        batch=min(len(state['tasks'])-len(state['done']),state['config']['tasks_per_batch'])
        for option in menu:
            if option['choice']=='continue':
                option['description']=f"Run the next {batch} task"+('s' if batch!=1 else '')+f", up to {state['config']['review_rounds']} reviews each."
    if root is not None and any(o['choice']=='pr' for o in menu):
        for option in menu:
            if option['choice']=='pr':
                option['description']='Publish the reviewed work and standard review summary.'
    if state['status']=='review_checkpoint':
        menu[0]['label']=f"Allow {state['config']['review_rounds']} more reviews"
        menu[1]['label']='Stop and take over'
    if state['status']=='completed':
        for option in menu:
            if option['choice']=='stop':
                option.update(label='Finish without a PR',description='Keep the completed commits locally; do not push or open a PR.')
    document=None
    if state['status'] in ('approval_checkpoint','prepared_checkpoint'):
        document=preview(journal,state,ident)
        explanation=(state['preview']['plan']['understanding'] if state.get('workflow')=='propose' else
                     state['rendered'].get('summary') or state['rendered']['title'] if state['status']=='approval_checkpoint' else
                     f"Review the {len(state['tasks'])} prepared task(s).")
        question=f'{title} [{MARK}{ident}]'
    else:
        explanation=decision_summary(state)
        if state['status']=='checkpoint':
            batch=min(len(state['tasks'])-len(state['done']),state['config']['tasks_per_batch'])
            explanation+=f" Continue allows {batch} more task(s), up to {state['config']['review_rounds']} reviews each."
        question=f'{title} [{MARK}{ident}]'
    return {'id': ident, 'run': state['id'], 'status': state['status'], 'host': state['host'],
            'summary':explanation,'details':summary(state,root,journal) if not document else '', 'question':question, 'options': menu, 'words': state['status'] == 'approval_checkpoint'}|({'preview':document} if document else {})


def current(root):
    from .workflow import active_file, load_run
    if not active_file(root).exists():return None
    journal, state = load_run(root)
    return None if state.get('refinement') else describe(journal, state,root)


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
    panel='Open gate.preview in the right panel with open_in_codex when available. Show its link. ' if gate.get('preview') else ''
    return (panel+'Use request_user_input_async with exactly gate.native_ask when an interruptible wait tool is available; '
            'keep the turn open and wait quietly with clock.sleep (at most 60 seconds per call), without a separate '
            'final response, until the human answers. Then call OH run to read that answer. Tool acceptance is not a human answer. '
            'Otherwise use the OH choose tool, which records the click itself. If the result has status pr, '
            'execution is finished: publish with pr_summary, without calling run again. '
            'If the person says the menu is missing, refresh status and reopen the current menu with choose. '
            f'If no menu can be shown, ask the person to type one of: {typed}.')


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
