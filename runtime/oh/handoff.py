"""Bounded evidence packets, never agent prompts or mandatory prose schemas."""
from pathlib import Path
from .storage import Refused, atomic_json, digest, read_json
VERSION=4
READINESS_LISTS=('requirements','rules','surfaces','proof','self_review','family_closure','verification','repairs','limits')
DISPOSITIONS=('fixed','routed','accepted','dismissed','still-open','disputed')


def family_fields(value):
    """Optional Markdown quoting does not change inline Family/Relation labels."""
    import re
    parts=re.split(r'\s+(?:\*\*)?Relation(?:\*\*)?\s*:\s*',value,maxsplit=1,flags=re.I)
    if len(parts)==1:return {'family':value.strip('`')}
    def plain(text):return text.strip().rstrip('.;').strip('`').rstrip('.;')
    return {'family':plain(parts[0]),'relation':plain(parts[1])}


def family_identity(finding):
    """Read historical inline metadata without changing its original evidence."""
    if isinstance(finding.get('family_id'),str):return finding['family_id']
    family=finding.get('family')
    return family_fields(family if isinstance(family,str) and family else finding['description'])['family']


def report(attempt):
    if not attempt or not attempt.get('evidence'):return {}
    try:
        if ref:=attempt.get('normalized_report'):
            value=read_json(ref['path'])
            if digest(value)!=ref['hash']:raise Refused('The normalized handoff changed; preserve the original evidence.')
        else:
            saved=read_json(Path(attempt['evidence'])/'result.json')
            value=saved.get('structured',saved)
    except FileNotFoundError:return {}  # a terminated host may have saved no final report
    return value if isinstance(value, dict) else {}

def confirms_repairs(state, attempt):
    """Only valid independent evidence closes earlier in-scope findings."""
    if attempt.get('finished') is False:return False
    if attempt.get('report_issues') or attempt.get('review_fragments'):return False
    findings=attempt.get('findings',[])
    if attempt.get('outcome')=='clean':return not findings
    if attempt.get('outcome')!='needs_resolution' or not findings or {f['severity'] for f in findings}!={'scope'}:return False
    if not attempt.get('git_tree') or not attempt.get('head'):return False
    from .publication import validate_evidence
    try:
        validate_evidence({'schema':1,'attempts':[attempt],'review':attempt['id'],
            'git_tree':attempt.get('git_tree'),'parent':attempt.get('head'),
            'resolutions':state.get('resolutions',{})})
    except Refused:return False
    return True

def finding_index(state, task):
    """Distinct cases and original locators, with later review evidence and labelled author claims."""
    families = {}
    incomplete = []
    history = [a for a in state['attempts'] if a['task'] == task and a.get('purpose','workflow')=='workflow']
    author = next((a for a in reversed(history) if a['role'] in ('implementation','analysis') and a.get('finished')), None)
    readiness = report(author).get('readiness') or {}
    items = readiness.get('prior_findings', []) if isinstance(readiness,dict) else []
    claims = {c['id']:c for c in items if isinstance(c,dict) and set(c)=={'id','disposition','proof'}
              and all(isinstance(v,str) for v in c.values())} if isinstance(items,list) else {}
    for position, attempt in enumerate(history):
        if attempt['task'] != task or attempt['role'] != 'review':continue
        # A live reviewer has not returned evidence yet. It is not a failed handoff.
        if attempt.get('finished') is False:continue
        if attempt.get('outcome') not in ('clean','blocking','needs_resolution') or attempt.get('report_issues') or attempt.get('review_fragments'):
            path=Path(attempt['evidence'])/'result.json' if attempt.get('evidence') else None
            incomplete.append({'attempt':attempt['id'],'outcome':attempt.get('outcome','unfinished'),
                'report':str(path) if path and path.is_file() else None,
                'issues':attempt.get('report_issues',[]),'fragments':attempt.get('review_fragments',[]),
                'note':('Historical incomplete evidence; a later valid review is recorded for this task.'
                        if any(a['role']=='review' and confirms_repairs(state,a) for a in history[position+1:]) else
                        'Inspect retained incomplete evidence. A later reviewer must address it explicitly before claiming clean.')})
        resolution = state.get('resolutions', {}).get(attempt['id'], {})
        scope = state.get('scope_records', {}).get(attempt['id'], {})
        for number, finding in enumerate(attempt.get('findings', []), 1):
            number=attempt.get('finding_positions',list(range(1,len(attempt['findings'])+1)))[number-1]
            key = (family_identity(finding), finding['severity'])
            group = families.setdefault(key, {'family': key[0], 'severity': key[1], 'cases': [], 'occurrences': []})
            disposition = 'still-open'
            choice = resolution.get('choice', '')
            if finding['severity'] == 'concern' and choice.startswith('accept concerns'):disposition = 'accepted'
            if finding['severity'] == 'scope':
                if scope.get('action') in ('route', 'noted') or 'route scope' in choice:disposition = 'routed'
                if scope.get('action') == 'dismiss' or 'dismiss scope' in choice:disposition = 'dismissed'
            case = {k: v for k, v in finding.items() if k not in ('severity', 'family', 'family_id', 'relation')}
            case_id = digest(case)[:16]
            if not any(c['case_key'] == case_id for c in group['cases']):group['cases'].append({'case_key': case_id} | case)
            occurrence = {'id': f"{attempt['id']}#{number}", 'disposition': disposition,
                'case_key': case_id,
                'review': str(Path(attempt['evidence'])/'result.json') if attempt.get('evidence') else '',
                'tree': attempt.get('git_tree') or attempt.get('tree'),
                'decision': choice, 'scope_action': scope.get('action')}
            # A later valid review closes earlier in-scope findings. An author claim alone cannot.
            clean = next((a for a in reversed(history[position+1:]) if a['role']=='review' and confirms_repairs(state,a)), None)
            if disposition=='still-open' and finding['severity']!='scope' and clean:
                occurrence.update(disposition='fixed', reviewed_by=clean['id'],
                    resolution_evidence=str(Path(clean['evidence'])/'result.json') if clean.get('evidence') else '')
            if claim:=claims.get(occurrence['id']):
                occurrence['author_claim']={k:claim[k] for k in ('disposition','proof')} | {
                    'attempt':author['id'], 'evidence':str(Path(author['evidence'])/'result.json')}
            group['occurrences'].append(occurrence)
    return {'schema': VERSION, 'task': task, 'families': list(families.values()), 'incomplete_reviews': incomplete}

