"""Current task context. Durable history is retained without replaying author transcripts."""
from pathlib import Path
from .storage import Refused, atomic_json, digest, read_json

VERSION = 2
READINESS_LISTS = ('requirements', 'rules', 'surfaces', 'proof', 'self_review',
                   'family_closure', 'verification', 'repairs', 'limits')
DISPOSITIONS = ('fixed', 'routed', 'accepted', 'dismissed', 'still-open', 'disputed')


def report(attempt):
    if not attempt or not attempt.get('evidence'):return {}
    try:value = read_json(Path(attempt['evidence'])/'result.json').get('structured')
    except FileNotFoundError:return {}  # a terminated host may have saved no final report
    return value if isinstance(value, dict) else {}


def finding_index(state, task):
    """Distinct cases and original locators, with later review evidence and labelled author claims."""
    families = {}
    incomplete = []
    history = [a for a in state['attempts'] if a['task'] == task]
    author = next((a for a in reversed(history) if a['role'] in ('implementation','analysis') and a.get('finished')), None)
    readiness = report(author).get('readiness') or {}
    items = readiness.get('prior_findings', []) if isinstance(readiness,dict) else []
    claims = {c['id']:c for c in items if isinstance(c,dict) and set(c)=={'id','disposition','proof'}
              and all(isinstance(v,str) for v in c.values())} if isinstance(items,list) else {}
    for position, attempt in enumerate(history):
        if attempt['task'] != task or attempt['role'] != 'review':continue
        if attempt.get('outcome') not in ('clean','blocking','needs_resolution'):
            path=Path(attempt['evidence'])/'result.json' if attempt.get('evidence') else None
            incomplete.append({'attempt':attempt['id'],'outcome':attempt.get('outcome','unfinished'),
                'report':str(path) if path and path.is_file() else None,
                'note':'No completed verdict. Inspect any returned report for findings that could not be classified.'})
        resolution = state.get('resolutions', {}).get(attempt['id'], {})
        scope = state.get('scope_records', {}).get(attempt['id'], {})
        for number, finding in enumerate(attempt.get('findings', []), 1):
            key = (finding['family'], finding['severity'])
            group = families.setdefault(key, {'family': key[0], 'severity': key[1], 'cases': [], 'occurrences': []})
            disposition = 'still-open'
            choice = resolution.get('choice', '')
            if finding['severity'] == 'concern' and choice.startswith('accept concerns'):disposition = 'accepted'
            if finding['severity'] == 'scope':
                if scope.get('action') in ('route', 'noted') or 'route scope' in choice:disposition = 'routed'
                if scope.get('action') == 'dismiss' or 'dismiss scope' in choice:disposition = 'dismissed'
            case = {k: v for k, v in finding.items() if k not in ('severity', 'family', 'relation')}
            case_id = digest(case)[:16]
            if not any(c['id'] == case_id for c in group['cases']):group['cases'].append({'id': case_id} | case)
            occurrence = {'id': f"{attempt['id']}#{number}", 'disposition': disposition,
                'case': case_id,
                'review': str(Path(attempt['evidence'])/'result.json') if attempt.get('evidence') else '',
                'tree': attempt.get('git_tree') or attempt.get('tree'),
                'decision': choice, 'scope_action': scope.get('action')}
            # A later clean review closes earlier in-scope findings. An author claim alone cannot.
            clean = next((a for a in reversed(history[position+1:]) if a['role']=='review' and a.get('outcome')=='clean'), None)
            if disposition=='still-open' and finding['severity']!='scope' and clean:
                occurrence.update(disposition='fixed', reviewed_by=clean['id'],
                    resolution_evidence=str(Path(clean['evidence'])/'result.json') if clean.get('evidence') else '')
            if claim:=claims.get(occurrence['id']):
                occurrence['author_claim']={k:claim[k] for k in ('disposition','proof')} | {
                    'attempt':author['id'], 'evidence':str(Path(author['evidence'])/'result.json')}
            group['occurrences'].append(occurrence)
    return {'schema': VERSION, 'task': task, 'families': list(families.values()), 'incomplete_reviews': incomplete}


