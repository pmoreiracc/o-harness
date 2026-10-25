"""Human-selected delivery recovery using the existing journal, Git and tool gates."""
from .system import Path
import time
from .storage import Refused, atomic_json, changes, digest, git, now, read_json
from .verification import tree
from .workflow import load_run, reduce


def facts(root, state):
    from .branches import main_ref
    artifacts = {}
    bound = state.get('delivery')
    if bound and bound['layout']['location'] == 'private':
        from .native import _files
        from .plans import approvals_file
        artifacts = _files([bound['path']])
        artifacts['approval'] = digest(read_json(approvals_file(root)).get(bound['doc']))
    base = main_ref(root, state['config'])
    return {'branch': git(root, 'branch', '--show-current'), 'head': git(root, 'rev-parse', 'HEAD'),
            'tree': tree(root), 'base': git(root, 'rev-parse', base) if base else None,
            'base_ref': base, 'paths': sorted(changes(root)), 'artifacts': artifacts}


def _private_restart(root, state, base):
    """Restore the already-approved private design at the retained code boundary."""
    bound = state.get('delivery')
    if not bound or bound['layout']['location'] != 'private': return None
    from .branches import contained
    kept = [s for s in state['summaries'] if s.get('commit') and contained(root, base, s['commit'])]
    approval = bound['approvals'][bound['doc']].copy()
    text = state['scope_snapshot']['documents'][bound['path']]
    if kept:
        summary = kept[-1]
        review = next(a for a in state['attempts'] if a['id'] == summary['review'])
        artifact = review['artifact_snapshots'][bound['path']]
        text = Path(artifact['path']).read_text()
        import hashlib
        if hashlib.sha256(text.encode()).hexdigest() != artifact['sha256']:
            raise Refused('The retained private design snapshot changed; preserve it and restore its original contents before restarting')
        approval.update(sha256=artifact['sha256'], delivery_commit=summary['commit'],
                        delivery_base=approval.get('delivery_base',state['base']),
                        delivery_baseline=approval.get('delivery_baseline',state['base']),
                        delivery_no_code=not bool(git(root,'diff','--name-only',state['base'],summary['commit'])))
    return {'path': bound['path'], 'text': text, 'doc': bound['doc'], 'approval': approval}


def prepare(root, state):
    from . import native
    from .decisions import boundary
    from .branches import fetched, trunk
    if state['workflow'] != 'deliver' or state.get('published'):
        raise Refused('This recovery gate is for unpublished delivery; use the saved planning or publication step')
    name = trunk(root, state['config'])
    if name: fetched(root, name)
    subject = facts(root, state)
    paths = set(subject['paths'])
    paths.update(path for path in subject['artifacts'] if path != 'approval')
    if subject['base']:
        paths.update(git(root, 'diff', '--name-only', '-z', subject['base']+'...HEAD').split('\0'))
    paths.discard('')
    details = (f'Work: {native._saved_subject(state)}\nBranch: {subject["branch"]}\n'
               'Continue keeps existing changes and finishes the approved delivery.\n'
               'Start fresh discards the listed local changes and this branch’s unmerged delivery work; no backup is made.\n'
               'Stop and take over ends OH execution and leaves the files unchanged.\n'
               'Old workers are revoked before continuation. Review usage and findings remain recorded.\n'
               'Affected paths: '+(', '.join(sorted(paths)) or 'none')+'\n')
    choices = {'resume': 'Continue', 'stop': 'Stop and take over'}
    if state.get('approved_repairs'):
        details += 'Continue retains approved supporting repairs. Start fresh discards repair approvals for restarted tasks; their history remains saved.\n'
    if subject['base'] and subject['branch'] in (state['branch'],state.get('recovery_intent',{}).get('branch')):
        choices = {'resume': 'Continue', 'restart': 'Start fresh', 'stop': 'Stop and take over'}
        details += 'Restart base: '+subject['base_ref']+' ('+subject['base'][:12]+').\n'
        from .branches import contained
        kept = {s['task'] for s in state['summaries'] if s.get('commit') and contained(root, subject['base'], s['commit'])}
        batch = [t['id'] for t in state['tasks'] if t['id'] not in kept][:state['config']['tasks_per_batch']]
        details += 'Restart authorizes this task batch: '+', '.join(batch)+'. No additional review rounds.\n'
    details += '\nHow would you like OH to proceed with this delivery?'
    value = {'kind': 'recover', 'run': state['id'], 'attempt': None, 'presentation': 'recovery-menu',
             'boundary': boundary(root,state,'resume'),
             'subject': subject, 'question': details, 'choices': choices,
             'menu_options': list(choices.values()), 'created_at': now()}
    if 'restart' in choices:value['private_restart'] = _private_restart(root,state,subject['base'])
    key = digest(value)
    native._immutable(native._home(root)/'decisions'/(key+'.json'), value)
    return {'decision': key, 'question': details, 'options': value['menu_options'],
            'actions': {label: action for action, label in choices.items()},
            'human_locator': 'Bind the selected action from this one native question with decision.'}


