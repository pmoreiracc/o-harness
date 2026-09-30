"""Delivery selection and document progress; execution belongs to the shared runner."""
import hashlib
from pathlib import Path
import re
from . import plans
from .design_parse import freeze_render, plan
from .storage import Final, Refused, atomic_json, git, read_json


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


def progress_only(root,fork,paths,doc):
    """Whether the committed plans are origin/main's exactly, apart from ticks for the tasks of design `doc` that
    OH's runs on this branch completed, with nothing uncommitted. However the branch got there (OH's commits, a
    merge of main resolved by hand, the person rebasing or amending OH's commits), the plans can't say more: a
    message that merely claims to be OH's changes nothing."""
    from subprocess import CalledProcessError
    from .publication import trailer
    from .storage import Journal,project
    from .workflow import reduce
    if git(root,'diff','--name-only','HEAD','--',*paths):return False
    branch=git(root,'branch','--show-current');completed=set();scope={}
    try:
        for commit in git(root,'rev-list','--reverse','--no-merges',fork+'..HEAD').splitlines():
            try:state=reduce(Journal(project(root)['id'],trailer(root,commit,'OH-Run')).records())
            except Refused:continue
            if state.get('design')==doc and state['branch']==branch:
                completed|={done['task'] for done in state['summaries']}
                scope.update({key:record for key,record in state.get('scope_records',{}).items() if record['task'] in completed})
        for path in git(root,'diff','--name-only','origin/main','HEAD','--',*paths).splitlines():
            from .scope import undo_notes
            import subprocess
            text=subprocess.check_output(['git','-C',str(root),'show','HEAD:'+path]).decode()
            records=[r for r in scope.values() if r.get('destination',{}).get('design')==str(Path(root)/path)]
            # Notes already merged on main are part of its plan, not this branch's progress.
            base_text=subprocess.check_output(['git','-C',str(root),'show','origin/main:'+path]).decode()
            records=[r for r in records if r.get('change',{}).get('after','') not in base_text]
            if unticked(undo_notes(text,records),completed)!=base_text:return False
    except (CalledProcessError,KeyError,IndexError,Refused):return False
    return True


def unticked(text,tasks):
    """The design text with these tasks' checkboxes back to pending."""
    for task in tasks:
        text=re.sub(r'^- \[x\] \*\*'+re.escape(task)+r'\.\*\*',f'- [ ] **{task}.**',text,flags=re.M)
    return text


def finished(root,doc,track,branch,event):
    """A resumed delivery branch that already holds all its work goes to its pull request, as the pre-separation
    harness did: OH offers that run's PR choice again, even after the person stopped it, and never merges main
    into it or adds tasks. New tasks for the design are delivered after that pull request merges."""
    from .publication import made
    from .storage import checkout_id,project
    from .workflow import reopen
    where=plans.layout(root)
    rows=[row.split(plans.US) for row in plan(root,doc,where).splitlines()]
    if any(row[1]=='pending' and (not track or row[2]==track) for row in rows):return None
    if not track and plans.approval(root,where,doc)!='frozen':return None  # its finalize step is still to run
    refused=Final(f'{branch} already holds all of design {doc}, but OH did not make its last commit here, so OH '
                    'cannot offer its pull request; open one yourself')
    # Only the run that made this exact commit can offer its PR: an amended or rebased head is the person's.
    if not (state:=made(root,project(root)['id'],git(root,'rev-parse','HEAD'))):raise refused
    if ((state.get('design'),state.get('track') or '')!=(doc,track) or state['branch']!=branch
            or state['checkout']!=checkout_id(root) or state['status'] not in ('completed','stopped','pr')):raise refused
    return reopen(root,state,event)


def without_main(root):
    """Whether the person chose to finish the checkout's delivery branch without main's changes."""
    from .storage import checkout_file
    try:return read_json(checkout_file(root,'oh-without-main.json'))['branch']==git(root,'branch','--show-current')
    except FileNotFoundError:return False


