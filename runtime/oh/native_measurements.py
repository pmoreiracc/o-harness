"""Collector-owned observations from verified journals and bound host records."""
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone
import json
import math
import sqlite3
import time

from .hosts import transcript_home
from .storage import Journal, Refused, atomic_json, digest, read_json, state_mkdir
from .system import Path
from .workflow import reduce

JOURNAL_BATCH = 12
RETRY_SECONDS = 300
MAX_RECORD = 2 * 1024 * 1024
MAX_TRANSCRIPT = 24 * 1024 * 1024
LEVELS = ('simple', 'standard', 'complex')
WORKFLOWS = ('deliver', 'design', 'propose', 'review')
COUNTERS = ('input', 'cached', 'output', 'reasoning')
SOURCE_ERRORS = (OSError, Refused, ValueError, KeyError, TypeError, IndexError, AttributeError, StopIteration)


def stamp(path):
    try:
        value = path.stat()
        return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]
    except OSError:
        return None


def timestamp(value):
    try:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is not None:
            return instant.astimezone(timezone.utc).isoformat(timespec='milliseconds')
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def event(state, kind, at, *, task=None, attempt=None, **payload):
    item = {'kind': kind, 'project': state['project'], 'run': state['id'], 'at': at,
            'task': task, 'attempt': attempt, 'payload': payload}
    return item | {'id': digest(item)}


def record_events(records):
    for record in records:
        if record['kind'] == 'transition':
            for entry in record['data']['events']:
                yield entry['kind'], entry['data'], record['at']
        else:
            yield record['kind'], record['data'], record['at']


def journal_events(state, records):
    events = []
    completed, starts, reset = {}, {}, {}
    for kind, value, at in record_events(records[1:]):
        if kind == 'task.started':
            starts[value['task']] = timestamp(value.get('started_at',at))
            reset.pop(value['task'],None)
        elif kind == 'workflow.restarted':
            reset.update({task:at for task in starts})
            completed.clear()
        elif kind == 'delivery.recovered':
            for task in completed.keys() - set(value['done']):
                reset[task] = at
                del completed[task]
        elif kind == 'task.completed':
            completed[value['task']] = timestamp(at)
            reset.pop(value['task'],None)
        elif kind == 'verification':
            checks = value.get('checks') or []
            if checks:
                reused = sum(bool(check.get('reused')) for check in checks)
                times = [check.get('duration_ms') for check in checks if not check.get('reused')]
                elapsed = sum(times) if all(type(t) in (int, float) and 0 <= t < math.inf for t in times) else None
                events.append(event(state, 'phase.finished', at, task=value['task'],
                                    phase='verification', checks=len(checks), reused=reused, duration_ms=elapsed))
    start = records[0]['at']
    events.append(event(state, 'run.started', start, name=state['name'], host=records[0]['data']['host'],
                        work_kind=state['work_kind'], version=state['harness_version'], config_hash=state['config_hash'],
                        workflow=state['workflow']))
    events.append(event(state, 'run.status', records[-1]['at'],status=state['status']))
    per_task = defaultdict(list)
    for attempt in state['attempts']:
        per_task[attempt['task']].append(attempt)
    for task in state['tasks']:
        task_id = task['id']
        started = timestamp(state['task_started'].get(task_id)) or starts.get(task_id)
        if not started:
            continue
        difficulty = state.get('assessments', {}).get(task_id, {}).get('difficulty')
        ended = completed.get(task_id) if task_id in state['done'] else None
        events.append(event(state, 'task.started', started, task=task_id, title=task['title'],
                            difficulty=difficulty if difficulty in LEVELS else None, rubric=2,native=True,
                            status='unknown' if task_id in reset else 'running'))
        if state['workflow'] == 'review' and state['status'] == 'completed':
            finished_reviews = [timestamp(a.get('finished_at')) for a in per_task[task_id] if a['role']=='review']
            feedback = max((value for value in finished_reviews if value and value >= started),default=None)
            if feedback:
                events.append(event(state,'task.finished',feedback,task=task_id,status='feedback',native=True))
        if not ended or started > ended:
            continue
        attempts = [attempt for attempt in per_task[task_id] if
                    (timestamp(attempt.get('started_at')) or ended) <= ended]
        reviews = [attempt for attempt in attempts if attempt['role'] == 'review' and attempt.get('purpose','workflow') == 'workflow']
        first = reviews[0].get('outcome') if reviews else None
        elapsed = (datetime.fromisoformat(ended)-datetime.fromisoformat(started)).total_seconds() * 1000
        events.append(event(state, 'task.finished', ended, task=task_id, status='completed',
                            wall_ms=round(elapsed), first_review=first if first in ('clean','blocking','needs_resolution') else None,
                            expected_attempts=len(attempts), expected_reviews=len(reviews), native=True))
    for attempt in state['attempts']:
        role = attempt['role']
        at = timestamp(attempt.get('started_at'))
        if not at:
            continue
        scope = 'correction' if completed.get(attempt['task']) and at > completed[attempt['task']] else role
        profile = attempt.get('profile') or {}
        events.append(event(state, 'attempt.started', at, task=attempt['task'], attempt=attempt['id'], role=role,
                            phase=scope, host=attempt['host'], model=profile.get('model'), effort=profile.get('effort')))
        ended = timestamp(attempt.get('finished_at'))
        if ended:
            events.append(event(state, 'attempt.finished', ended, task=attempt['task'], attempt=attempt['id'],
                                outcome=attempt['outcome'], duration_ms=attempt.get('duration_ms')))
    return events, completed


