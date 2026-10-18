"""Bind a native answer to a presented effect, without interpreting natural-language grants."""
from .storage import Refused, digest, now, read_json
from .workflow import load_run, next_task, review_limit


def boundary(root,state,kind,attempt=None):
    from .native import _subject
    value={k:state.get(k) for k in ('id','scope_id','branch')}
    # Resume transfers existing authority; settling an old child must not invalidate it.
    if kind not in ('resume','pause','stop'):
        value.update(_subject(root,state),done=state['done'],granted=state['granted'],
                     reviews=[a['id'] for a in state['attempts'] if a['role']=='review'],
                     grants=state.get('review_grants',[]),attempt=attempt)
    return value


def _checkpoint(root,state,kind,details):
    """Bind the native batch menu's existing actions; the host still owns its UI."""
    from .native import _active
    from .publication import destination,settled
    from .storage import changes
    if (kind not in ('continue','publish') or state['status'] not in ('checkpoint','completed')
            or not state['done'] or not state['summaries'] or _active(state)
            or state.get('plans',{}).get('location')=='private'):return None
    settled(state)
    pending=[t['id'] for t in state['tasks'] if t['id'] not in state['done']]
    if any(t in state['granted'] for t in pending):return None
    choices={}
    details+='\nCompleted tasks: '+', '.join(state['done'])
    if pending:
        choices['continue']='Continue with the next task batch'
        details+='\nContinue authorizes tasks: '+', '.join(pending[:state['config']['tasks_per_batch']])
    dest=destination(root)
    unavailable=None
    if dest and not changes(root) and state['summaries'][-1].get('commit')==state_head(root):
        from .branches import trunk
        dest=dest|{'base_branch':trunk(root,state['config'])}
        choices['publish']='Open PR with completed tasks'
        details+='\nRepository: '+dest['destination']+'\nBase branch: '+dest['base_branch']+'\nReviewed HEAD: '+state_head(root)
    else:
        dest=None
        unavailable='PR unavailable: completed work needs its clean reviewed HEAD and one origin push destination. Preserve local changes and resolve that prerequisite before publishing.'
        details+='\n'+unavailable
    choices['stop']='Stop and take over'
    details+='\nStop preserves local work and commits; it does not push or open a PR.'
    menu=list(choices.values())
    if len(menu)==1:menu.append('Not now')
    return {'question':details+'\n\nWhat would you like to do next?', 'choices':choices,
            'presentation':'checkpoint-menu','menu_options':menu,
            'coordinator':{k:state['human'][k] for k in ('host','session')},
            'checkpoint_status':state['status'],'publication_destination':dest,'unavailable':unavailable}


def prepare(root,kind,attempt=None,rounds=None,run=None,also=None):
    from .native import _locked, _home, _immutable, _attempt, _saved_subject, _active
    with _locked(root):
        journal,state=load_run(root,run)
        task=next_task(state|{'status':'running'}) or next((t for t in state['tasks'] if t['id'] not in state['done']),state['tasks'][-1])
        subject=_saved_subject(state)
        details=f'Work: {subject}\nBranch: {state["branch"]}'
        if kind=='grant-review':
            if _active(state):raise Refused('Retain the current native attempt before asking for more review allowance')
            count=state['config']['review_rounds'] if rounds is None else rounds
            if type(count) is not int or count<1:raise Refused('Review allowance must be a positive whole number')
            used=sum(a['role']=='review' and a['task']==task['id'] for a in state['attempts'])
            if used<review_limit(state,task['id']):raise Refused('Use the remaining review allowance before asking for more')
            label=f'Allow {count} additional review round'+('s' if count!=1 else '')
            details+=(f'\nTask: {task["title"]}\nReviews used: {used} of {review_limit(state,task["id"])}.'
                      f'\nConfigured renewal window: {state["config"]["review_rounds"]} review rounds.'
                      f'\nThis adds exactly {count} review round'+('s.' if count!=1 else '.'))
        elif rounds is not None:raise Refused('A review count belongs only to a review allowance decision')
        elif kind=='continue':
            ids=[t['id'] for t in state['tasks'] if t['id'] not in state['done']][:state['config']['tasks_per_batch']]
            if not ids or any(t in state['granted'] for t in ids):raise Refused('Use existing task authority before asking for another batch')
            label='Continue with the next task batch';details+='\nNext task batch: '+', '.join(ids)
        elif kind=='resume':label='Resume saved work';details+='\nExisting scope and remaining allowances stay the same.'
        elif kind=='pause':label='Pause the work'
        elif kind=='stop':label='Stop the work'
        elif kind=='accept-concerns':
            review=_attempt(state,attempt)
            if not any(f['severity']=='concern' for f in review.get('findings',[])):raise Refused('This review has no concerns to accept')
            label='Accept these concerns'
            count=sum(f['severity']=='concern' for f in review['findings'])
            details+=f'\nAccept the {count} concerns shown in the review report for this candidate, leaving them unfixed.'
        elif kind=='approve-proposal':
            _attempt(state,attempt)
            label='Apply these proposed additions';details+='\nApply the complete proposal preview shown above.'
        elif kind=='approve-private':
            review=_attempt(state,attempt)
            label='Approve this design';details+='\nDesign artifacts: '+', '.join(review.get('artifacts',{}))
        elif kind=='publish':
            from .publication import destination
            dest=destination(root)
            label='Open the pull request'
            if dest:details+='\nRepository: '+dest['destination']+'\nReviewed HEAD: '+state_head(root)
        else:raise Refused('Unknown consequential decision')
        if also is not None:
            if not isinstance(also,str) or not also.strip():raise Refused('The accompanying native action must be readable text')
            details+='\nRequested action: '+label+'\nAlso: '+also.strip()
            label='Approve both actions'
        value={'kind':kind,'run':state['id'],'attempt':attempt,'boundary':boundary(root,state,kind,attempt),
               'question':details+'\n\n'+label+'?','label':label,'created_at':now()}
        if kind=='grant-review':value['rounds']=count
        checkpoint=_checkpoint(root,state,kind,f'Work: {subject}\nBranch: {state["branch"]}') if also is None and attempt is None else None
        if checkpoint:value.update(checkpoint)
        elif kind=='publish' and not dest:destination(root,required=True)
        key=digest(value);_immutable(_home(root)/'decisions'/(key+'.json'),value)
        options=(value['menu_options'] if checkpoint else
                 [label,'Refine the proposal','Cancel'] if kind=='approve-proposal' else [label,'Refine the design','Cancel'] if kind=='approve-private' else [label,'Not now'])
        if len(options)==1:options.append('Not now')
        return {'decision':key,'question':value['question'],'options':options,
                **({'actions':{label:action for action,label in value['choices'].items()}} if checkpoint else {}),
                'human_locator':'Include decision in the native human locator. The native host displays this question; OH displays no menu.'}