def _settle(root, journal, state, source):
    """Keep verifiable results; explicitly abandon only after old writes are fenced."""
    from . import authority, cancellation, native
    from .system import recover_process
    for attempt in native._active(state):
        try:
            native._retain_locked(root, attempt['id'], {}, run=state['id'])
            continue
        except (authority.Saving, FileNotFoundError):
            pass
        control = cancellation._read(root)
        record = (control or {}).get('attempts', {}).get(attempt['id'])
        if not record or not record.get('guard_observed'):
            raise Refused('The old worker has no verified OH tool guard. Stop it in its native host, then retry this same recovery answer.')
        owner = control['owners'][record['owner']]
        revocation = {'event': 'recovery', 'at': source['at'], 'turn': source['turn'],
                      'session': source['session'], 'decision': source['decision']}
        with cancellation._edit(root):
            atomic_json(owner['marker'], revocation)
        # Owned wrappers observe revocation themselves. Recover a killed wrapper
        # only through its saved OS identity; an answer is not process-exit proof.
        for _ in range(10):
            control = cancellation._read(root)
            for key, command in control['commands'].items():
                if command['attempt'] != attempt['id'] or command.get('ended'): continue
                proof = recover_process(command)
                if proof:
                    with cancellation._edit(root) as updated:
                        updated['commands'][key].update(ended=now(), returncode=130, cleanup=proof)
            try: cancellation.reconcile_tools(root, attempt)
            except FileNotFoundError: pass
            with cancellation._edit(root) as updated:
                for tool in updated['tools'].values():
                    if tool['attempt'] == attempt['id'] and tool['kind'] == 'launch':
                        # Only launch bookkeeping is retired here. Known child
                        # tools and command receipts still require real cleanup.
                        tool.setdefault('ended', now())
                        tool.setdefault('completion_source', 'recovery-revocation')
            if cancellation.quiescent(root, attempt['id']): break
            time.sleep(.1)
        if not cancellation.quiescent(root, attempt['id']):
            raise authority.Saving('Old operations are still settling. Retry this same recovery answer; do not ask again or start another worker.')
        directory = Path(attempt['evidence'])
        native._immutable(directory/'revoked-result.json', {
            'status': 'abandoned', 'text': '', 'origin': 'human-recovery',
            'record_hashes': source['record_hashes'], 'interruption': revocation,
            'note': 'Execution authority revoked and tracked operations settled; no native success or model termination is asserted.'})
        if not (directory/'result.json').exists():
            native._immutable(directory/'result.json', {'summary': 'Abandoned by the recovery decision; existing files preserved.', 'findings': []})
        with cancellation.settlement(root, attempt['id']):
            journal.append('attempt.finished', {'id': attempt['id'], 'outcome': 'abandoned',
                'summary': 'Abandoned by explicit recovery.', 'revocation': revocation,
                'native_source': source['record_hashes'], 'findings': attempt.get('findings', [])})
    return load_run(root, state['id'])[1]


