"""Focused evidence/admissibility helpers. Native skills, never this module, run agents."""
from contextlib import ExitStack, contextmanager, nullcontext
from .system import Path
import hashlib
import json
import os
import re
from . import authority
from .config import snapshot, project_checks
from .storage import (Journal, Refused, atomic_json, checkout_file, checkout_id, digest,
                      git, identifier, lock, now, project, read_json, state_home, whole, changes)
from .verification import tree, candidate_tree, check_failed, provenance
from .workflow import load_run, reduce, next_task, review_limit, validate_tasks, committed, display_task
from .workflow import saved_runs as _saved_runs
from .telemetry import best_effort




def _immutable(path,value):
    """Retry an evidence write only when its original contents are unchanged."""
    path=Path(path)
    if path.exists():
        if read_json(path)!=value:raise Refused('Immutable native evidence changed: '+str(path))
        return
    try:atomic_json(path,value,immutable=True)
    except FileExistsError:
        if read_json(path)!=value:raise Refused('Immutable native evidence changed: '+str(path))


def _human_key(source,state=None):
    """Use native message identity; preserve already-consumed pre-ID receipts."""
    identity={k:source[k] for k in ('host','session','turn','prompt')}
    legacy=digest(identity)
    field='question_call' if source.get('question_call') else 'message_id'
    if not source.get(field):return legacy
    current=digest(identity|{field:source[field]})
    if not state or (legacy!=state.get('source') and legacy not in state.get('decisions',[])):return current
    journal=Journal(state['project'],state['id'])
    if legacy==state.get('source'):
        prior=journal.records()[0]['data'].get('human',{})
    else:
        path=journal.path/'decisions'/(legacy+'.json')
        prior=read_json(path).get('human',{}) if path.exists() else {}
    # Missing old evidence must not turn a consumed answer into a new grant.
    old=set(prior.get('record_hashes',[]));new=set(source.get('record_hashes',[]))
    if not old or not new or old & new or prior.get('at')==source.get('at'):return legacy
    return current


def _render_attempt(journal,state,attempt):
    directory=Path(attempt['evidence'])
    from .receipts import completed,index
    from . import retention
    records=journal.records();end=retention.completion_cut(records,attempt['id'])
    original=reduce(records[:end+1]);rendered=_attempt(original,attempt['id'])
    report=retention.read(rendered['report_ref']) if rendered.get('report_ref') else read_json(directory/'result.json')
    source=retention.read(rendered['source_ref']) if rendered.get('source_ref') else read_json(directory/('revoked-result.json' if (directory/'revoked-result.json').exists() else 'native-result.json'))
    completed(directory,read_json(directory/'request.json'),{'structured':report,'text':source.get('text','')},rendered,original)
    index(journal,state)


def _reparse_review(root,journal,state,attempt):
    """Repair only the old missing-header classification, preserving its original receipt.
    Re-read the same native result and exact subject; never synthesize a reviewer verdict.
    """
    from .review_report import read
    if (attempt.get('role')!='review' or attempt.get('outcome')!='review_incomplete'
            or not attempt.get('finished') or attempt.get('findings') or attempt.get('review_fragments')
            or attempt.get('normalized_report') or not attempt.get('native_child')):return attempt
    directory=Path(attempt['evidence']);original=read_json(directory/'result.json')
    if original.get('verdict') is not None or original.get('findings'):return attempt
    source=read_json(directory/'native-result.json')
    if source.get('status')!='completed':return attempt
    report,issues=read(source.get('text',''))
    if issues or report.get('decision_format')!=1 or report.get('verdict')=='incomplete':return attempt
    # A later attempt may have changed the interpretation or subject. It owns recovery now.
    if state['attempts'][-1]['id']!=attempt['id']:return attempt
    subject=_subject(root,state)
    if any(subject[k]!=attempt[k] for k in ('head','tree','git_tree','artifacts')):
        raise Refused('The retained review covers an earlier candidate; verify and review the current work')
    if digest(read_json(directory/'request.json'))!=attempt['request_hash']:
        raise Refused('The original review admission changed; preserve its evidence')
    if authority.native_result(root,state,attempt,{})!=source:
        raise Refused('The native reviewer evidence changed; retain the original and obtain a fresh review')
    findings=[]
    for finding in report['findings']:
        value=dict(finding)
        for key in ('relation','path','anchor','failure','fix'):
            if key in value and not isinstance(value[key],str):value.pop(key)
        value.update(family_id=value['family']);value.setdefault('path','');findings.append(value)
    outcome='blocking' if any(f['severity']=='blocking' for f in findings) else 'needs_resolution' if findings else 'clean'
    path=directory/'reparsed-review.json';_immutable(path,report)
    record={'id':attempt['id'],'outcome':outcome,'findings':findings,
            'finding_positions':list(range(1,len(findings)+1)),
            'summary':report['receipt'][:state['config']['context']['result_chars']],
            'normalized_report':{'path':str(path),'hash':digest(report)},
            'original_result_hash':digest(original),'native_result_hash':digest(source)}
    events=[{'kind':'review.reparsed','data':record}]
    if state.get('extra_review') and not state.get('correction') and (outcome=='blocking' or any(f['severity']=='concern' for f in findings)):
        extra=state['extra_review']
        correction={'task':attempt['task'],'prior_commit':extra['prior_commit'],'return_status':extra['return_status'],
                    'key':attempt['task']+'-correction-'+attempt['id']}
        events.append({'kind':'correction.started','data':correction});state['correction']=correction
    journal.append('transition',{'events':events})
    updated=_attempt(reduce(journal.records()),attempt['id']);attempt.clear();attempt.update(updated)
    best_effort('review.reparsed',state['project'],state['id'],attempt['task'],attempt['id'],outcome=outcome)
    from .receipts import index
    index(journal,state)
    return attempt


def _home(root):return state_home()/'projects'/project(root)['id']


def _scope(root, key):
    if not re.fullmatch(r'[0-9a-f]{64}',key or ''):raise Refused('Invalid immutable scope identity')
    path=_home(root)/'scopes'/key/'scope.json';value=read_json(path)
    if digest(value)!=key:raise Refused('The immutable scope changed; preserve its original evidence')
    if value['checkout']!=checkout_id(root):raise Refused('Scope belongs to another checkout')
    return value


@contextmanager
def _locked(root):
    with lock(checkout_file(root,'oh-control.lock')):yield


def _files(paths):
    values={}
    for name in paths:
        p=Path(name)
        if not p.is_file() or p.is_symlink():raise Refused('Evidence must be an ordinary file: '+str(p))
        values[str(p.resolve())]=hashlib.sha256(p.read_bytes()).hexdigest()
    return values


def _unchanged(files):
    if _files(files)!=files:raise Refused('A bound artifact changed; retain the original and prepare fresh evidence')


def _attempt(state, attempt_id):
    matches=[a for a in state['attempts'] if a['id']==attempt_id]
    if len(matches)!=1:raise Refused('No unique admitted attempt has this identity')
    return matches[0]


def _active(state):return [a for a in state['attempts'] if not a.get('finished')]


def _idle(root):
    from .controls import busy
    if busy(root):raise Refused('OH is still executing in this checkout; wait for its current step, then retry the same operation')


def _execution(root,state):
    """Execution observations do not rewrite the workflow's durable disposition."""
    from . import cancellation
    caught_up=cancellation.poll(root,state=state)
    stopped=cancellation.marker(root,state=state)
    control=cancellation._read(root)
    pending=[a['id'] for a in _active(state)]
    unsettled=[a['id'] for a in state['attempts'] if not cancellation._quiescent(control,a['id'],retained=a.get('finished',False))]
    interruption=read_json(stopped) if stopped and stopped.exists() else None
    return {'state':'unsettled' if pending or unsettled else 'idle',
            'pending_attempts':len(pending),'unsettled_operations':len(unsettled),
            'interruption':{k:interruption[k] for k in ('host','session','turn','at','event') if k in interruption} if interruption else None,
            'observation':'current' if caught_up else 'unavailable'}


def _switchable(root,states):
    """Idle saved authority is history, not a reservation of this checkout."""
    _idle(root)
    for state in states:
        from . import cancellation
        control=cancellation._read(root)
        for attempt in state['attempts']:
            if not attempt.get('finished'):continue
            try:
                needs_terminal=cancellation.reconcile_execution(root,attempt)
                if attempt.get('native_child') and attempt['id'] not in (control or {}).get('attempts',{}):
                    operations=authority.claude_operations(state,attempt)
                    if any(o['state']=='pending' for o in operations.values()):raise authority.Saving('Native reactivation has no settled result; await or cancel that native operation before advancing.')
                    needs_terminal=needs_terminal or bool(operations)
                if needs_terminal:
                    try:terminal=authority.native_result(root,state,attempt,{})
                    except authority.Unavailable:raise
                    except authority.Saving:
                        if not attempt.get('revocation') or needs_terminal:raise
                    else:
                        cancellation.reconcile_execution(root,attempt,terminal=terminal)
            except (FileNotFoundError,authority.Unavailable):
                # A committed result survives host transcript expiry. Missing old
                # logs do not settle any positively tracked pending operation.
                if not cancellation._quiescent(cancellation._read(root),attempt['id'],retained=True):
                    raise Refused('A tracked operation still needs native settlement evidence; await or cancel that original operation and retry the same decision.')
        facts=_execution(root,state)
        if facts['state']!='idle':
            raise Refused('Saved work '+state['id']+' has an unsettled native attempt or operation. '
                          'Inspect and retain its terminal result or use its existing recovery decision; '
                          'let the native host finish/cancel old operations and save cleanup evidence, then retry the original request. '
                          'A workflow status alone is not cleanup evidence.')


def _selection_boundary(journal,excluding=None,*,selection_only=False):
    records=journal.records()
    boundary=records[0]['data'].get('human',{}).get('at') or records[0]['at']
    for record in records[1:]:
        events=record['data'].get('events',[]) if record['kind']=='transition' else [record]
        for event in events:
            if event['kind']!='decision' or event['data'].get('source')==excluding:continue
            if selection_only and event['data'].get('target_only'):continue
            path=journal.path/'decisions'/(event['data']['source']+'.json')
            source=read_json(path).get('human',{}) if path.exists() else {}
            at=source.get('at') or record['at']
            if authority.newer(at,boundary):boundary=at
    return boundary


def _owner_order(root,source,state=None):
    """The execution owner can be newer than an interrupted selection-file write."""
    from . import cancellation
    control=cancellation._read(root) or {}
    current=control.get('current')
    owner=control.get('owners',{}).get(current,{})
    if not owner.get('since') or authority.newer(source.get('at'),owner['since']):return
    if state and source.get('at')==owner['since']:
        if cancellation.owner_key(state|{'human':source})==current:return
        if (cancellation.owner_key(state)==current and
                _human_key(source,state)==_human_key(state['human'],state)):return  # Already-consumed pre-ID native evidence.
    raise Refused('This selection predates the current execution owner and was superseded; use the current native request or saved-work decision')


def _entry_order(root,source,saved=None):
    owner=source.get('prerequisite_human',source);state=None
    if source.get('prerequisite'):
        # request_source reattested this accepted effect and its exact answer.
        prepared=read_json(_home(root)/'decisions'/(source['prerequisite']+'.json'))
        _,state=load_run(root,prepared['run'])
    _owner_order(root,owner,state)
    for journal,prior in _saved_runs(root) if saved is None else saved:
        if not authority.newer(owner.get('at'),_selection_boundary(journal,_human_key(owner,prior),selection_only=True)):
            raise Refused('This request predates the current work selection. Preserve it as history; use the current native request or a verified prerequisite continuation.')


def _continuation_order(root,state,source):
    """A retry may finish its own transfer, but cannot reclaim a newer selection."""
    from .workflow import active_file
    _owner_order(root,source,state)
    selected=active_file(root)
    if selected.exists():
        journal,_=load_run(root)
        if not authority.newer(source.get('at'),_selection_boundary(journal,_human_key(source,state))):
            raise Refused('This continuation was superseded by another work selection; ask the Resume question for the intended saved work')


def _finish_owner(root,state,source=None,*,retry_resume=False,force=False,ordering_state=None):
    """Complete an interrupted owner write; callers hold the control lock."""
    from . import cancellation
    control=cancellation._read(root) or {}
    if control.get('current')==cancellation.owner_key(state) and not force:return
    owner=(source or state['human']).get('prerequisite_human',source or state['human'])
    if (_human_key(owner,state)!=_human_key(state['human'],state) or
            owner.get('at')!=state['human'].get('at')):
        raise Refused('Retry the original accepted selection; this input belongs to a different owner')
    _owner_order(root,owner,ordering_state or state)
    _switchable(root,[state]+[s for _,s in _saved_runs(root) if s['id']!=state['id']])
    locator={k:owner[k] for k in ('host','session','turn','prompt','transcript_path','message_id') if owner.get(k)}
    if owner.get('question_call'):locator['tool_use_id']=owner['question_call']
    actual=authority.coordinator(root,state,locator,retry_resume=retry_resume)
    if _human_key(actual,state)!=_human_key(state['human'],state) or actual.get('at')!=state['human'].get('at'):
        raise Refused('The original native selection changed; preserve its evidence and use the current saved-work decision')
    with cancellation.continuation(root,state,state['human'],replacing=True):pass


