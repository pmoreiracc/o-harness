"""Bound delivery token accounting to verified native conversation evidence."""
from .authority import prompted
from .storage import digest, read_json

COST_EVENTS = {'decision', 'run.owner', 'workflow.restarted', 'delivery.recovered'}
CODEX_COUNTERS = ('input_tokens', 'cached_input_tokens', 'output_tokens')


def decision_source(directory, grant):
    from .native import _human_key

    key = grant.get('source') or ''
    if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
        return None
    path = directory / 'decisions' / (key + '.json')
    if not path.is_file() or path.is_symlink():
        return None
    source = read_json(path).get('human')
    if not isinstance(source, dict) or any(not source.get(k) for k in ('host', 'session', 'turn', 'prompt')):
        return None
    legacy = digest({k: source[k] for k in ('host', 'session', 'turn', 'prompt')})
    return source if key in (legacy, _human_key(source)) else None


def payload(record):
    return record.get('payload') or {}


def native_event(record, kind):
    return record.get('type') == 'event_msg' and payload(record).get('type') == kind


def complete_value(value):
    return all(type(value.get(key)) is int for key in ('input', 'output'))


def codex_ledger(records, first, last, values):
    """Reconcile unique per-response rows against the host's cumulative snapshots."""
    from .native_measurements import nonnegative

    def counters(record):
        info = payload(record).get('info') or {}
        total = info.get('total_token_usage') or {}
        counts = tuple(nonnegative(total.get(key)) for key in CODEX_COUNTERS)
        return counts if None not in counts else None

    prior = [v for r in records[:first] if native_event(r, 'token_count') and (v := counters(r))]
    current = [v for r in records[first:last] if native_event(r, 'token_count') and (v := counters(r))]
    if not current or not values or any(not complete_value(v) or v['cached'] is None for v in values):
        return False
    totals = tuple(sum(v[key] for v in values) for key in ('input', 'cached', 'output'))
    return tuple(end - start for end, start in zip(current[-1], prior[-1] if prior else (0, 0, 0))) == totals


def observed_claude(records):
    """Keep one finalized set of counters per message and prove request coverage."""
    from .native_measurements import usage_record

    requests, messages = set(), {}
    valid = True
    for record in records:
        if record['type'] == 'api-request':
            if record.get('id'):
                requests.add(record['id'])
            else:
                valid = False
        elif record['type'] == 'assistant' and (record.get('message') or {}).get('model') != '<synthetic>':
            value = usage_record('claude', record)
            ref = record.get('requestRef')
            if not value or not ref or not complete_value(value):
                valid = False
                continue
            identity = value['response_id']
            prior = messages.get(identity)
            if prior and (prior[0] != ref or any(prior[1][k] != value[k] for k in ('input', 'cached'))):
                valid = False
            if not prior or value['output'] >= prior[1]['output']:
                # A content-block snapshot can raise output counts. The request
                # belongs to the phase in which its first response was observed.
                messages[identity] = (ref, value | {'at': prior[1]['at'] if prior else value['at']})
    replies = [ref for ref, _ in messages.values()]
    return [value for _, value in messages.values()], bool(
        valid and requests and requests == set(replies) and len(requests) == len(replies))


def codex_window(records, source, anchor, through):
    from .native_measurements import timestamp, usage_record

    session, turn = source['session'], source['turn']
    meta = payload(records[0])
    if records[0].get('type') != 'session_meta' or meta.get('id') != session or meta.get('model_provider') != 'openai':
        return [], False
    starts = [i for i, record in enumerate(records[:anchor + 1]) if native_event(record, 'task_started')
              and payload(record).get('turn_id') == turn]
    if len(starts) != 1:
        return [], False
    first = starts[0]
    last = next((i for i in range(anchor + 1, len(records)) if native_event(records[i], 'task_complete')
                 and payload(records[i]).get('turn_id') == turn), None)
    if last is None or not through or (timestamp(records[last].get('timestamp')) or '') < through:
        return [], False
    window = records[first:last]
    if any(native_event(r, k) for r in window[1:] for k in ('task_started', 'turn_aborted')):
        return [], False
    model = next((payload(r).get('model') for r in window if r.get('type') == 'turn_context'
                  and payload(r).get('turn_id') == turn), None)
    responses = [r for r in window if r.get('type') == 'token_usage_record']
    unique, valid = {}, True
    for record in responses:
        info = payload(record)
        value = usage_record('codex', record, model)
        if not value or (info.get('thread_id'), info.get('turn_id')) != (session, turn):
            valid = False
            continue
        identity = value['response_id']
        if identity in unique and unique[identity] != value:
            valid = False
        unique[identity] = value
    values = list(unique.values())
    return values, valid and codex_ledger(records, first, last, values)


def claude_window(records, source, anchor, through):
    from .native_measurements import timestamp

    session = source['session']
    relevant = []
    closed_response = None
    for record in records[anchor + 1:]:
        if record.get('sessionId') != session or record.get('isSidechain') or record.get('agentId'):
            continue
        if prompted(record, session):
            break
        kind = record.get('type')
        message = record.get('message') or {}
        if kind == 'system' and record.get('subtype') == 'turn_duration':
            if through and (timestamp(record.get('timestamp')) or '') >= through:
                return observed_claude(relevant)
        if kind == 'api-request' and closed_response:
            break
        if kind == 'assistant':
            if closed_response and message.get('id') != closed_response:
                break
            if message.get('stop_reason') == 'end_turn' and through and (timestamp(record.get('timestamp')) or '') >= through:
                closed_response = message.get('id')
        relevant.append(record)
    values, complete = observed_claude(relevant)
    return values, bool(complete and closed_response)


