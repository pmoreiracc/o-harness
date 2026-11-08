"""Human-selected delivery recovery using the existing journal, Git and tool gates."""
from .system import Path
from subprocess import SubprocessError
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
    current=git(root,'branch','--show-current')
    from .workspace import observation,parked
    if (current!=state['branch'] and current!=state.get('recovery_intent',{}).get('branch') or
            current==state['branch'] and parked(root,current) and not changes(root)):
        saved=observation(root,state['branch'])
        selected={k:saved[k] for k in ('branch','head','tree','paths')}
    else:selected={'branch':current,'head':git(root,'rev-parse','HEAD'),'tree':tree(root),'paths':sorted(changes(root))}
    return selected|{'base':git(root,'rev-parse',base) if base else None,'base_ref':base,'artifacts':artifacts}


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
        review = next((a for a in state['attempts'] if a['id'] == summary['review']), {})
        artifact = review.get('artifact_snapshots',{}).get(bound['path'])
        if not artifact:
            raise Refused('The reviewed private design snapshot is unavailable.')
        text = Path(artifact['path']).read_text()
        import hashlib
        if hashlib.sha256(text.encode()).hexdigest() != artifact['sha256']:
            raise Refused('The retained private design snapshot changed; preserve it and restore its original contents before restarting')
        approval.update(sha256=artifact['sha256'], delivery_commit=summary['commit'],
                        delivery_base=approval.get('delivery_base',state['base']),
                        delivery_baseline=approval.get('delivery_baseline',state['base']),
                        delivery_no_code=not bool(git(root,'diff','--name-only',state['base'],summary['commit'])))
    return {'path': bound['path'], 'text': text, 'doc': bound['doc'], 'approval': approval}