def finding_ids(index):
    return {item['id'] for family in index['families'] for item in family['occurrences']}

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
        path = Path(author['normalized_report']['path']) if author.get('normalized_report') else Path(author['evidence'])/'result.json'
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
    packet = {'purpose':admission.get('purpose','workflow'),'schema': VERSION, 'run': state['id'], 'task': task,
        'subject': {k: admission.get(k) for k in ('head', 'tree', 'git_tree', 'config_hash')},
        'role': role, 'current_work': current, 'remaining_work': feedback,
        'verification': verification,
        'findings': {'path': str(index_path), 'hash': digest(index)},
        'scope_snapshot':{'path':str(directory.parent.parent/'scope'/'scope.json'),'hash':digest(state['scope_snapshot'])} if state.get('scope_snapshot') else None,
        'accepted_scope':{'path':str(directory.parent.parent/'scope'/'accepted.md')} if state.get('accepted_scope') else None,
        'proposal_decisions':state.get('proposal_answers',[]),
        'supplementary_evidence':state.get('supplementary',[]),
        'completed_tasks':[{'id':t['id'],'title':t['title']} for t in state['tasks'] if t['id'] in state['done']],
        'standalone_subject':state.get('standalone_subject'),
        'standalone_artifact':state.get('standalone_artifact'),
        'history': str(directory.parent.parent),
        'history_policy': 'Read the current packet, complete finding index and full current_review report before repairing findings. Consult older reports for unresolved questions; do not replay prior author reports or transcripts.'}
    latest=next((a for a in reversed(state['attempts']) if a['task']==task['id'] and a['role']=='review' and a.get('finished') and a.get('evidence')),None)
    if latest:
        path=Path(latest['evidence'])/'result.json'
        packet['current_review']={'attempt':latest['id'],'outcome':latest.get('outcome'),
            'report':{'path':str(path),'hash':digest(read_json(path))},
            'instruction':'Read the full receipt, including reasoning and limits, before deciding repairs. Judge claims against the approved scope and concrete behavior; do not implement suggestions blindly.'}
    if not state.get('standalone_subject'):
        approval=directory.parent.parent/'scope'/'approval.json'
        if approval.is_file():packet['human_scope_approval']={'path':str(approval)}
        else:
            original=directory.parent.parent/'000001.json'
            if original.is_file():packet['original_scope_provenance']={'path':str(original),
                'authority':'Original run provenance; not a newly accepted native scope.'}
    if state.get('repair_source'):packet['repair_source']=state['repair_source']
    if (original:=state.get('pr_target') or state.get('original_work')) and not state['summaries']:
        packet['included_original_work']={k:original[k] for k in ('url','head','review_base','covers') if k in original}
    if state.get('plans'):
        packet['planning'] = state['plans']
        packet['human_refinements'] = [{'source': a['source'], 'feedback': a['feedback']}
            for a in state.get('proposal_answers', []) if a['choice'] == 'refine']
    limit=state['config']['context']['handoff_chars']
    from .storage import encode
    if len(encode(packet))>limit:
        original=packet;details=directory/'task-details.json'
        atomic_json(details,original,immutable=True)
        packet={'schema':VERSION,'purpose':admission.get('purpose','workflow'),'run':state['id'],'role':role,
                'task':{'id':task['id'],'title':task['title'][:160]},
                'details':{'path':'task-details.json','hash':digest(original)},
                'findings':{'path':'finding-index.json','hash':digest(index)}}
    if len(encode(packet))>limit:
        raise Refused('The task title and immutable references exceed the configured context bound; increase context.handoff_chars before admission')
    packet_path = directory/'task-context.json'
    atomic_json(packet_path, packet, immutable=True)
    return {'path': str(packet_path), 'hash': digest(packet)}, index
