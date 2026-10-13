"""Independent review admission and the explicit handoff to prepared delivery.

The review pointer selects an operation, never replaces a saved delivery journal.
Actual agents, reports, cancellation and repairs use the shared runner.
"""
from pathlib import Path
import hashlib
import os
import re
import shlex
import subprocess

from .storage import (Refused, Journal, atomic_json, checkout_file, checkout_id, digest,
                      git, git_env, identifier, project, read_json, state_home, state_writer)


def input_path(root):
    resolved=Path(root).resolve()
    try:
        found=subprocess.run(['git','-C',str(resolved),'rev-parse','--show-toplevel'],
                             capture_output=True,text=True,env=git_env(),timeout=10)
        if found.returncode==0:resolved=Path(found.stdout.strip()).resolve()
    except (OSError,subprocess.TimeoutExpired):pass
    return state_home()/'review-inputs'/(digest(str(resolved))+'.json')


def remember_input(root,host,payload):
    """A passive locator, consumed only by the Review tool; never a pending workflow command."""
    from .workflow import human_event
    try:
        human_event(payload,host)
        atomic_json(input_path(root),{'host':host,'payload':payload})
    except (OSError,Refused):
        pass  # Optional discovery must not block an ordinary conversation.


def input_event(root):
    from .authority import attest,latest_answer,claude_history,newer
    path=input_path(root)
    if not path.exists():return None
    value=read_json(path)
    if value.get('menu_answer'):
        from .workflow import load_run
        from .gates import current,ask,native_ask,menu_record
        journal,state=load_run(root);identity=request_identity(value['menu_answer'])
        consumed=(state['source']==identity or any(request_identity(r['source'])==identity for r in requests(journal)))
        if not consumed:
            gate=current(root)
            question=((ask(gate) if value['host']=='claude' else native_ask(gate))['questions'][0]) if gate else None
            if question!=value['question'] or menu_record(journal,state)['at']!=value['since']:
                raise Refused('That decision moved on. Request review in the current conversation; no older reply was reused.')
    if value.get('menu_answer') and value['host']=='claude':
        if os.environ.get('CODEX_THREAD_ID'):raise Refused('This command belongs to another conversation; continue it there.')
        expected=value['menu_answer'];transcript=Path(expected['transcript_path']).resolve()
        if not transcript.is_relative_to((Path.home()/'.claude/projects').resolve()):raise Refused('Review input is outside native Claude records')
        found,_=latest_answer(transcript,expected['session'],root,value['question'],value['since'])
        if not found or found['record_hashes']!=expected['record_hashes']:raise Refused('The review request changed; use the current human request.')
        messages=claude_history(transcript,expected['session'])
        if messages and newer(messages[-1]['at'],found['at']):raise Refused('A newer message replaced this review request.')
        return found
    if value.get('menu_answer'):
        event=attest(value['host'],value['payload'],root)
        import json
        wrapped=re.fullmatch(r'<send_user_message_question_reply>\s*(.*?)\s*</send_user_message_question_reply>',event['prompt'],re.S)
        replies=json.loads(wrapped[1]) if wrapped else []
        if len(replies)!=1 or replies[0].get('answer')!=value['menu_answer']['prompt']:
            raise Refused('The native review request changed; use the current human request.')
        return event|{'prompt':replies[0]['answer']}
    return attest(value['host'],value['payload'],root)


def menu_request(root,event,question,since,*,payload=None):
    """A proven menu reply can request inspection without becoming a menu grant."""
    if not isinstance(event.get('prompt'),str) or not re.search(r'\breview\b',event['prompt'],re.I):return None
    atomic_json(input_path(root),{'host':event['host'],'menu_answer':event,'question':question,'since':since,
                                  **({'payload':payload} if payload else {})})
    return {'prepare_review':True,'intent':event['prompt'],'human':event,
            'next':'This is the person’s request, not a menu choice. Answer questions directly. If they requested an inspection, resolve its subject and call Review; do not repeat the old menu or grant implementation/publication.'}


def pointer(root):
    return checkout_file(root, 'oh-active-review.json')


def purpose(state):
    return 'standalone' if state.get('workflow') == 'review' else 'workflow'


def workflow_reviews(state, task):
    return [a for a in state['attempts'] if a['task'] == task and a['role'] == 'review'
            and a.get('purpose', 'workflow') == 'workflow']


