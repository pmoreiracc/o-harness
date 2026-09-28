"""Clickable choices. A menu shows the choices OH is waiting for; the click reaches OH through the host,
never through the model. Claude asks with its own question tool and OH reads the click from Claude's
transcript. Codex asks through OH's MCP server, which records the click itself. Typed words still work."""
import re
from .storage import Refused, checkout_file, digest, lock, state_writer

MARK = 'OH gate '
LABELS = {'continue': ('Continue', ''), 'pr': ('Open a PR', 'Publish the committed work as one pull request.'),
          'stop': ('Stop', 'End this run here.'), 'approve': ('Approve', ''),
          'reconsider': ('Reconsider', 'Undo what OH wrote and write nothing.'),
          'retry': ('Retry', 'Try the unfinished task again.'), 'grant review': ('More reviews', 'Allow another round of reviews.'),
          'fix findings': ('Fix findings', 'Send every finding back to be fixed.'),
          'fix concerns': ('Fix concerns', 'Send the concerns back to be fixed.'),
          'fix scope': ('Fix scope', 'Fix the scope findings here instead of filing them.'),
          'accept concerns': ('Accept concerns', 'Keep the work as it is; the concerns stay on record.'),
          'route scope': ('File scope issue', 'File the scope findings as an issue and go on.'),
          'accept concerns and route scope': ('Accept and file', 'Accept the concerns and file the scope findings as an issue.')}
REFINE = {'claude': 'To change it, pick Other and type what to change.', 'codex': 'To change it, pick Refine and say what to change.'}


def options(state):
    """The choices this run is waiting for, as (choice, description) pairs; None when it waits for none."""
    from .workflow import committed, continue_limits
    status = state['status']
    if status == 'checkpoint':
        left = len([t for t in state['tasks'] if t['id'] not in state['done']])
        found = ([('continue', continue_limits(left, state['config']))] if left else [])
        found += [('pr', '')] if committed(state) and any('commit' in s for s in state['summaries']) else []
        return found + [('stop', '')]
    if status == 'completed':
        if not committed(state) or not any('commit' in s for s in state['summaries']):return None
        return [('pr', ''), ('stop', '')]
    if status == 'approval_checkpoint':
        what = 'the proposal' if state.get('workflow') == 'propose' else 'this plan'
        return [('approve', f'Accept {what} exactly as reviewed. {REFINE[state["host"]]}'), ('reconsider', '')]
    if status == 'review_checkpoint':return [('grant review', ''), ('stop', '')]
    if status == 'needs_attention':
        task = next((t['id'] for t in state['tasks'] if t['id'] not in state['done']), None)
        return ([('retry', '')] if task and task in state['granted'] else []) + [('stop', '')]
    if status == 'findings_checkpoint':
        severities = {f['severity'] for f in state['attempts'][-1].get('findings', [])}
        pairs = {frozenset({'concern'}): ('fix concerns', 'accept concerns'), frozenset({'scope'}): ('fix scope', 'route scope'),
                 frozenset({'concern', 'scope'}): ('fix findings', 'accept concerns and route scope')}
        found = pairs.get(frozenset(severities), ('fix findings',))
        return [(choice, '') for choice in found] + [('stop', '')]
    return None


def describe(journal, state):
    """The menu for the current choice, or None. Its id binds the run, its status and the journal head, so a
    click on an older menu never applies to a later state."""
    found = options(state)
    if not found or len(found) < 2:return None
    head = journal.records()[-1]['hash']
    ident = digest({'run': state['id'], 'status': state['status'], 'head': head})[:12]
    title = {'checkpoint': 'This batch is done. What next?', 'completed': 'The run is complete. Open a pull request?',
             'approval_checkpoint': 'Approve the proposal?' if state.get('workflow') == 'propose' else 'Approve this plan?',
             'review_checkpoint': 'The review rounds are spent. Allow more?', 'needs_attention': 'A task needs attention. Retry it?',
             'findings_checkpoint': 'How should OH handle the review findings?'}[state['status']]
    menu = [{'choice': choice, 'label': LABELS[choice][0], 'description': text or LABELS[choice][1] or LABELS[choice][0]}
            for choice, text in found]
    return {'id': ident, 'run': state['id'], 'status': state['status'], 'host': state['host'],
            'question': f'{title} [{MARK}{ident}]', 'options': menu, 'words': state['status'] == 'approval_checkpoint'}


def current(root):
    from .workflow import active_file, load_run
    if not active_file(root).exists():return None
    journal, state = load_run(root)
    return describe(journal, state)


def ask(gate):
    """Claude's AskUserQuestion input for this menu, exactly as OH will compare it."""
    return {'questions': [{'question': gate['question'], 'header': 'OH', 'multiSelect': False,
                           'options': [{'label': o['label'], 'description': o['description']} for o in gate['options']]}]}


def how(gate, root):
    typed = ', '.join(o['choice'] for o in gate['options']) + (', or refine: <what to change>' if gate['words'] else '')
    if gate['host'] == 'claude':
        return ('Ask the person with AskUserQuestion, passing exactly `gate.ask` and never an `answers` field. '
                'After they answer, run OH `run`; OH reads the click from Claude\'s own record. '
                f'Typing works too: {typed}.')
    return (f'Call the o-harness `choose` tool with root "{root}". It shows these choices as a menu and records the click '
            f'itself. Then run OH `run`. If it says the menu could not be shown, ask the person to type one of: {typed}.')


def pick(gate, answer):
    """The choice a click names. Only an offered label counts; free text is a change request where one is allowed."""
    if not isinstance(answer, str) or not answer.strip():raise Refused('The menu came back without a choice; ask again.')
    answer = answer.strip()
    for option in gate['options']:
        if answer.casefold() in (option['label'].casefold(), option['choice'].casefold()):return option['choice']
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
        gate = describe(journal, state)
        if not gate or gate['id'] != gate_id:
            raise Refused('That menu is out of date: the run moved on after it was shown. Run OH `status` and ask again.')
        # Every menu waits on a run that isn't executing, so Stop is recorded as this person's decision
        # directly, and a finished run offered Open a PR / Stop closes instead of asking again.
        _choose(root, event['prompt'], event)
    return checkpoint(root)