def conflict(root,choice,doc,track=''):
    """Carry out the person's pick when their delivery branch conflicts with main. `keep` finishes the delivery
    without main's changes; `fresh` discards the branch, and any private progress it recorded, so the delivery
    starts over from main."""
    import os
    from .branches import delivery_branch,fetched,holder,run_git,trunk,untouched
    from .storage import checkout_file
    if os.environ.get('OH_CHILD_ATTEMPT'):raise Refused('Only the person decides what happens to their delivery')
    if choice not in ('fresh','keep'):raise Refused('The choice is fresh or keep')
    name=delivery_branch(doc,track)
    if run_git(root,'rev-parse','--verify','--quiet','refs/heads/'+name).returncode:raise Refused(f'There is no {name} branch')
    if elsewhere:=holder(root,name):raise Refused(f'{name} is checked out in {elsewhere}; choose there')
    untouched(root)
    base=fetched(root,trunk(root))
    marker=checkout_file(root,'oh-without-main.json')
    if choice=='keep':
        atomic_json(marker,{'branch':name,'base':git(root,'rev-parse',base)})
        return {'kept':name,'message':f'OH finishes {name} without {base}\'s changes; the conflicts are resolved when its pull request merges.'}
    from .workflow import active_file,load_run
    if active_file(root).exists() and (state:=load_run(root)[1])['branch']==name and state['status'] not in ('stopped','completed','pr'):
        raise Refused(f'OH is still working on {name}; stop that run first')
    where=plans.layout(root)
    if where['location']=='private':forget_progress(root,where,doc,name,base)
    if git(root,'branch','--show-current')==name:git(root,'switch','--quiet','--detach',base)
    git(root,'branch','-D',name)
    marker.unlink(missing_ok=True)
    return {'discarded':name,'message':f'{name} was discarded; the delivery starts over from {base}.'}


def forget_progress(root,where,doc,name,base):
    """Undo the private progress the discarded branch's runs recorded: untick their tasks and restore the approval
    from before them, which must match the untouched design exactly."""
    from .publication import trailer
    from .storage import Journal,project
    path=document(root,where,doc);records=read_json(plans.approvals_file(root))
    intents=[]
    from .branches import contained
    for commit in git(root,'rev-list','--reverse','--no-merges',git(root,'merge-base',name,base)+'..'+name).splitlines():
        try:run=trailer(root,commit,'OH-Run')
        except Refused:continue  # the person's own commit records no progress
        intents+=[r['data'] for r in Journal(project(root)['id'],run).records() if r['kind']=='delivery.approval.intent' and r['data'] not in intents]
    if not intents:return
    if records.get(doc)!=intents[-1]['after']:raise Refused(f'The private approval of design {doc} changed outside OH; restore it before starting over')
    # Progress whose code main already holds (a pull request merged or squashed) stays; the rest is undone.
    kept=max((index+1 for index,intent in enumerate(intents) if contained(root,base,intent['after']['delivery_commit'])),default=0)
    undo=intents[kept:]
    if not undo:return
    from .scope import undo_notes
    text=unticked(undo_notes(path.read_bytes().decode(),[r for i in undo for r in i.get('scope',[])]),{i['task'] for i in undo})  # bytes as saved: CRLF plans keep their hash
    if hashlib.sha256(text.encode()).hexdigest()!=undo[0]['before'].get('sha256'):
        raise Refused(f'Design {doc} changed beyond this delivery\'s progress; OH cannot start it over safely')
    plans.write(path,text)
    atomic_json(plans.approvals_file(root),records|{doc:undo[0]['before']})


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