def request_identity(event):
    return digest({k:event[k] for k in ('host','session','turn','prompt')})


def requests(journal):
    for record in journal.records():
        events=record['data']['events'] if record['kind']=='transition' else [record]
        for event in events:
            if event['kind']=='review.requested':yield event['data']


def subject(root, arguments):
    """Explicit selectors avoid guessing whether a number is a revision or a task."""
    words=shlex.split(arguments)
    feedback_only='--feedback-only' in words
    words=[w for w in words if w!='--feedback-only']
    if not words:raise Refused('Name the review subject: changes, tree, commit <ref>, range <base> <head>, paths <paths>, or task <id>.')
    kind=words.pop(0)
    from .verification import tree,candidate_tree
    current={'head':git(root,'rev-parse','HEAD'),'branch':git(root,'branch','--show-current'),'tree':tree(root)}
    if kind in ('changes','tree') and not words:
        target=candidate_tree(root);base=current['head']
    elif kind=='paths' and words:
        for name in words:
            path=Path(name)
            if path.is_absolute() or '..' in path.parts or not (Path(root)/path).exists():
                raise Refused('Review paths must exist inside the checkout: '+name)
        target=candidate_tree(root);base=current['head']
    elif kind=='commit' and len(words)==1:
        target=git(root,'rev-parse','--verify',words[0]+'^{commit}')
        parents=git(root,'rev-list','--parents','-n','1',target).split()[1:]
        base=parents[0] if parents else subprocess.check_output(['git','-C',str(root),'hash-object','-w','-t','tree','--stdin'],input=b'',env=git_env()).decode().strip()
    elif kind=='range' and len(words)==2:
        base,target=[git(root,'rev-parse','--verify',ref+'^{commit}') for ref in words]
    else:raise Refused('Use changes, tree, paths <paths>, commit <ref>, range <base> <head>, or task <id>.')
    return current|{'kind':kind,'base':base,'revision':target,'git_tree':git(root,'rev-parse',target+'^{tree}'),
                    'paths':words if kind=='paths' else [],'feedback_only':feedback_only,'description':arguments}