def apply(root, kind, locator, *, run=None):
    from . import authority, cancellation, native
    from .branches import contained, delivery_branch, execution_branch, holder, refresh, run_git, trunk
    from .decisions import verify
    with native._locked(root):
        prepared = read_json(native._home(root)/'decisions'/(locator['decision']+'.json'))
        journal, state = load_run(root, run or prepared['run'])
        locator = native._presented(root, locator, state)
        source = authority.native_human(root, locator, latest=False)
        verify(root, state, kind, locator, source, replay=True)
        key = native._human_key(source,state)
        if key in state['decisions']:
            if state['human']['session'] != source['session']:
                raise Refused('A newer coordinator owns this delivery; use its current recovery decision')
            return native.select(root, state['id'])
        source = authority.coordinator(root, state, locator, retry_resume=True)
        source = source | {'decision': locator['decision']}
        verify(root, state, kind, locator, source)
        original = prepared['subject']
        current = facts(root, state)
        intent = state.get('recovery_intent')
        retry = intent and intent['key'] == key and intent['kind'] == kind
        applied = retry and current['branch'] == intent['branch'] and current['head'] == intent['base'] and not current['paths']
        if kind == 'restart' and current != original and not applied:
            raise Refused('The files or Git base changed since this recovery question. Inspect the changes and present the updated choices.')
        if kind != 'stop' and current['branch'] not in (state['branch'],(intent or {}).get('branch')) and not applied:
            raise Refused('This checkout is on different work. Return to '+state['branch']+' without discarding edits, then present recovery there.')
        for _, other in native._saved_runs(root):
            if other['id'] != state['id'] and native._active(other):
                raise Refused('Another delivery owns live work in this checkout; settle that delivery before changing these files')
        cancellation.register_owner(root, state | {'human': source}, active=False)
        state = _settle(root, journal, state, source)
        native._idle(root)
        with cancellation.continuation(root, state, source, replacing=True):
            # Recheck after cleanup: an old operation may have changed files while
            # the question was open. Never discard changes the person did not see.
            settled = facts(root, state)
            if kind == 'restart' and settled != original and not applied:
                raise Refused('Old work changed the files during cleanup. Inspect the result and present the updated recovery choices.')
            if kind != 'restart':
                if settled['branch'] != original['branch']:
                    raise Refused('The selected branch changed during recovery; return to '+original['branch']+' and retry the same answer without discarding edits.')
                # Continue preserves the current candidate, including an old worker's
                # final writes. Only destructive restart binds the exact shown files.
                current = original = settled
            changed_base = bool(applied) or current['branch'] != state['branch']
            if kind != 'stop':
                base = original['base']
                merged = base and contained(root, base, original['head'])
                if not applied and (kind == 'restart' or merged and not original['paths'] and
                                    (original['head'] != base or original['branch'] == trunk(root,state['config']))):
                    name = (original['branch'] if kind == 'restart' and not merged and original['branch'] != trunk(root,state['config']) else
                            delivery_branch(state['design'], state.get('track', '')) if state.get('design') else
                            execution_branch(root, state['tasks'][0]['title'], state['id']))
                    if name != original['branch'] and run_git(root, 'show-ref', '--verify', '--quiet', 'refs/heads/'+name).returncode == 0:
                        if not contained(root, base, name):
                            name += '-'+state['id'][:8]
                            if run_git(root,'show-ref','--verify','--quiet','refs/heads/'+name).returncode == 0:
                                raise Refused('The recovery branch is already occupied: '+name+'; select an unused execution branch before retrying')
                    if holder(root, name): raise Refused('The selected delivery branch is in use by another worktree: '+name)
                    if not retry:
                        journal.append('recovery.started', {'key': key, 'kind': kind, 'branch': name, 'base': base})
                    if kind == 'restart':
                        git(root, 'reset', '--hard', original['head'])
                        # Explicit paths only; never git clean -fdx or ignored files.
                        for path in original['paths']:
                            git(root, 'clean', '-fd', '--', path)
                    git(root, 'switch', '--quiet', '--no-overwrite-ignore', '-C', name, base)
                    if kind == 'restart' and (private := prepared.get('private_restart')):
                        from .plans import write, approvals_file
                        write(Path(private['path']),private['text'])
                        path=approvals_file(root)
                        atomic_json(path,read_json(path)|{private['doc']:private['approval']})
                    changed_base = True
                elif not applied and base and not original['paths']:
                    refresh(root, original['branch'], base)
                    changed_base = git(root, 'rev-parse', 'HEAD') != original['head']
            events = []
            if kind == 'restart' or changed_base:
                retained = [s for s in state['summaries'] if kind != 'restart' or
                            s.get('commit') and contained(root, original['base'], s['commit'])]
                done = [t for t in state['done'] if any(s['task'] == t for s in retained)]
                pending = [t['id'] for t in state['tasks'] if t['id'] not in done]
                events.append({'kind': 'delivery.recovered', 'data': {
                    'branch': git(root, 'branch', '--show-current'), 'base': git(root, 'rev-parse', 'HEAD'),
                    'restart': kind == 'restart', 'done': done, 'summaries': retained,
                    'granted': pending[:state['config']['tasks_per_batch']] if kind == 'restart' else state['granted']}})
            events += [{'kind': 'run.owner', 'data': {'human': source}},
                       {'kind': 'run.status', 'data': {'status': 'stopped' if kind == 'stop' else 'running'}},
                       {'kind': 'decision', 'data': {'choice': kind, 'source': key, 'recovery': locator['decision']}}]
            native._immutable(journal.path/'decisions'/(key+'.json'), {'human': source, 'prepared': prepared})
            journal.append('transition', {'events': events})
        updated = reduce(journal.records())
        if kind != 'stop':native._resume_binding(root, updated, write=True)
        from .receipts import index
        index(journal, updated)
        return native.select(root, state['id'])