def difficulty(block):
    """The difficulty the design gives a task on its `Difficulty: <level> — <why>` line, or nothing."""
    found=re.search(r'^[ \t]*Difficulty:[ \t]*(simple|standard|complex)\b[ \t—–:-]*(.*)$',block,re.M|re.I)
    return {'difficulty':found[1].lower(),'difficulty_reason':'Set by the design'+(': '+found[2].strip() if found[2].strip() else '')} if found else {}


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
        # The plans are origin/main's, apart from the progress OH's own reviewed commits recorded on a delivery
        # branch that is being resumed.
        fork=git(root,'merge-base','HEAD','origin/main')
        if git(root,'diff','--name-only',fork,'origin/main','--',*paths) or not progress_only(root,fork,paths,doc):
            if without_main(root):
                branch=git(root,'branch','--show-current')
                raise Final(f'Delivery {doc} stops here: main changed the plans since {branch} started, and main\'s code '
                            f'conflicts with it, so OH can\'t bring main in. The tasks done so far are saved on {branch}. '
                            'From here it\'s yours: merge main into it, resolve the conflicts and open the pull request '
                            'when you\'re ready.')
            if not git(root,'diff','--name-only',fork,'origin/main','--',*paths):
                raise Refused('The plans on this branch must be main\'s exactly, apart from ticks for the tasks OH '
                              'completed; restore their files to main\'s version with only those ticks, commit, and run again')
            raise Refused('The design and planning context must match origin/main; merge the plans first')
        for filename in inputs(where):
            relative=Path(filename).relative_to(root).as_posix()
            try:matches=git(root,'hash-object','--no-filters','--',relative)==git(root,'rev-parse','HEAD:'+relative)
            except CalledProcessError:matches=False
            if not matches:raise Refused('The design and planning context must match origin/main; merge the plans first')
    rows=[row.split(plans.US) for row in plan(root,doc,where).splitlines()]
    if any(len(row)!=6 for row in rows):raise Refused('Malformed design task projection')
    if where['location']=='private':
        approvals[doc]=read_json(plans.approvals_file(root))[doc]
        delivered_base(root,approvals[doc],progressed=any(row[1]=='done' for row in rows))
    tracks={row[2] for row in rows}
    if len(tracks)>1 and not track and any(row[1]=='pending' for row in rows):raise Refused('This design has several tracks; choose one: '+', '.join(sorted(tracks)))
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
    available=set(completed);tasks=[];text=path.read_bytes().decode()
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
                          'design':str(path),'transition':{'profile':'delivery','doc':doc,'task':task_id}}|difficulty(match[0]))
            available.add(task_id);pending.remove(row)
    if not tasks:
        if any(row[1]=='pending' for row in rows):raise Refused('No ready tasks in this design or track; resolve its dependencies or open questions')
        freeze_render(root,doc,layout=where)
        tasks=[{'id':'finalize','title':'Finalize the completed design','instructions':'Verify the completed design and affected documentation.',
                'design':str(path),'transition':{'profile':'delivery','doc':doc,'task':'finalize'}}]
    if not any(row[1]=='pending' and row[0] not in {t['id'] for t in tasks} for row in rows):
        tasks[-1]['instructions']+='\nThis is the last pending task across all tracks. Update documentation this delivery made outdated, including delivery-status claims; do not rewrite unrelated docs.'
    freeze_render(root,doc,'' if tasks[0]['id']=='finalize' else tasks[0]['id'],where)
    from .branches import main_ref
    base=main_ref(root)
    covers=unreviewed(root,git(root,'merge-base','HEAD',base),base) if base else []
    from .delivery_verify import authority
    approved=authority(root,where,path,text,approvals.get(doc))
    return ({'workflow':'deliver','design':doc,'track':track,'tasks':tasks},
            {'delivery':{'layout':plans.layout_snapshot(where),'inputs':inputs(where),'path':str(path),'doc':doc,'status':status,'approvals':approvals,'authority':approved}
                        |({'covers':covers} if covers else {})})


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
           'before_identity':plans.file_identity(path),'write_before':plans.file_identity(path)}
    if where['location']=='private':value['candidate']=str(journal.path/'delivery'/f'{task["id"]}.md')
    journal.append('delivery.render',value)
    plans.write(Path(value.get('candidate',path)),text)


def recover(root,state):
    if not state.get('delivery'):return
    render=state.get('delivery_render')
    if render:
        where=plans.layout(root)
        if plans.layout_snapshot(where)!=state['delivery']['layout']:raise Refused('Restore the delivery plan paths before recovery')
        actual=inputs(where);expected=render['after_inputs']
        if {p:h for p,h in actual.items() if p!=render['path']}!={p:h for p,h in expected.items() if p!=render['path']}:
            raise Refused('Plan documents changed outside this delivery run; preserve the edits and stop the run')
        if where['location']=='private':
            candidate=Path(render['candidate'])
            if not candidate.exists() or plans.file_identity(candidate)==render.get('write_before'):plans.write(candidate,render['text'])
            if plans.digest_of(candidate)!=render['after_inputs'][render['path']]:raise Refused('Delivery candidate changed outside the runner')
        elif plans.file_identity(Path(render['path']))==render.get('write_before',render['before_identity']):
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
        intent={'task':render['task'],'before':old,'after':after,
                'scope':[r for r in state.get('scope_records',{}).values() if r['task']==render['task'] and r.get('change')]}
        journal.append('delivery.approval.intent',intent)
    path=plans.approvals_file(root);records=read_json(path)
    if records.get(doc) not in (intent['before'],intent['after']):raise Refused('Private approval changed during delivery')
    expected=render['after_inputs'][render['path']]
    if plans.digest_of(Path(render['path']))!=expected:plans.write(Path(render['path']),render['text'])
    atomic_json(path,records|{doc:intent['after']})
