"""Historical readable review rendering. Native hosts own every question."""
from pathlib import Path
from .storage import Refused


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
