"""Delivery selection and document progress; execution belongs to the shared runner."""
import hashlib
from pathlib import Path
import re
from . import plans
from .design_parse import freeze_render, plan
from .storage import Refused, atomic_json, git, read_json


def parse(arguments):
    text=arguments.strip()
    if not text:return {'kind':'list'}
    match=re.fullmatch(r'([0-9]{4})(?:\s+([a-zA-Z0-9_-]+))?(?:\s+(request:[0-9a-f]{64}))?',text)
    if match:return {'kind':'design','doc':match[1],'track':match[2] or '', 'request':match[3]}
    if re.fullmatch(r'request:[0-9a-f]{64}',text):return {'kind':'request','request':text}
    if re.match(r'(?:[0-9]|request:)',text):raise Refused('Use /oh-deliver NNNN [track], or describe a quick fix')
    return {'kind':'quick_fix','intent':text,'authorized':False,'prepare':True,
            'next':'Propose a bounded task list for this fix, prepare it, and present its exact approval trigger and limits. Do not implement before approval.'}


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
            # Squash merges must contain every delivered path, with an inherited baseline.
            paths=[path for path in changed.split('\0') if path]
            if paths:git(root,'--literal-pathspecs','diff','--exit-code',commit,'HEAD','--',*paths)
    except CalledProcessError:
        raise Refused('Private plan progress belongs to code this checkout does not contain; use its delivery branch or merge it first') from None


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


def selection(root,doc,track='',*,claim=True):
    where=plans.layout(root,claim=claim);path=document(root,where,doc)
    status=plans.approval(root,where,doc)
    if status!='approved':raise Refused(f'Design {doc} is {status or "missing a status"}; delivery requires approval')
    approvals={}
    if where['location']=='repo':
        from subprocess import CalledProcessError
        paths=[Path(where[key]).relative_to(root).as_posix() for key in ('roadmap','designs','decisions')]
        try:git(root,'rev-parse','--verify','origin/main^{commit}')
        except CalledProcessError:raise Refused('Fetch origin/main before delivering repository plans') from None
        if git(root,'diff','--name-only','origin/main','--',*paths):
            raise Refused('The design and planning context must match origin/main; merge the plans first')
        for filename in inputs(where):
            relative=Path(filename).relative_to(root).as_posix()
            try:matches=git(root,'hash-object','--no-filters','--',relative)==git(root,'rev-parse','origin/main:'+relative)
            except CalledProcessError:matches=False
            if not matches:raise Refused('The design and planning context must match origin/main; merge the plans first')
    rows=[row.split(plans.US) for row in plan(root,doc,where).splitlines()]
    if any(len(row)!=6 for row in rows):raise Refused('Malformed design task projection')
    if where['location']=='private':
        approvals[doc]=read_json(plans.approvals_file(root))[doc]
        delivered_base(root,approvals[doc],progressed=any(row[1]=='done' for row in rows))
    tracks={row[2] for row in rows}
    if track and track not in tracks:raise Refused('Unknown design track; choose '+', '.join(sorted(tracks)))
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
                if record.get('path')!=str(dependency_path) or record.get('sha256')!=plans.digest_of(dependency_path):
                    raise Refused(f'Completed dependency {dependency} changed since its approved delivery')
                delivered_base(root,record,progressed=True)
                approvals[number]=record
            freeze_render(root,number,layout=where)  # a frozen label with pending tasks is not delivery
    completed={row[0] for row in rows if row[1]=='done'}
    available=set(completed);tasks=[];text=path.read_text()
    pending=[row for row in rows if row[1]=='pending' and (not track or row[2]==track)]
    # A stable topological selection permits ready work despite an unrelated blocked task.
    while pending:
        ready=[row for row in pending if not row[4] and set(filter(None,row[3].split(',')))<=available]
        if not ready:break
        for row in ready:
            task_id,_,owner,needs,_,title=row
            match=re.search(r'^- \[ \] \*\*'+re.escape(task_id)+r'\.\*\*.*?(?=^- \[[ x]\] \*\*\d+\.\*\*|^##|\Z)',text,re.M|re.S)
            if not match:raise Refused('Cannot extract the approved design task')
            tasks.append({'id':task_id,'title':title,'instructions':match[0].strip(),
                          'needs':sorted(set(filter(None,needs.split(',')))-completed),
                          'design':str(path),'transition':{'profile':'delivery','doc':doc,'task':task_id}})
            available.add(task_id);pending.remove(row)
    if not tasks:
        if any(row[1]=='pending' for row in rows):raise Refused('No ready tasks in this design or track; resolve its dependencies or open questions')
        freeze_render(root,doc,layout=where)
        tasks=[{'id':'finalize','title':'Finalize the completed design','instructions':'Verify the completed design and affected documentation.',
                'design':str(path),'transition':{'profile':'delivery','doc':doc,'task':'finalize'}}]
    freeze_render(root,doc,'' if tasks[0]['id']=='finalize' else tasks[0]['id'],where)
    return ({'workflow':'deliver','design':doc,'track':track,'tasks':tasks},
            {'delivery':{'layout':plans.layout_snapshot(where),'inputs':inputs(where),'path':str(path),'doc':doc,'approvals':approvals}})