def _initial_grant(root,journal,state):
    if (state['granted'] or state.get('source') in state['decisions'] or
            any(r['kind']=='grant' for r in journal.records())):return None
    if state['workflow']=='review':
        return {'tasks':['review'],'source':state['source'],'kind':'standalone','config_hash':state['config_hash']}
    approval=journal.path/'scope'/'approval.json'
    if not state.get('scope_id') or not approval.is_file():return None
    if _human_key(read_json(approval),state)!=state['source']:
        raise Refused('The initial scope acceptance changed; preserve its original approval evidence')
    scope=_scope(root,state['scope_id'])
    return {'tasks':[t['id'] for t in scope['tasks'][:scope['config']['tasks_per_batch']]],
            'source':state['source'],'kind':'initial','config_hash':state['config_hash']}


def _finish_entry(root,journal,state,source):
    from .workflow import active_file
    from . import cancellation
    canonical=checkout_file(root,'oh-active-review.json' if state['workflow']=='review' else 'oh-active-run.json')
    if not canonical.exists() or read_json(canonical).get('run')!=state['id']:
        raise Refused('This entry was superseded; inspect the current saved work before continuing')
    binding=read_json(active_file(root))
    grant=_initial_grant(root,journal,state)
    if (binding.get('run')==state['id'] and not grant and
            (cancellation._read(root) or {}).get('current')==cancellation.owner_key(state)):
        return select(root,state['id'])
    if _human_key(source,state)!=state.get('source'):
        raise Refused('Retry the original accepted entry or use the current saved-work decision')
    owner=state['human'] if state.get('entry_prerequisite') else source
    order_state=state
    if state.get('entry_prerequisite'):
        prepared=read_json(_home(root)/'decisions'/(state['entry_prerequisite']+'.json'))
        _,prior=load_run(root,prepared['run'])
        if (cancellation._read(root) or {}).get('current')==cancellation.owner_key(prior):order_state=prior
    _owner_order(root,owner,order_state)
    for other_journal,other in _saved_runs(root):
        boundary=_selection_boundary(other_journal,_human_key(owner,other),selection_only=other['id']!=state['id'])
        if (authority.newer(boundary,owner.get('at')) if other['id']==state['id'] else
                not authority.newer(owner.get('at'),boundary)):
            raise Refused('This entry predates a newer selection or decision; use the current native request')
    _resume_binding(root,state)
    _finish_owner(root,state,owner,force=True,ordering_state=order_state)
    if grant:
        journal.append('grant',grant)
        state=reduce(journal.records())
    _resume_binding(root,state,write=True)
    return select(root,state['id'])


def _entry_retry(root,state,source):
    with _locked(root):
        journal,state=load_run(root,state['id'])
        return _finish_entry(root,journal,state,source)


def _owner(root,state):
    authority.coordinator(root,state)
    _owner_order(root,state['human'],state)
    since=state['human'].get('at') or load_run(root,state['id'])[0].records()[0]['at']
    if any(other['id']!=state['id'] and authority.newer(_selection_boundary(journal,_human_key(state['human'],other),selection_only=True),since)
           for journal,other in _saved_runs(root)):
        raise Refused('This coordinator was superseded by a newer saved selection; finish its original entry or use the current saved-work decision')
    from .workflow import active_file
    if read_json(active_file(root)).get('run')!=state['id']:
        raise Refused('This work selection was superseded; use the existing Resume decision to select it again')
    from .cancellation import guard
    guard(root,state=state)
    if state.get('published'):raise Refused('Published delivery is finished; prepare new bounded work')
    if git(root,'branch','--show-current')!=state['branch']:raise Refused('Return to the admitted branch before continuing this work')


def _structure(root,state):
    bound=state.get('delivery')
    if not bound:return
    from .delivery_verify import parsed
    original=state['scope_snapshot']['documents'][bound['path']]
    _,before=parsed(original);_,after=parsed(Path(bound['path']).read_text())
    if set(before)!=set(after):raise Refused('Delivery cannot add or remove approved tasks')
    for task,row in before.items():
        if row[2:]!=after[task][2:]:raise Refused('Delivery changed an approved task, track, dependency or blocker')
        if row[1]=='done' and after[task][1]!='done':raise Refused('Previously completed task progress cannot regress')
        current=next_task(state|{'status':'running'})
        permitted=set(state['done'])|({current['id']} if current else set())
        if after[task][1]=='done' and row[1]!='done' and task not in permitted:raise Refused('Only the selected task may have provisional completion marks')
    # Roadmap prose may change; its initiative dependencies and design ownership remain contracts.
    from .design_parse import roadmap
    where=bound['layout']
    from .plans import initiatives
    actual=[list(r) for r in initiatives(root,{k:Path(v) if k!='location' else v for k,v in where.items()})]
    if actual!=bound.get('initiatives',actual):raise Refused('Delivery cannot change approved roadmap initiative ownership or dependencies')


def _subject(root,state):
    _structure(root,state)
    artifact={}
    if state.get('delivery',{}).get('layout',{}).get('location')=='private':
        artifact=_files([state['delivery']['path']])
    if state.get('plans',{}).get('location')=='private':
        from .plans import private_inputs
        where={k:Path(v) if k!='location' else v for k,v in state['plans'].items()}
        artifact=_files(private_inputs(where))
    if state.get('workflow')=='review' and state.get('standalone_artifact'):
        from .review import artifact_content
        exact=artifact_content(state['standalone_artifact'])
        _unchanged(exact['files']);artifact=exact['files']
    return {'head':git(root,'rev-parse','HEAD'),'tree':tree(root),'git_tree':candidate_tree(root),'artifacts':artifact}



def _command(source):
    """Reuse host-normalized invocation syntax; never interpret free prose as commands."""
    prompt=source.get('prompt','').strip()
    linked=re.fullmatch(r'\[(\$(?:o-harness:)?oh-[a-z]+)\]\([^\r\n]*SKILL\.md\)(.*)',prompt,re.S)
    if linked:prompt=linked[1]+linked[2]
    return authority.typed_command('/'+prompt[1:] if prompt.startswith('$') else prompt)


def _initiative(state):
    if state.get('design'):return state['design']
    original=_command(state.get('entry_human',state.get('human',{})))
    if original and original[0]=='oh-design' and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',original[1]):return original[1]
    return None


def _finished(state):
    feedback=state['workflow']=='review' and state.get('attempts') and state['attempts'][-1].get('outcome') in ('clean','blocking','needs_resolution','review_incomplete','unfinished')
    return bool(state.get('published') or (state['status']=='completed' and (feedback or state.get('plans',{}).get('location')=='private')))


def _pending_attempt(state,attempt):
    """Describe saved binding facts without inferring whether native work ran or ended."""
    child=attempt.get('native_child') or {}
    original=authority._attempt_parent(state,attempt)
    parent={'host':original['host'],**{k:original['human'][k] for k in ('session','transcript_path') if k in original['human']}}
    return {'id':attempt['id'],'role':attempt['role'],'native_child':child.get('child_session'),
            'binding_status':'bound' if child else 'unbound','execution_status':'not_checked',
            'parent':parent,'request':str(Path(attempt['evidence'])/'request.json') if attempt.get('evidence') else None,
            'next':(('Inspect this child’s latest native outcome; a saved binding does not mean it is still running. '
                    if child else 'No child binding is saved; this does not mean it was never launched. Inspect the original parent’s launch and result records. ')
                   +'The already-authorized current coordinator retains this same attempt and continues its remaining phase without another Continue question. '
                    'A new owner or workflow invocation uses the existing saved-work recovery decision before transferring ownership or replacing the attempt.')}



def _continuation(state):
    """Compact evidence hints, not a second execution/admission state machine."""
    pending=[a for a in state['attempts'] if not a.get('finished')]
    task=display_task(state)
    history=[a for a in state['attempts'] if a['task']==task['id'] and not a.get('superseded')]
    phase=('native_attempt' if pending else 'task_correction' if state.get('correction') else 'task_review' if state.get('extra_review') else 'finished' if _finished(state)
           else 'publication' if state.get('publication') or state['status']=='pr'
           else 'completion' if len(state['done'])==len(state['tasks'])
           else 'task_window' if task['id'] not in state['granted']
           else history[-1]['role']+'_result' if history else 'authoring' if state['workflow'] in ('design','propose') else 'review' if state['workflow']=='review'
           else 'implementation' if state.get('assessments',{}).get(task['id']) else 'assessment')
    decision=None
    if not pending and history and history[-1].get('outcome')=='abandoned':phase=history[-1]['role']
    if not pending:
        if phase=='task_window':decision='task_window'
        elif phase=='completion' and state.get('plans',{}).get('location')!='private':decision='publication'
        elif history:
            latest=history[-1]
            if latest['role']=='analysis' and state['workflow']=='propose' and not state.get('proposal_answers'):decision='proposal_approval'
            elif latest['role']=='review':
                resolution=state.get('resolutions',{}).get(latest['id'],{})
                if latest.get('outcome')=='needs_resolution' and any(f['severity']=='concern' and not resolution.get('concerns_accepted') for f in latest.get('findings',[])):decision='review_findings'
                elif state['workflow']=='design' and latest.get('outcome') in ('clean','needs_resolution') and state.get('plans',{}).get('location')=='private' and state.get('private_native_approval',{}).get('attempt')!=latest['id']:decision='private_approval'
    from .scope import followups
    result={'phase':phase,'pending_decision':decision,'pending_attempts':[_pending_attempt(state,a) for a in pending],
            'followup_count':sum(len(item['findings']) for item in followups(state)),
            'latest_result':({k:history[-1].get(k) for k in ('id','role','outcome','evidence')} if history else None)}
    if state['status'] in ('checkpoint','completed') and decision in ('task_window','publication'):
        kind='continue' if decision=='task_window' else 'publish'
        result['next_action']={'tool':'decision_request','arguments':{'kind':kind,'run':state['id']},
            'instruction':'Prepare and present the returned final or task-batch checkpoint before ending. '
                          'This prepares choices; it does not push or publish. Local-only work still needs '
                          'the available handoff choices. Bind the actual answer through decision.'}
    return result


def _saved_subject(state):
    return (state.get('standalone_subject',{}).get('description') or _initiative(state) or state['tasks'][0]['title'])[:240]


def saved_work(root):
    result=[];runs=_saved_runs(root)
    for journal,state in runs:
        task=display_task(state)
        summary={k:state.get(k) for k in ('workflow','status','branch','design','track','published')}
        summary.update(run=state['id'],subject=_saved_subject(state),
                       execution=_execution(root,state),
                       recorded_remaining=[t['id'] for t in state['tasks'] if t['id'] not in state['done']],
                       remaining_work='Reconcile the saved scope/results with the current checkout and approved documents; recorded tasks are not proof that work remains.',
                       task=task['id'],scope=str(journal.path/'scope'/'scope.json') if state.get('scope_id') else None,
                       journal=str(journal.path),report=str(journal.path/'report.md') if (journal.path/'report.md').is_file() else None,
                       reviews_used=sum(a['role']=='review' and a['task']==task['id'] for a in state['attempts']),reviews_allowed=review_limit(state,task['id']),
                       granted_remaining=[t['id'] for t in state['tasks'] if t['id'] in state['granted'] and t['id'] not in state['done']],
                       **_continuation(state))
        summary['resumable']=not _finished(state)
        result.append(summary)
    output={'saved_work':result,'next':'For matching unfinished work, read workflows/recovery.md and workflows/decisions.md, then prepare decision-request resume --run ID before asking. Show that returned question once; do not ask a preliminary Resume question. A matching command alone does not confirm continuation.'}
    from .storage import encode
    budget=min((state['config']['context']['result_chars'] for _,state in runs),default=1000)
    if len(encode(output))>budget:
        output['saved_work']=[{k:item[k] for k in ('run','workflow','status','execution','subject','branch','journal','phase','pending_decision','resumable')} for item in result]
    if len(encode(output))>budget:
        output['saved_work']=[{k:item[k] for k in ('run','workflow','status','execution','journal','resumable')} for item in result]
        output.pop('next',None)
    if len(encode(output))>budget:
        output['saved_work']=[{k:item[k] for k in ('run','workflow','status','execution','resumable')} for item in result]
    return output