def read_transcript(path):
    """Read a bounded prefix. A malformed or pending record never supplies counters."""
    records = []
    bad = False
    with path.open('rb') as stream:
        while stream.tell() < MAX_TRANSCRIPT:
            line = stream.readline(MAX_RECORD + 1)
            if not line:
                break
            if not line.endswith(b'\n'):
                bad = True
                if len(line) <= MAX_RECORD:
                    break
                while line and not line.endswith(b'\n') and stream.tell() < MAX_TRANSCRIPT:
                    line = stream.readline(MAX_RECORD + 1)
                continue
            try:
                record = json.loads(line)
            except (ValueError, UnicodeError):
                bad = True
                continue
            if (not isinstance(record,dict) or any(
                    name in record and record[name] is not None and not isinstance(record[name],dict)
                    for name in ('payload','message'))):
                bad = True
                continue
            records.append(record)
        if stream.tell() >= MAX_TRANSCRIPT and stream.read(1):
            bad = True
    return records, bad


def bound_path(host, value):
    if not isinstance(value, str) or not value:
        return None
    path = Path(value).expanduser().resolve()
    return path if path.suffix == '.jsonl' and path.is_relative_to(transcript_home(host)) else None


def nonnegative(value):
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def usage_record(host, record, model=None):
    if host == 'codex':
        message = record.get('payload') or {}
        native = message.get('response_id')
        usage = message.get('usage') or {}
        if not isinstance(usage,dict):
            return None
        cache = nonnegative(usage.get('cached_input_tokens'))
        input_tokens = nonnegative(usage.get('input_tokens'))
        reasoning = nonnegative(usage.get('reasoning_output_tokens'))
    else:
        message = record.get('message') or {}
        native = message.get('id')
        usage = message.get('usage') or {}
        model = message.get('model')
        if not isinstance(usage,dict):
            return None
        cache = nonnegative(usage.get('cache_read_input_tokens'))
        parts = [nonnegative(usage.get(key)) for key in ('input_tokens', 'cache_creation_input_tokens')]
        input_tokens = sum(parts) + cache if cache is not None and None not in parts else None
        reasoning = None
    output = nonnegative(usage.get('output_tokens'))
    at = timestamp(record.get('timestamp'))
    if not isinstance(native, str) or not native or not at or (input_tokens is None and output is None):
        return None
    if input_tokens is not None and cache is not None and cache > input_tokens:
        return None
    if output is not None and reasoning is not None and reasoning > output:
        return None
    return {'response_id': digest([host,native]), 'at': at, 'input': input_tokens, 'cached': cache,
            'output': output, 'reasoning': reasoning, 'model': model if isinstance(model,str) else None}


def child_usage(host, records, binding):
    child, parent = binding['child_session'], binding['parent_session']
    if host == 'claude':
        return [value for record in records if record.get('type') == 'assistant'
                and record.get('agentId') == child and record.get('sessionId') == parent
                if (value := usage_record(host, record))]
    meta = next((item.get('payload') or {} for item in records if item.get('type') == 'session_meta'), {})
    source = meta.get('source')
    spawn = ((source.get('subagent') or {}).get('thread_spawn') or {}) if isinstance(source,dict) else {}
    if (meta.get('id') != child or (spawn.get('parent_thread_id') or meta.get('parent_thread_id')) != parent
            or meta.get('model_provider') != 'openai'):
        return []
    models = {}
    for record in records:
        if record.get('type') == 'turn_context':
            context = record.get('payload') or {}
            models[context.get('turn_id')] = context.get('model')
    return [value for record in records if record.get('type') == 'token_usage_record'
            and (payload := record.get('payload') or {}).get('thread_id') == child
            if (value := usage_record(host,record,models.get(payload.get('turn_id'))))]


