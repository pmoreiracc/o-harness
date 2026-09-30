"""Keep unrelated observations as future work, without changing the admitted task list."""
import hashlib
from pathlib import Path
import re
import tempfile
from . import plans
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


def prepare(root,journal,state,attempt,action,source):
    """Prepare one journalled disposition; only recovery applies the document replacement."""
    if attempt['id'] in state.get('scope_records',{}):return None
    findings=([{'description':note,'path':'','severity':'scope'} for note in attempt.get('found_along_way',[])]
              if action=='noted' else [f for f in attempt.get('findings',[]) if f['severity']=='scope'])
    if not findings:return None
    from .delivery import guard
    guard(root,state)
    value={'attempt':attempt['id'],'task':attempt['task'],'action':action,'source':source,'findings':findings}
    bound=state.get('delivery') or {}
    # Use the admitted lifecycle, before OH ticks/freezes the candidate for this task.
    mutable=bound and bound.get('status','approved') in ('draft','approved')
    if mutable:
        render=state.get('delivery_render')
        if not render or render['task']!=attempt['task']:raise Refused('Render this task before recording its scope notes')
        target=Path(render.get('candidate',render['path']))
        heading='## Scope decisions' if action=='dismiss' else '## Open review scope'
        prose='\n\n'.join(f['description']+('\nEvidence: '+f['path'] if f['path'] else '') for f in findings)
        entry='\n'.join('> '+line for line in prose.splitlines())
        entry+=f"\n\nReview attempt: `{attempt['id']}`\nDisposition: `{action}` ({source})\n"
        text=append_section(render['text'],heading,entry)
        # Validate in scratch, before journalling an intent that recovery must replay.
        with tempfile.TemporaryDirectory() as directory:
            candidate=Path(directory)/Path(render['path']).name
            plans.write(candidate,text)
            plans.verify_design(root,plans.layout(root)|{'designs':Path(directory)},bound['doc'],orphans=False)
        before=render['text'];prefix=0;suffix=0
        while prefix<min(len(before),len(text)) and before[prefix]==text[prefix]:prefix+=1
        while suffix<min(len(before),len(text))-prefix and before[-suffix-1]==text[-suffix-1]:suffix+=1
        value['change']={'before':before[prefix:len(before)-suffix], 'after':text[prefix:len(text)-suffix]}
        value.update(destination={'design':render['path'],'section':heading},render=render|{
            'text':text,'write_before':plans.file_identity(target),
            'after_inputs':render['after_inputs']|{render['path']:hashlib.sha256(text.encode()).hexdigest()}})
        if 'candidate' in render:
            # Every admitted private subject remains readable at its original path and hash.
            candidate=target.with_name(f'{attempt["task"]}-{attempt["id"]}-{action}.md')
            if candidate.exists():raise Refused('The next scope candidate already exists; preserve it and inspect the retained disposition')
            value['render'].update(candidate=str(candidate),write_before=None)
    elif action=='route':
        from .issues import route
        value['destination']={'issue':route(root,state['project'],state['id'],attempt['id'],findings)}
    else:value['destination']={'pr':True}
    return value


def record(root,journal,state,attempt,action,source):
    value=prepare(root,journal,state,attempt,action,source)
    if value:
        journal.append('scope.recorded',value)
        from .delivery import recover
        from .workflow import reduce
        recover(root,reduce(journal.records()))
    return value


def undo_notes(text,records):
    """Remove only exact journalled insertions, preserving any unrelated plan edits."""
    for record in reversed(list(records)):
        change=record.get('change')
        if not change:continue
        if text.count(change['after'])!=1:raise Refused('Recorded scope notes changed; restore their reviewed text before resuming')
        text=text.replace(change['after'],change['before'],1)
    return text