def _resume_offer(root,state):
    kind='recover' if state['workflow']=='deliver' else 'resume'
    return select(root,state['id'])|{'resume_required':True,'next':'Read workflows/recovery.md and workflows/decisions.md, then prepare decision-request '+kind+' --run '+state['id']+' before asking. Show its returned question once and preserve that answer through recovery; bind the selected action.'}


def _same_review_subject(selected,state):
    prior=state.get('standalone_subject',{})
    return all(selected[k]==prior.get(k) for k in
               ('kind','head','branch','tree','base','revision','git_tree','paths','feedback_only'))


def _matching_entry(root,source,workflow,design=None,track='',selected=None):
    # Exact selectors can be checked mechanically. Free-text identity remains the
    # native coordinator's judgment after inspecting saved scope, through resume.
    matches=[]
    request=_command(source)
    if not request or request[0]!='oh-'+workflow or not request[1]:return None
    for _,state in _saved_runs(root):
        if state['workflow']!=workflow:continue
        if state.get('published') and workflow!='design':continue
        if workflow=='review' and _finished(state):continue
        if workflow=='design' and design and design==_initiative(state):matches.append(state)
        elif workflow=='deliver' and design==state.get('design') and design and (not track or track==(state.get('track') or '')):matches.append(state)
        elif workflow=='review' and selected and _same_review_subject(selected,state):matches.append(state)
    if len(matches)==1:
        state=matches[0]
        key=_human_key(source,state)
        if key==state.get('source'):return _entry_retry(root,state,source)
        if state.get('published') or (state['status']=='completed' and state.get('plans',{}).get('location')=='private'):return select(root,state['id'])
        return _resume_offer(root,state)
    if len(matches)>1:raise Refused('More than one saved run matches; inspect status --saved and select the intended run with resume --run')


def _resume_binding(root,state,*,write=False):
    _switchable(root,[other for _,other in _saved_runs(root) if other['id']!=state['id']])
    if git(root,'branch','--show-current')!=state['branch']:
        from .workspace import observation
        observation(root,state['branch'])
    if not write:return
    _switchable(root,[state])
    from .workspace import switch
    switch(root,state['branch'])
    review=checkout_file(root,'oh-active-review.json')
    if state['workflow']=='review':
        atomic_json(review,{'project':state['project'],'run':state['id'],'checkout':state['checkout'],'selected':True})
    else:
        atomic_json(checkout_file(root,'oh-active-run.json'),{'project':state['project'],'run':state['id'],'checkout':state['checkout']})
        if review.exists():atomic_json(review,read_json(review)|{'selected':False})


def switch_workspace(root,branch,human,base=None,after=None):
    """Lossless Git preparation under the current native request; grants no task scope."""
    from .entry import enroll,request_source
    if blocked:=enroll(root):raise Refused(blocked['onboarding'])
    source=request_source(root,human,after)
    with _locked(root):
        saved=_saved_runs(root)
        _entry_order(root,source,saved)
        _switchable(root,[state for _,state in saved])
        source=request_source(root,human,after)
        _entry_order(root,source,saved)
        owner=source.get('prerequisite_human',source)
        authority.coordinator(root,{'host':owner['host'],'human':owner})
        from .workspace import switch
        return switch(root,branch,base)|{'authority':'Git preparation only; existing scopes, findings and allowances are unchanged.'}


def prepare_scope(root, manifest=None, doc=None, track='', workflow='deliver', human=None, keep_checkout=False, after=None):
    """Snapshot an explicit scope. Preparing delivery is never its approval."""
    from .entry import enroll
    if blocked:=enroll(root):raise Refused(blocked['onboarding'])
    if workflow not in ('deliver','design','propose'):raise Refused('Unknown workflow')
    from .entry import request_source
    source=request_source(root,human,after) if human is not None else None
    if after is not None and source is None:raise Refused('Supply the retained initiating request locator with its prerequisite identity')
    request=_command(source) if source else None
    if request and request[0]!='oh-'+workflow:
        raise Refused('This native request selects a different workflow; it grants no authority here')
    if source and workflow=='deliver' and doc is not None:
        from .delivery import requested
        requested(source,doc,track,request)
    initiative=(manifest or {}).get('design') if workflow=='design' else doc
    if workflow=='design' and request and request[0]=='oh-design':
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',request[1]):raise Refused('Select one roadmap initiative before preparing Design')
        if initiative and initiative!=request[1]:raise Refused('The native request selects a different initiative')
        initiative=request[1];manifest=dict(manifest or {},design=initiative)
    if source and (existing:=_matching_entry(root,source,workflow,initiative,track)) is not None:return existing
    if doc is not None and manifest is not None:
        raise Refused('Choose approved design selection or a task manifest')
    with _locked(root):
        if source:
            saved=_saved_runs(root)
            for journal,prior in saved:
                if (prior['workflow']!=workflow or prior.get('design')!=initiative or
                        (track and (prior.get('track') or '')!=track) or prior.get('entry_prerequisite')!=after or
                        _human_key(source,prior)!=prior.get('source')):
                    continue
                scope=prior.get('scope_snapshot')
                if not scope:
                    continue
                if doc is None:
                    if workflow=='deliver' or not isinstance(manifest,dict):
                        continue  # A quick-fix preview is not an accepted entry.
                    if (validate_tasks(manifest.get('tasks'))!=scope['tasks'] or
                            any(manifest.get(k)!=scope.get(k) for k in ('repair_source','pr_target'))):
                        continue
                result=_finish_entry(root,journal,prior,source)
                return result|{'scope_id':prior['scope_id'],'approved':True}
            _entry_order(root,source,saved)
        if doc is not None:
            # Serialize quiescence and Git preparation with admissions/selection.
            new_branch=False
            if not keep_checkout:
                _switchable(root,[s for _,s in _saved_runs(root)])
                from .branches import delivery_branch,to_delivery,refresh,contained,fetched,trunk,from_main,holder
                if not changes(root):
                    main=trunk(root)
                    base=fetched(root,main) if main else None
                    current=git(root,'branch','--show-current')
                    if base and (current==main or contained(root,base,'HEAD')):
                        if holder(root,main):git(root,'switch','--quiet','--detach',base)
                        else:from_main(root,base=base)
                        new_branch=True
                    elif base:refresh(root,current,base)
            from .delivery import selection
            manifest,extra=selection(root,doc,track)
            track=manifest['track']
            if new_branch:
                name=delivery_branch(doc,track)
                if base:=to_delivery(root,name):refresh(root,name,base)
        else:extra={}
        if not isinstance(manifest,dict):raise Refused('Supply a task manifest or approved design number')
        tasks=validate_tasks(manifest.get('tasks'));config=snapshot(root)
        if workflow=='deliver' and not project_checks(root):raise Refused('Register this project’s existing verification checks before delivery')
        if workflow=='deliver' and doc is None and not keep_checkout and not _saved_runs(root):
            from .branches import main_ref,trunk,contained,from_main,execution_branch
            current=git(root,'branch','--show-current');base=main_ref(root,config)
            if not changes(root) and base and (current==trunk(root,config) or
                    git(root,'rev-parse','HEAD')!=git(root,'rev-parse',base) and contained(root,base,'HEAD')):
                from_main(root)
                git(root,'switch','--quiet','-c',execution_branch(root,tasks[0]['title'],identifier()))
    documents={};bound=extra.get('delivery')
    if bound:
        for name in bound['inputs']:
            documents[name]=Path(name).read_text()
        from .plans import initiatives
        where={k:Path(v) if k!='location' else v for k,v in bound['layout'].items()}
        bound['initiatives']=[list(r) for r in initiatives(root,where)]
    value={'schema':2,'checkout':checkout_id(root),'project':project(root)['id'],'created_at':now(),
           'base':git(root,'rev-parse','HEAD'),'branch':git(root,'branch','--show-current'),
           'starting_tree':tree(root),'starting_edits':sorted(changes(root)),
           'workflow':workflow,'tasks':tasks,'design':doc or manifest.get('design'),'track':track,
           'documents':documents,'project_checks':project_checks(root),**config,**extra,
           **{k:manifest[k] for k in ('repair_source','pr_target') if k in manifest}}
    if workflow=='deliver' and doc is None:value['preview_format']=1
    value['retained_work']=[{'run':s['id'],'workflow':s['workflow'],'subject':_saved_subject(s),
                             'branch':s['branch'],'journal':str(j.path),'findings':str(j.path/'index.md')}
                            for j,s in _saved_runs(root)]
    if workflow!='deliver':
        from .plans import layout,layout_snapshot
        value['plans']=layout_snapshot(layout(root))
        from .plans import private_inputs
        source_where={k:Path(v) if k!='location' else v for k,v in value['plans'].items()}
        if value['plans']['location']=='private':value['documents']={p:Path(p).read_text() for p in private_inputs(source_where)}
    else:
        from .branches import main_ref
        from .delivery import unreviewed
        base=main_ref(root,value['config'])
        fork=git(root,'merge-base',base,value['base']) if base else value['base']
        covers=unreviewed(root,fork,base) if base else []
        requested=manifest.get('covers',[])
        if not isinstance(requested,list) or any(c not in covers for c in requested):raise Refused('Included original commits must belong to this branch’s unreviewed work')
        if covers:
            value.update(covers=covers,original_work={'review_base':fork,'head':value['base'],'covers':covers})
    key=digest(value);folder=_home(root)/'scopes'/key
    _immutable(folder/'scope.json',value)
    from .receipts import save
    save(folder/'scope.md',_scope_preview(value),immutable=True)
    result={'scope_id':key,'preview':str(folder/'scope.md'),'tasks':[{k:t[k] for k in ('id','title')} for t in tasks],'config':value['config'],'approved':False}
    from .branches import trunk
    result['execution_branch_required']=committed(value) and value['branch']==trunk(root,value['config'])
    if result['execution_branch_required']:
        result['next']='This is a preview on the base branch. Before admission, use default safe branch selection or create an execution branch and reprepare there; --keep-checkout preserves the base branch too.'
    if doc is not None:
        result['next']=result.get('next','')+' A real explicit request for this approved design, passed as human, selects its batch directly; do not ask for another quick-fix scope approval after that request.'
    if human is not None and (workflow!='deliver' or doc is not None):
        return _start(root,key,source)|{'scope_id':key,'approved':True}
    if workflow=='deliver':
        from .decisions import scope_request
        result['approval']=scope_request(root,value)
    return result


def _scope_preview(value):
    from .prepared import limits
    sections=[f"# {value['workflow'].title()} scope",limits(len(value['tasks']),value['config'])]
    if value.get('preview_format')==1:
        sections.append(f"Branch: `{value['branch']}`\nScope: `{digest(value)}`")
    sections.extend(f"## {t['id']}. {t['title']}\n\n{t['instructions']}" for t in value['tasks'])
    preview='\n\n'.join(sections)+'\n'
    if value.get('starting_edits'):
        preview+='\n## Included starting edits\n\n'+', '.join('`'+name+'`' for name in value['starting_edits'])+'\n\nContents fingerprint: `'+value['starting_tree']+'`.\n'
    if target:=value.get('pr_target'):
        preview+=f"\n## Included original PR work\n\n{target['url']}\n\nReview the original range `{target['review_base']}..{target['head']}` together with the repair candidate.\n"
        if target.get('covers'):preview+='\nIncluded original commits: '+', '.join('`'+c+'`' for c in target['covers'])+'.\n'
    elif original:=value.get('original_work'):
        preview+=f"\n## Included original branch work\n\nReview `{original['review_base']}..{original['head']}` together with the task candidate.\n\nIncluded original commits: "+', '.join('`'+c+'`' for c in original['covers'])+'.\n'
    return preview


def _verify_scope_plan(scope, source, *, replay=False):
    if source.get('via')!='plan':return
    preview=_scope_preview(scope)
    accepted=source.get('accepted_plan','').replace('\r\n','\n')
    if source['host']=='codex':
        if scope.get('preview_format')!=1 and not replay:
            raise Refused('Prepare the scope with its native plan identity before using Codex Plan approval.')
        # The native Plan item can add a framing newline.
        accepted,preview=accepted.strip('\n'),preview.strip('\n')
    if accepted!=preview:
        raise Refused('The person accepted changed scope. Preserve the accepted plan and prepare its actual tasks; the old task projection is not approved.')