def claude_anchor(records, binding):
    """Only a message whose tool-call IDs identify a single native spawn."""
    messages = defaultdict(list)
    use = binding['tool_use_id']
    for record in records:
        if (record.get('type') == 'assistant' and record.get('sessionId') == binding['parent_session']
                and not record.get('isSidechain')):
            message = record.get('message') or {}
            if message.get('id'):
                messages[message['id']].append(record)
    for versions in messages.values():
        calls = {(part.get('id'),part.get('name')) for version in versions
                 for part in version['message'].get('content') or ()
                 if isinstance(part,dict) and part.get('type') == 'tool_use'}
        if calls in ({(use,'Agent')}, {(use,'Task')}):
            return [value for version in versions if (value := usage_record('claude',version))]
    return []


def codex_anchor(records, binding):
    """Match the persisted spawn, response usage, native activity and call result."""
    use, parent, child = (binding[key] for key in ('tool_use_id','parent_session','child_session'))
    for index, (call, usage, activity, result) in enumerate(zip(records,records[1:],records[2:],records[3:])):
        args = call.get('payload') or {}
        if (call.get('type') != 'response_item' or args.get('type') != 'function_call'
                or args.get('call_id') != use or args.get('name','').split('.')[-1] != 'spawn_agent'):
            continue
        prior_call = False
        for previous in reversed(records[:index]):
            payload = previous.get('payload') or {}
            if previous.get('type') == 'token_usage_record':
                break
            if previous.get('type') == 'event_msg' and payload.get('type') == 'token_count':
                break
            if previous.get('type') == 'response_item' and payload.get('type') in ('function_call','custom_tool_call'):
                prior_call = True
                break
        if prior_call:
            continue
        tokens, done, output = (record.get('payload') or {} for record in (usage,activity,result))
        item = done.get('item') or {}
        if (usage.get('type') == 'token_usage_record' and tokens.get('thread_id') == parent
                and activity.get('type') == 'event_msg' and done.get('type') == 'item_completed'
                and done.get('thread_id') == parent and done.get('turn_id') == tokens.get('turn_id')
                and item.get('type') == 'SubAgentActivity' and item.get('id') == use
                and item.get('agent_thread_id') == child and result.get('type') == 'response_item'
                and output.get('type') == 'function_call_output' and output.get('call_id') == use):
            value = usage_record('codex',usage,item.get('model'))
            return [value] if value else []
    return []


def host_events(state, completed, cache, run_start):
    sources, events, missing = {}, [], 0

    def read(host, value):
        path = bound_path(host,value)
        if path is None:
            return [], True
        key = str(path)
        signature = stamp(path)
        sources[key] = signature
        if signature is None:
            return [], True
        identity = (key,tuple(signature))
        if identity not in cache:
            if len(cache) >= 3:
                cache.popitem(last=False)
            try:
                cache[identity] = read_transcript(path)
            except SOURCE_ERRORS:
                cache[identity] = [], True
        cache.move_to_end(identity)
        return cache[identity]

    for attempt in state['attempts']:
        host = attempt.get('host')
        binding = attempt.get('native_child')
        if host not in ('codex','claude') or not binding or not attempt.get('finished'):
            continue
        try:
            parent = attempt['parent']
            if binding['parent_session'] != parent['session']:
                continue
            first, last = (timestamp(attempt.get(key)) for key in ('started_at','finished_at'))
            if not first or not last:
                continue
            records, incomplete = read(host,binding['transcript_path'])
            child = child_usage(host,records,binding)
            scoped = [value for value in child if first <= value['at'] <= last]
            if incomplete or not scoped or any(v['input'] is None or v['output'] is None for v in scoped):
                missing += 1
            correction = completed.get(attempt['task']) and first > completed[attempt['task']]
            for value in scoped:
                events.append(event(state,'usage',value['at'],task=attempt['task'],attempt=attempt['id'],
                                    source='native.correction.'+host if correction else 'native.child.'+host,
                                    **{key:v for key,v in value.items() if key != 'at'}))
            records, _ = read(host,parent.get('transcript_path'))
            anchored = (codex_anchor if host == 'codex' else claude_anchor)(records,binding)
            phase = 'correction' if correction else 'coordination'
            task = attempt['task'] if state['workflow'] == 'deliver' and len(state['tasks']) == 1 and not correction else None
            coordinator = digest(['native.coordinator',state['id'],host,phase])
            for value in anchored:
                if not first <= value['at'] <= last:
                    continue
                events.append(event(state,'attempt.started',run_start,task=task,attempt=coordinator,
                                    role='orchestrator',phase=phase,host=host,model=None))
                events.append(event(state,'usage',value['at'],task=task,attempt=coordinator,source='native.anchor.'+host,
                                    **{key:v for key,v in value.items() if key != 'at'}))
        except SOURCE_ERRORS:
            missing += 1  # A bad source cannot suppress other attempts or journal facts.
    return sources, events, missing


