"""Focused evidence/admissibility helpers. Native skills, never this module, run agents."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import re
from . import authority
from .config import snapshot, project_checks
from .storage import (Journal, Refused, atomic_json, checkout_file, checkout_id, digest,
                      git, identifier, lock, now, project, read_json, state_home, whole, changes)
from .verification import tree, candidate_tree, check_failed
from .workflow import load_run, reduce, next_task, review_limit, validate_tasks, committed
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


def _render_attempt(journal,state,attempt):
    directory=Path(attempt['evidence'])
    from .receipts import completed,index
    records=journal.records();end=next((n for n,r in enumerate(records) if r['kind']=='attempt.finished' and r['data'].get('id')==attempt['id']),None)
    original=reduce(records[:end+1]) if end is not None else state
    report=read_json(directory/'result.json');source=read_json(directory/'native-result.json')
    completed(directory,read_json(directory/'request.json'),{'structured':report,'text':source.get('text','')},attempt,original)
    index(journal,state)


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


def _owner(root,state):
    authority.coordinator(root,state)
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


def prepare_scope(root, manifest=None, doc=None, track='', workflow='deliver', human=None):
    """Snapshot an explicit scope. Preparing delivery is never its approval."""
    from .entry import enroll
    if blocked:=enroll(root):raise Refused(blocked['onboarding'])
    if workflow not in ('deliver','design','propose'):raise Refused('Unknown workflow')
    if doc is not None:
        if manifest is not None:raise Refused('Choose approved design selection or a task manifest')
        from .delivery import selection
        manifest,extra=selection(root,doc,track)
    else:extra={}
    if not isinstance(manifest,dict):raise Refused('Supply a task manifest or approved design number')
    tasks=validate_tasks(manifest.get('tasks'));config=snapshot(root)
    if workflow=='deliver' and not project_checks(root):raise Refused('Register this project’s existing verification checks before delivery')
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
    from .prepared import limits
    preview='\n\n'.join([f"# {workflow.title()} scope",limits(len(tasks),value['config']),*[f"## {t['id']}. {t['title']}\n\n{t['instructions']}" for t in tasks]])+'\n'
    if value['starting_edits']:
        preview+='\n## Included starting edits\n\n'+', '.join('`'+name+'`' for name in value['starting_edits'])+'\n\nContents fingerprint: `'+value['starting_tree']+'`.\n'
    if target:=value.get('pr_target'):
        preview+=f"\n## Included original PR work\n\n{target['url']}\n\nReview the original range `{target['review_base']}..{target['head']}` together with the repair candidate.\n"
        if target.get('covers'):preview+='\nIncluded original commits: '+', '.join('`'+c+'`' for c in target['covers'])+'.\n'
    elif original:=value.get('original_work'):
        preview+=f"\n## Included original branch work\n\nReview `{original['review_base']}..{original['head']}` together with the task candidate.\n\nIncluded original commits: "+', '.join('`'+c+'`' for c in original['covers'])+'.\n'
    from .receipts import save
    save(folder/'scope.md',preview,immutable=True)
    result={'scope_id':key,'preview':str(folder/'scope.md'),'tasks':[{k:t[k] for k in ('id','title')} for t in tasks],'config':value['config'],'approved':False}
    if human is not None:
        source=authority.native_human(root,human)
        prompt=source['prompt'].strip()
        linked=re.fullmatch(r'\[(\$(?:o-harness:)?oh-[a-z]+)\]\([^\r\n]*SKILL\.md\)(.*)',prompt,re.S)
        if linked:prompt=linked[1]+linked[2]
        parsed=authority.typed_command('/'+prompt[1:] if prompt.startswith('$') else prompt)
        request=(parsed[0].removeprefix('oh-'),parsed[1]) if parsed else None
        if request and request[0]!=workflow:raise Refused('This native request selects a different workflow; it grants no authority here')
        if workflow=='deliver' and doc is not None:
            from .delivery import parse
            selected=parse(request[1]) if request else None
            if selected and (selected.get('kind'),selected.get('doc'),selected.get('track'))!=('design',doc,track):raise Refused('The native request selects a different design or track')
            if not selected:
                text=source['prompt'].strip()
                direct=re.match(r'(?i)^(?:(?:can|could|would) you |please )?(?:deliver|implement|build|finish)\b',text)
                contextual=source.get('via')=='question' and re.search(r'(?i)\b(?:deliver|implement)\b',source.get('question',''))
                if not (direct or contextual) or not re.search(r'(?<![0-9])'+re.escape(doc)+r'(?![0-9])',text):raise Refused('Request delivery of this approved design explicitly before admitting its task batch')
        if workflow!='deliver' or doc is not None:return _start(root,key,source)|{'scope_id':key,'approved':True}
    return result


def approve_scope(root, scope_id, locator):
    scope=_scope(root,scope_id)
    from .workflow import active_file
    if active_file(root).exists():
        _,current=load_run(root)
        if current.get('scope_id')==scope_id:
            original=authority.native_human(root,locator,latest=False)
            if digest({k:original[k] for k in ('host','session','turn','prompt')})==current.get('source'):
                return select(root)
    source=authority.native_human(root,locator,since=scope['created_at'],subject=_home(root)/'scopes'/scope_id/'scope.md')
    if source.get('via')=='plan':
        preview=(_home(root)/'scopes'/scope_id/'scope.md').read_text()
        if source.get('accepted_plan','').replace('\r\n','\n')!=preview:
            raise Refused('The person accepted changed scope. Preserve the accepted plan and prepare its actual tasks; the old task projection is not approved.')
    if source.get('via')!='plan' and not _affirmed(source['prompt'],'approve',source.get('question','')):
        raise Refused('The native human reply did not approve this scope; no work was granted')
    authority.coordinator(root,{'human':source,'host':source['host']},locator)
    return _start(root,scope_id,source)


def _start(root,key,source):
    scope=_scope(root,key)
    with _locked(root):
        from .workflow import active_file
        if active_file(root).exists():
            journal,prior=load_run(root)
            if prior.get('scope_id')==key:return select(root)
            if _active(prior):raise Refused('A native attempt still owns this checkout; stop it through its host first')
            unused=(prior['status']=='prepared_checkpoint' and not prior['granted'] and not prior['attempts'] and not prior.get('activation'))
            if unused:journal.append('run.status',{'status':'stopped','reason':'Superseded unused preparation; no execution authority was granted'})
            elif prior['status'] not in ('stopped','completed','pr'):raise Refused('Finish or stop the saved scope before admitting different work')
        if (git(root,'rev-parse','HEAD'),git(root,'branch','--show-current'))!=(scope['base'],scope['branch']):
            raise Refused('Prepared scope belongs to a different base/branch; prepare against the intended current work')
        if scope.get('starting_tree')!=tree(root):
            raise Refused('The included starting contents changed after scope preparation. Preserve the edits and prepare the same tasks again to show their current contents before approval.')
        from .branches import trunk
        if committed(scope) and scope['branch']==trunk(root,scope['config']):raise Refused('Create an execution branch from the selected base with native Git tools, then prepare scope on that branch')
        source_key=digest({k:source[k] for k in ('host','session','turn','prompt')})
        p=project(root);run=identifier()
        from .branches import incarnation
        data={'id':run,'project':p['id'],'name':p['name'],'work_kind':p['kind'],'checkout':checkout_id(root),
              'host':source['host'],'human':source,'source':source_key,'native_version':2,
              'scope_id':key,'scope_snapshot':scope,'workflow':scope['workflow'],'tasks':scope['tasks'],
              'design':scope.get('design'),'track':scope.get('track'),'base':scope['base'],'branch':scope['branch'],
              'incarnation':incarnation(root,scope['branch'],create=True),'checks':[],
              **{k:scope[k] for k in ('config','config_hash','harness_version','project_checks')},
              **{k:scope[k] for k in ('delivery','plans') if k in scope}}
        if source.get('accepted_plan') is not None:data['accepted_scope']=source['accepted_plan']
        data.update({k:scope[k] for k in ('repair_source','pr_target','covers','original_work') if k in scope})
        journal=Journal(p['id'],run);journal.append('run.started',data)
        best_effort('run.started',p['id'],run,name=p['name'],work_kind=p['kind'],host=source['host'],version=data['harness_version'],config_hash=data['config_hash'])
        _immutable(journal.path/'scope'/'scope.json',scope)
        _immutable(journal.path/'scope'/'approval.json',source)
        if data.get('accepted_scope'):
            from .receipts import save
            save(journal.path/'scope'/'accepted.md',data['accepted_scope'],immutable=True)
        journal.append('grant',{'tasks':[t['id'] for t in scope['tasks'][:scope['config']['tasks_per_batch']]],'source':source_key,'kind':'initial','config_hash':scope['config_hash']})
        atomic_json(checkout_file(root,'oh-active-run.json'),{'project':p['id'],'run':run,'checkout':checkout_id(root)})
        checkout_file(root,'oh-active-review.json').unlink(missing_ok=True)
        return select(root)


def select(root):
    journal,state=load_run(root);task=next_task(state)
    current=task or next((t for t in reversed(state['tasks']) if t['id'] in state['done']),state['tasks'][-1])
    history=[a for a in state['attempts'] if a['task']==current['id']]
    checked=state.get('verification',{}).get(current['id'])
    attempts=[]
    for attempt in history[-2:]:
        item={k:attempt.get(k) for k in ('id','task','role','profile','outcome','finished','evidence','model_fallback')}
        item['summary']=str(attempt.get('summary',''))[:800]
        if attempt.get('native_child'):item['native_child']={'child_session':attempt['native_child']['child_session']}
        attempts.append(item)
    result={k:state.get(k) for k in ('id','status','workflow','design','track','branch','scope_id','published')}
    result.update(run=state['id'],task={k:task[k] for k in ('id','title')} if task else None,
                  granted=state['granted'],done=state['done'],attempts=attempts,attempt_count=len(state['attempts']),
                  scope=str(journal.path/'scope'/'scope.json') if state.get('native_version') and state.get('scope_id') else None,
                  report=str(journal.path/'report.md') if (journal.path/'report.md').is_file() else None,journal=str(journal.path),
                  supplementary={'count':len(state.get('supplementary',[])),'path':str(journal.path/'evidence'/'index.json') if (journal.path/'evidence'/'index.json').is_file() else None})
    if checked:
        result['verification']={k:checked.get(k) for k in ('task','head','tree','git_tree','at')}
        result['verification']['passed']=not any(check_failed(c) for c in checked['checks'])
        result['verification']['checks']=[{k:c[k] for k in ('name','returncode','cancellation','unavailable') if k in c} for c in checked['checks']]
    reviews=[a for a in history if a['role']=='review' and a.get('purpose','workflow')=='workflow']
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
        result={k:result[k] for k in ('run','status','task','report','attempt_count','reviews_used','reviews_allowed','done_count','granted_count') if k in result}
    if len(encode(result))>state['config']['context']['result_chars']:result={'run':state['id'],'status':state['status'],'attempt_count':len(state['attempts'])}
    return result


def _repeated_family(state,task):
    from .handoff import family_identity
    reviews=[a for a in state['attempts'] if a['task']==task and a['role']=='review' and a.get('finished')]
    seen=set()
    for attempt in reviews:
        families={family_identity(f) for f in attempt.get('findings',[]) if f['severity']=='blocking'}
        if seen&families:return True
        seen|=families
    return False


def admit(root,role):
    if role not in ('assessment','implementation','analysis','review'):raise Refused('Unknown native agent role')
    with _locked(root):
        journal,state=load_run(root);_owner(root,state)
        if state['status']!='running':raise Refused('This scope is not running; retain existing work and resolve its actual state')
        if _active(state):raise Refused('Retain the current native attempt before admitting another')
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
            authors=[a for a in state['attempts'] if a['task']==task['id'] and a['role'] in ('implementation','analysis') and a.get('finished')]
            if not state.get('extra_review') and (not authors or authors[-1]['outcome']!='implemented'):
                raise Refused('Finish the approved task before requesting its independent review')
            checked=state.get('verification',{}).get(task['id'])
            if not checked or any(checked.get(k)!=subject[k] for k in ('head','tree','git_tree','artifacts')) or any(check_failed(c) for c in checked['checks']):
                raise Refused('Run final configured checks on this candidate before admitting review')
            used=sum(a['role']=='review' and a['task']==task['id'] and a.get('purpose','workflow')=='workflow' for a in state['attempts'])
            if used>=review_limit(state,task['id']):raise Refused('This task’s review allowance is spent; only a native human grant renews it')
        level='review' if role=='review' else 'complex' if _repeated_family(state,task['id']) else assessment['difficulty'] if assessment else 'standard'
        requested=state['config']['models'][state['host']][level]
        from .capabilities import select_profile
        profile,fallback=select_profile(state['host'],requested,root)
        attempt_id=identifier();directory=journal.path/'attempts'/attempt_id
        admission={'id':attempt_id,'task':task['id'],'role':role,'profile':profile,'purpose':'standalone' if state['workflow']=='review' else 'workflow',
                   'evidence':str(directory),'config_hash':state['config_hash'],'root':str(Path(root).resolve()),'run':state['id'],**subject}
        if state['workflow']=='review':
            selected=state['standalone_subject']
            admission['standalone_subject']={k:selected[k] for k in ('kind','base','revision','git_tree','description') if k in selected}
            admission['checkout_guard']=subject
        if fallback:admission['model_fallback']=fallback
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
        if task['id'] not in state['task_started']:
            best_effort('task.started',state['project'],state['id'],task['id'],title=task['title'],difficulty=(assessment or {}).get('difficulty'),rubric=2)
        best_effort('attempt.started',state['project'],state['id'],task['id'],attempt_id,role=role,phase=role,host=state['host'],**profile)
        return {k:admission[k] for k in ('id','task','role','profile','head','tree','git_tree','task_context','model_fallback','standalone_subject') if k in admission}|{'request':str(directory/'request.json'),'native_task_name':'oh_'+attempt_id.replace('-',''),'fresh_context':True,'fork_turns':'none'}


def bind(root,attempt_id,locator):
    with _locked(root):
        journal,state=load_run(root);_owner(root,state);attempt=_attempt(state,attempt_id)
        if attempt.get('finished'):raise Refused('A completed attempt cannot be reused')
        value=authority.native_child(root,state,attempt,locator)
        for other in state['attempts']:
            if other['id']!=attempt_id and other.get('native_child',{}).get('child_session')==value['child_session']:
                raise Refused('Every attempt needs a fresh native child')
        if attempt.get('native_child'):
            if attempt['native_child']!=value:raise Refused('The original child binding cannot be replaced')
        else:
            journal.append('native.child.bound',{'attempt':attempt_id,'child':value})
            best_effort('attempt.native',state['project'],state['id'],attempt['task'],attempt_id,child_session=value['child_session'],host=state['host'])
        return value


def _report(text):
    for candidate in (text,text.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()):
        try:value=json.loads(candidate)
        except (ValueError,TypeError):continue
        if isinstance(value,dict):return value
    findings=[]
    # Ignore fenced examples, while accepting a report wrapped in one outer fence.
    readable=text.strip()
    lines=readable.splitlines(keepends=True)
    opening=re.match(r'^\s*(`{3,}|~{3,})',lines[0]) if lines else None
    if opening and len(lines)>1 and re.fullmatch(r'\s*'+re.escape(opening[1])+r'\s*',lines[-1]) and not any(re.fullmatch(r'\s*'+re.escape(opening[1])+r'\s*',line) for line in lines[1:-1]):
        lines=lines[1:-1]
    visible=[];fence=None
    for line in lines:
        marker=re.match(r'^\s*(`{3,}|~{3,})',line)
        if fence:
            if marker and marker[1][0]==fence[0] and len(marker[1])>=len(fence):fence=None
            visible.append('\n')
        elif marker:fence=marker[1];visible.append('\n')
        else:visible.append(line)
    readable=''.join(visible)
    # Unknown finding-like headings keep their positions as incomplete fragments.
    starts=list(re.finditer(r'(?im)^\s*(?:[-*#]\s*)*(?:`?\[(BLOCKING|CONCERN|SCOPE|(?-i:[A-Z][A-Z_-]*))\](?!\()`?\s*:?|(BLOCKING|CONCERN|SCOPE)\s*:)\s*(.+)$',readable))
    labels={'anchor':'anchor','rule':'anchor','where':'path','location':'path','path':'path',
            'failure':'failure','why':'failure','fix':'fix','correction':'fix','smallest correction':'fix',
            'family':'family','defect family':'family','relation':'relation'}
    for number,match in enumerate(starts):
        end=starts[number+1].start() if number+1<len(starts) else len(readable)
        body=readable[match.end():end]
        finding={'severity':(match[1] or match[2]).lower(),'description':match[3].strip('* `'),'path':''}
        for field in re.finditer(r'(?im)^\s*(?:[-*]\s*)?\*{0,2}([A-Za-z -]+)\*{0,2}\s*:\*{0,2}\s*(.*)$',body):
            key=labels.get(field[1].strip().casefold())
            if key:
                finding[key]=field[2].strip('* ')
                if key=='family':
                    from .handoff import family_fields
                    finding.update(family_fields(finding[key]))
        finding.setdefault('family',finding['description']);findings.append(finding)
    assessment=re.search(r'(?im)^\s*difficulty\s*:\s*(simple|standard|complex)\b',text)
    result={'summary':text,'findings':findings}
    if re.search(r'(?im)^\s*(?:[*# ]*verdict\s*[:\u2014-]\s*)?(?:clean\b|no findings\b)',readable):result['verdict']='clean'
    if assessment:result.update(difficulty=assessment[1].lower(),rationale=text)
    return result


def retain(root,attempt_id,locator):
    with _locked(root):
        journal,state=load_run(root);attempt=_attempt(state,attempt_id)
        if attempt.get('finished'):
            _render_attempt(journal,state,attempt)
            return attempt
        source=authority.native_result(root,state,attempt,locator)
        directory=Path(attempt['evidence']);_immutable(directory/'native-result.json',source)
        text=source.get('text','');report=_report(text)
        _immutable(directory/'result.json',report)
        raw_findings=report.get('findings',[])
        findings=[];positions=[];fragments=[]
        for position,finding in enumerate(raw_findings if isinstance(raw_findings,list) else [raw_findings],1):
            if isinstance(finding,dict) and finding.get('severity') in ('blocking','concern','scope') and isinstance(finding.get('description'),str):
                findings.append(finding);positions.append(position)
            else:fragments.append({'position':position,'finding':finding})
        malformed=not isinstance(raw_findings,list) or len(findings)!=len(raw_findings)
        for finding in findings:
            finding.setdefault('family',finding['description']);finding.setdefault('path','')
        if source.get('status')!='completed':outcome=source.get('status','failed')
        elif malformed and not findings:
            outcome='review_incomplete' if attempt['role']=='review' else 'unfinished'
        else:
            outcome='implemented'
            if attempt['role']=='review':
                if any(f['severity']=='blocking' for f in findings):outcome='blocking'
                elif malformed:outcome='review_incomplete'
                elif findings:outcome='needs_resolution'
                elif report.get('verdict')=='clean' or re.search(r'(?im)^\s*(?:[*# ]*verdict\s*[:—-]\s*)?(?:clean\b|no findings\b)',text):outcome='clean'
                else:outcome='review_incomplete'
            elif attempt['role']=='assessment':outcome='assessed' if report.get('difficulty') in ('simple','standard','complex') else 'unfinished'
            elif report.get('status') in ('blocked','unfinished'):outcome=report['status']
        try:
            subject=_subject(root,state)
            packet=read_json(Path(attempt['evidence'])/'task-context.json')
            if digest(packet)!=read_json(Path(attempt['evidence'])/'request.json')['task_context']['hash']:raise Refused('Admitted task packet changed')
            if packet.get('details'):
                detail=read_json(Path(attempt['evidence'])/packet['details']['path'])
                if digest(detail)!=packet['details']['hash']:raise Refused('Admitted task details changed')
                packet=detail
            for reference in packet.get('supplementary_evidence',[]) if isinstance(packet.get('supplementary_evidence'),list) else []:_unchanged(reference['files'])
        except Refused:
            subject={};outcome='binding_failed'
        if attempt['role'] in ('review','assessment') and any(subject.get(k)!=attempt[k] for k in ('head','tree','git_tree','artifacts')):
            outcome='binding_failed'
        result={k:attempt[k] for k in ('id','task','role','profile','purpose','head','tree','git_tree','artifacts','evidence')}
        result.update(outcome=outcome,summary=str(report.get('summary') or text)[:state['config']['context']['result_chars']],findings=findings,
                      duration_ms=source.get('duration_ms'),native_source=source.get('record_hashes',[]))
        if malformed:
            result.update(finding_positions=positions,review_fragments=fragments,
                          report_issues=['Some findings could not be classified; inspect the retained original positions and fragments.'])
        if source.get('status')=='binding_failed':
            result['native_failure']={k:source.get(k) for k in ('native_id','tool_use_id','profile','admitted_profile','requested_profile','requested_context','binding_issues','terminal_status')}
        if attempt['role'] in ('implementation','analysis'):result.update(subject)
        journal.append('attempt.finished',result)
        best_effort('attempt.finished',state['project'],state['id'],attempt['task'],attempt_id,outcome=outcome,duration_ms=source.get('duration_ms'),substantive=bool(text))
        _render_attempt(journal,reduce(journal.records()),_attempt(reduce(journal.records()),attempt_id))
        from .receipts import index
        if outcome=='assessed':journal.append('task.assessed',{'task':attempt['task'],'attempt':attempt_id,'difficulty':report['difficulty'],'rationale':report.get('rationale','Native assessment')})
        if state['workflow']=='review':
            journal.append('run.status',{'status':'completed'})
            best_effort('task.finished',state['project'],state['id'],attempt['task'],status='feedback',wall_ms=None)
            best_effort('run.status',state['project'],state['id'],status='completed')
        elif state.get('extra_review') and attempt['role']=='review' and outcome in ('blocking','needs_resolution') and not state.get('correction'):
            extra=state['extra_review']
            journal.append('correction.started',{'task':attempt['task'],'prior_commit':extra['prior_commit'],'return_status':extra['return_status'],'key':attempt['task']+'-correction-'+attempt_id})
        index(journal,reduce(journal.records()))
        return result


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


def candidate(root):
    with _locked(root):
        journal,state=load_run(root)
        active=_active(state)
        if active:
            import os
            caller=os.environ.get('CODEX_THREAD_ID') or os.environ.get('OH_NATIVE_SESSION_ID')
            if len(active)!=1 or active[0]['role'] not in ('implementation','analysis') or not active[0].get('native_child') or caller and active[0]['native_child']['child_session']!=caller:
                raise Refused('Only the bound author may prepare the active candidate')
        else:_owner(root,state)
        task=next_task(state)
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


def verify(root,base=None,mode='review'):
    journal,state=load_run(root);task=next_task(state)
    if not task:raise Refused('No granted pending task to verify')
    if state['status'] not in ('running','paused'):raise Refused('Saved work is not available for verification')
    before=_subject(root,state)
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
    after=_subject(root,state)
    if before!=after:raise Refused('Checks changed the candidate; inspect those changes and verify the final candidate again')
    value={'task':task['id'],**after,'checks':results,'at':now()}
    with _locked(root):journal.append('verification',value)
    return value


def _intents(text):
    text=re.sub(r'\((?:recommended|default)\)','',text,flags=re.I).casefold()
    result=set()
    patterns={'publish':r'\b(?:publish|ship|open\s+(?:a\s+|the\s+)?(?:pr|pull request))\b',
              'pause':r'\bpause\b','stop':r'\bstop\b','resume':r'\bresume\b',
              'continue':r'\bcontinue\b',
              'grant-review':r'\b(?:grant|allow|renew)\b.*\breview',
              'accept-concerns':r'\baccept\b.*\bconcerns?\b',
              'route-scope':r'\broute\b.*\bscope\b','dismiss-scope':r'\bdismiss\b.*\bscope\b',
              'approve':r'\bapprove\b|\baccept(?:ed)?\s+(?:the\s+)?(?:plan|scope|proposal|design)\b'}
    for kind,pattern in patterns.items():
        if re.search(pattern,text):result.add(kind)
    if text.strip() in ('accept','accepted','approve','approved'):result.add('approve')
    return result


def _positive_actions(text):
    text=re.sub(r'\((?:recommended|default)\)','',text,flags=re.I).strip().casefold().rstrip('.!')
    linked=re.fullmatch(r'\[(\$(?:o-harness:)?oh-[a-z]+)\]\([^\r\n]*skill\.md\)(.*)',text,re.S)
    if linked:text=linked[1]+linked[2]
    command=re.fullmatch(r'[$/](?:o-harness:)?oh-(resume|pause|stop)',text)
    if command:text=command[1]
    text=re.sub(r'^please\s+|\s+please$','',text)
    patterns={
        'approve':r'(?:approve|accept)(?: (?:the|this) (?:scope|plan|proposal|design))?',
        'publish':r'(?:open (?:a |the )?(?:pr|pull request)|publish(?: (?:the |this )?(?:reviewed |approved )?(?:work|changes))?)',
        'continue':r'continue(?: with (?:the )?next task window)?',
        'grant-review':r'grant(?: another| next)? review window|grant review',
        'accept-concerns':r'accept(?: these| the)? concerns',
        'route-scope':r'route(?: the)? scope(?: to https?://\S+)?',
        'dismiss-scope':r'dismiss(?: the)? scope',
        'pause':r'pause(?: (?:the )?work)?',
        'stop':r'stop(?: now| and take (?:it )?over)?|keep (?:the )?work local',
        'resume':r'resume(?: the approved work)?'}
    whole={kind for kind,pattern in patterns.items() if re.fullmatch(pattern,text)}
    if len(whole)==1:return whole
    pieces=re.split(r'\s+and\s+',text)
    result=set()
    for piece in pieces:
        found={kind for kind,pattern in patterns.items() if re.fullmatch(pattern,piece)}
        if len(found)!=1:return set()
        result.update(found)
    if len(result)>1 and not result<={'accept-concerns','route-scope','dismiss-scope'}:return set()
    if {'route-scope','dismiss-scope'}<=result:return set()
    return result


def _affirmed(text,kind,question=''):
    expected='approve' if kind in ('approve-private','approve-proposal') else kind
    positive=_positive_actions(text)
    if positive:return expected in positive
    generic=re.sub(r'[.!]','',text.strip().casefold()) in ('yes','yes please','proceed','proceed with the task')
    if not generic or re.search(r"\b(?:not|never|no|don't|reject|decline)\b",question,re.I):return False
    context=_intents(question)
    return expected in context and (len(context)==1 or context<={'accept-concerns','route-scope','dismiss-scope'})


def decision(root,kind,locator,attempt=None,destination=None):
    allowed={'continue','grant-review','accept-concerns','dismiss-scope','route-scope','publish','pause','stop','resume','approve-private','approve-proposal'}
    if kind not in allowed:raise Refused('Unknown consequential decision')
    with _locked(root):
        journal,state=load_run(root)
        since=journal.records()[0]['at']
        if attempt:since=_attempt(state,attempt).get('finished_at') or since
        elif kind in ('publish','continue','grant-review','resume'):
            relevant=[a.get('finished_at') for a in state['attempts'] if a.get('finished_at')]
            relevant += [r['at'] for r in journal.records() if r['kind'] in ('task.completed','run.status','transition')]
            since=max(relevant+[since])
        subject_path=None
        if kind in ('accept-concerns','dismiss-scope','route-scope','approve-proposal'):
            subject_path=Path(_attempt(state,attempt)['evidence'])/'result.json'
        elif kind=='approve-private':
            reviewed=_attempt(state,attempt)
            artifacts=reviewed.get('artifacts',{})
            design_folder=Path(state.get('plans',{}).get('designs',''))
            designs=[name for name in artifacts if Path(name).parent==design_folder]
            subject_path=Path(designs[0]) if len(designs)==1 else Path(reviewed['evidence'])/'result.json'
        source=authority.native_human(root,locator,subject=subject_path,latest=False)
        if state.get('published'):return select(root)
        if not _affirmed(source['prompt'],kind,source.get('question','')):raise Refused('The native human reply does not authorize this decision')
        key=digest({k:source[k] for k in ('host','session','turn','prompt')})
        if key in state['decisions']:
            if kind not in ('accept-concerns','dismiss-scope','route-scope'):return select(root)
            effect_used=False
            for record in journal.records():
                entries=record['data'].get('events',[]) if record['kind']=='transition' else [{'kind':record['kind'],'data':record['data']}]
                if any(e['kind']=='decision' and e['data'].get('source')==key and e['data'].get('choice')==kind for e in entries):effect_used=True
            if effect_used:return select(root)
        source=authority.native_human(root,locator,subject=subject_path)
        authority.coordinator(root,state,locator)
        if not authority.newer(source.get('at'),since):raise Refused('This human decision predates the current subject or allowance boundary')
        subject=_subject(root,state);events=[]
        def add(name,value):events.append({'kind':name,'data':value})
        task=next_task(state|{'status':'running'}) or next((t for t in state['tasks'] if t['id'] not in state['done']),state['tasks'][-1])
        if kind=='continue':
            if _active(state):raise Refused('A task grant cannot replace an active attempt')
            ids=[t['id'] for t in state['tasks'] if t['id'] not in state['done']][:state['config']['tasks_per_batch']]
            if any(t in state['granted'] for t in ids):raise Refused('Existing task authority must be used before granting another window')
            add('grant',{'tasks':ids,'source':key,'kind':'continue','config_hash':state['config_hash']});add('run.status',{'status':'running'})
        elif kind=='grant-review':
            used=sum(a['role']=='review' and a['task']==task['id'] for a in state['attempts'])
            if used<review_limit(state,task['id']):raise Refused('Existing review allowance is not spent')
            add('review.grant',{'task':task['id'],'rounds':state['config']['review_rounds'],'source':key})
        elif kind in ('accept-concerns','dismiss-scope','route-scope'):
            review=_attempt(state,attempt)
            if review['role']!='review' or review.get('purpose','workflow')!='workflow' or review['outcome'] not in ('blocking','needs_resolution'):
                raise Refused('This decision requires retained workflow findings')
            severities={f['severity'] for f in review.get('findings',[])}
            if kind=='accept-concerns' and ('blocking' in severities or any(review[k]!=subject[k] for k in ('head','tree','git_tree','artifacts'))):
                raise Refused('Concern acceptance requires the current exact candidate with no blockers')
            prior=state.get('resolutions',{}).get(attempt,{})
            accepted=bool(prior.get('concerns_accepted'))
            scope=prior.get('scope')
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
            scope_done='scope' not in severities or scope is not None
            concern_done='concern' not in severities or accepted
            choice='partial disposition'
            if scope_done and concern_done:
                parts=[]
                if accepted:parts.append('accept concerns')
                if scope:parts.append('dismiss scope' if scope['action']=='dismiss' else 'route scope')
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
            if state.get('plans',{}).get('location')!='private' or review['outcome']!='clean' or any(review[k]!=subject[k] for k in ('head','tree','git_tree','artifacts')):raise Refused('Private approval requires the exact reviewed private artifact')
            add('native.private.approved',{'attempt':attempt,'source':source,'artifacts':subject['artifacts']})
        elif kind=='publish':
            from .publication import settled
            settled(state)
            if _active(state) or changes(root):raise Refused('Publication requires completed work on its clean reviewed head')
            from .publication import destination as publication_destination,commits,made
            from .branches import main_ref,trunk
            dest=publication_destination(root,required=True)|{'base_branch':trunk(root,state['config'])}
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
            if _active(state):raise Refused('A native attempt still owns this work; retain its terminal result before transfer')
            add('run.owner',{'human':source});add('run.status',{'status':'running'})
        if kind!='publish':add('decision',{'choice':kind,'source':key,'head':subject['head'],'scope':state.get('scope_id'),'attempt':attempt})
        journal.append('transition',{'events':events})
        for event in events:
            if event['kind']=='run.status':best_effort('run.status',state['project'],state['id'],status=event['data']['status'])
        from .receipts import index
        index(journal,reduce(journal.records()))
        return select(root)


def complete(root,attempt_id):
    with _locked(root):
        journal,state=load_run(root);_owner(root,state);review=_attempt(state,attempt_id)
        task=next((t for t in state['tasks'] if t['id']==review['task']),None)
        existing=next((d for d in state['summaries'] if d.get('review')==attempt_id),None)
        if existing:return existing
        correction=state.get('correction')
        if state.get('extra_review') and not correction:
            if review['role']!='review' or review.get('purpose')!='workflow' or review['outcome']!='clean':raise Refused('Additional review remains unresolved')
            subject=_subject(root,state)
            if any(subject[k]!=review[k] for k in ('head','tree','git_tree','artifacts')):raise Refused('Additional review no longer covers current work')
            from .publication import task_evidence
            task_evidence(root,state,task,review,subject['head'])
            journal.append('review.checked',{'attempt':attempt_id})
            journal.append('run.status',{'status':state['extra_review']['return_status']})
            return {'review':attempt_id,'outcome':'clean','committed':False}
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
        if not checked or any(checked.get(k)!=subject[k] for k in ('head','tree','git_tree','artifacts')) or any(check_failed(c) for c in checked['checks']):
            raise Refused('Passing verification does not cover the final candidate')
        if state['workflow']=='propose' and not any(a.get('choice')=='approve' for a in state.get('proposal_answers',[])):
            raise Refused('The proposed additions were not approved before writing')
        if state['workflow']=='design' and state.get('plans',{}).get('location')=='private' and state.get('private_native_approval',{}).get('attempt')!=attempt_id:
            raise Refused('The human must approve the exact reviewed private plan')
        from .publication import task_evidence,validate_evidence
        evidence=intent['publication'] if recovered else task_evidence(root,state,task,review,subject['head'])
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
            journal.append('correction.completed',value);journal.append('run.status',{'status':correction['return_status']})
        else:
            journal.append('task.completed',value)
            current=reduce(journal.records())
            if len(current['done'])==len(current['tasks']):journal.append('run.status',{'status':'completed'})
            elif not next_task(current):journal.append('run.status',{'status':'checkpoint'})
        best_effort('task.finished',state['project'],state['id'],task['id'],status='completed',wall_ms=None,expected_attempts=sum(a['task']==task['id'] for a in state['attempts']),expected_reviews=sum(a['role']=='review' and a['task']==task['id'] for a in state['attempts']))
        best_effort('run.status',state['project'],state['id'],status=reduce(journal.records())['status'])
        from .receipts import index
        index(journal,reduce(journal.records()))
        return value


def resume(root,locator=None):
    from .workflow import active_file
    review_pointer=checkout_file(root,'oh-active-review.json')
    canonical=checkout_file(root,'oh-active-run.json')
    if active_file(root)==review_pointer:
        with _locked(root):
            _,feedback=load_run(root)
            if feedback['workflow']=='review' and feedback['status']=='completed':
                if not canonical.exists():return select(root)
                saved=read_json(canonical)
                if saved['checkout']!=checkout_id(root) or saved['project']!=project(root)['id']:
                    raise Refused('Saved delivery belongs to another checkout or project')
                reduce(Journal(saved['project'],saved['run']).records())
                review_pointer.unlink()
    journal,state=load_run(root)
    if state.get('published'):return select(root)
    if locator is not None and not state.get('native_version'):
        source=authority.native_human(root,locator)
        authority.coordinator(root,state,locator)
        with _locked(root):
            from .controls import busy
            if busy(root) or _active(state):raise Refused('A legacy attempt is unsettled; finish its native host cleanup before adoption')
            if state['status'] not in ('stopped','paused','completed','checkpoint','needs_attention'):raise Refused('Stop legacy work at a quiescent boundary before native adoption')
            if git(root,'branch','--show-current')!=state['branch']:raise Refused('Return to the saved execution branch before adoption')
            documents={}
            if state.get('delivery'):
                bound=state['delivery'];documents[bound['path']]=(bound.get('authority') or {}).get('start_text',Path(bound['path']).read_text())
            scope={k:state.get(k) for k in ('tasks','config','config_hash','harness_version','base','branch','workflow','design','track','project_checks','delivery','plans')}
            scope.update(schema=2,documents=documents,checkout=checkout_id(root),created_at=journal.records()[0]['at'])
            key=digest(scope);_immutable(_home(root)/'scopes'/key/'scope.json',scope)
            _immutable(journal.path/'scope'/'scope.json',scope)
            journal.append('native.adopted',{'native_version':2,'scope_id':key,'scope_snapshot':scope})
    if locator is not None:return decision(root,'resume',locator)
    return select(root)


def review(root,arguments,human=None):
    import shlex
    if isinstance(arguments,list):arguments=shlex.join(arguments)
    source=authority.native_human(root,human) if human is not None else None
    from .entry import enroll
    if blocked:=enroll(root):raise Refused(blocked['onboarding'])
    from .review import subject,capture
    words=__import__('shlex').split(arguments)
    if len(words)==2 and words[0]=='task':
        with _locked(root):
            journal,state=load_run(root);_owner(root,state)
            if state.get('published') or state['workflow']!='deliver' or state['status'] not in ('completed','checkpoint','stopped') or words[1] not in state['done']:
                raise Refused('Task review requires completed unpublished work from this delivery')
            if _active(state):raise Refused('Retain the current attempt before additional review')
            saved=next(d for d in reversed(state['summaries']) if d['task']==words[1])
            selected_task=next(t for t in state['tasks'] if t['id']==words[1])
            journal.append('review.requested',{'task':words[1],'return_status':state['status'],'prior_commit':saved['commit']})
            journal.append('run.status',{'status':'running'})
            current=reduce(journal.records());current_subject=_subject(root,current)
            checked=state.get('verification',{}).get(words[1])
            if checked and checked.get('git_tree')==current_subject['git_tree']:
                journal.append('verification',checked|current_subject)
            return select(root)
    selected=subject(root,arguments)
    host=source['host'] if source else 'codex' if __import__('os').environ.get('CODEX_THREAD_ID') else 'claude'
    session=source['session'] if source else __import__('os').environ.get('CODEX_THREAD_ID') or __import__('os').environ.get('OH_NATIVE_SESSION_ID')
    if not session:raise Refused('Native standalone review needs its current host session identity')
    from .workflow import active_file
    if active_file(root).exists():
        _,prior=load_run(root)
        if _active(prior):raise Refused('A native attempt owns this checkout; retain its terminal result before standalone review')
    p=project(root);run=identifier();config=snapshot(root);journal=Journal(p['id'],run)
    source=source or {'host':host,'session':session,'turn':identifier(),'prompt':arguments}
    data={'id':run,'project':p['id'],'name':p['name'],'work_kind':p['kind'],'checkout':checkout_id(root),'host':host,'human':source,
          'source':digest(source),'workflow':'review','native_version':2,'branch':selected['branch'],'base':selected['head'],'incarnation':'standalone',
          'tasks':[{'id':'review','title':selected['description'],'instructions':'Inspect the exact selected subject; feedback only.'}],
          'checks':[],'project_checks':[],'standalone_subject':selected,**config}
    data['subject']=selected
    data['standalone_artifact']=capture(root,journal.path/'standalone',selected)
    journal.append('run.started',data)
    best_effort('run.started',p['id'],run,name=p['name'],work_kind=p['kind'],host=host,version=config['harness_version'],config_hash=config['config_hash'])
    journal.append('grant',{'tasks':['review'],'source':digest(source),'kind':'standalone','config_hash':config['config_hash']})
    atomic_json(checkout_file(root,'oh-active-review.json'),{'project':p['id'],'run':run,'checkout':checkout_id(root)})
    return select(root)
