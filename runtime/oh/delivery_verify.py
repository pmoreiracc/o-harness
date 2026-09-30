"""Re-derive design delivery from the approved task list and actual task commits before publication."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
from .storage import Journal, Refused, git


def contents(root,revision,path):
    try:return subprocess.check_output(['git','-C',str(root),'show',revision+':'+path],stderr=subprocess.DEVNULL).decode()
    except (subprocess.CalledProcessError,UnicodeDecodeError):raise Refused(f'Delivery design {path} is missing or unreadable at {revision}; restore its approved path and review the repair') from None


def parsed(text):
    from .design_parse import plan, fm_value, US
    with tempfile.TemporaryDirectory(prefix='oh-delivery-check-') as directory:
        folder=Path(directory);path=folder/'0001-design.md';path.write_bytes(text.replace('\r\n','\n').encode())
        rows=[r.split(US) for r in plan(folder,'0001',{'designs':folder,'roadmap':folder/'roadmap.md'}).split('\n') if r]
        return fm_value(path,'status'),{r[0]:r for r in rows}


def authority(root,where,path,text,approval):
    if where['location']=='private':
        if not approval or approval.get('sha256')!=hashlib.sha256(path.read_bytes()).hexdigest():raise Refused('Private design needs its unchanged human approval before delivery')
        return {'text':text,'start_text':text,'approval':approval}
    main=git(root,'rev-parse','origin/main');relative=path.relative_to(root).as_posix()
    approved=contents(root,main,relative)
    if parsed(approved)[0]!='approved':raise Refused('The design must be approved on main before delivery; merge its approval first')
    return {'main':main,'path':relative,'text':approved,'start_text':text}


def transitions(before,after,task):
    if set(before)!=set(after):raise Refused('Delivery changed the approved task list; restore its task IDs and review the repair')
    for number,row in before.items():
        if after[number][2:]!=row[2:]:raise Refused(f'Delivery changed the approved definition of task {number}; restore it and review the repair before PR')
        expected='done' if number==task else row[1]
        if after[number][1]!=expected:
            if number==task:raise Refused(f'Delivery task {number} was completed but is not marked done; restore its recorded progress and review the repair before PR')
            raise Refused(f'Delivery changed task {number} from {row[1]} to {after[number][1]} without completing it; restore its recorded status and review the repair before PR')


def verify_run(root,state,*,current=False):
    bound=state.get('delivery')
    if not bound:return  # quick fixes have no design contract
    source=bound.get('authority')
    if not source:raise Refused('This older delivery lacks its saved approval snapshot; restore the approved design and obtain a fresh delivery review before PR')
    private=bound['layout']['location']=='private'
    approved_status,approved=parsed(source['text']);_,initial=parsed(source['start_text'])
    if approved_status!='approved':raise Refused('Delivery did not start from an approved design')
    if private:
        if source['approval']!=bound['approvals'].get(bound['doc']):raise Refused('Private delivery approval differs from its saved starting approval')
        if hashlib.sha256(source['text'].encode()).hexdigest()!=source['approval']['sha256']:raise Refused('Private starting design differs from its human-approved hash')
    elif contents(root,source['main'],source['path'])!=source['text']:
        raise Refused('Delivery approval snapshot does not match its recorded main commit')
    tracks={row[2] for row in approved.values()}
    from .branches import delivery_branch
    if len(tracks)>1 and not state.get('track') and any(t['id']!='finalize' for t in state['tasks']):raise Refused('A design with several tracks needs its per-track delivery branch')
    if state['branch']!=delivery_branch(bound['doc'],state.get('track') or ''):raise Refused('Delivery is on the wrong design/track branch; return to '+delivery_branch(bound['doc'],state.get('track') or ''))
    records=Journal(state['project'],state['id']).records()
    renders={r['data']['task']:r['data'] for r in records if r['kind']=='delivery.render'}
    # Scope records can retain a later version of the same private candidate.
    for record in records:
        if record['kind']=='transition':
            for event in record['data']['events']:
                if event['kind']=='scope.recorded' and event['data'].get('render'):renders[event['data']['task']]=event['data']['render']
        elif record['kind']=='scope.recorded' and record['data'].get('render'):renders[record['data']['task']]=record['data']['render']
    before=initial
    from .publication import verify_record
    for done in state['summaries']:
        task=done['task'];commit=done['commit'];evidence=state['commit_intents'][task]['publication']
        verify_record(root,commit,evidence)
        if git(root,'show','-s','--format=%s',commit)!=f"task {task}: {evidence['title']}":raise Refused(f'Commit {commit[:12]} needs the recorded task {task}: title and OH trailers; repair its message before PR')
        if task!='finalize':
            row=approved.get(task)
            if not row or row[1]!='pending' or row[4] or (state.get('track') and row[2]!=state['track']):raise Refused(f'Task {task} was not approved and ready on this delivery track; restore its approved scope before PR')
            if any(before.get(n,['','missing'])[1]!='done' for n in filter(None,row[3].split(','))):raise Refused(f'Task {task} ran before its dependencies were done; complete and review them before PR')
        if private:
            render=renders.get(task)
            if not render:raise Refused(f'Task {task} lacks recorded private progress; recover its saved delivery before PR')
            text=render['text']
        else:
            _,parent=parsed(contents(root,evidence['parent'],source['path']))
            if parent!=before:raise Refused('The design changed between task commits; restore its recorded task state and review the repair')
            text=contents(root,commit,source['path'])
        _,after=parsed(text)
        transitions(before,after,task)
        before=after
    if current:
        _,actual=parsed(Path(bound['path']).read_bytes().decode())
        transitions(before,actual,None)
        from .delivery import guard
        guard(root,state)
    return {'tasks':len(state['summaries']),'design':bound['doc']}


def verify(root,state):
    if not state.get('delivery'):return
    from .branches import main_ref
    from .publication import commits,made
    seen=set()
    for commit in commits(root,main_ref(root),reviewed=None):
        other=made(root,state['project'],commit)
        if other and other['id'] not in seen:
            verify_run(root,other,current=other['id']==state['id']);seen.add(other['id'])
    if state['id'] not in seen:verify_run(root,state,current=True)