def apply_bundle(db, bundle):
    from .telemetry import ingest
    # Start and finish records project the current task history together. A
    # restart can remove a completion while the start itself was seen before.
    facts = sum(ingest(db,item,reproject=item['kind'] in ('task.started','task.finished'))
                for item in bundle['facts'])
    return facts + sum(ingest(db,item) for item in bundle['usage'])


def replay(home, db):
    return sum(apply_bundle(db,read_json(file))
               for file in sorted((home/'native-observations').glob('*.json')))


def collect(home, db, limit=JOURNAL_BATCH):
    """Save normalized observations before indexing, so a crash or rebuild can replay them."""
    indexed = 0
    cache = OrderedDict()
    roots = {host:str(transcript_home(host)) for host in ('codex','claude')}
    for directory in sorted((home/'projects').glob('*/runs/*')):
        if not directory.is_dir() or directory.is_symlink():
            continue
        key = digest([directory.parent.parent.name,directory.name])
        cursor_key, gap_key = 'native:'+key, 'gap:native:'+key
        signature = stamp(directory)
        row = db.execute('SELECT value FROM collector_state WHERE key=?',(cursor_key,)).fetchone()
        cursor = json.loads(row[0]) if row else {}
        retry_due = cursor.get('pending') and time.time() - cursor.get('checked',0) >= RETRY_SECONDS
        if (not retry_due and signature == cursor.get('journal') and cursor.get('roots') == roots
                and all(stamp(Path(p)) == st for p,st in cursor.get('sources',{}).items())):
            continue
        if not limit:
            break
        limit -= 1
        sources, pending = {}, False
        db.execute('SAVEPOINT native_measurement')
        try:
            records = Journal.read_records(directory)
            start = records[0]['data'] if records else {}
            if start.get('native_version') != 2 or start.get('workflow') not in WORKFLOWS:
                continue
            state = reduce(records)
            if (state['id'], state['project']) != (directory.name,directory.parent.parent.name):
                raise Refused('Run journal does not match its stored identity')
            facts, completed = journal_events(state,records)
            sources, new, missing = host_events(state,completed,cache,records[0]['at'])
            pending = bool(missing)
            out = home/'native-observations'
            state_mkdir(out)
            file = out/(key+'.json')
            previous = read_json(file) if file.exists() else {'facts':[], 'usage':[]}
            old = {item['id']:item for item in previous['usage']}
            old.update((item['id'],item) for item in new)
            raw_usage = sorted(old.values(),key=lambda item:(item['at'],item['kind']!='attempt.started',item['id']))
            bundle = {'facts':facts,'usage':raw_usage}
            if bundle != previous:
                atomic_json(file,bundle)
            recorded = apply_bundle(db,bundle)
            if missing:
                db.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)',
                           (gap_key,f'{missing} bound worker histories have missing or partial token evidence.'))
            else:
                db.execute('DELETE FROM collector_state WHERE key=?',(gap_key,))
            indexed += recorded
        except SOURCE_ERRORS + (sqlite3.IntegrityError, sqlite3.DataError):
            pending = True
            db.execute('ROLLBACK TO native_measurement')
            db.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)',
                       (gap_key,'A run’s saved observations could not be verified or indexed.'))
        finally:
            db.execute('INSERT OR REPLACE INTO collector_state VALUES(?,?)',
                       (cursor_key,json.dumps({'journal':signature,'sources':sources,'roots':roots,
                                                       'pending':pending,'checked':time.time()})))
            db.execute('RELEASE native_measurement')
    return max(0,indexed)
