"""Approved document selection and historical progress validation; no execution loop."""
import hashlib
from .system import Path
import re
from . import plans
from .design_parse import freeze_render, plan
from .storage import Refused, git, read_json


def parse(arguments):
    text=arguments.strip()
    if not text:return {'kind':'list'}
    match=re.fullmatch(r'([0-9]{4})(?:\s+([a-zA-Z0-9_-]+))?(?:\s+(request:[0-9a-f]{64}))?',text)
    if match:return {'kind':'design','doc':match[1],'track':match[2] or '', 'request':match[3]}
    if re.fullmatch(r'request:[0-9a-f]{64}',text):return {'kind':'request','request':text}
    if re.match(r'(?:[0-9]|request:)',text):raise Refused('Use /oh-deliver NNNN [track], or describe a quick fix')
    return {'kind':'quick_fix','intent':text,'authorized':False,'prepare':True,
            'next':'Prepare the agreed task list and return its preview and decision menu, including the task/review limits. Execution has not started.'}

def inputs(where):
    return plans.private_inputs(where|{'location':'private'})

def document(root,where,doc):
    found=list(Path(where['designs']).glob(doc+'-*.md'))
    if len(found)!=1:raise Refused('Design does not resolve uniquely')
    plans.ordinary_outputs(found[0])
    return found[0]

def delivered_base(root,record,*,progressed=False):
    """Private progress requires recorded code lineage, even after squash merges."""
    from subprocess import CalledProcessError
    commit=record.get('delivery_commit');base=record.get('delivery_base');baseline=record.get('delivery_baseline')
    if not commit and not progressed:return
    if not all((commit,base,baseline)):
        raise Refused('Private progress has no code lineage; review and reapprove the plan with /oh-design from the checkout containing its completed code')
    try:
        git(root,'merge-base','--is-ancestor',baseline,base)
        git(root,'merge-base','--is-ancestor',base,commit)
        git(root,'merge-base','--is-ancestor',baseline,'HEAD')
        changed=git(root,'diff','--name-only','-z',base,commit)
        if not changed and not record.get('delivery_no_code'):
            raise Refused('Private progress has an unrecorded empty delivery range; restore its original approval record')
        try:git(root,'merge-base','--is-ancestor',commit,'HEAD')
        except CalledProcessError:
            # Squash merges must contain every delivered path, with an inherited baseline, or carry the delivery's
            # exact change in one commit, still found after main changed those paths again.
            from .branches import contained,delivered
            paths=[path for path in changed.split('\0') if path]
            if paths and not contained(root,'HEAD',commit) and not delivered(root,'HEAD',commit):git(root,'--literal-pathspecs','diff','--exit-code',commit,'HEAD','--',*paths)
    except CalledProcessError:
        raise Refused('Private plan progress belongs to code this checkout does not contain; merge the branch that holds it, through its pull request, first') from None

def dependencies(root,where,rows,name):
    """The roadmap accepts a slug or a whole milestone, including collapsed delivery pointers."""
    from .design_parse import roadmap
    by_slug={row[0]:row for row in rows}
    if name in by_slug:return [by_slug[name][3]]
    milestones=dict(plans.milestones(where))
    if name not in milestones:return []
    if milestones[name]:
        return [doc for doc,milestone in (row.split(plans.US) for row in roadmap(root,'--delivered',where).splitlines()) if milestone==name]
    return [row[3] for row in rows if row[1]==name]

def unreviewed(root,fork,base):
    """Commits on this branch since `fork` that OH didn't make and no review has covered yet: the person's own
    commits, and merges of `base` (main) that aren't Git's clean merge because a conflict was resolved by hand. The
    next task's review covers them, so the pull request carries only reviewed code. An OH commit the person amended
    or rebased is theirs now, like a message that merely claims to be OH's."""
    from .publication import made,merged
    from .storage import project
    covered=set();found=[]
    for line in git(root,'rev-list','--reverse','--parents',fork+'..HEAD').splitlines():
        commit,*parents=line.split()
        if len(parents)>1:
            try:merged(root,commit,parents,base)
            except Refused:found.append(commit)
            continue
        state=made(root,project(root)['id'],commit)
        if not state:found.append(commit);continue
        for intent in state['commit_intents'].values():
            covered|=set((intent.get('publication') or {}).get('covers',[]))
    return [commit for commit in found if commit not in covered]

def guard(root,state):
    """Accept only the run's admitted context or its recorded, deterministic progress edit."""
    if state.get('native_version'):
        from .native import _structure
        return _structure(root,state)
    if not state.get('delivery'):return
    where=plans.layout(root);bound=state['delivery'];render=state.get('delivery_render')
    if plans.layout_snapshot(where)!=bound['layout']:raise Refused('Plan paths changed during delivery; restore them or stop the run')
    pending=render and render['task'] not in state['done']
    deferred=pending and 'candidate' in render
    expected=render['before_inputs'] if deferred else render['after_inputs'] if render else bound['inputs']
    actual=inputs(where)
    publishing=render and (render['task'] in state.get('commit_intents',{}) or
                          (state.get('delivery_approval') or {}).get('task')==render['task'])
    if actual!=expected and not (publishing and actual==render['after_inputs']):
        raise Refused('Plan documents changed outside this delivery run; preserve the edits and stop the run')
    if where['location']=='private':
        records=read_json(plans.approvals_file(root));intent=state.get('delivery_approval')
        expected_records=bound['approvals'].copy()
        if intent:expected_records[bound['doc']]=intent['after']
        for number,record in expected_records.items():
            accepted=[record]
            if intent and number==bound['doc'] and intent['task'] not in state['done']:accepted.append(intent['before'])
            if records.get(number) not in accepted:raise Refused('Private approval changed during delivery; restore its bound record or stop the run')
    if render and 'candidate' in render and plans.digest_of(Path(render['candidate']))!=render['after_inputs'][render['path']]:
        raise Refused('Delivery candidate changed outside the runner')