def approve_scope(root, scope_id, locator, after=None):
    scope=_scope(root,scope_id)
    locator=_presented(root,locator)
    subject=None if locator.get('decision') else _home(root)/'scopes'/scope_id/'scope.md'
    from .workflow import active_file
    if active_file(root).exists():
        _,current=load_run(root)
        if current.get('scope_id')==scope_id:
            original,locator=authority.scope_human(root,locator,since=scope['created_at'],subject=subject,latest=False)
            if _human_key(original,current)==current.get('source'):
                if current.get('accepted_scope') and original.get('via')!='plan':
                    raise Refused('Retry the original native plan acceptance with its saved preview')
                _verify_scope_plan(scope,original,replay=True)
                return _entry_retry(root,current,original)
    if after is None:source,locator=authority.scope_human(root,locator,since=scope['created_at'],subject=subject)
    else:
        from .entry import request_source
        carried=request_source(root,locator,after)
        source,locator=authority.scope_human(root,locator,since=scope['created_at'],subject=subject,latest=False)
        if source['record_hashes']!=carried['record_hashes']:
            raise Refused('The retained approval does not identify this original scope acceptance')
        source=source|{k:carried[k] for k in ('prerequisite_human','prerequisite')}
    _verify_scope_plan(scope,source)
    if locator.get('decision') and source.get('via')!='plan':
        from .decisions import verify_scope
        verify_scope(root,scope,locator,source)
        source=source|{'decision':locator['decision']}
    elif source.get('via')!='plan' and authority.shown_offer_reference(source):
        raise Refused('Use the original prepared scope decision identity with this answer.')
    elif source.get('via')!='plan' and not _affirmed(source['prompt'],'approve',source.get('question','')):
        raise Refused('The native human reply did not approve this scope; no work was granted')
    if after is None:authority.coordinator(root,{'human':source,'host':source['host']},locator)
    else:authority.coordinator(root,{'human':source['prerequisite_human'],'host':source['host']})
    return _start(root,scope_id,source,approved_preview=True)


def _start(root,key,source,*,approved_preview=False):
    scope=_scope(root,key)
    with _locked(root):
        owner=source.get('prerequisite_human',source)
        saved=_saved_runs(root)
        from .workflow import active_file
        for journal,prior in saved:
            if prior.get('scope_id')==key and _human_key(source,prior)==prior.get('source'):
                return _finish_entry(root,journal,prior,source)
            if prior.get('scope_id')==key and read_json(active_file(root)).get('run')==prior['id']:return select(root,prior['id'])
        _entry_order(root,source,saved)
        _switchable(root,[prior for _,prior in saved])
        if (saved and committed(scope) and not approved_preview and
                (scope['starting_edits'] or scope.get('covers')) and
                any(prior['status'] not in ('stopped','completed','pr') for _,prior in saved)):
            raise Refused('The selected checkout carries local edits or unreviewed commits alongside saved work. '
                          'Inspect ownership and the retained findings; save unrelated work with workspace in this folder or explicitly include it '
                          'in an approved scope preview before selecting different work. Stop alone does not authorize discarding it.')
        for journal,prior in saved:
            unused=(prior['status']=='prepared_checkpoint' and not prior['granted'] and not prior['attempts'] and not prior.get('activation'))
            if unused:journal.append('run.status',{'status':'stopped','reason':'Superseded unused preparation; no execution authority was granted'})
        if (git(root,'rev-parse','HEAD'),git(root,'branch','--show-current'))!=(scope['base'],scope['branch']):
            raise Refused('Prepared scope belongs to a different base/branch; prepare against the intended current work')
        if scope.get('starting_tree')!=tree(root):
            raise Refused('The included starting contents changed after scope preparation. Preserve the edits and prepare the same tasks again to show their current contents before approval.')
        from .branches import trunk
        if committed(scope) and scope['branch']==trunk(root,scope['config']):raise Refused('Create an execution branch from the selected base with native Git tools, then prepare scope on that branch')
        source_key=_human_key(source)
        p=project(root);run=identifier()
        data={'id':run,'project':p['id'],'name':p['name'],'work_kind':p['kind'],'checkout':checkout_id(root),
              'host':owner['host'],'human':owner,'source':source_key,'native_version':2,
              'scope_id':key,'scope_snapshot':scope,'workflow':scope['workflow'],'tasks':scope['tasks'],
              'design':scope.get('design'),'track':scope.get('track'),'base':scope['base'],'branch':scope['branch'],
              'checks':[],
              **{k:scope[k] for k in ('config','config_hash','harness_version','project_checks')},
              **{k:scope[k] for k in ('delivery','plans') if k in scope}}
        if source.get('prerequisite'):
            data.update(entry_request={k:v for k,v in source.items() if k not in ('prerequisite_human','prerequisite')},
                        entry_prerequisite=source['prerequisite'])
        if source.get('accepted_plan') is not None:data['accepted_scope']=source['accepted_plan']
        data.update({k:scope[k] for k in ('repair_source','pr_target','covers','original_work','retained_work') if k in scope})
        journal=Journal(p['id'],run);journal.append('run.started',data)
        best_effort('run.started',p['id'],run,name=p['name'],work_kind=p['kind'],host=source['host'],version=data['harness_version'],config_hash=data['config_hash'])
        _immutable(journal.path/'scope'/'scope.json',scope)
        _immutable(journal.path/'scope'/'approval.json',source)
        if data.get('accepted_scope'):
            from .receipts import save
            save(journal.path/'scope'/'accepted.md',data['accepted_scope'],immutable=True)
        atomic_json(checkout_file(root,'oh-active-run.json'),{'project':p['id'],'run':run,'checkout':checkout_id(root)})
        return _finish_entry(root,journal,reduce(journal.records()),source)


def select(root,run=None):
    journal,state=load_run(root,run);task=next_task(state)
    current=task or next((t for t in reversed(state['tasks']) if t['id'] in state['done']),state['tasks'][-1])
    history=[a for a in state['attempts'] if a['task']==current['id']]
    checked=state.get('verification',{}).get(current['id'])
    attempts=[]
    for attempt in history[-2:]:
        item={k:attempt.get(k) for k in ('id','task','role','profile','outcome','finished','superseded','evidence','model_fallback')}
        item['summary']=str(attempt.get('summary',''))[:800]
        if attempt.get('native_child'):item['native_child']={'child_session':attempt['native_child']['child_session']}
        attempts.append(item)
    result={k:state.get(k) for k in ('id','status','workflow','design','track','branch','scope_id','published')}
    result.update(execution=_execution(root,state),
                  recorded_remaining=[t['id'] for t in state['tasks'] if t['id'] not in state['done']],
                  remaining_work='Reconcile saved scope/results with current Git and approved documents; recorded tasks do not establish current unfinished work.')
    if state.get('retained_work'):result['retained_work']=state['retained_work']
    from .scope import followups
    pending_followups=followups(state)
    result.update(followups={'count':sum(len(i['findings']) for i in pending_followups),'index':str(journal.path/'index.md')},continuation=_continuation(state),run=state['id'],task={k:task[k] for k in ('id','title')} if task else None,
                  granted=state['granted'],done=state['done'],attempts=attempts,attempt_count=len(state['attempts']),
                  scope=str(journal.path/'scope'/'scope.json') if state.get('native_version') and state.get('scope_id') else None,
                  report=str(journal.path/'report.md') if (journal.path/'report.md').is_file() else None,journal=str(journal.path),
                  supplementary={'count':len(state.get('supplementary',[])),'path':str(journal.path/'evidence'/'index.json') if (journal.path/'evidence'/'index.json').is_file() else None})
    if checked:
        result['verification']={k:checked.get(k) for k in ('task','head','tree','git_tree','at')}
        result['verification']['passed']=not any(check_failed(c) for c in checked['checks'])
        result['verification']['checks']=[{k:c[k] for k in ('name','returncode','cancellation','unavailable','logs') if k in c} for c in checked['checks']]
    reviews=[a for a in history if a['role']=='review' and (state['workflow']=='review' or a.get('purpose','workflow')=='workflow')]
    result.update(reviews_used=len(reviews),reviews_allowed=review_limit(state,current['id']))
    assessment=state.get('assessments',{}).get(current['id'])
    if assessment:result['initial_profile']=state['config']['models'][state['host']][assessment['difficulty']]
    if state.get('candidate'):result['current_candidate']={k:state['candidate'][k] for k in ('task','head','tree','git_tree')}
    if state.get('publication'):result['publication']=state['publication']
    from .storage import encode
    if len(encode(result))>state['config']['context']['result_chars']:
        result['attempts']=[{k:v for k,v in a.items() if k!='summary'} for a in attempts]
        result.pop('verification',None)
        if result.get('task'):result['task']['title']=result['task']['title'][:150]
    if len(encode(result))>state['config']['context']['result_chars']:
        result.pop('done',None);result.pop('granted',None)
        result.update(done_count=len(state['done']),granted_count=len(state['granted']))
        if result.get('publication'):
            result['publication']={k:state['publication'].get(k) for k in ('head','branch','base_branch','destination','remote')}
    if len(encode(result))>state['config']['context']['result_chars']:
        result['continuation']={k:result['continuation'][k] for k in ('phase','pending_decision')}
        result={k:result[k] for k in ('run','status','execution','task','report','attempt_count','reviews_used','reviews_allowed','done_count','granted_count','followups','continuation') if k in result}
    if len(encode(result))>state['config']['context']['result_chars']:result={'run':state['id'],'status':state['status'],'execution':result['execution'],'attempt_count':len(state['attempts']),'continuation':result['continuation']}
    return result


def _repeated_family(state,task):
    from .handoff import family_identity
    reviews=[a for a in state['attempts'] if a['task']==task and a['role']=='review'
             and a.get('finished') and a.get('outcome')=='blocking']
    seen=set()
    for attempt in reviews:
        families={family_identity(f) for f in attempt.get('findings',[]) if f['severity']=='blocking'}
        if seen&families:return True
        seen|=families
    return False


def admit(root,role):
    if role not in ('assessment','implementation','analysis','review'):raise Refused('Unknown native agent role')
    with _locked(root):
        journal,state=load_run(root);_owner(root,state);_idle(root)
        if state['status']!='running':raise Refused('This scope is not running; retain existing work and resolve its actual state')
        if _active(state):raise Refused('Retain the current native attempt before admitting another')
        _switchable(root,[s for _,s in _saved_runs(root)])
        journal,state=load_run(root)
        task=next_task(state)
        if not task:raise Refused('No remaining task is covered by the existing task grant')
        if state.get('workflow')=='review' and role!='review':raise Refused('Standalone review grants no implementation authority')
        assessment=state.get('assessments',{}).get(task['id'])
        if role=='assessment' and state['workflow']!='deliver':raise Refused('Native assessment is for delivery tasks only')
        if role=='assessment' and assessment:raise Refused('This task already has its retained assessment; do not reassess repairs')
        if role=='implementation' and not assessment:raise Refused('Retain one native assessment before implementation')
        if role=='analysis' and state['workflow'] not in ('propose','design'):raise Refused('Analysis is for the admitted planning artifact')
        if state.get('native_authenticated')!={'host':state['host'],'session':state['human']['session']}:
            from .hosts import authentication
            authentication(state['host'],root)
            journal.append('native.authenticated',{'host':state['host'],'session':state['human']['session']})
        subject=_subject(root,state)
        if role=='review' and state['workflow']!='review':
            authors=[a for a in state['attempts'] if a['task']==task['id'] and a['role'] in ('implementation','analysis') and a.get('finished') and not a.get('superseded')]
            if not state.get('extra_review') and (not authors or authors[-1]['outcome'] not in ('reported','implemented')):
                raise Refused('Finish the approved task before requesting its independent review')
            checked=state.get('verification',{}).get(task['id'])
            if not provenance(journal.records(),checked,subject):
                raise Refused('Run final configured checks on this candidate before admitting review')
        if role=='review':
            used=sum(a['role']=='review' and a['task']==task['id'] for a in state['attempts'])
            if used>=review_limit(state,task['id']):raise Refused('This task’s review allowance is spent; only a native human grant renews it')
        level='review' if role=='review' else 'complex' if _repeated_family(state,task['id']) else assessment['difficulty'] if assessment else 'standard'
        requested=state['config']['models'][state['host']][level]
        from .capabilities import select_profile
        profile,fallback=select_profile(state['host'],requested,root)
        attempt_id=identifier();directory=journal.path/'attempts'/attempt_id
        admission={'id':attempt_id,'task':task['id'],'role':role,'profile':profile,'purpose':'standalone' if state['workflow']=='review' else 'workflow',
                   'evidence':str(directory),'config_hash':state['config_hash'],'root':str(Path(root).resolve()),'run':state['id'],
                   'parent':{k:state['human'][k] for k in ('host','session','transcript_path') if k in state['human']},**subject}
        if state['workflow']=='review':
            selected=state['standalone_subject']
            admission['standalone_subject']={k:selected[k] for k in ('kind','base','revision','git_tree','description') if k in selected}
            admission['checkout_guard']=subject
        if fallback:admission['model_fallback']=fallback
        if role=='review' and state['workflow']!='review' and committed(state):
            # Snapshot branch history at review admission, not only at intake:
            # the developer may have committed a checkpoint since then.
            from .branches import main_ref
            from .delivery import unreviewed
            base=main_ref(root,state['config'])
            if base:
                fork=git(root,'merge-base','HEAD',base)
                covers=unreviewed(root,fork,base)
                admission['included_original_work']={'review_base':fork,'head':subject['head'],'covers':covers}
                if url:=state.get('pr_target',{}).get('url'):admission['included_original_work']['url']=url
        # No native launch is authorized until every required artifact exists. Save the
        # charge and admission together, so construction failures cannot orphan a child.
        admission['started_at']=now()
        from .handoff import prepare
        packet,index=prepare(state,task,role,directory,admission)
        admission['task_context']=packet
        snapshots={}
        for name,expected in (subject['artifacts'].items() if state['workflow']!='review' else []):
            target=directory/'artifacts'/hashlib.sha256(name.encode()).hexdigest()
            from .receipts import save
            save(target,Path(name).read_text(),immutable=True)
            snapshots[name]={'path':str(target),'sha256':expected}
        if snapshots:admission['artifact_snapshots']=snapshots
        _immutable(directory/'request.json',admission)
        from .receipts import request
        request(directory,admission)
        events=[]
        if task['id'] not in state['task_started']:events.append({'kind':'task.started','data':{'task':task['id']}})
        events.extend([{'kind':'attempt.started','data':admission},
                       {'kind':'attempt.admitted','data':{'id':attempt_id,'hash':digest(admission)}}])
        journal.append('transition',{'events':events})
        from .cancellation import register_attempt
        register_attempt(root,state,admission)
        if task['id'] not in state['task_started']:
            best_effort('task.started',state['project'],state['id'],task['id'],title=task['title'],difficulty=(assessment or {}).get('difficulty'),rubric=2)
        best_effort('attempt.started',state['project'],state['id'],task['id'],attempt_id,role=role,phase=role,host=state['host'],**profile)
        from .cancellation import command_prefix, shell_line
        bootstrap=shell_line(command_prefix(root,attempt_id)[:-3]+['admission',str(directory)],
                             windows=os.name=='nt' and state['host']=='codex')
        return {k:admission[k] for k in ('id','task','role','profile','head','tree','git_tree','task_context','model_fallback','standalone_subject') if k in admission}|{'request':str(directory/'request.json'),'native_task_name':'oh_'+attempt_id.replace('-',''),'fresh_context':True,'fork_turns':'none','admission_command':bootstrap}