def listing(root):
    from .prepared import limits
    from .config import load
    where=plans.layout(root,claim=False);result={'kind':'list','ready':[],'unavailable':[]}
    if not Path(where['roadmap']).exists():return result
    for slug,_,_,doc in plans.initiatives(root,where):
        if not doc:continue
        try:
            manifest,_=selection(root,doc,claim=False)
            result['ready'].append({'design':doc,'slug':slug,'tasks':[{'id':t['id'],'title':t['title']} for t in manifest['tasks']],
                                    'command':'/oh-deliver '+doc,'limits':limits(len(manifest['tasks']),load(root))})
        except Refused as exc:result['unavailable'].append({'design':doc,'slug':slug,'reason':str(exc)})
    return result


def guard(root,state):
    """Accept only the run's admitted context or its recorded, deterministic progress edit."""
    if not state.get('delivery'):return
    where=plans.layout(root);bound=state['delivery'];render=state.get('delivery_render')
    if plans.layout_snapshot(where)!=bound['layout']:raise Refused('Plan paths changed during delivery; restore them or stop the run')
    expected=render['after_inputs'] if render else bound['inputs']
    actual=inputs(where)
    pending=render and where['location']=='private' and render['task'] not in state['done']
    if actual!=expected and not (pending and actual==render['before_inputs']):
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


def render(root,journal,state,task):
    guard(root,state)
    previous=state.get('delivery_render')
    if previous and previous['task']==task['id']:return
    where=plans.layout(root);path=Path(state['delivery']['path']);before=inputs(where)
    text=freeze_render(root,state['delivery']['doc'],'' if task['id']=='finalize' else task['id'],where)
    after=before|{str(path):hashlib.sha256(text.encode()).hexdigest()}
    value={'task':task['id'],'path':str(path),'text':text,'before_inputs':before,'after_inputs':after,
           'before_identity':plans.file_identity(path)}
    if where['location']=='private':value['candidate']=str(journal.path/'delivery'/f'{task["id"]}.md')
    journal.append('delivery.render',value)
    plans.write(Path(value.get('candidate',path)),text)


def recover(root,state):
    if not state.get('delivery'):return
    render=state.get('delivery_render')
    if render:
        where=plans.layout(root)
        if plans.layout_snapshot(where)!=state['delivery']['layout']:raise Refused('Restore the delivery plan paths before recovery')
        if where['location']=='private':
            candidate=Path(render['candidate'])
            if not candidate.exists():plans.write(candidate,render['text'])
            if plans.digest_of(candidate)!=render['after_inputs'][render['path']]:raise Refused('Delivery candidate changed outside the runner')
        elif inputs(where)==render['before_inputs']:
            if plans.file_identity(Path(render['path']))!=render['before_identity']:raise Refused('Plan identity changed before delivery recovery')
            plans.write(Path(render['path']),render['text'])
    guard(root,state)


def reviewed(root,state,review):
    guard(root,state)
    if not state.get('delivery') or state['delivery']['layout']['location']!='private':return
    artifact=review.get('artifact') or {}
    render=state.get('delivery_render')
    if not render or artifact.get('files')!={render['candidate']:render['after_inputs'][render['path']]}:
        raise Refused('The review does not bind the private delivery progress')
    if artifact.get('identities')!={render['candidate']:plans.file_identity(Path(render['candidate']))}:
        raise Refused('Private delivery candidate changed after review')
    identity=plans.file_identity(Path(render['path']))
    if identity not in (render['before_identity'],render['before_identity']|{'hash':render['after_inputs'][render['path']]}):
        raise Refused('Private design identity changed after review')


def finish(root,journal,state,review):
    """Journal the exact approval update after the reviewed commit, before either private write."""
    reviewed(root,state,review)
    if not state.get('delivery') or state['delivery']['layout']['location']!='private':return
    doc=state['delivery']['doc'];render=state['delivery_render'];intent=state.get('delivery_approval')
    if not intent or intent['task']!=render['task']:
        old=intent['after'] if intent else state['delivery']['approvals'][doc]
        head=git(root,'rev-parse','HEAD');base=old.get('delivery_base',state['base'])
        after=old|{'sha256':render['after_inputs'][render['path']], 'delivery_commit':head,
                   'delivery_base':base,'delivery_baseline':old.get('delivery_baseline',state['base']),
                   'delivery_no_code':not bool(git(root,'diff','--name-only',base,head))}
        intent={'task':render['task'],'before':old,'after':after}
        journal.append('delivery.approval.intent',intent)
    path=plans.approvals_file(root);records=read_json(path)
    if records.get(doc) not in (intent['before'],intent['after']):raise Refused('Private approval changed during delivery')
    expected=render['after_inputs'][render['path']]
    if plans.digest_of(Path(render['path']))!=expected:plans.write(Path(render['path']),render['text'])
    atomic_json(path,records|{doc:intent['after']})