def capture(root, directory, selected):
    """Export exact Git blobs for both hosts; never check out a historical revision."""
    folder=Path(directory)/'subject';folder.mkdir(parents=True,exist_ok=True)
    files={};links=[]
    for entry in git(root,'ls-tree','-rz',selected['git_tree'],raw=True).split(b'\0'):
        if not entry:continue
        metadata,name=entry.split(b'\t',1);mode,kind,oid=metadata.split()
        name=name.decode('utf-8');path=Path(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name:
            raise Refused('Cannot safely export the review subject path: '+name)
        if kind!=b'blob':
            links.append(name+' (Git submodule; inspect its bound commit separately)');continue
        if mode==b'120000':
            links.append(name+' (symbolic link; not followed in the exported subject)');continue
        data=git(root,'cat-file','blob',oid.decode(),raw=True)
        destination=folder/path;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
        files[str(destination)]=hashlib.sha256(data).hexdigest()
    from .plans import file_identity
    manifest={'files':files,'identities':{p:file_identity(Path(p)) for p in files}}
    path=Path(directory)/'subject-files.json';atomic_json(path,manifest,immutable=True)
    return {'manifest':{'path':str(path),'hash':digest(manifest)},'limits':links,'root':str(folder)}


def artifact_content(artifact):
    if not artifact.get('manifest'):return artifact
    reference=artifact['manifest'];value=read_json(reference['path'])
    if digest(value)!=reference['hash']:raise Refused('The retained subject manifest changed; preserve it and request a fresh review.')
    return value


@state_writer
def start(root, arguments, event):
    from .workflow import active_file,load_run,reduce,settled_owner,checkpoint
    from .config import snapshot
    source=request_identity(event)
    if active_file(root).exists():
        _,saved=load_run(root)
        if saved['source']==source:return checkpoint(root)
    if re.fullmatch(r'task\s+\S+',arguments.strip()):
        return again(root,arguments.split()[1],event)
    with settled_owner(root):
        if active_file(root).exists():
            _,saved=load_run(root)
            if saved['status'] in ('running','pausing','stopping'):
                raise Refused('Stop or pause the active work before reviewing this checkout.')
            if pointer(root).exists() and saved['status'] not in ('completed','stopped'):
                raise Refused('Finish the pending review decision before starting another review.')
        selected=subject(root,arguments)
        p=project(root);run=identifier();config=snapshot(root)
        from .branches import incarnation
        data={'id':run,'project':p['id'],'name':p['name'],'work_kind':p['kind'],
              'host':event['host'],'checkout':checkout_id(root),'source':source,'human':event,
              'branch':selected['branch'],'incarnation':incarnation(root,selected['branch'],create=True) if selected['branch'] else None,
              'base':selected['head'],'workflow':'review','subject':selected,'checks':[],'project_checks':[],
              'tasks':[{'id':'review','title':'Review '+arguments,'instructions':event['prompt'],'needs':[]}],**config}
        journal=Journal(p['id'],run);journal.append('run.started',data)
        journal.append('grant',{'tasks':['review'],'source':source,'kind':'inspection','config_hash':data['config_hash']})
        atomic_json(pointer(root),{'project':p['id'],'run':run,'checkout':checkout_id(root)})
    from .telemetry import best_effort
    best_effort('run.started',p['id'],run,name=p['name'],work_kind=p['kind'],host=event['host'],
                version=data['harness_version'],config_hash=data['config_hash'])
    return checkpoint(root)


def dismiss_finished(root):
    """A new workflow can find the saved delivery after a terminal feedback operation."""
    from .registry import index_path
    if not index_path(root).is_file():return
    if not pointer(root).exists():return
    from .workflow import load_run
    _,state=load_run(root)
    if state['status'] in ('completed','stopped') and (state['workflow']=='review' or
            state.get('repair_source') and state['status']=='stopped' and not state['summaries']):
        pointer(root).unlink()


def result(root,journal,state):
    from .receipts import index
    index(journal,state)
    latest=state['attempts'][-1] if state['attempts'] else None
    value={'run':state['id'],'status':state['status'],'purpose':'standalone',
           'subject':state['subject']['description'],'report':str(journal.path/'index.md'),
           'next_action':{'kind':'finished' if state['status'] in ('completed','stopped') else 'review','phase':'review'},
           'continue_execution':False}
    from .workflow import running_progress
    value.update(running_progress(state,journal.path))
    if latest:
        value['last_review']={k:latest.get(k) for k in ('id','outcome','findings','human_summary','report_issues','summary')}
        valid=latest.get('outcome') in ('clean','blocking','needs_resolution') and not latest.get('report_issues')
        if state['status']=='completed' and valid and latest['findings'] and not state['subject']['feedback_only']:
            value.update(prepare=True,review_source=state['id'],next='Present these findings and prepare bounded fixes with prepare --review '+state['id']+'. The existing approval menu offers Approve fixes, Refine, or Keep as feedback. No repair is authorized yet.')
        elif state['status']=='completed' and not valid:
            value['next']='The review is incomplete; retain its findings and explain the reported cause. A new review needs a new human request.'
    return value


def repair_source(root, run):
    """Read-only eligibility; a completed review is input, not delivery authority."""
    from .workflow import reduce
    journal=Journal(project(root)['id'],run);state=reduce(journal.records())
    if state.get('workflow')!='review' or state['status']!='completed':raise Refused('Fix preparation requires a completed standalone review.')
    latest=state['attempts'][-1]
    if latest.get('outcome') not in ('blocking','needs_resolution') or not latest.get('findings') or latest.get('report_issues'):
        raise Refused('This receipt has no complete findings to prepare as repairs.')
    from .verification import tree
    current={'branch':git(root,'branch','--show-current'),'head':git(root,'rev-parse','HEAD'),'tree':tree(root)}
    # Historical findings are reconciled by the coordinator against the current source before preparing.
    if state['subject']['kind'] in ('changes','tree','paths') and any(current[k]!=state['subject'][k] for k in current):
        raise Refused('The reviewed work changed. Review the current work before preparing its fixes; your edits are retained.')
    from .storage import changes
    paths=state['subject']['paths']
    if paths and any(not any(name==p or name.startswith(p.rstrip('/')+'/') for p in paths) for name in changes(root)):
        raise Refused('Other uncommitted files are outside this review. Preserve them separately or review the complete change before approving a commit.')
    canonical=checkout_file(root,'oh-active-run.json')
    published_branch=False
    if canonical.exists():
        other=reduce(Journal(state['project'],read_json(canonical)['run']).records())
        published_branch=bool(other.get('published') and other['branch']==current['branch'])
        if other['status'] not in ('completed','stopped') and not other.get('published'):
            raise Refused('A delivery is still pending in this checkout. Keep this review as feedback and finish or stop that delivery before starting unrelated repairs.')
    from .branches import main_ref
    from .delivery import unreviewed
    base=main_ref(root)
    fork=git(root,'merge-base','HEAD',base) if base else current['head']
    covers=unreviewed(root,fork,base) if base else []
    return {'run':run,'attempt':latest['id'],'receipt':str(Path(latest['evidence'])/'result.json'),
            'hash':digest(read_json(Path(latest['evidence'])/'result.json')),'findings':latest['findings'],
            'subject':state['subject'],'starting_work':current,'files':changes(root),'covers':covers,
            'review_base':fork if covers else current['head'],'new_branch':published_branch}


def again(root, task_id, event):
    """Explicit additional review of completed, unpublished work; no task grant renewal."""
    from .workflow import load_run,settled_owner,owned,checkpoint,review_limit
    dismiss_finished(root)
    with settled_owner(root):
        journal,state=load_run(root)
        if any(request_identity(r['source'])==request_identity(event) for r in requests(journal)):
            result=checkpoint(root)
            return result|{'review_request_applied':True,'continue_execution':result['status']=='running' or bool(result['next_action'].get('resume'))}
        incomplete=state['status']=='needs_attention' and state.get('extra_review') and not state.get('correction')
        if state.get('correction'):raise Refused('Resume the current approved repair before requesting another completed-task review.')
        if state.get('workflow')!='deliver' or state.get('published') or not (state['status'] in ('checkpoint','completed','stopped') or incomplete):
            raise Refused('Task re-review requires an unpublished delivery at its saved decision. Use commit/range review for published work.')
        if task_id not in state['done']:raise Refused('Name a completed task in this delivery; unfinished tasks continue with Deliver.')
        owned(root,journal,state,event)
        request_again(root,journal,state,task_id,event)
    return checkpoint(root)


def request_again(root,journal,state,task_id,event):
    from .workflow import review_limit
    from .storage import changes
    from .delivery_verify import verify_run
    if changes(root) or git(root,'rev-parse','HEAD')!=state['summaries'][-1]['commit']:
        raise Refused('The completed delivery changed. Preserve those changes and review them explicitly before requesting a task re-review.')
    verify_run(root,state,current=True)
    source=request_identity(event);events=[]
    if len(workflow_reviews(state,task_id))>=review_limit(state,task_id):
        events.append({'kind':'review.grant','data':{'task':task_id,'source':source,'rounds':1}})
    original=next(d for d in state['summaries'] if d['task']==task_id)
    events.append({'kind':'review.requested','data':{'task':task_id,'source':event,'head':git(root,'rev-parse','HEAD'),
        'base':git(root,'rev-parse',original['commit']+'^'),'after':len(state['attempts']),
        'return_status':'completed' if len(state['done'])==len(state['tasks']) else 'checkpoint'}})
    events.extend([{'kind':'decision','data':{'source':source,'choice':'review again'}},
                   {'kind':'run.status','data':{'status':'running'}}])
    journal.append('transition',{'source':event,'events':events})


def finish_again(journal,state,last):
    """Return to the same boundary, or repair within the original task's scope."""
    request=state['extra_review']
    if last['outcome']=='clean' or last['id'] in state.get('resolutions',{}):
        journal.append('review.checked',{'task':request['task'],'review':last['id']})
        journal.append('run.status',{'status':request['return_status']})
    elif last['outcome']=='blocking':
        journal.append('correction.started',{'task':request['task'],'key':identifier(),
            'source_review':last['id'],'prior_commit':request['head'],'return_status':request['return_status']})
    elif last['outcome']=='needs_resolution':journal.append('run.status',{'status':'findings_checkpoint'})
    else:
        from .actions import external_failures
        from .workflow import review_limit
        reviews=workflow_reviews(state,request['task'])
        if external_failures(reviews,state):
            journal.append('run.status',{'status':'needs_attention','reason':'The reviewer could not run twice. Repair the reported host obstacle and resume; work and allowances are retained.'})
            return
        # Reuse the existing window and fresh-review path. This is a continuation
        # of the same human request, never another grant or an implementation retry.
        journal.append('review.requested',request|{'after':len(state['attempts'])})
        if len(reviews)>=review_limit(state,request['task']):
            journal.append('run.status',{'status':'review_checkpoint'})