def bind(root,attempt_id,locator):
    with _locked(root):
        journal,state=load_run(root);_owner(root,state);attempt=_attempt(state,attempt_id)
        return _bind(root,journal,state,attempt,locator)


def _bind(root,journal,state,attempt,locator):
    """One checked binding path for coordinator, native hooks and child recovery."""
    if attempt.get('finished'):raise Refused('A completed attempt cannot be reused')
    value=authority.native_child(root,state,attempt,locator)
    for other in state['attempts']:
        if other['id']!=attempt['id'] and other.get('native_child',{}).get('child_session')==value['child_session']:
            raise Refused('Every attempt needs a fresh native child')
    if attempt.get('native_child'):
        original=attempt['native_child']
        # A running child appends new model records. Their hashes may change
        # without changing its already-verified identity, launch or profile.
        if {k:v for k,v in original.items() if k!='record_hashes'}!={k:v for k,v in value.items() if k!='record_hashes'}:
            raise Refused('The original child binding cannot be replaced')
        value=original
    else:
        journal.append('native.child.bound',{'attempt':attempt['id'],'child':value})
        attempt['native_child']=value
        best_effort('attempt.native',state['project'],state['id'],attempt['task'],attempt['id'],child_session=value['child_session'],host=attempt.get('host',state['host']))
    from .cancellation import bind as bind_execution
    aliases=()
    if attempt.get('host',state['host'])=='claude' and value.get('tool_use_id'):
        parent=authority._attempt_parent(state,attempt)
        path=authority._path('claude',value['parent_session'],parent['human'].get('transcript_path'))
        aliases=authority.claude_aliases(value,list(authority._records(path)))
    bind_execution(root,attempt,value['child_session'],aliases=aliases)
    return value


def _report(text):
    for candidate in (text,text.strip().removeprefix('```json').removesuffix('```').strip()):
        try:
            value=json.loads(candidate)
            if isinstance(value,dict):return value
        except (ValueError,TypeError):pass
    assessment=re.search(r'(?im)^\s*difficulty\s*:\s*(simple|standard|complex)\b',text)
    result={'summary':text,'findings':[]}
    if assessment:result.update(difficulty=assessment[1].lower(),rationale=text)
    return result


def retain(root,attempt_id,locator):
    with _locked(root):
        return _retain_locked(root,attempt_id,locator)


def _retain_locked(root,attempt_id,locator,run=None):
    _idle(root)  # Verification holds its execution lock through the final evidence write.
    from .retention import SelectionChanged
    from time import sleep
    for delay in (0,.05,.1):
        if delay:sleep(delay)
        try:return _retain_once(root,attempt_id,locator,run)
        except SelectionChanged:
            if delay==.1:raise


def _retain_once(root,attempt_id,locator,run=None):
    journal,state=load_run(root,run);attempt=_attempt(state,attempt_id)
    if attempt.get('finished'):
        from .cancellation import finished
        finished(root,attempt_id)
        state=_repair_completion(journal,state,attempt)
        if attempt.get('revocation') and not attempt.get('late_report'):
            _retain_late_result(root,journal,state,attempt,locator)
        attempt=_reparse_review(root,journal,state,attempt)
        _render_attempt(journal,state,attempt)
        return attempt
    if not attempt.get('native_child'):
        try:_bind(root,journal,state,attempt,locator)
        except Refused:
            # Retain rejected launches through their original failure path;
            # a failed profile check must never prevent cancellation accounting.
            pass
    from .retention import capture
    stamp=authority.native_stamp(state,attempt)
    capture(root,journal,state,attempt)
    from .cancellation import interrupted, quiescent, reconcile_execution, unlaunched_stop, guarded
    stopped=interrupted(root,attempt=attempt_id)
    source=None
    cleanup_attempt=attempt
    if not attempt.get('native_child'):
        try:source=authority.native_result(root,state,attempt,locator)
        except authority.Saving:pass
        if source and source.get('status')=='binding_failed' and source.get('rejected_child'):
            # Attribution of a terminal rejected child permits execution reconciliation,
            # never successful binding, accepted work, or waived command cleanup.
            cleanup_attempt=attempt|{'native_child':source['rejected_child']}
    pending_lifecycle=reconcile_execution(root,cleanup_attempt)
    if pending_lifecycle:
        try:source=authority.native_result(root,state,attempt,locator)
        except authority.Saving:pass
        if source:reconcile_execution(root,cleanup_attempt,terminal=source)
    if not quiescent(root,attempt_id):
        raise authority.Saving('Native Stop cleanup is still pending. Retry with the same Resume answer after owned execution settles.'
                               if stopped else 'Owned execution is still running. Retain this same attempt after they finish; do not start another worker.')
    synthetic=False
    unlaunched=unlaunched_stop(root,attempt,stopped) if stopped and not attempt.get('native_child') else None
    try:
        if unlaunched:raise authority.Saving('Native Stop preceded launch')
        source=source or authority.native_result(root,state,attempt,locator)
    except authority.Saving:
        if not stopped or not (attempt.get('native_child') and guarded(root,attempt_id) or unlaunched):raise
        synthetic=True
        source={'status':'cancelled','text':'','origin':'oh-revocation',
                'record_hashes':[digest(stopped)],'interruption':stopped,
                'note':'Native tools are revoked and owned commands are settled. Native model termination is not asserted.'}
        if unlaunched:source.update(unlaunched_source=unlaunched,note='The saved native Stop preceded any launch for this admission.')
    return _finish_attempt(root,journal,state,attempt,source,stopped=stopped,revoked=synthetic,stamp=stamp)


def _dependent_completion(state,attempt,result,report,*,recovery=False):
    events=[]
    if result['outcome']=='assessed':
        events.append({'kind':'task.assessed','data':{'task':attempt['task'],'attempt':attempt['id'],
            'difficulty':report['difficulty'],'rationale':report.get('rationale','Native assessment')}})
    if state['workflow']=='review' and not recovery:
        events.append({'kind':'run.status','data':{'status':'completed'}})
    extra=state.get('extra_review')
    baseline=(extra or {}).get('baseline') or attempt
    repair=(attempt['role'] in ('implementation','analysis') and result['outcome']!='binding_failed'
            and any(result.get(k)!=baseline.get(k) for k in ('tree','git_tree','artifacts')))
    review=(attempt['role']=='review' and (result['outcome']=='blocking' or result['outcome']=='needs_resolution'
            and any(f['severity']=='concern' for f in result['findings'])))
    if extra and not state.get('correction') and not recovery and (repair or review):
        events.append({'kind':'correction.started','data':{'task':attempt['task'],'prior_commit':extra['prior_commit'],
            'return_status':extra['return_status'],'key':attempt['task']+'-correction-'+attempt['id']}})
    return events


def _finish_attempt(root,journal,state,attempt,source,*,stopped=None,revoked=False,stamp=None,recovery=False):
    """One evidence/commit boundary for native returns and explicit recovery abandonment."""
    from . import retention,cancellation
    if stamp is None:stamp=authority.native_stamp(state,attempt)
    if revoked and (not stopped or source.get('interruption')!=stopped or source.get('status') not in ('cancelled','abandoned')):
        raise Refused('Revocation requires its verified Stop or recovery decision and cannot supply a successful report.')
    retention.capture(root,journal,state,attempt)
    # Save the actual observation before a partial canonical write can interrupt
    # retention. It remains a diagnostic, not a completion or current verdict.
    if source.get('text'):retention.attach(journal,state,attempt,source)
    try:
        subject=_subject(root,state)
        packet=read_json(Path(attempt['evidence'])/'request.json')
        context=read_json(Path(attempt['evidence'])/'task-context.json')
        binding_ok=attempt.get('request_hash')==digest(packet) and digest(context)==packet['task_context']['hash']
        if context.get('details'):
            detail=context['details'];binding_ok=binding_ok and digest(read_json(Path(attempt['evidence'])/detail['path']))==detail['hash']
    except Refused:subject={};binding_ok=False
    with cancellation.settlement(root,attempt['id']) as control:
        if authority.native_stamp(state,attempt)!=stamp:
            raise retention.SelectionChanged('Native evidence changed during retention. Retry this same attempt; no new approval is needed.')
        record=control.get('attempts',{}).get(attempt['id'])
        if record:
            owner=control['owners'][record['owner']]
            if Path(owner['marker']).exists():stopped=read_json(owner['marker'])
            if record['owner']!=control.get('current') and not stopped:
                raise Refused('This attempt belongs to a superseded owner; retain it through its existing recovery decision.')
        pinned,report,projection,stale=retention.selected(root,journal,state,attempt,source,revoked=revoked)
        findings=projection['findings'];issues=projection.get('report_issues',[]);fragments=projection.get('review_fragments',[])
        malformed=bool(issues or fragments)
        outcome=pinned.get('status','failed')
        if outcome=='completed':
            outcome='reported'
            if attempt['role']=='review':
                outcome=('blocking' if any(f['severity']=='blocking' for f in findings) else
                         'review_incomplete' if malformed or report.get('verdict')=='incomplete' else
                         'needs_resolution' if findings else 'clean' if report.get('verdict')=='clean' else 'review_incomplete')
            elif malformed or report.get('status') in ('blocked','unfinished'):
                outcome=report.get('status') if report.get('status') in ('blocked','unfinished') else 'unfinished'
            elif attempt['role']=='assessment':outcome='assessed' if report.get('difficulty') in ('simple','standard','complex') else 'unfinished'
        if stale:outcome='unfinished'  # Excludes stale canonical evidence from legacy preamble reparse.
        if not binding_ok or attempt['role'] in ('review','assessment') and any(subject.get(k)!=attempt[k] for k in ('head','tree','git_tree','artifacts')):
            outcome='binding_failed'
        if stopped:outcome='abandoned' if recovery else 'cancelled'
        result={k:attempt[k] for k in ('id','task','role','profile','purpose','head','tree','git_tree','artifacts','evidence')}
        result.update(projection,outcome=outcome,
            summary=str(report.get('summary') or report.get('receipt') or pinned.get('text',''))[:state['config']['context']['result_chars']],
            duration_ms=pinned.get('duration_ms'),native_source=pinned.get('record_hashes',[]))
        if source.get('status')=='binding_failed':
            result['native_failure']={k:source.get(k) for k in ('native_id','tool_use_id','profile','admitted_profile','requested_profile','requested_context','binding_issues','terminal_status')}
        if attempt['role'] in ('implementation','analysis'):result.update(subject)
        if stopped:result['revocation']=stopped
        events=[{'kind':'attempt.finished','data':result}]+_dependent_completion(state,attempt,result,report,recovery=recovery)
        cancellation.close_settled(root,attempt['id'],control)
        journal.append('transition',{'events':events})
    updated=reduce(journal.records())
    _render_attempt(journal,updated,_attempt(updated,attempt['id']))
    best_effort('attempt.finished',state['project'],state['id'],attempt['task'],attempt['id'],outcome=outcome,
                duration_ms=source.get('duration_ms'),substantive=bool(source.get('text')))
    if state['workflow']=='review' and not recovery:
        best_effort('task.finished',state['project'],state['id'],attempt['task'],status='feedback',wall_ms=None)
        best_effort('run.status',state['project'],state['id'],status='completed')
    return result


