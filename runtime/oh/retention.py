"""Immutable report selection and projection, shared by completion and recovery.

These functions retain evidence; the existing native/control boundaries decide
whether an attempt may finish. No report or attachment grants execution.
"""
import hashlib
from .system import Path
from .storage import Refused, digest, read_json, now
from .authority import Saving


class SelectionChanged(Saving):
    """No completion was committed; re-read before selecting immutable evidence."""

PINNED_FIELDS=('findings','finding_positions','finding_sources','review_fragments','report_issues',
               'source_ref','report_ref','diagnostics','outcome','summary')


def read(ref):
    value=read_json(ref['path'])
    if digest(value)!=ref['hash']:raise Refused('Retained evidence changed; preserve the original report and source.')
    return value


def save(path,value):
    from .native import _immutable
    _immutable(path,value)
    return {'path':str(path),'hash':digest(value)}


def parse(attempt,source):
    if attempt['role']=='review':
        from .review_report import read as review
        return review(source.get('text',''))
    from .native import _report
    return _report(source.get('text','')),[]


def project(report):
    raw=report.get('findings',[]);findings=[];positions=[];fragments=[]
    for position,finding in enumerate(raw if isinstance(raw,list) else [raw],1):
        if isinstance(finding,dict) and finding.get('severity') in ('blocking','concern','scope') and isinstance(finding.get('description'),str):
            value=dict(finding)
            for key in ('family','relation','path','anchor','failure','fix'):
                if key in value and not isinstance(value[key],str):value.pop(key)
            if report.get('decision_format')==1 and isinstance(value.get('family'),str):value['family_id']=value['family']
            value.setdefault('family',value['description']);value.setdefault('path','')
            findings.append(value);positions.append(position)
        else:fragments.append({'position':position,'finding':finding})
    return findings,positions,fragments


def attach(journal,state,attempt,source):
    report,issues=parse(attempt,source)
    value={'attempt':attempt['id'],'role':attempt['role'],'source':source,'report':report,'issues':issues}
    path=Path(attempt['evidence'])/'diagnostics'/(digest(value)+'.json')
    ref={'path':str(path),'hash':digest(value)}
    existing=next((e for e in state.get('supplementary',[]) if e.get('diagnostic')==ref),None)
    if not existing:
        save(path,value)
        findings,positions,_=project(report)
        entry={'attempt':attempt['id'],'diagnostic':ref,'at':now(),'text_hash':digest(source.get('text','')),'report_hash':digest(report),
               'findings':[{'position':n,**{k:f[k][:300] for k in ('severity','family','description') if isinstance(f.get(k),str)}} for f,n in zip(findings,positions)],
               'files':{ref['path']:hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest()},
               'summary':'Historical '+attempt['role']+' evidence; not a current verdict or approval.'}
        journal.append('evidence.attached',entry);state.setdefault('supplementary',[]).append(entry)
    return ref


def capture(root,journal,state,attempt):
    from . import authority
    try:observed=authority.native_diagnostics(root,state,attempt)
    except (FileNotFoundError,authority.Saving):observed=[]
    for source in observed:attach(journal,state,attempt,source)
    return [e['diagnostic'] for e in state.get('supplementary',[]) if e.get('attempt')==attempt['id'] and e.get('diagnostic')]


def diagnostic_index(state, task=None):
    """Optional history with report-local identity; never current readiness proof."""
    attempts={a['id']:a for a in state['attempts'] if task is None or a['task']==task}
    result=[]
    for entry in state.get('supplementary',[]):
        ref=entry.get('diagnostic');attempt=attempts.get(entry.get('attempt'))
        if not ref or not attempt:continue
        if (entry.get('report_hash') and entry['report_hash']==attempt.get('report_ref',{}).get('hash')
                and attempt.get('outcome') in ('reported','assessed','clean','blocking','needs_resolution')):continue
        item={'attempt':attempt['id'],'task':attempt['task'],'role':attempt['role'],'report':ref,
              'authority':'Historical diagnostics, not a current verdict or disposition.'}
        try:
            value=read(ref);findings,positions,fragments=project(value['report'])
            item.update(status='available',findings=[dict(f,position=n) for f,n in zip(findings,positions)],
                        issues=value['issues'],unparsed=len(fragments))
        except FileNotFoundError:item.update(status='unavailable',findings=entry.get('findings',[]))
        except (Refused,ValueError,KeyError,TypeError):item.update(status='changed',findings=entry.get('findings',[]))
        result.append(item)
    return result


def selected(root,journal,state,attempt,source,*,revoked=False):
    """Select independently established proof; partial files cannot authenticate it."""
    directory=Path(attempt['evidence']);partial=False
    def persist(name,value):
        nonlocal partial
        path=directory/name
        if path.exists():
            try:original=read_json(path)
            except (ValueError,Refused):original=None
            if original!=value:
                # Fresh native proof can differ in timing/notification hashes
                # without changing the report or its purpose. Keep both bytes,
                # but only a substantive conflict makes this result incomplete.
                keys=('text','status','native_id','origin','interruption','error')
                partial=partial or (original!=value if name=='result.json' else
                    not isinstance(original,dict) or any(original.get(k)!=value.get(k) for k in keys))
                files={str(path):hashlib.sha256(path.read_bytes()).hexdigest()}
                if not any(e.get('files')==files for e in state.get('supplementary',[])):
                    entry={'attempt':attempt['id'],'files':files,'at':now(),
                           'summary':'Preserved partial '+name+'; not verified as current native proof.'}
                    journal.append('evidence.attached',entry);state.setdefault('supplementary',[]).append(entry)
                path=directory/'diagnostics'/('selected-'+name.removesuffix('.json')+'-'+digest(value)+'.json')
        return save(path,value)
    source_ref=persist('revoked-result.json' if revoked else 'native-result.json',source)|{'kind':'revocation' if revoked else 'native'}
    report,issues=parse(attempt,source)
    report_ref=persist('result.json',report)
    entries=[e for e in state.get('supplementary',[]) if e.get('attempt')==attempt['id'] and e.get('diagnostic')]
    # Native adapters decide lifecycle eligibility. Conflicting observed review
    # reports are incomplete feedback, never a union or a later clean override.
    conflict=attempt['role']=='review' and any(e.get('text_hash') not in (None,digest(source.get('text',''))) for e in entries)
    if conflict:issues.append('Different review reports were observed in this attempt; retain diagnostics and obtain a fresh review.')
    if partial:issues.append('Partial canonical files differ from current verified evidence and remain preserved separately.')
    findings,positions,fragments=project(report)
    result={'source_ref':source_ref,'report_ref':report_ref,'diagnostics':[e['diagnostic'] for e in entries],
            'findings':findings,'finding_positions':positions}
    if fragments:result['review_fragments']=fragments
    if issues:result['report_issues']=list(dict.fromkeys(issues))
    return source,report,result,partial or conflict


def completion_cut(records,attempt):
    for number,record in enumerate(records):
        events=record['data']['events'] if record['kind']=='transition' else [record]
        if any(e['kind']=='attempt.finished' and e['data']['id']==attempt for e in events):return number
    raise Refused('The original attempt completion is missing; preserve its journal before rendering.')