def state_head(root):
    from .storage import git
    return git(root,'rev-parse','HEAD')


def verify(root,state,kind,locator,source,attempt=None,replay=False):
    from .native import _home
    import re
    key=locator.get('decision')
    if not isinstance(key,str) or not re.fullmatch(r'[0-9a-f]{64}',key):raise Refused('Prepare the consequential decision before presenting its native question')
    value=read_json(_home(root)/'decisions'/(key+'.json'))
    choices=value.get('choices')
    if (digest(value)!=key or (kind not in choices if choices else value['kind']!=kind)
            or value['run']!=state['id'] or value['attempt']!=attempt):
        raise Refused('This answer belongs to a different decision')
    question=source.get('question','')
    if value.get('presentation')=='checkpoint-menu' and source.get('via')=='question':
        if {k:source.get(k) for k in ('host','session')}!=value['coordinator']:
            raise Refused('This checkpoint belongs to its saved coordinator; resume the work before presenting a new checkpoint')
        shown=source.get('question_options')
        expected=value['menu_options']
        if not isinstance(shown,list) or len(shown)!=len(expected) or set(shown)!=set(expected):
            raise Refused('Use the complete single-select checkpoint menu; retain the prepared decision and all its choices')
    elif (question!=value['question'] if source.get('via')=='question' else value['question'] not in question):
        raise Refused('Use the actual native question for this prepared decision')
    # A short ordinary-chat Yes is valid only about this exact, already-bound question.
    label=choices[kind] if choices else value['label']
    accepted=(label.casefold(),) if choices else (label.casefold(),'yes','yes please')
    if source['prompt'].strip().casefold().rstrip('.!') not in accepted:
        raise Refused('This native answer does not accept the presented effect; preserve it and resolve the actual choice')
    from .authority import newer
    if not source.get('question_at') or not newer(source['question_at'],value['created_at']):
        raise Refused('This native question predates the prepared decision')
    if not replay:
        if value.get('presentation')=='checkpoint-menu' and {k:state['human'].get(k) for k in ('host','session')}!=value['coordinator']:
            raise Refused('This checkpoint coordinator changed; use the current saved-work decision')
        if value['boundary']!=boundary(root,state,value['kind'] if choices else kind,attempt):raise Refused('The decision subject changed; present the actual current effect before granting authority')
        if choices and value['checkpoint_status']!=state['status']:raise Refused('This checkpoint changed; present its current actions before continuing')
        if choices and kind=='publish':
            from .publication import destination
            from .branches import trunk
            if value['publication_destination']!=(destination(root,required=True)|{'base_branch':trunk(root,state['config'])}):
                raise Refused('The publication destination changed; present the current destination before publishing')
    return value|{'kind':kind,'label':label} if choices else value


def scope_request(root,scope):
    from .native import _home, _immutable
    titles='; '.join(t['title'] for t in scope['tasks'][:3])
    if len(scope['tasks'])>3:titles+=f'; and {len(scope["tasks"])-3} more tasks in the shown preview'
    question=(f'Scope: {titles}\nBranch: {scope["branch"]}\n'
              f'Task batch: {scope["config"]["tasks_per_batch"]}; review rounds per task: {scope["config"]["review_rounds"]}.\n\nApprove this scope?')
    value={'kind':'approve-scope','scope':digest(scope),'label':'Approve this scope','question':question,'created_at':now()}
    key=digest(value);_immutable(_home(root)/'decisions'/(key+'.json'),value)
    return {'decision':key,'question':question,'options':[value['label'],'Keep planning']}


def verify_scope(root,scope,locator,source):
    from .native import _home
    import re
    key=locator.get('decision')
    if not isinstance(key,str) or not re.fullmatch(r'[0-9a-f]{64}',key):raise Refused('Use the prepared scope approval question')
    value=read_json(_home(root)/'decisions'/(key+'.json'))
    if digest(value)!=key or value.get('kind')!='approve-scope' or value['scope']!=digest(scope):raise Refused('This answer belongs to another scope')
    question=source.get('question','')
    if (question!=value['question'] if source.get('via')=='question' else value['question'] not in question) or source['prompt'].strip().casefold().rstrip('.!') not in ('approve this scope','yes','yes please'):
        raise Refused('This answer does not approve the presented scope')
    from .authority import newer
    if not source.get('question_at') or not newer(source['question_at'],value['created_at']):raise Refused('This question predates the prepared scope')