def _repair_completion(journal,state,attempt):
    """Repair a legacy lone finish only where later history has not replaced its effect."""
    from .retention import completion_cut
    records=journal.records();cut=completion_cut(records,attempt['id'])
    if records[cut]['kind']=='transition':return state
    original=reduce(records[:cut+1]);pinned=_attempt(original,attempt['id'])
    report=read_json(Path(attempt['evidence'])/'result.json')
    expected=_dependent_completion(original,pinned,pinned,report,recovery=pinned.get('outcome')=='abandoned')
    later=[e for r in records[cut+1:] for e in (r['data']['events'] if r['kind']=='transition' else [r])]
    needed=[]
    for event in expected:
        kind=event['kind']
        if kind=='task.assessed':
            superseded=any(e['kind'] in ('task.assessed','attempt.started') and e['data'].get('task')==pinned['task'] for e in later)
        elif kind=='correction.started':
            superseded=any(e['kind'] in ('correction.started','correction.completed','review.checked','review.requested','attempt.started') for e in later)
        else:superseded=any(e['kind'] in ('run.status','decision','attempt.started') for e in later)
        if not superseded:needed.append(event)
    if needed:journal.append('transition',{'events':needed})
    return reduce(journal.records())


def _retain_late_result(root,journal,state,attempt,locator):
    """Preserve a late native report without reviving its cancelled attempt."""
    try:source=authority.native_result(root,state,attempt,locator)
    except authority.Saving:return
    directory=Path(attempt['evidence'])
    from . import retention
    retention.capture(root,journal,state,attempt)
    report,_=retention.parse(attempt,source)
    retention.attach(journal,state,attempt,source)
    source_ref=retention.save(directory/'diagnostics'/('late-native-'+digest(source)+'.json'),source)
    report_ref=retention.save(directory/'diagnostics'/('late-report-'+digest(report)+'.json'),report)
    data={'id':attempt['id'],'late_report':report_ref,'late_source':source_ref}
    if attempt.get('late_source')!=source_ref:journal.append('attempt.late-result',data)
    attempt.update(data)


def attach_evidence(root,attachment):
    with _locked(root):
        journal,state=load_run(root)
        if not isinstance(attachment,dict) or not isinstance(attachment.get('paths'),list):raise Refused('Evidence needs paths and an optional concise summary')
        value={'files':_files(attachment['paths']),'summary':str(attachment.get('summary','')),'at':now()}
        key=digest(value['files'])
        if any(digest(e['files'])==key for e in state.get('supplementary',[])):return value
        journal.append('evidence.attached',value)
        atomic_json(journal.path/'evidence'/'index.json',state.get('supplementary',[])+[value])
        return value


def _author(root,state):
    active=_active(state)
    if active:
        import os
        caller=os.environ.get('CODEX_THREAD_ID') or os.environ.get('OH_NATIVE_SESSION_ID')
        if len(active)==1 and active[0]['role'] in ('implementation','analysis') and not active[0].get('native_child'):
            journal,_=load_run(root)
            _bind(root,journal,state,active[0],{'child_session':caller} if caller else {})
        if len(active)!=1 or active[0]['role'] not in ('implementation','analysis') or not active[0].get('native_child') or caller and active[0]['native_child']['child_session']!=caller:
            raise Refused('Only the bound author may prepare or verify the active candidate')
        from .cancellation import guard
        guard(root,attempt=active[0]['id'])
        return active[0]
    _owner(root,state)


def candidate(root):
    with _locked(root):
        journal,state=load_run(root);_idle(root);author=_author(root,state)
        task=next_task(state|{'status':'running'} if author and state['status']=='paused' else state)
        if not task:raise Refused('No granted pending task')
        _structure(root,state)
        if state.get('delivery') and not state.get('correction') and not state.get('extra_review'):
            from .design_parse import freeze_render
            bound=state['delivery'];where={k:Path(v) if k!='location' else v for k,v in bound['layout'].items()}
            text=freeze_render(root,bound['doc'],'' if task['id']=='finalize' else task['id'],where)
            from .plans import write
            write(Path(bound['path']),text)
        if state.get('plans',{}).get('location')=='private' and state['workflow']=='design':
            from .plans import private_inputs,write
            where={k:Path(v) if k!='location' else v for k,v in state['plans'].items()}
            original=state.get('scope_snapshot',{}).get('documents',{})
            for name in private_inputs(where):
                path=Path(name);text=path.read_text()
                if path.parent==where['designs'] and text!=original.get(name) and re.search(r'^status:\s*draft\s*$',text,re.M):
                    write(path,re.sub(r'^status:\s*draft\s*$', 'status: approved',text,count=1,flags=re.M))
        value={'task':task['id'],**_subject(root,state)}
        journal.append('native.candidate',value)
        return value


def verify(root,base=None,mode='review',*,attempt_id=None):
    # The existing execution lock protects checks while short control transitions
    # remain available for human Pause/Stop. A new coordinator waits for this step.
    with ExitStack() as executing:
        from .processes import interruptible
        executing.enter_context(interruptible())
        with _locked(root):
            journal,state=load_run(root)
            if attempt_id is not None:
                expected=_attempt(state,attempt_id)
                if expected.get('finished') or expected not in _active(state):
                    raise Refused('This verification belongs to an ended attempt; do not retry it against replacement work')
                from .cancellation import guard
                guard(root,attempt=attempt_id)
            author=_author(root,state)
            if attempt_id is not None and (not author or author['id']!=attempt_id):
                raise Refused('This verification does not belong to the current author')
            executing.enter_context(lock(checkout_file(root,'oh-runner.lock'),wait=False))
            task=next_task(state|{'status':'running'} if author and state['status']=='paused' else state)
            if not task:raise Refused('No granted pending task to verify')
            if state['status'] not in ('running','paused'):raise Refused('Saved work is not available for verification')
            before=_subject(root,state)
            if author:
                from .cancellation import execution
                executing.enter_context(execution(root,state,author['id']))
        if state['workflow'] in ('design','propose'):
            from .plans import check
            where={k:Path(v) if k!='location' else v for k,v in state['plans'].items()}
            if where['location']=='private':
                from .plans import verify_roadmap,verify_design
                if where['roadmap'].exists():verify_roadmap(root,where)
                if where['designs'].exists():verify_design(root,where,approving=True)
            else:check(root,where)
            results=[]
        else:
            from .checks import resolve
            from .verification import verify as run_checks
            checks=resolve(root,state['project_checks'],base or state['base'],mode)
            results=run_checks(root,checks,state['project'])
        with _locked(root):
            _,current=load_run(root);current_author=_author(root,current)
            if (current['id'],current['human'],current_author)!=(state['id'],state['human'],author):raise Refused('Saved work changed during verification; retry checks for the selected work')
            after=_subject(root,current)
            if before!=after:raise Refused('Checks changed the candidate; inspect those changes and verify the final candidate again')
            value={'task':task['id'],**after,'checks':results,'at':now()}
            journal.append('verification',value)
        return value


def _affirmed(text,kind,question=''):
    """Compatibility for already-presented canonical choices; new grants use bound effects."""
    labels={'approve':('approve','approved','accept','accepted'), 'publish':('publish','open pr'),
            'continue':('continue','continue with next task window','continue with the next task window'), 'grant-review':('grant review','grant next review window','grant another review window'),
            'accept-concerns':('accept concerns',), 'route-scope':('route scope',), 'dismiss-scope':('dismiss scope',),
            'resume':('resume','resume the approved work'), 'pause':('pause','pause work'),
            'stop':('stop','stop now','keep work local')}
    expected='approve' if kind in ('approve-private','approve-proposal') else kind
    prompt=text.strip().casefold().rstrip('.!')
    command=_command({'prompt':text})
    if command:return expected in ('pause','stop','resume') and command==('oh-'+expected,'')
    combined={'accept concerns and route scope':{'accept-concerns','route-scope'},
              'accept concerns and dismiss scope':{'accept-concerns','dismiss-scope'}}
    return prompt in labels.get(expected,()) or expected in combined.get(prompt,set())


def _presented(root,locator,state=None):
    """Find the native question that showed a prepared decision, so the coordinator can
    pass its conversation locator without copying tool-call identities. Authority still
    comes only from the saved native answer, validated by the ordinary helpers."""
    key=locator.get('decision') if isinstance(locator,dict) else None
    if not isinstance(key,str) or not re.fullmatch(r'[0-9a-f]{64}',key) or locator.get('tool_use_id'):return locator
    try:prepared=read_json(_home(root)/'decisions'/(key+'.json'));question=prepared['question']
    except (OSError,ValueError,KeyError,TypeError):return locator
    env=os.environ.get('CODEX_THREAD_ID') or os.environ.get('OH_NATIVE_SESSION_ID')
    host=locator.get('host') or ('codex' if os.environ.get('CODEX_THREAD_ID') else (state or {}).get('host'))
    session=locator.get('session') or env or ((state or {}).get('human') or {}).get('session')
    if not host or not session:return locator
    options=prepared['menu_options'] if prepared.get('presentation') in ('checkpoint-menu','recovery-menu') and not prepared.get('bound_question') else None
    try:path,calls=authority.question_calls(root,host,session,question,locator.get('transcript_path'),options=options)
    except Refused:return locator
    consumed=(state or {}).get('decisions',{})
    for call in reversed(calls):
        candidate={'host':host,'session':session,'transcript_path':str(path),'tool_use_id':call,'decision':key}
        try:
            source=authority.native_human(root,candidate,latest=False)
            if not authority.newer(source.get('question_at'),prepared['created_at']):continue
            # Replay keeps a consumed answer; new authority still needs the latest input.
            if _human_key(source,state) not in consumed:authority.native_human(root,candidate,retry_resume=prepared.get('kind')=='resume')
        except Refused:continue
        return candidate
    return locator


def _recorded_choice(journal,key,kind):
    return any(e['kind']=='decision' and e['data'].get('choice')==kind and e['data'].get('source')==key
               for record in journal.records()
               for e in (record['data'].get('events',[]) if record['kind']=='transition' else [record]))