def coordinator_view(journal, value, limit):
    """Keep a large planning decision available by reference without repeating its full body in status."""
    from .storage import encode
    if len(encode(value)) <= limit:return value
    fingerprint=digest(value);path=journal.path/'views'/(fingerprint+'.json')
    # This is a regenerable presentation; the original proposal remains in its immutable attempt.
    atomic_json(path,value)
    return {k:value[k] for k in ('route','choices') if k in value} | {
        'summary':str(value.get('summary') or value.get('understanding') or '')[:800],
        'details':str(path), 'hash':fingerprint}


def finding_ids(index):
    return {item['id'] for family in index['families'] for item in family['occurrences']}


def validate_readiness(value, expected=None):
    if not isinstance(value, dict) or set(value) != {*READINESS_LISTS, 'prior_findings'}:
        return 'Return the current readiness sections: '+', '.join((*READINESS_LISTS, 'prior_findings'))+'.'
    for key in READINESS_LISTS:
        if not isinstance(value[key], list) or any(not isinstance(x, str) or not x.strip() for x in value[key]):
            return f'Readiness {key} must be a list of concrete observations.'
    for key in ('requirements', 'rules', 'surfaces', 'proof', 'self_review', 'verification'):
        if not value[key]:return f'Complete readiness {key}; state why a section does not apply when appropriate.'
    items = value['prior_findings']
    if not isinstance(items, list):return 'Account for every prior finding in prior_findings.'
    for item in items:
        if (not isinstance(item, dict) or set(item) != {'id', 'disposition', 'proof'} or
                any(not isinstance(v, str) or not v.strip() for v in item.values()) or
                item['disposition'] not in DISPOSITIONS):
            return 'Each prior finding needs its id, disposition and concrete proof.'
    ids = [item['id'] for item in items]
    if len(ids) != len(set(ids)) or expected is not None and set(ids) != expected:
        return 'Account for every finding id in the supplied finding index exactly once; do not omit or invent findings.'
    return None


def prepare(state, task, role, directory, admission, feedback=''):
    """An immutable projection of native facts and the latest author's explicitly labelled claims."""
    directory = Path(directory)
    index = finding_index(state, task['id'])
    index_path = directory/'finding-index.json'
    atomic_json(index_path, index, immutable=True)
    authors = [a for a in state['attempts'] if a['task'] == task['id'] and
               a['role'] in ('implementation', 'analysis') and a.get('finished') and a.get('evidence')]
    author = authors[-1] if authors else None
    value = report(author)
    current = None
    if author:
        path = Path(author['evidence'])/'result.json'
        current = {'attempt': author['id'], 'outcome': author.get('outcome'),
            'summary': value.get('summary') or author.get('summary', ''),
            'readiness': value.get('readiness'), 'report': {'path': str(path),
                'hash': digest(read_json(path)) if path.is_file() else None, 'available':path.is_file()},
            'authority': 'Author claims to verify, never approval or proof of completion.'}
    verification = state.get('verification', {}).get(task['id'])
    # Full command logs stay with their native check receipt, outside the mandatory context.
    if verification:
        verification = {k: v for k, v in verification.items() if k != 'checks'} | {
            'checks': [{k: c[k] for k in ('name', 'command', 'returncode', 'cancellation', 'unavailable', 'duration_ms', 'reused') if k in c}
                       for c in verification['checks']]}
    packet = {'schema': VERSION, 'run': state['id'], 'task': task,
        'subject': {k: admission.get(k) for k in ('head', 'tree', 'git_tree', 'config_hash')},
        'role': role, 'current_work': current, 'remaining_work': feedback,
        'verification': verification,
        'findings': {'path': str(index_path), 'hash': digest(index)},
        'history': str(directory.parent.parent),
        'history_policy': 'Read the current packet and complete finding index. Consult original reports only for a specific unresolved question; do not replay prior author reports or transcripts.'}
    if state.get('plans'):
        packet['planning'] = state['plans']
        packet['human_refinements'] = [{'source': a['source'], 'feedback': a['feedback']}
            for a in state.get('proposal_answers', []) if a['choice'] == 'refine']
    packet_path = directory/'task-context.json'
    atomic_json(packet_path, packet, immutable=True)
    return {'path': str(packet_path), 'hash': digest(packet)}, index
