"""OH's plan document format only; execution and grants belong to the common runner."""
from pathlib import Path
import re
from .design_parse import freeze_render, plan
from .storage import Refused, git, project


def document(root, doc):
    if not re.fullmatch(r'[0-9]{4}', doc):raise Refused('Expected a four-digit design ID')
    paths=list((Path(root)/'docs/design').glob(doc+'-*.md'))
    if len(paths)!=1:raise Refused('Design does not resolve uniquely')
    return paths[0]


def manifest(root, doc, track=''):
    if project(root).get('design_profile')!='consumer-v1':
        raise Refused('This project does not use OH\'s plan documents (roadmap and numbered design docs); use a generic task plan')
    path=document(root,doc);relative=path.relative_to(root).as_posix()
    approved=git(root,'show','origin/main:'+relative)
    if not re.search(r'^status:\s*approved\s*$',approved,re.M):
        raise Refused('The design must be approved on main before delivery')
    if git(root,'hash-object','--no-filters','--',relative)!=git(root,'rev-parse','origin/main:'+relative):
        raise Refused('Prepare the design against its approved main revision')
    try:output=plan(root,doc)
    except Refused as exc:raise Refused(str(exc)[-2000:]) from None
    rows=[line.split('\x1f') for line in output.splitlines() if line]
    if any(len(row)!=6 for row in rows):raise Refused('Malformed design task projection')
    tracks={row[2] for row in rows}
    if not track:
        if len(tracks)!=1:raise Refused('Choose one of the design tracks: '+', '.join(sorted(tracks)))
        track=next(iter(tracks))
    if track not in tracks:raise Refused('Unknown design track')
    completed={row[0] for row in rows if row[1]=='done'}
    pending=[row for row in rows if row[1]=='pending' and row[2]==track]
    tasks=[];available=set(completed)
    text=path.read_text()
    for task_id,_,owner,needs,blocked,title in pending:
        dependencies=set(needs.split(',')) if needs else set()
        if blocked or not dependencies<=available:
            raise Refused('Task '+task_id+' is blocked or depends on unfinished work in another track')
        match=re.search(r'^- \[ \] \*\*'+re.escape(task_id)+r'\.\*\*.*?(?=^- \[[ x]\] \*\*\d+\.\*\*|^##|\Z)',text,re.M|re.S)
        if not match:raise Refused('Cannot extract the admitted design task')
        tasks.append({'id':task_id,'title':title,'instructions':match.group(0).strip(),
                      'needs':sorted(dependencies-completed),'design':relative,
                      'transition':{'profile':'consumer-v1','doc':doc,'task':task_id}})
        available.add(task_id)
    if not tasks:
        if any(row[1]=='pending' for row in rows):raise Refused('This track is complete; other tracks still have work')
        tasks=[{'id':'finalize','title':'Finalize the completed design',
                'instructions':'Verify the complete design and affected documentation. The runner renders the final lifecycle before review.',
                'design':relative,'transition':{'profile':'consumer-v1','doc':doc,'task':'finalize'}}]
    return {'workflow':'deliver','design':doc,'track':track,'tasks':tasks}


def render(root, task):
    transition=task.get('transition')
    if not transition:return
    if transition.get('profile')!='consumer-v1' or project(root).get('design_profile')!='consumer-v1':
        raise Refused('Unsupported document transition profile')
    path=document(root,transition['doc'])
    if path.relative_to(root).as_posix()!=task.get('design'):raise Refused('Transition does not match the admitted design')
    # Pure renderer only: it neither consumes a receipt nor runs a legacy delivery loop.
    try:text=freeze_render(root,transition['doc'],'' if transition['task']=='finalize' else transition['task'])
    except Refused as exc:raise Refused('Cannot render final design lifecycle: '+str(exc)[-2000:]) from None
    text=text.replace('\r\n','\n').replace('\r','\n')  # newlines as the former text-mode subprocess read them
    if path.read_text()!=text:path.write_text(text,newline='\n')