def decision(root,kind,locator,attempt=None,destination=None,run=None):
    if isinstance(locator,dict) and re.fullmatch(r'[0-9a-f]{64}',locator.get('decision') or ''):
        prepared=read_json(_home(root)/'decisions'/(locator['decision']+'.json'))
        if prepared.get('presentation')=='recovery-menu':
            from .recovery import apply
            return apply(root,kind,locator,run=run)
        if kind=='stop' and prepared.get('stop_boundary') and run is None:
            run=prepared.get('run')
    allowed={'continue','grant-review','accept-concerns','dismiss-scope','route-scope','publish','pause','stop','resume','approve-private','approve-proposal','approve-repair'}
    if kind not in allowed:raise Refused('Unknown consequential decision')
    with _locked(root):
        journal,state=load_run(root,run)
        locator=_presented(root,locator,state)
        since=journal.records()[0]['at']
        if attempt:since=_attempt(state,attempt).get('finished_at') or since
        elif kind=='resume':
            # Settling a child after the current command is routine recovery, not
            # a new human boundary that makes that same command stale.
            decisions=[r['at'] for r in journal.records() if r['kind']=='decision' or
                       (r['kind']=='transition' and any(e['kind']=='decision' for e in r['data'].get('events',[])))]
            since=max(decisions+[since])
        elif kind in ('publish','continue','grant-review'):
            relevant=[a.get('finished_at') for a in state['attempts'] if a.get('finished_at')]
            relevant += [r['at'] for r in journal.records() if r['kind'] in ('task.completed','run.status','transition')]
            since=max(relevant+[since])
        subject_path=None
        if not locator.get('decision') and kind in ('accept-concerns','dismiss-scope','route-scope','approve-proposal'):
            subject_path=Path(_attempt(state,attempt)['evidence'])/'result.json'
        elif not locator.get('decision') and kind=='approve-private':
            reviewed=_attempt(state,attempt)
            artifacts=reviewed.get('artifacts',{})
            design_folder=Path(state.get('plans',{}).get('designs',''))
            designs=[name for name in artifacts if Path(name).parent==design_folder]
            subject_path=Path(designs[0]) if len(designs)==1 else Path(reviewed['evidence'])/'result.json'
        source=authority.native_human(root,locator,subject=subject_path,latest=False)
        if state.get('published'):return select(root,state['id'])
        if not locator.get('decision') and kind=='resume' and (_saved_subject(state) not in source.get('question','') or state['branch'] not in source.get('question','')):
            raise Refused('Ask whether to resume '+_saved_subject(state)+' on '+state['branch']+', then use the native answer; no continuation was started')
        prepared=None
        key=_human_key(source,state)
        if locator.get('decision'):
            from .decisions import verify as verify_decision
            prepared=verify_decision(root,state,kind,locator,source,attempt,replay=True)
        elif (kind=='stop' and source.get('via')=='question'
              or authority.shown_offer_reference(source) and not _command(source)
              or not _affirmed(source['prompt'],kind,source.get('question',''))):
            if key not in state['decisions'] or not _recorded_choice(journal,key,kind):
                raise Refused('This reply needs its bound decision effect. Include the decision identity returned before the question in the same native locator and retry; do not ask the person to answer again.')
        if kind=='resume':
            _continuation_order(root,state,source)
            _resume_binding(root,state)
        if key in state['decisions']:
            if kind=='approve-repair':
                if not any(r['source']==key and r['decision']==locator.get('decision')
                           for repairs in state.get('approved_repairs',{}).values() for r in repairs):
                    raise Refused('This human input was already used for another decision; retain its original result')
            if kind not in ('accept-concerns','dismiss-scope','route-scope'):
                if kind=='resume':
                    if not _recorded_choice(journal,key,'resume'):raise Refused('This human input was already used for another decision; keep its saved result')
                    owner_key=_human_key(state['human'],state)
                    if key!=owner_key:raise Refused('This continuation was superseded; ask the current Resume question before continuing')
                    _finish_owner(root,state,source,retry_resume=True)
                    from .workflow import active_file
                    if read_json(active_file(root)).get('run')!=state['id']:
                        authority.native_human(root,locator)
                        authority.coordinator(root,state,locator)
                        _resume_binding(root,state,write=True)
                from .receipts import index
                index(journal,state)
                return select(root,state['id'])
            if _recorded_choice(journal,key,kind):
                from .receipts import index
                index(journal,state)
                return select(root)
        source=authority.native_human(root,locator,subject=subject_path,retry_resume=kind=='resume')
        authority.coordinator(root,state,locator,retry_resume=kind=='resume')
        if prepared:verify_decision(root,state,kind,locator,source,attempt)
        if not authority.newer(source.get('at'),since):raise Refused('This human decision predates the current subject or allowance boundary')
        adoption=None
        if kind=='resume' and not state.get('native_version'):
            if _active(state):raise Refused('A legacy attempt is unsettled; finish its native host cleanup before adoption')
            documents={}
            if state.get('delivery'):
                bound=state['delivery'];documents[bound['path']]=(bound.get('authority') or {}).get('start_text',Path(bound['path']).read_text())
            scope={k:state.get(k) for k in ('tasks','config','config_hash','harness_version','base','branch','workflow','design','track','project_checks','delivery','plans')}
            scope.update(schema=2,documents=documents,checkout=checkout_id(root),created_at=journal.records()[0]['at'])
            scope_id=digest(scope)
            adoption={'native_version':2,'scope_id':scope_id,'scope_snapshot':scope}
            state=state|adoption
        if kind=='stop' and prepared:
            _continuation_order(root,state,source)
            from .recovery import _settle
            state=_settle(root,journal,state,source|{'decision':locator['decision']})
            _switchable(root,[state])
        subject={'head':git(root,'rev-parse','HEAD')} if kind in ('stop','resume') else _subject(root,state)
        events=[]
        def add(name,value):events.append({'kind':name,'data':value})
        if adoption:
            _immutable(_home(root)/'scopes'/scope_id/'scope.json',scope)
            _immutable(journal.path/'scope'/'scope.json',scope)
            add('native.adopted',adoption)
        task=next_task(state|{'status':'running'}) or next((t for t in state['tasks'] if t['id'] not in state['done']),state['tasks'][-1])
        if kind=='continue':
            if _active(state):raise Refused('A task grant cannot replace an active attempt')
            ids=[t['id'] for t in state['tasks'] if t['id'] not in state['done']][:state['config']['tasks_per_batch']]
            if any(t in state['granted'] for t in ids):raise Refused('Existing task authority must be used before granting another window')
            add('grant',{'tasks':ids,'source':key,'kind':'continue','config_hash':state['config_hash']});add('run.status',{'status':'running'})
        elif kind=='grant-review':
            used=sum(a['role']=='review' and a['task']==task['id'] for a in state['attempts'])
            if used<review_limit(state,task['id']):raise Refused('Existing review allowance is not spent')
            add('review.grant',{'task':task['id'],'rounds':prepared['rounds'] if prepared else state['config']['review_rounds'],'source':key})
        elif kind=='approve-repair':
            from .decisions import repair_task
            task=repair_task(root,state)
            if not prepared or prepared['task']!=task['id']:raise Refused('Use the prepared decision for this task repair')
            add('task.repair-approved',{'task':task['id'],'instructions':prepared['repair'],
                'source':key,'decision':locator['decision']})
        elif kind in ('accept-concerns','dismiss-scope','route-scope'):
            review=_attempt(state,attempt)
            if review['role']!='review' or review.get('purpose','workflow')!='workflow' or review['outcome'] not in ('blocking','needs_resolution'):
                raise Refused('This decision requires retained workflow findings')
            severities={f['severity'] for f in review.get('findings',[])}
            if kind=='accept-concerns' and ('blocking' in severities or any(review[k]!=subject[k] for k in ('head','tree','git_tree','artifacts'))):
                raise Refused('Concern acceptance requires the current exact candidate with no blockers')
            prior=state.get('resolutions',{}).get(attempt,{})
            accepted=bool(prior.get('concerns_accepted'))
            scope=state.get('scope_records',{}).get(attempt) or prior.get('scope')
            if kind=='accept-concerns':
                if 'concern' not in severities:raise Refused('This review has no concerns to accept')
                accepted=True
            else:
                if 'scope' not in severities:raise Refused('This review has no scope finding to dispose')
                scope={'attempt':attempt,'task':review['task'],'action':'dismiss' if kind=='dismiss-scope' else 'route','source':source,
                       'findings':[f for f in review['findings'] if f['severity']=='scope'],'destination':{'pr':True}}
                if kind=='route-scope':
                    if destination and isinstance(destination.get('issue'),str):scope['destination']={'issue':destination['issue']}
                    elif state.get('delivery') and state['delivery'].get('status') in ('draft','approved') and not state.get('correction'):
                        from .scope import append_section
                        from .plans import write
                        path=Path(state['delivery']['path']);heading='## Open review scope'
                        quoted='\n\n'.join(f['description']+('\nEvidence: '+f.get('path','') if f.get('path') else '') for f in scope['findings'])
                        entry='\n'.join('> '+line for line in quoted.splitlines())+f"\n\nReview attempt: `{attempt}`\nDisposition: `route`\n"
                        write(path,append_section(path.read_text(),heading,entry))
                        scope['destination']={'design':str(path),'section':heading}
                    else:raise Refused('Name an existing authorized issue, or dismiss the scope finding into the retained PR record')
                add('scope.recorded',scope)
            concern_done='concern' not in severities or accepted
            choice='partial disposition'
            if concern_done:
                parts=[]
                if accepted:parts.append('accept concerns')
                if scope and scope['action']!='retained':parts.append('dismiss scope' if scope['action']=='dismiss' else 'route scope')
                choice=' and '.join(parts)
            value={'attempt':attempt,'source':key,'sources':prior.get('sources',[])+[key],'tree':review['git_tree'],
                   'choice':choice,'concerns_accepted':accepted}
            if scope:
                value['scope']=scope
                if scope['destination'].get('issue'):value['issue']=scope['destination']['issue']
            add('review.resolution',value)
        elif kind=='approve-proposal':
            author=_attempt(state,attempt)
            if state['workflow']!='propose' or author['role']!='analysis' or not author.get('finished'):raise Refused('Approve the actual completed proposal preview before writing')
            add('proposal',{'attempt':attempt,'choice':'approve','source':source,'shown':author['native_source']})
        elif kind=='approve-private':
            review=_attempt(state,attempt)
            if state.get('plans',{}).get('location')!='private' or review['outcome'] not in ('clean','needs_resolution') or any(review[k]!=subject[k] for k in ('head','tree','git_tree','artifacts')):raise Refused('Private approval requires the exact reviewed private artifact')
            from .publication import task_evidence
            task_evidence(root,state,next(t for t in state['tasks'] if t['id']==review['task']),review,subject['head'])
            add('native.private.approved',{'attempt':attempt,'source':source,'artifacts':subject['artifacts']})
        elif kind=='publish':
            from .publication import settled
            settled(state)
            if _active(state) or changes(root):raise Refused('Publication requires completed work on its clean reviewed head')
            from .publication import destination as publication_destination,commits,made
            from .branches import main_ref,trunk
            dest=publication_destination(root,required=True)|{'base_branch':trunk(root,state['config'])}
            if prepared and prepared.get('presentation')=='checkpoint-menu':
                # The verified native menu binds this destination and the exact
                # work boundary. Its concise heading need not repeat those facts.
                if prepared['publication_destination']!=dest:
                    raise Refused('The publication destination changed; present the current destination before publishing')
            else:
                context=source.get('question','')+' '+source['prompt']
                destination_name=dest['destination'].removesuffix('.git').rsplit('/',2)[-2:]
                if state['branch'] not in context or '/'.join(destination_name) not in context:
                    raise Refused('The publication decision must identify this branch and repository destination')
            if source.get('question_at') and not authority.newer(source['question_at'],since):raise Refused('The publication question predates the current completed review')
            if destination and destination!=dest:raise Refused('The supplied publication destination differs from the project')
            base=main_ref(root,state['config'])
            branch_commits=commits(root,base,reviewed=None)
            prior_states=[other for commit in branch_commits if (other:=made(root,state['project'],commit))]
            covered={c for other in prior_states for intent in other['commit_intents'].values() for c in (intent.get('publication') or {}).get('covers',[])}
            own=commits(root,base,reviewed=covered)
            if not state['summaries'] or own[-1]!=state['summaries'][-1].get('commit'):raise Refused('Current head is not the completed reviewed delivery')
            add('decision',{'source':key,'choice':'pr','head':subject['head'],'branch':state['branch'],'base_branch':dest['base_branch'],'destination':dest['destination'],'remote':dest['remote'],'remote_fingerprint':dest['remote_fingerprint'],'commits':own})
            add('run.status',{'status':'pr'})
        elif kind=='stop':
            if _active(state):raise Refused('Cancel the owned native child and retain its terminal cancellation before recording Stop; native cancellation is not established by this helper')
            add('run.status',{'status':'stopped'})
        elif kind=='pause':add('run.status',{'status':'paused','head':subject['head'],'tree':subject['tree']})
        elif kind=='resume':
            from .cancellation import interrupted, register_owner
            # Observe Stop in the recovering conversation while old work settles.
            # This creates no execution authority; transfer still follows verified cleanup.
            register_owner(root,state|{'human':source},active=False)
            for pending in _active(state):
                if interrupted(root,attempt=pending['id']):
                    _retain_locked(root,pending['id'],{},run=state['id'])
            journal,state=load_run(root,state['id'])
            from .recovery import _settle
            state=_settle(root,journal,state,source|{'decision':locator.get('decision')})
            _switchable(root,[state])
            from .workspace import switch
            switch(root,state['branch'])
            subject=_subject(root,state)
            initial=_initial_grant(root,journal,state) if state.get('native_version') else None
            if initial:
                # Finish the original accepted entry in the same durable transfer.
                add('grant',initial)
                state=state|{'granted':initial['tasks']}
            add('run.owner',{'human':source})
            status=state['status']
            if status=='completed' and state['workflow']=='review' and not _finished(state):status='running'
            if status in ('paused','stopped','pausing'):
                status=state.get('control_return_status') or state.get('pause_return_status') or 'running'
            if status in ('running','needs_attention') or (initial and status=='checkpoint'):
                status='running' if next_task(state|{'status':'running'}) else 'completed' if len(state['done'])==len(state['tasks']) else 'checkpoint'
            add('run.status',{'status':status})
        if kind!='publish':
            effect={'choice':kind,'source':key,'head':subject['head'],'scope':state.get('scope_id'),'attempt':attempt}
            if kind=='stop':
                from .workflow import active_file
                selected=active_file(root)
                if selected.exists() and read_json(selected)['run']!=state['id']:effect['target_only']=True
            add('decision',effect)
        from .cancellation import continuation
        with continuation(root,state,source) if kind=='resume' else nullcontext():
            _immutable(journal.path/'decisions'/(key+'.json'),{'human':source,'prepared':prepared,'locator':locator})
            journal.append('transition',{'events':events})
        for event in events:
            if event['kind']=='run.status':best_effort('run.status',state['project'],state['id'],status=event['data']['status'])
        from .receipts import index
        index(journal,reduce(journal.records()))
        if kind=='resume':_resume_binding(root,state,write=True)
        return select(root,state['id'])