def selection(root,doc,track='',*,claim=True):
    where=plans.layout(root,claim=claim);path=document(root,where,doc);text=path.read_text()
    status=plans.approval(root,where,doc)
    if status!='approved':raise Refused(f'Design {doc} is {status}; delivery requires approved pending work')
    approvals={}
    if where['location']=='private':
        approvals[doc]=read_json(plans.approvals_file(root))[doc]
        delivered_base(root,approvals[doc],progressed=False)
    from .delivery_verify import authority,parsed
    approved=authority(root,where,path,text,approvals.get(doc))
    _,contract=parsed(approved['text']);_,current=parsed(text)
    if set(contract)!=set(current) or any(contract[n][2:]!=current[n][2:] for n in contract):
        raise Refused('The working design task contract differs from its approved source')
    rows=list(current.values());tracks={r[2] for r in rows}
    if where['location']=='private':delivered_base(root,approvals[doc],progressed=any(r[1]=='done' for r in rows))
    roadmap=plans.initiatives(root,where)
    named=[row for row in roadmap if row[3]==doc]
    if len(named)!=1:raise Refused('The design must belong to exactly one roadmap initiative')
    for dependency in filter(None,named[0][2].split(',')):
        required=dependencies(root,where,roadmap,dependency)
        if not required or any(not number or plans.approval(root,where,number)!='frozen' for number in required):
            raise Refused(f'Initiative {named[0][0]} depends on unfinished {dependency}')
        for number in required:
            if where['location']=='private':
                record=read_json(plans.approvals_file(root)).get(number,{})
                dependency_path=document(root,where,number)
                if record.get('path')!=str(dependency_path) or record.get('sha256')!=plans.digest_of(dependency_path):raise Refused(f'Completed dependency {dependency} changed since its approved delivery')
                delivered_base(root,record,progressed=True);approvals[number]=record
            freeze_render(root,number,layout=where)
    if len(tracks)>1 and not track and any(r[1]=='pending' for r in rows):raise Refused('Choose one design track: '+', '.join(sorted(tracks)))
    if track and track not in tracks:raise Refused('Unknown design track')
    # Working checkboxes cannot create completion authority. Only reviewed delivery records can.
    completed={n for n,row in contract.items() if row[1]=='done'}
    from .workflow import load_run
    try:
        _,saved=load_run(root)
        if saved.get('design')==doc:completed.update(saved['done'])
    except Refused:pass
    for n,row in current.items():
        if row[1]=='done' and n not in completed:raise Refused('Unrecorded task completion cannot grant subsequent work')
    tasks=[];available=set(completed)
    for row in rows:
        task_id,_,owner,needs,blocked,title=row
        if task_id in completed or (track and owner!=track):continue
        deps=set(filter(None,needs.split(',')))
        if blocked or not deps<=available:continue
        match=re.search(r'^- \[ \] \*\*'+re.escape(task_id)+r'\.\*\*.*?(?=^- \[[ x]\] \*\*\d+\.\*\*|^##|\Z)',text,re.M|re.S)
        if not match:raise Refused('Cannot extract the approved pending task')
        tasks.append({'id':task_id,'title':title,'instructions':match[0].strip(),'needs':sorted(deps-completed),
                      'design':str(path),'transition':{'profile':'delivery','doc':doc,'task':task_id}})
        available.add(task_id)
    if not tasks:
        if completed!=set(current):raise Refused('No ready pending tasks in this design or track')
        tasks=[{'id':'finalize','title':'Finalize the completed design',
                'instructions':'Verify the converged completed design and affected documentation. Prepare its frozen lifecycle candidate, run checks, and independently review it before completion.',
                'needs':[],'design':str(path),'transition':{'profile':'delivery','doc':doc,'task':'finalize'}}]
    if completed|{t['id'] for t in tasks}==set(current):
        tasks[-1]['instructions']+='\nThis is the last pending task. Update documentation and delivery-status claims made stale by this delivery without changing approved scope.'
    return ({'workflow':'deliver','design':doc,'track':track,'tasks':tasks},
            {'delivery':{'layout':plans.layout_snapshot(where),'inputs':inputs(where),'path':str(path),'doc':doc,
                         'status':status,'approvals':approvals,'authority':approved}})


def listing(root):
    result={'ready':[],'unavailable':[]}
    where=plans.layout(root,claim=False)
    if not Path(where['roadmap']).exists():return result
    for initiative in plans.initiatives(root,where):
        slug,_,_,doc=initiative
        if not doc:continue
        try:
            manifest,_=selection(root,doc,claim=False)
            result['ready'].append({'design':doc,'slug':slug,'tasks':manifest['tasks']})
        except Refused as exc:result['unavailable'].append({'design':doc,'slug':slug,'reason':str(exc)})
    return result
