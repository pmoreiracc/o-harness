"""Runner controls share the finalization lock and never replenish authority."""
import os
from .storage import Refused, checkout_file, lock, state_writer
from .workflow import load_run, reduce
from .telemetry import best_effort


class Interrupted(Refused):
    pass


def status_event(journal, state, value, **extra):
    journal.append('run.status', {'status': value, **extra})
    best_effort('run.status', state['project'], state['id'], status=value)


def busy(root):
    try:
        with lock(checkout_file(root, 'oh-runner.lock'), wait=False):
            return False
    except Refused:
        return True


@state_writer
def request(root, action, *, expected_run=None, source=None):
    if os.environ.get('OH_CHILD_ATTEMPT'):
        raise Refused('Workers cannot control their parent run')
    if action not in ('pause', 'stop'):
        raise Refused('This direct control only reduces authority; resume requires a human grant')
    def clear_waits():
        from .authority import drop_waits
        drop_waits(root)
        checkout_file(root,'oh-preparation-owner.json').unlink(missing_ok=True)
    if action=='stop' and expected_run is None:clear_waits()
    with lock(checkout_file(root, 'oh-control.lock')):
        journal, state = load_run(root)
        if expected_run is not None and state['id']!=expected_run:
            return {'run':state['id'],'status':state['status']}
        if source and (source.get('session')!=state['human']['session'] or source.get('host',state['host'])!=state['host']):
            return {'run':state['id'],'status':state['status']}
        if action=='stop' and expected_run is not None:clear_waits()
        if state['status'] in ('stopped', 'pr', 'completed'):
            return {'run': state['id'], 'status': state['status']}
        if state['status'] in ('stopping', 'pausing', 'paused') and action == 'pause':
            return {'run': state['id'], 'status': state['status']}
        target = ('pausing' if action == 'pause' else 'stopping')
        if state['status'] != target:
            status_event(journal, state, target, return_status=state['status'],**({'source':source} if source else {}))
        if not busy(root):
            _settle(root, journal, reduce(journal.records()))
        return {'project': state['project'], 'run': state['id'], 'status': reduce(journal.records())['status']}


def _settle(root, journal, state):
    if state['status'] == 'pausing':
        from .verification import tree
        from .storage import git
        status_event(journal, state, 'paused', tree=tree(root), head=git(root, 'rev-parse', 'HEAD'))
    elif state['status'] == 'stopping':
        from .verification import tree
        from .storage import git
        # Capture only after owned processes drain. This is the continuation boundary,
        # including renders/checks that happened after the last worker returned.
        try:snapshot={'tree':tree(root),'head':git(root,'rev-parse','HEAD')}
        except Exception as exc:snapshot={'error':str(exc)}
        status_event(journal, state, 'stopped', snapshot=snapshot)


def settle(root):
    """Called only after all processes owned by this runner have returned."""
    with lock(checkout_file(root, 'oh-control.lock')):
        journal, state = load_run(root)
        _settle(root, journal, state)


def allowed(root):
    _, state = load_run(root)
    return state['status'] == 'running'


def stopping(root):
    _, state = load_run(root)
    return state['status'] in ('stopping', 'stopped')


def check(root):
    if not allowed(root):
        raise Interrupted('The run is paused, stopping, or at a checkpoint; no new step was launched')