def complete(root,attempt_id):
    with _locked(root):
        journal,state=load_run(root);_owner(root,state);_idle(root);review=_attempt(state,attempt_id)
        if review.get('superseded'):raise Refused('Recovery changed the reviewed subject; finish fresh checks and review before completion')
        task=next((t for t in state['tasks'] if t['id']==review['task']),None)
        existing=next((d for d in state['summaries'] if d.get('review')==attempt_id),None)
        if existing:return existing|{'continuation':_continuation(state)}
        _switchable(root,[s for _,s in _saved_runs(root)])
        review=_reparse_review(root,journal,state,review)
        correction=state.get('correction')
        if state.get('extra_review') and not correction:
            if review['role']!='review' or review.get('purpose')!='workflow' or review['outcome'] not in ('clean','needs_resolution'):raise Refused('Additional review remains unresolved')
            subject=_subject(root,state)
            if any(subject[k]!=review[k] for k in ('head','tree','git_tree','artifacts')):raise Refused('Additional review no longer covers current work')
            baseline=state['extra_review'].get('baseline')
            if changes(root) or baseline and subject['artifacts']!=baseline['artifacts']:
                raise Refused('This additional review includes uncommitted repairs. Retain its authorized repair author and complete the correction; do not close it as unchanged feedback.')
            from .publication import task_evidence
            task_evidence(root,state,task,review,subject['head'])
            journal.append('review.checked',{'attempt':attempt_id})
            journal.append('run.status',{'status':state['extra_review']['return_status'],**({'head':subject['head'],'tree':subject['tree']} if state['extra_review']['return_status']=='paused' else {})})
            return {'review':attempt_id,'outcome':review['outcome'],'committed':False,'continuation':_continuation(reduce(journal.records()))}
        if state['status']!='running' or _active(state) or not task or (not correction and (task['id'] not in state['granted'] or task['id'] in state['done'])):
            raise Refused('No remaining completion authority for this task')
        if review['role']!='review' or review.get('purpose')!='workflow':raise Refused('Standalone feedback cannot authorize completion')
        key=correction['key'] if correction else task['id']
        intent=state['commit_intents'].get(key)
        recovered=False
        if intent and git(root,'rev-parse','HEAD')!=intent['parent']:
            if changes(root):raise Refused('Preserve new edits before recovering a reviewed commit')
            from .publication import verify_record
            verify_record(root,git(root,'rev-parse','HEAD'),intent['publication'])
            if intent['review']!=attempt_id:raise Refused('Commit intent belongs to a different exact review')
            recovered=True
            subject={k:review[k] for k in ('head','tree','git_tree','artifacts')}
        else:subject=_subject(root,state)
        if any(subject[k]!=review[k] for k in ('head','tree','git_tree','artifacts')):raise Refused('The final review does not cover the current candidate')
        checked=state.get('verification',{}).get(task['id'])
        if not recovered and not provenance(journal.records(),checked,subject):
            raise Refused('Passing verification does not cover the final candidate')
        if state['workflow']=='propose' and not any(a.get('choice')=='approve' for a in state.get('proposal_answers',[])):
            raise Refused('The proposed additions were not approved before writing')
        if state['workflow']=='design' and state.get('plans',{}).get('location')=='private' and state.get('private_native_approval',{}).get('attempt')!=attempt_id:
            raise Refused('The human must approve the exact reviewed private plan')
        from .publication import task_evidence,validate_evidence
        # A saved intent is not a commit. Validate current proof before every new
        # Git write; only an already-created exact commit recovers from its seal.
        current_evidence=None if recovered else task_evidence(root,state,task,review,subject['head'])
        if intent and any(intent.get(k)!=v for k,v in {'task':task['id'],'review':attempt_id,'parent':subject['head'],'git_tree':subject['git_tree']}.items()):
            if recovered:raise Refused('The committed seal covers a different task or candidate')
            intent=None  # A new validated intent supersedes the unexecuted one; its journal record remains.
        evidence=intent['publication'] if intent else current_evidence
        validate_evidence(evidence)
        value={'task':task['id'],'review':attempt_id,'summary':review['summary'],'evidence':review.get('native_source',[]),'tree':subject['git_tree']}
        if committed(state):
            if not recovered:
                if not intent:
                    intent={'task':task['id'],'key':key,'review':attempt_id,'git_tree':subject['git_tree'],'parent':subject['head'],'publication':evidence}
                    journal.append('commit.intent',intent)
                git(root,'add','--all',*whole(root))
                if git(root,'write-tree')!=subject['git_tree']:raise Refused('Staged tree differs from independently reviewed candidate')
                title=('fix ' if correction else '')+f"task {task['id']}: {task['title']}"
                git(root,'commit','--allow-empty','-m',f"{title}\n\nOH-Run: {state['id']}\nOH-Review: {attempt_id}\nOH-Reviewed-Tree: {subject['git_tree']}\nOH-Evidence: {digest(evidence)}")
                if git(root,'rev-parse','HEAD^{tree}')!=subject['git_tree'] or git(root,'rev-parse','HEAD^')!=subject['head']:
                    raise Refused('Commit hooks changed the reviewed candidate or parent')
            value['commit']=git(root,'rev-parse','HEAD')
        else:value['artifact']={'files':subject['artifacts']}
        bound=state.get('delivery')
        if bound and bound['layout']['location']=='private':
            from .plans import approvals_file
            records=read_json(approvals_file(root));old=records[bound['doc']]
            updated=old|{'sha256':subject['artifacts'][bound['path']],'delivery_commit':value.get('commit',subject['head']),
                         'delivery_base':old.get('delivery_base',state['base']),'delivery_baseline':old.get('delivery_baseline',state['base']),
                         'delivery_no_code':not bool(git(root,'diff','--name-only',state['base'],value.get('commit',subject['head'])))}
            atomic_json(approvals_file(root),records|{bound['doc']:updated})
        if state.get('plans',{}).get('location')=='private' and state['workflow']=='design':
            from .plans import approve
            where={k:Path(v) if k!='location' else v for k,v in state['plans'].items()}
            for path in subject['artifacts']:
                number=re.match(r'([0-9]{4})-',Path(path).name)
                if number and Path(path).parent==where['designs'] and Path(path).read_text()!=state['scope_snapshot'].get('documents',{}).get(path) and re.search(r'^status:\s*approved\s*$',Path(path).read_text(),re.M):
                    approve(root,where,number[1],state['id'],False)
        if correction:
            value.update(commit_key=key,correction_of=correction['prior_commit'])
            journal.append('correction.completed',value);journal.append('run.status',{'status':correction['return_status'],**({'head':git(root,'rev-parse','HEAD'),'tree':tree(root)} if correction['return_status']=='paused' else {})})
        else:
            journal.append('task.completed',value)
            current=reduce(journal.records())
            if len(current['done'])==len(current['tasks']):journal.append('run.status',{'status':'completed'})
            elif not next_task(current):journal.append('run.status',{'status':'checkpoint'})
        best_effort('task.finished',state['project'],state['id'],task['id'],status='completed',wall_ms=None,expected_attempts=sum(a['task']==task['id'] for a in state['attempts']),expected_reviews=sum(a['role']=='review' and a['task']==task['id'] for a in state['attempts']))
        best_effort('run.status',state['project'],state['id'],status=reduce(journal.records())['status'])
        from .receipts import index
        index(journal,reduce(journal.records()))
        return value|{'continuation':_continuation(reduce(journal.records()))}


def resume(root,locator=None,run=None):
    # A factual read may prefer the underlying workflow after completed feedback,
    # but never changes a binding. Only a verified continuation selects its owner.
    if run is None:
        from .workflow import active_file
        review_pointer=checkout_file(root,'oh-active-review.json')
        canonical=checkout_file(root,'oh-active-run.json')
        if active_file(root)==review_pointer:
            _,feedback=load_run(root)
            if feedback['workflow']=='review' and feedback['status']=='completed' and canonical.exists():run=read_json(canonical)['run']
    journal,state=load_run(root,run)
    if locator is None or _finished(state):
        return select(root,state['id'])
    return decision(root,'resume',locator,run=state['id'])


def review(root,arguments,human=None):
    import shlex
    if isinstance(arguments,list):arguments=shlex.join(arguments)
    source=authority.native_human(root,human) if human is not None else None
    from .entry import enroll
    if blocked:=enroll(root):raise Refused(blocked['onboarding'])
    from .review import subject,capture
    words=__import__('shlex').split(arguments)
    if len(words)==2 and words[0]=='task':
        return_status=None
        for _,saved in _saved_runs(root):
            if saved['workflow']!='deliver' or words[1] not in saved['done'] or saved.get('published'):continue
            pending=saved.get('extra_review') or saved.get('correction')
            if pending and pending['task']==words[1]:
                if source and not _command(source):return resume(root,source,saved['id'])
                return _resume_offer(root,saved) if source else select(root,saved['id'])
            return_status=saved['status']
            if source:
                if _command(source):return _resume_offer(root,saved)
                decision(root,'resume',source,run=saved['id'])
        with _locked(root):
            journal,state=load_run(root);_owner(root,state);_idle(root)
            if state.get('published') or state['workflow']!='deliver' or state['status'] not in ('running','completed','checkpoint','stopped') or words[1] not in state['done']:
                raise Refused('Task review requires completed unpublished work from this delivery')
            if _active(state):raise Refused('Retain the current attempt before additional review')
            saved=next(d for d in reversed(state['summaries']) if d['task']==words[1])
            selected_task=next(t for t in state['tasks'] if t['id']==words[1])
            journal.append('review.requested',{'task':words[1],'return_status':return_status or state['status'],
                'prior_commit':saved['commit'],'baseline':_subject(root,state)})
            journal.append('run.status',{'status':'running'})
            return select(root)
    selected=subject(root,arguments)
    if source and (existing:=_matching_entry(root,source,'review',selected=selected)) is not None:return existing
    with _locked(root):
        saved=_saved_runs(root)
        selected=subject(root,arguments)
        if source:
            for journal,prior in saved:
                if (prior['workflow']=='review' and _same_review_subject(selected,prior) and
                        _human_key(source,prior)==prior.get('source')):
                    return _finish_entry(root,journal,prior,source)
            _entry_order(root,source,saved)
        _switchable(root,[prior for _,prior in saved])
        host=source['host'] if source else 'codex' if __import__('os').environ.get('CODEX_THREAD_ID') else 'claude'
        session=source['session'] if source else __import__('os').environ.get('CODEX_THREAD_ID') or __import__('os').environ.get('OH_NATIVE_SESSION_ID')
        if not session:raise Refused('Native standalone review needs its current host session identity')
        p=project(root);run=identifier();config=snapshot(root);journal=Journal(p['id'],run)
        source=source or {'host':host,'session':session,'turn':identifier(),'prompt':arguments}
        data={'id':run,'project':p['id'],'name':p['name'],'work_kind':p['kind'],'checkout':checkout_id(root),'host':host,'human':source,
              'source':_human_key(source),'workflow':'review','native_version':2,'branch':selected['branch'],'base':selected['head'],
              'tasks':[{'id':'review','title':selected['description'],'instructions':'Inspect the exact selected subject; feedback only.'}],
              'checks':[],'project_checks':[],'standalone_subject':selected,**config}
        data['subject']=selected
        data['retained_work']=[{'run':s['id'],'workflow':s['workflow'],'subject':_saved_subject(s),
                               'branch':s['branch'],'journal':str(j.path),'findings':str(j.path/'index.md')} for j,s in saved]
        data['standalone_artifact']=capture(root,journal.path/'standalone',selected)
        journal.append('run.started',data)
        best_effort('run.started',p['id'],run,name=p['name'],work_kind=p['kind'],host=host,version=config['harness_version'],config_hash=config['config_hash'])
        atomic_json(checkout_file(root,'oh-active-review.json'),{'project':p['id'],'run':run,'checkout':checkout_id(root)})
        if source.get('record_hashes'):return _finish_entry(root,journal,reduce(journal.records()),source)
        journal.append('grant',{'tasks':['review'],'source':data['source'],'kind':'standalone','config_hash':config['config_hash']})
        from .cancellation import register_owner
        register_owner(root,reduce(journal.records()))
        return select(root)
