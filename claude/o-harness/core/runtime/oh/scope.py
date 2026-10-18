"""Keep unrelated observations as future work, without changing the admitted task list."""
import re
from .storage import Refused


def append_section(text, heading, entry):
    """Quote untrusted prose so a reported checkbox or heading cannot become a design task."""
    ending='\r\n' if '\r\n' in text else '\n'
    text=text.replace('\r\n','\n')
    block='\n\n'+entry.strip()+'\n'
    match=re.search(r'^'+re.escape(heading)+r'[ \t]*$',text,re.M)
    if match:
        following=re.search(r'^## ',text[match.end():],re.M)
        at=match.end()+following.start() if following else len(text)
        text=text[:at].rstrip()+block+'\n'+text[at:]
    else:text=text.rstrip()+'\n\n'+heading+block
    return text.replace('\n',ending)


def undo_notes(text,records):
    """Remove only exact journalled insertions, preserving any unrelated plan edits."""
    for record in reversed(list(records)):
        change=record.get('change')
        if not change:continue
        if text.count(change['after'])!=1:raise Refused('Recorded scope notes changed; restore their reviewed text before resuming')
        text=text.replace(change['after'],change['before'],1)
    return text


def followups(state):
    """Existing retained reviews are the durable queue; no parallel backlog database."""
    result=[]
    for attempt in state['attempts']:
        findings=[f for f in attempt.get('findings',[]) if f['severity']=='scope']
        if not findings:continue
        resolution=state.get('resolutions',{}).get(attempt['id'],{})
        record=state.get('scope_records',{}).get(attempt['id']) or resolution.get('scope') or {}
        if not record and resolution.get('issue'):record={'action':'route','destination':{'issue':resolution['issue']}}
        if not record and 'dismiss scope' in resolution.get('choice',''):record={'action':'dismiss'}
        if record.get('action')=='dismiss':continue  # The original finding and human dismissal remain in review history.
        item={'attempt':attempt['id'],'task':attempt['task'],'findings':findings,
              'action':record.get('action','retained'),'destination':record.get('destination',{'saved':True})}
        bound=state.get('delivery',{})
        if bound and bound.get('status') in ('draft','approved') and not state.get('correction'):
            item['suggested_design']=bound['path']
        result.append(item)
    return result


def track(root,attempt_id,destination=None):
    """Record tracking facts. This grants no implementation, issue-creation or review authority."""
    from pathlib import Path
    from .native import _locked, _owner, _attempt, _active, _subject, _idle
    from .workflow import load_run
    from .plans import write
    with _locked(root):
        journal,state=load_run(root)
        review=_attempt(state,attempt_id)
        findings=[f for f in review.get('findings',[]) if f['severity']=='scope']
        if review['role']!='review' or not review.get('finished') or not findings:raise Refused('Track actual retained outside-scope findings')
        bound=state.get('delivery',{})
        mutable=bool(bound and bound.get('status') in ('draft','approved') and not state.get('correction') and not state.get('extra_review') and state['status']=='running' and len(state['done'])<len(state['tasks']))
        latest=next((a for a in reversed(state['attempts']) if a['role']=='review' and a.get('finished')),None)
        # Automatic filing must not change an already successful review candidate.
        if destination is None and (prior:=state.get('scope_records',{}).get(attempt_id)):
            current=_subject(root,state) if prior['destination'].get('design') and latest else None
            needs_review=bool(current and any(current[k]!=latest[k] for k in ('head','tree','git_tree','artifacts')))
            return prior|{'candidate_changed':False,'requires_review':needs_review}
        if destination is None:
            repair_pending=latest and latest.get('outcome')=='blocking'
            destination={'design':bound['path']} if mutable and repair_pending and not _active(state) else {'saved':True}
        if not isinstance(destination,dict) or len(destination)!=1:raise Refused('Track in saved follow-ups, a mutable design, or an issue URL')
        changed=False
        if destination.get('issue'):
            if not isinstance(destination['issue'],str) or not re.fullmatch(r'https://[^/\s]+/[^/\s]+/[^/\s]+/issues/[1-9][0-9]*',destination['issue']):
                raise Refused('Supply the actual created or linked issue URL; creating it uses native tools under human authority')
        elif destination.get('design'):
            path=Path(destination['design']).resolve()
            allowed=mutable and path==Path(bound['path']).resolve()
            where=state.get('plans',{})
            if state['workflow'] in ('design','propose') and where.get('designs') and state['status']=='running' and not state.get('correction'):
                from .storage import changes
                original=state['scope_snapshot'].get('documents',{})
                touched=(str(path) in review.get('artifacts',{}) and path.read_text(encoding='utf-8')!=original.get(str(path))) if where['location']=='private' else path.is_relative_to(root) and path.relative_to(root).as_posix() in changes(root)
                approved=state['workflow']!='propose' or any(a.get('choice')=='approve' for a in state.get('proposal_answers',[]))
                allowed=path.parent==Path(where['designs']).resolve() and path.is_file() and touched and approved and bool(re.search(r'^status:\s*(?:draft|approved)\s*$',path.read_text(encoding='utf-8'),re.M))
            if not allowed:raise Refused('This design is frozen or outside the current planning authority; retain the finding or track an authorized issue')
            _owner(root,state)
            if _active(state):raise Refused('Retain the current native attempt before editing its design')
            _idle(root)
            heading='## Open review scope'
            quoted='\n\n'.join(f['description']+('\nEvidence: '+f.get('path','') if f.get('path') else '') for f in findings)
            entry='\n'.join('> '+line for line in quoted.splitlines())+f"\n\nReview attempt: `{attempt_id}`\nDisposition: `route`\n"
            text=path.read_text(encoding='utf-8')
            if entry.rstrip() not in text:
                write(path,append_section(text,heading,entry));changed=True
            destination={'design':str(path),'section':heading}
        elif destination!={'saved':True}:raise Refused('Unknown tracking destination')
        value={'attempt':attempt_id,'task':review['task'],'action':'retained' if destination.get('saved') else 'route',
               'source':{'review':attempt_id},'findings':findings,'destination':destination}
        if state.get('scope_records',{}).get(attempt_id)!=value:journal.append('scope.recorded',value)
        from .receipts import index
        from .workflow import reduce
        index(journal,reduce(journal.records()))
        needs_review=changed
        if destination.get('design') and latest:
            current=_subject(root,state)
            needs_review=any(current[k]!=latest[k] for k in ('head','tree','git_tree','artifacts'))
        return value|{'candidate_changed':changed,'requires_review':needs_review}