def verified_window(read, source, through):
    host, path = source.get('host'), source.get('transcript_path')
    if host not in ('codex', 'claude') or not source.get('session') or not source.get('turn'):
        return [], False
    records, incomplete = read(host, path)
    hashes = set(source.get('record_hashes') or ())
    if not records or not hashes:
        return [], False
    anchor = None
    for index, record in enumerate(records):
        kind = record.get('type')
        data = payload(record)
        candidate = (kind in ('assistant', 'attachment', 'user') if host == 'claude' else
                     native_event(record,'user_message')
                     or (native_event(record,'item_completed') and (data.get('item') or {}).get('type') == 'UserMessage')
                     or (kind == 'response_item' and data.get('type') == 'function_call'))
        if candidate and (identity := digest(record)) in hashes:
            hashes.remove(identity)
            anchor = index
            if not hashes:
                break
    if hashes:
        return [], False
    # The reply is the later of the attested records for a native question.
    # A typed command anchors its own turn.
    measure = codex_window if host == 'codex' else claude_window
    values, complete = measure(records, source, anchor, through)
    return [value | {'host':host} for value in values], complete and not incomplete


def worker_complete(host, records, binding, scoped):
    if host == 'codex':
        if not any(native_event(r, 'task_complete') for r in records):
            return False
        count = len({v['response_id'] for v in scoped})
        return count == len(scoped) and codex_ledger(records, 0, len(records), scoped)
    child = [r for r in records if r.get('agentId') == binding['child_session']
             and r.get('sessionId') == binding['parent_session']]
    values, complete = observed_claude(child)
    def totals(rows):
        result = {}
        for value in rows:
            identity = value['response_id']
            if not complete_value(value):
                return None
            result[identity] = max(result.get(identity, (0, 0)), (value['input'], value['output']))
        return result
    return complete and totals(values) == totals(scoped)


def delivery_windows(directory, state, records, read):
    from .native_measurements import record_events, timestamp

    start = records[0]['data'].get('entry_request') or records[0]['data']['human']
    grant = state.get('publication') or {}
    publication = decision_source(directory, grant) if grant else None
    transitions = [(kind, value, timestamp(at)) for kind, value, at in record_events(records[1:])]
    terminal = next((at for kind, _, at in reversed(transitions) if kind == 'publication.completed'), None)
    approval = next((at for kind, value, at in reversed(transitions)
                     if kind == 'decision' and value.get('source') == grant.get('source')), None)
    if not state['done']:
        return [], [], False

    # Resuming changes the verified owner even when the CLI reuses a conversation.
    # Include each owner only for its own span of this run.
    owners = [(start, timestamp(records[0]['at']))]
    owners.extend((value['human'], at) for kind, value, at in transitions if kind == 'run.owner')
    continuous = not any(kind in COST_EVENTS and kind != 'run.owner'
                         and not (kind == 'decision' and value.get('choice') in ('resume','pr'))
                         for kind, value, _ in transitions)
    if sum(kind == 'decision' and value.get('choice') == 'resume' for kind, value, _ in transitions) != len(owners)-1:
        continuous = False

    cut = timestamp(publication.get('at')) if publication else None
    coordinator, published, unassigned = {}, [], set()
    delivery_start = timestamp(start.get('at')) or owners[0][1]
    complete = continuous
    for index, (owner, bound_at) in enumerate(owners):
        last = index == len(owners)-1
        next_owner, next_at = (publication, approval) if last else owners[index+1]
        start_at = timestamp(owner.get('at')) or bound_at
        next_anchor = timestamp(next_owner.get('at')) if next_owner else None
        if not start_at or (next_anchor and next_anchor <= start_at):
            complete = False
            continue
        through = max((at for kind, _, at in transitions
                       if kind in ('attempt.finished','task.completed')
                       and at and bound_at <= at and (not next_at or at < next_at)), default=bound_at)
        same_thread = last and publication and (owner.get('host'),owner.get('session')) == (
            publication['host'],publication['session'])
        may_share_turn = same_thread and (publication.get('question_call') if owner['host']=='claude'
                                          else owner.get('turn') == publication['turn'])
        rows, verified = verified_window(read, owner, terminal if may_share_turn and terminal else through)
        if not rows and may_share_turn:
            rows, verified = verified_window(read, owner, through)
        for value in rows:
            if delivery_start <= value['at'] < start_at:
                unassigned.add(value['response_id'])
            if start_at <= value['at'] and (not next_anchor or value['at'] < next_anchor):
                identity = value['response_id']
                if identity in coordinator:
                    complete = False
                coordinator[identity] = value
        complete = complete and verified and bool(rows)
    if cut and terminal and cut <= terminal:
        published, verified = verified_window(read, publication, terminal)
        unassigned.update(v['response_id'] for v in published if delivery_start <= v['at'] < cut)
        # A Codex answer may arrive midway through a long native turn. Earlier
        # responses and work after the verified PR sit outside publication.
        published = [v for v in published if cut <= v['at'] <= terminal and v['response_id'] not in coordinator]
        complete = complete and verified and bool(published)
    else:
        complete = False
    # Reconciled counters prove a response exists, but a different turn's
    # pre-approval work cannot be counted without its own coordinator binding.
    return list(coordinator.values()), published, bool(complete and coordinator and not unassigned.difference(coordinator))