def prepare(root, state, entry_request=None, *, stop_boundary):
    from . import native
    from .decisions import boundary, save_offer, TAKE_OVER
    from .branches import contained, fetch_base, trunk
    if state['workflow'] != 'deliver' or state.get('published'):
        raise Refused('This recovery gate is for unpublished delivery; use the saved planning or publication step')
    observed = None
    unavailable = ''
    try:
        name = trunk(root, state['config'])
        observed = fetch_base(root, name)
        subject = facts(root, state)
        paths = set(subject['paths'])
        paths.update(path for path in subject['artifacts'] if path != 'approval')
        if subject['base']:
            paths.update(git(root, 'diff', '--name-only', '-z', subject['base']+'...'+subject['head']).split('\0'))
        paths.discard('')
    except (OSError, Refused, ValueError, SubprocessError) as exc:
        subject = None
        unavailable = str(exc)
    branch = subject['branch'] if subject else state['branch']
    details = (f'Work: {native._saved_subject(state)}\nBranch: {branch}\n'
               'Stop and take over ends OH execution and leaves the files unchanged.\n'
               'Old execution is settled before any action. Review usage and findings remain recorded.\n')
    if observed:
        details += 'Base freshness: '+observed['freshness']+(' — '+observed['reason'] if observed['reason'] else '')+'\n'
    if entry_request:
        from .entry import request_description
        details+='After this prerequisite, continue the initiating request: '+request_description(entry_request)+'\n'
    choices = {}
    private_restart = None
    if subject:
        choices['resume'] = 'Continue'
        details += 'Continue keeps existing changes, including approved repairs, and finishes the approved delivery.\n'
        if git(root,'branch','--show-current')!=state['branch']:
            details+='Current checkout work is saved before switching here to '+state['branch']+' and restoring its parked changes. No parallel folder is created.\n'
        details += ('Affected paths: '+(', '.join(sorted(paths)) or 'none') if len(paths)<=3 else
                    f'{len(paths)} affected paths. See the full list below.')+'\n'
        if subject['base'] and subject['branch'] in (state['branch'],state.get('recovery_intent',{}).get('branch')):
            try:
                private_restart = _private_restart(root, state, subject['base'])
                kept = {s['task'] for s in state['summaries'] if s.get('commit') and contained(root, subject['base'], s['commit'])}
                batch = [t['id'] for t in state['tasks'] if t['id'] not in kept][:state['config']['tasks_per_batch']]
            except (OSError, Refused, ValueError, SubprocessError) as exc:
                details += 'Start fresh unavailable. Restore the saved restart evidence before trying again. '+str(exc)+'\n'
            else:
                choices['restart'] = 'Start fresh'
                details += 'Start fresh discards the affected local changes and this branch’s unmerged work without making a new backup.\n'
                if state.get('approved_repairs'):
                    details += 'Start fresh discards repair approvals for restarted tasks; their history remains saved.\n'
                details += 'Restart base: '+subject['base_ref']+' ('+subject['base'][:12]+').\n'
                details += 'Restart authorizes this task batch: '+', '.join(batch)+'. No additional review rounds.\n'
    else:
        details += 'Continue and Start fresh unavailable. Restore the required recovery input before trying again. '+unavailable+'\n'
    choices['stop'] = TAKE_OVER
    question=f'Continue {native._saved_subject(state)} on {branch} with its existing edits?' if len(choices)>1 else f'Hand off {branch}?'
    value = {'kind': 'recover', 'run': state['id'], 'attempt': None, 'presentation': 'recovery-menu',
             'boundary': boundary(root,state,'resume'),
             'stop_boundary': stop_boundary, 'bound_question': True,
             'subject': subject, 'base_observation':observed, 'disclosure':details.rstrip(), 'question':question, 'choices': choices,
             'affected_paths':sorted(paths) if subject else [],
             'menu_options': list(choices.values()), 'created_at': now()}
    if subject and git(root,'branch','--show-current')==state['branch']:
        value['keep_edits_question']=True
    if entry_request:value['entry_request']=entry_request
    if 'restart' in choices:value['private_restart'] = private_restart
    path_list=''.join('\n- '+repr(path) for path in value['affected_paths'])
    key = save_offer(root,value,details='Affected paths\n'+path_list+'\n' if len(value['affected_paths'])>3 else None)
    return {'decision': key, 'question': value['question'], 'disclosure': value['disclosure'], 'options': value['menu_options'],
            'base_observation':observed,
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
            try: cancellation.reconcile_execution(root, attempt)
            except (FileNotFoundError,authority.Unavailable): pass
            with cancellation._edit(root) as updated:
                for tool in updated['tools'].values():
                    if tool['attempt'] == attempt['id'] and tool['kind'] == 'launch':
                        # Only launch bookkeeping is retired here. Known child
                        # lifecycle and command receipts still require real cleanup.
                        tool.setdefault('ended', now())
                        tool.setdefault('completion_source', 'recovery-revocation')
            if cancellation.quiescent(root, attempt['id']): break
            time.sleep(.1)
        if not cancellation.quiescent(root, attempt['id']):
            raise authority.Saving('Old operations are still settling. Retry this same recovery answer; do not ask again or start another worker.')
        state=load_run(root,state['id'])[1]
        attempt=native._attempt(state,attempt['id'])
        native._finish_attempt(root,journal,state,attempt,{
            'status':'abandoned','text':'','origin':'human-recovery',
            'record_hashes':source['record_hashes'],'interruption':revocation,
            'note':'Execution authority revoked and owned execution settled; no native success or model termination is asserted.'},
            stopped=revocation,revoked=True,recovery=True)
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
        native._continuation_order(root,state,source)
        if key in state['decisions']:
            if native._human_key(state['human'],state)!=key:
                raise Refused('A newer coordinator owns this delivery; use its current recovery decision')
            if kind!='stop':
                source=authority.coordinator(root,state,locator,retry_resume=True)
                native._switchable(root,[state]+[s for _,s in native._saved_runs(root) if s['id']!=state['id']])
                with cancellation.continuation(root,state,state['human'],replacing=True):pass
                native._resume_binding(root,state,write=True)
            from .receipts import index
            index(journal,state)
            return native.select(root, state['id'])
        source = authority.coordinator(root, state, locator, retry_resume=True)
        source = source | {'decision': locator['decision']}
        verify(root, state, kind, locator, source)
        original = prepared['subject']
        if kind != 'stop':
            current = facts(root, state)
            intent = state.get('recovery_intent')
            retry = intent and intent['key'] == key and intent['kind'] == kind
            applied = retry and current['branch'] == intent['branch'] and current['head'] == intent['base'] and not current['paths']
            if kind == 'restart' and current != original and not applied:
                raise Refused('The files or Git base changed since this recovery question. Inspect the changes and present the updated choices.')
        native._switchable(root,[s for _,s in native._saved_runs(root) if s['id']!=state['id']])
        cancellation.register_owner(root, state | {'human': source}, active=False)
        state = _settle(root, journal, state, source)
        native._switchable(root,[state])
        initial = native._initial_grant(root, journal, state) if kind == 'resume' and state.get('native_version') else None
        granted = initial['tasks'] if initial else state['granted']
        from .workflow import active_file
        selected=active_file(root)
        keep_other=kind=='stop' and selected.exists() and read_json(selected)['run']!=state['id']
        with cancellation.continuation(root, state, source, replacing=True,activate=not keep_other):
            changed_base = False
            if kind != 'stop':
                from .workspace import switch
                if not applied:switch(root,state['branch'])
                # Recheck after cleanup before changing branch or discarding files.
                settled = facts(root, state)
                comparable=settled if original['tree'] is not None else settled|{'tree':None}
                if kind == 'restart' and comparable != original and not applied:
                    raise Refused('Old work changed the files during cleanup. Inspect the result and present the updated recovery choices.')
                if kind == 'resume':
                    if settled['branch'] != original['branch']:
                        raise Refused('The selected branch changed during recovery; return to '+original['branch']+' and retry the same answer without discarding edits.')
                    # Continue preserves any final writes from the previous worker.
                    current = original = settled
                changed_base = bool(applied) or current['branch'] != state['branch']
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
                    if holder(root, name): raise Refused('The selected delivery branch is in use by another worktree: '+name+'. Preserve its work and release that branch there before retrying this same recovery here; do not move the task to another checkout.')
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
            events = [{'kind': 'grant', 'data': initial}] if initial else []
            if kind == 'restart' or changed_base:
                retained = [s for s in state['summaries'] if kind != 'restart' or
                            s.get('commit') and contained(root, original['base'], s['commit'])]
                done = [t for t in state['done'] if any(s['task'] == t for s in retained)]
                pending = [t['id'] for t in state['tasks'] if t['id'] not in done]
                events.append({'kind': 'delivery.recovered', 'data': {
                    'branch': git(root, 'branch', '--show-current'), 'base': git(root, 'rev-parse', 'HEAD'),
                    'restart': kind == 'restart', 'done': done, 'summaries': retained,
                    'granted': pending[:state['config']['tasks_per_batch']] if kind == 'restart' else granted}})
            events += [{'kind': 'run.owner', 'data': {'human': source}},
                       {'kind': 'run.status', 'data': {'status': 'stopped' if kind == 'stop' else 'running'}},
                       {'kind': 'decision', 'data': {'choice': kind, 'source': key, 'recovery': locator['decision'],
                                                    **({'target_only': True} if keep_other else {})}}]
            native._immutable(journal.path/'decisions'/(key+'.json'), {'human': source, 'prepared': prepared,'locator':locator})
            journal.append('transition', {'events': events})
        updated = reduce(journal.records())
        if kind != 'stop':native._resume_binding(root, updated, write=True)
        from .receipts import index
        index(journal, updated)
        return native.select(root, state['id'])
