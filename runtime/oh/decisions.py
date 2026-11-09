"""Bind a native answer to a presented effect, without interpreting natural-language grants."""
from .storage import Refused, digest, now, read_json
from .workflow import load_run, next_task, review_limit

TAKE_OVER = 'Stop and take over'


def boundary(root,state,kind,attempt=None):
    from .native import _subject
    value={k:state.get(k) for k in ('id','scope_id','branch')}
    # Resume transfers existing authority; settling an old child must not invalidate it.
    if kind not in ('resume','pause','stop'):
        value.update(_subject(root,state),done=state['done'],granted=state['granted'],
                     reviews=[a['id'] for a in state['attempts'] if a['role']=='review'],
                     grants=state.get('review_grants',[]),attempt=attempt)
        if kind=='approve-repair':value['recovery_decision']=state.get('recovery_decision')
    if state.get('approved_repairs') and kind not in ('pause','stop'):value['approved_repairs']=state['approved_repairs']
    return value


def stop_boundary(root,journal,state):
    from .native import _selection_boundary
    return boundary(root,state,'stop')|{'status':state['status'],'owner':digest(state['human']),
                                        'selection':_selection_boundary(journal)}


def save_offer(root,value,*,details=None,details_title='View all affected paths'):
    from .native import _home, _immutable
    if 'menu_options' in value:value['menu_version']=2
    if details:
        from .receipts import save
        path=_home(root)/'decisions'/('decision-'+digest(value)+'.md')
        save(path,details,immutable=True)
        value['details_file']={'path':str(path),'hash':digest(details)}
        value['disclosure']+='\n['+details_title+'](<'+path.as_posix()+'>)'
    key=digest(value)
    _immutable(_home(root)/'decisions'/(key+'.json'),value)
    if 'disclosure' in value:
        from .storage import atomic_json, checkout_file
        atomic_json(checkout_file(root,'oh-recovery-menu.json'),{'decision':key,'menu_version':2,'kind':value['kind'],'question':value['question'],
                    'options':value['menu_options'],'disclosure':value['disclosure'],'created_at':value['created_at']})
    return key


def repair_task(root,state):
    """Additional repair authority supplements one unfinished delivery task."""
    from .native import _active, _idle
    task=next_task(state)
    if state.get('workflow')!='deliver' or not task or task['id'] in state['done'] or state.get('extra_review') or state.get('correction'):
        raise Refused('Resume the unfinished delivery task before proposing its supporting repair')
    _idle(root)
    if _active(state):raise Refused('Retain the current worker result before proposing the additional repair')
    if state['commit_intents'].get(task['id']):raise Refused('Settle the existing reviewed commit with complete before selecting further work')
    return task


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
    from .delivery import checkpoint_progress
    details+=checkpoint_progress(state)
    if pending:
        batch=pending[:state['config']['tasks_per_batch']]
        choices['continue']=('Start task ' if len(batch)==1 else 'Start tasks ')+', '.join(batch)
        details+='\nContinue authorizes tasks: '+', '.join(pending[:state['config']['tasks_per_batch']])
    dest=destination(root)
    unavailable=None
    if dest and not changes(root) and state['summaries'][-1].get('commit')==state_head(root):
        from .branches import trunk
        dest=dest|{'base_branch':trunk(root,state['config'])}
        choices['publish']='Open PR to '+dest['destination'].removeprefix('https://github.com/').removesuffix('.git')+' → '+dest['base_branch']
        details+='\nRepository: '+dest['destination']+'\nBase branch: '+dest['base_branch']+'\nReviewed HEAD: '+state_head(root)
    else:
        dest=None
        unavailable='PR unavailable: completed work needs its clean reviewed HEAD and one origin push destination. Preserve local changes and resolve that prerequisite before publishing.'
        details+='\n'+unavailable
    choices['stop']=TAKE_OVER
    details+='\nStop preserves local work and commits; it does not push or open a PR.'
    menu=list(choices.values())
    completed=('Task ' if len(state['done'])==1 else 'Tasks ')+', '.join(state['done'])
    question=f'{completed} finished on {state["branch"]}. What would you like to do next?'
    if len(menu)==1:question=f'{completed} finished on {state["branch"]}. Hand off this work?'
    return {'disclosure':details, 'question':question, 'choices':choices,
            'presentation':'checkpoint-menu','menu_options':menu,
            'coordinator':{k:state['human'][k] for k in ('host','session')},
            'checkpoint_status':state['status'],'publication_destination':dest,'unavailable':unavailable}


def prepare(root,kind,attempt=None,rounds=None,run=None,also=None,repair=None,request=None,after=None):
    from .native import _locked, _attempt, _saved_subject, _active
    with _locked(root):
        journal,state=load_run(root,run)
        entry_request=None
        if request is not None:
            if kind not in ('recover','resume','stop'):raise Refused('Retain an initiating request only for its recovery/continuation prerequisite')
            from .entry import request_source
            entry_request=request_source(root,request,after)
            entry_request={k:v for k,v in entry_request.items() if k not in ('prerequisite_human','prerequisite')}
        elif after is not None:raise Refused('A prerequisite identity requires its initiating request locator')
        if repair is not None and kind!='approve-repair':raise Refused('A repair description belongs to approve-repair')
        if kind=='recover':
            from .recovery import prepare
            return prepare(root,state,entry_request,stop_boundary=stop_boundary(root,journal,state))
        task=next_task(state|{'status':'running'}) or next((t for t in state['tasks'] if t['id'] not in state['done']),state['tasks'][-1])
        subject=_saved_subject(state)
        reference='Saved run: '+state['id']
        details=f'Work: {subject}\nBranch: {state["branch"]}\n{reference}'
        if entry_request:
            from .entry import request_description
            details+='\nAfter this prerequisite, continue the initiating request: '+request_description(entry_request)
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
        elif kind=='approve-repair':
            task=repair_task(root,state)
            if attempt is not None or also is not None:raise Refused('Present the supporting repair as one complete decision')
            if not isinstance(repair,str) or not repair.strip():raise Refused('Describe the bounded supporting repair and why it needs additional approval')
            label='Approve repair and continue'
            details+=(f'\nTask: {task["id"]} — {task["title"]}\nSupporting repair: {repair.strip()}'
                      '\nContinue this same task with the repair included. Original tasks, required checks, remaining review allowance and publication authority stay unchanged.')
        elif kind=='continue':
            ids=[t['id'] for t in state['tasks'] if t['id'] not in state['done']][:state['config']['tasks_per_batch']]
            if not ids or any(t in state['granted'] for t in ids):raise Refused('Use existing task authority before asking for another batch')
            label='Continue with the next task batch';details+='\nNext task batch: '+', '.join(ids)
        elif kind=='resume':label='Resume saved work';details+='\nExisting scope and remaining allowances stay the same.'
        elif kind=='pause':label='Pause the work'
        elif kind=='stop':label=TAKE_OVER
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
            label+=' and '+also.strip()
        value={'kind':kind,'run':state['id'],'attempt':attempt,'boundary':boundary(root,state,kind,attempt),
               'question':details+'\n\n'+label+'?','label':label,'created_at':now()}
        if entry_request:value['entry_request']=entry_request
        if kind=='grant-review':value['rounds']=count
        if kind=='approve-repair':value.update(task=task['id'],repair=repair.strip())
        compact_details=details.replace('\n'+reference,'',1)
        checkpoint=_checkpoint(root,state,kind,compact_details) if also is None and attempt is None else None
        if checkpoint:value.update(checkpoint,bound_question=True)
        elif kind=='publish':
            from .branches import trunk
            value['publication_destination']=destination(root,required=True)|{'base_branch':trunk(root,state['config'])}
        actions={}
        if checkpoint:
            options=value['menu_options']
            actions={choice:action for action,choice in value['choices'].items()}
        elif kind in ('approve-proposal','approve-private'):
            options=[label,'Refine the proposal' if kind=='approve-proposal' else 'Refine the design','Cancel']
        elif kind=='accept-concerns':
            options=[label,'Fix concerns']
        elif kind=='stop':
            options=[label]
            actions={label:kind}
            value.update(disclosure=compact_details+'\nStop preserves local work and existing grants.',
                         question=f'Hand off {subject} on {state["branch"]}?',menu_options=options)
        else:
            options=[label,TAKE_OVER]
            actions={label:kind,TAKE_OVER:'stop'}
            value['takeover']=True
        if not checkpoint and kind!='stop':
            title=f'{label} for {subject}?'
            if kind=='accept-concerns':title=f'How should we handle the findings for {subject}?'
            if kind=='approve-repair':title=f'Expand task {task["id"]} to include the proposed repair?'
            value.update(disclosure=compact_details,question=title,menu_options=options)
        # The existing immutable scope or reviewed artifact gives a generic
        # affirmative button a concrete subject without prescribing its wording.
        if kind in ('approve-private','approve-proposal','accept-concerns'):
            from .system import Path
            evidence=_attempt(state,attempt)
            artifact=Path(evidence['evidence'])/'result.json'
            if kind=='approve-private':
                folder=Path(state.get('plans',{}).get('designs',''))
                artifact=next((Path(name) for name in evidence.get('artifacts',{}) if Path(name).parent==folder),artifact)
            value['approval_material']=str(artifact)
            value['disclosure']+='\n[View the reviewed work](<'+artifact.as_posix()+'>)'
        elif kind=='approve-repair':
            value['approval_material']=repair.strip()
        if 'stop' in actions.values():value['stop_boundary']=stop_boundary(root,journal,state)
        key=save_offer(root,value,details=compact_details if kind=='approve-repair' else None,
                       details_title='View the proposed repair')
        return {'decision':key,'question':value['question'],'options':options,
                **({'disclosure':value['disclosure']} if 'disclosure' in value else {}),
                **({'actions':actions} if actions else {}),
                'human_locator':'Keep decision internal. Explain the action and share any supplied Markdown review link in a separate chat message before asking. Keep file paths and IDs out of the native menu. Bind the actual answer.'}


def state_head(root):
    from .storage import git
    return git(root,'rev-parse','HEAD')


def _path_shown(path,text):
    import re
    return re.search(r"(?<![\w./-])"+re.escape(path)+r"(?![\w./-])",text) is not None


def _verify_menu(value,source,*,discard=False):
    """Correlate the actual input with its prepared effect. Presentation prose is agent-owned."""
    from .authority import menu_text,newer
    offer=source.get('prepared_offer') or {}
    if offer.get('decision')!=digest(value) or offer.get('ambiguous'):
        raise Refused('This answer does not identify the prepared choice. Recover its original native question and preparation.')
    if not newer(source.get('question_at'),value['created_at']):
        raise Refused('This question predates the prepared choice')
    from .authority import action_text
    selected=action_text(source['prompt'])
    if selected not in map(action_text,value['menu_options']):
        raise Refused('Choose the named action before granting its effect')
    if source.get('via')=='question':
        options=source.get('question_options') or []
        if list(map(action_text,options)).count(selected)!=1:
            raise Refused('The native single-select menu must contain the chosen action')
    else:
        displays=[d['text'] for d in source.get('question_context',[]) if newer(d.get('at'),value['created_at'])]
        shown=menu_text(' '.join(displays+[source.get('question','')])).casefold()
        if selected not in shown:
            raise Refused('The typed answer needs its original visible action')
    material=value.get('approval_material')
    if discard or (material and selected==action_text(value['label'])):
        parts=[d['text'] for d in source.get('question_context',[]) if newer(d.get('at'),value['created_at'])]
        parts.extend([source.get('question',''),source.get('option_descriptions' if discard else 'selected_description','')])
        shown=' '.join(parts)
        if material and not discard:
            anchors=[material,material.replace('\\','/')]
            if detail:=value.get('details_file'):anchors.extend([detail['path'],detail['path'].replace('\\','/')])
            if not any(anchor in shown for anchor in anchors):
                raise Refused('Show the supplied link to the prepared work before approval, then bind the actual answer.')
            return
        paths=value['affected_paths']
        link=value.get('details_file',{}).get('path')
        if paths and not (link in shown if link else all(_path_shown(path,shown) for path in paths)):
            raise Refused('Show the affected paths or their inspection link before discarding work.')



def _verify_display(value,source,*,need_disclosure=True,preview=None):
    """Verify the identified human choice and any extra disclosure its effect needs."""
    from .authority import menu_text, newer, presented_question_at, question_text, shown_offer_reference
    question=value['question']
    expected=shown_offer_reference({'question':question})
    visible=shown_offer_reference(source)
    returned=source.get('prepared_offer') or {}
    # Only an already-authorized continuation or a refusal can use the native
    # preparation record if the host omitted the visible fingerprint.
    implicit=(not need_disclosure and visible is None and not returned.get('ambiguous') and returned.get('decision')==digest(value)
              and returned.get('reference')==expected and newer(returned.get('at'),value['created_at'])
              and newer(value['created_at'],returned.get('exchange_at')))
    title=question.rsplit(' [ref ',1)[0] if implicit else question
    if source.get('via')=='question':
        if menu_text(source.get('question',''))!=menu_text(title):
            raise Refused('This native question does not match the prepared offer')
        if sorted(source.get('question_options') or [])!=sorted(value['menu_options']):
            raise Refused('Use the complete single-select menu for this prepared decision')
        asked=source.get('question_at')
    else:
        asked=presented_question_at(source,title,normalize=menu_text)
        if not asked and implicit and preview:
            # A direct refusal can name the exact immutable scope preview in
            # the same displayed message as its choices, even if its title was paraphrased.
            import re
            last=source.get('question','')
            paths={str(preview),preview.as_posix()}
            exact_path=any(re.search(r'(?:^|[\s`<(])'+re.escape(path)+r'(?=$|[\s`>)\]]|[.,](?:\s|$))',last) for path in paths)
            if exact_path and all(label in last for label in value['menu_options']):asked=source.get('question_at')
        if not asked:raise Refused('Use the actual native question for this prepared offer')
        context=source.get('question_context') or [{'text':source['question'],'at':asked}]
        shown=question_text(' '.join(d['text'] for d in context if newer(d.get('at'),value['created_at'])))
        if any(label not in shown for label in value['menu_options']):
            raise Refused('Use the actual native question and its choices from the displayed offer')
    if not newer(asked,returned['at'] if implicit else value['created_at']):raise Refused('This native question predates the prepared decision')
    if need_disclosure:
        at=presented_question_at(source,value['disclosure'],reference_text=question)
        if not newer(at,value['created_at']):
            raise Refused('The answer does not match the prepared offer disclosure. Use the original displayed decision and native reply.')


def verify(root,state,kind,locator,source,attempt=None,replay=False):
    from .native import _home
    import re
    key=locator.get('decision')
    if not isinstance(key,str) or not re.fullmatch(r'[0-9a-f]{64}',key):raise Refused('Prepare the consequential decision before presenting its native question')
    value=read_json(_home(root)/'decisions'/(key+'.json'))
    choices=value.get('choices')
    takeover=kind=='stop' and bool(value.get('takeover'))
    if (digest(value)!=key or (kind not in choices if choices else value['kind']!=kind and not takeover)
            or value['run']!=state['id'] or value['attempt']!=attempt):
        raise Refused('This answer belongs to a different decision')
    from .authority import question_text,presented_question_at
    question=question_text(source.get('question',''))
    shown_at=source.get('question_at')
    if value.get('presentation')=='checkpoint-menu' and source.get('via')=='question' and {k:source.get(k) for k in ('host','session')}!=value['coordinator']:
        raise Refused('This checkpoint belongs to its saved coordinator; resume the work before presenting a new checkpoint')
    old_checkpoint=(value.get('presentation')=='checkpoint-menu' and source.get('via')=='question'
                    and (source.get('prepared_offer') or {}).get('decision')==key
                    and source.get('question')==value['question'])
    if value.get('menu_version')==2 or old_checkpoint:
        _verify_menu(value,source,discard=kind=='restart')
    elif 'disclosure' in value:
        # The identified short question names the handoff or ordinary
        # keep-edits continuation. A reset, new grant, destination or carried
        # request additionally needs the complete material effects in chat.
        ordinary=not value.get('entry_request') and (kind=='stop' or kind=='resume' and value.get('keep_edits_question'))
        _verify_display(value,source,need_disclosure=not ordinary)
    elif value.get('presentation') in ('checkpoint-menu','recovery-menu') and source.get('via')=='question':
        shown=source.get('question_options')
        expected=value['menu_options']
        if not isinstance(shown,list) or len(shown)!=len(expected) or set(shown)!=set(expected):
            raise Refused('Use the complete single-select checkpoint menu; retain the prepared decision and all its choices')
        if value.get('bound_question') and question!=question_text(value['question']):
            raise Refused('This native question does not match the prepared offer; retain its actual decision')
    elif source.get('via')=='question' and question!=question_text(value['question']):
        raise Refused('Use the actual native question for this prepared decision')
    elif source.get('via')!='question':
        shown_at=presented_question_at(source,value['question'])
        if shown_at is None:raise Refused('Use the actual native question for this prepared decision')
    if takeover and value.get('menu_version')!=2 and source.get('via')=='question':
        shown=source.get('question_options')
        if not isinstance(shown,list) or sorted(shown)!=sorted(value['menu_options']):
            raise Refused('Use the complete single-select menu for this takeover decision')
    # A short ordinary-chat Yes selects only the single affirmative effect.
    label=TAKE_OVER if takeover else choices[kind] if choices else value['label']
    accepted=(label.casefold(),) if choices or takeover else (label.casefold(),'yes','yes please')
    if kind=='resume':accepted+=('resume','resume the saved work','yes, resume saved work','please resume saved work')
    from .authority import action_text
    answer=action_text(source['prompt']) if value.get('menu_version')==2 else source['prompt'].strip().casefold().rstrip('.!')
    if answer not in accepted:
        raise Refused('This native answer does not accept the presented effect; preserve it and resolve the actual choice')
    from .authority import newer
    if 'disclosure' not in value and not newer(shown_at,value['created_at']):
        raise Refused('This native question predates the prepared decision')
    if not replay:
        if kind=='restart' and (detail:=value.get('details_file')):
            from .system import Path
            path=Path(detail['path'])
            if not path.is_file() or digest(path.read_text(encoding='utf-8'))!=detail['hash']:
                raise Refused('The disclosed list of affected paths changed. Prepare a current recovery decision before discarding work.')
        if value.get('presentation') in ('checkpoint-menu','recovery-menu') and not value.get('bound_question'):
            raise Refused('This pending historical menu lacks its saved run binding. Preserve the answer and present the current prepared question.')
        if value.get('presentation')=='checkpoint-menu' and {k:state['human'].get(k) for k in ('host','session')}!=value['coordinator']:
            raise Refused('This checkpoint coordinator changed; use the current saved-work decision')
        if kind=='stop':
            journal,_=load_run(root,state['id'])
            current=stop_boundary(root,journal,state)
            if value.get('stop_boundary') and value['stop_boundary']!=current:
                raise Refused('The saved work changed after the takeover question; inspect the current work')
            if not value.get('stop_boundary'):
                if any(value['boundary'].get(k)!=current[k] for k in ('id','scope_id','branch')):
                    raise Refused('This historical Stop decision belongs to different saved work')
        else:
            compared=boundary(root,state,'resume' if value.get('presentation')=='recovery-menu' else value['kind'],attempt)
            if value['boundary']!=compared:raise Refused('The decision subject changed; present the actual current effect before granting authority')
        if value.get('presentation')=='checkpoint-menu' and value['checkpoint_status']!=state['status']:raise Refused('This checkpoint changed; present its current actions before continuing')
        if choices and kind=='publish':
            from .publication import destination
            from .branches import trunk
            if value['publication_destination']!=(destination(root,required=True)|{'base_branch':trunk(root,state['config'])}):
                raise Refused('The publication destination changed; present the current destination before publishing')
    return value|{'kind':kind,'label':label} if choices else value


def scope_request(root,scope):
    from .native import _scope_preview
    fix=scope.get('workflow')=='deliver' and not scope.get('design')
    label='Approve and fix' if fix else 'Approve this scope'
    options=[label,TAKE_OVER]
    from textwrap import shorten
    title=shorten(scope['tasks'][0]['title'],width=64,placeholder='…')
    value={'kind':'approve-scope','scope':digest(scope),'label':label,
           'disclosure':_scope_preview(scope,plan=False).rstrip()+'\n\nStop and take over leaves this scope unapproved.',
           'question':f'Approve “{title}”?' if len(scope['tasks'])==1 else f'Approve {len(scope["tasks"])} tasks starting with “{title}”?',
           'menu_options':options,'created_at':now()}
    from .native import _home
    preview=_home(root)/'scopes'/value['scope']/'scope.md'
    value['approval_material']=str(preview)
    value['disclosure']+='\n[View the prepared scope](<'+preview.as_posix()+'>)'
    key=save_offer(root,value)
    return {'decision':key,'disclosure':value['disclosure'],'question':value['question'],'options':options,
            'present':'Explain the bounded change in your own words. Put [View the prepared scope](...) in a separate chat message before asking. Keep file paths and IDs out of the native menu. Show the actions and wait.',
            'bind':'For approval use scope approve (scope_approve). For refusal use decision stop with this decision ID and no run argument.',
            'actions':{label:'approve-scope',TAKE_OVER:'stop'}}


def verify_scope(root,scope,locator,source,*,decline=False):
    from .native import _home
    import re
    key=locator.get('decision')
    if not isinstance(key,str) or not re.fullmatch(r'[0-9a-f]{64}',key):raise Refused('Use the prepared scope approval question')
    value=read_json(_home(root)/'decisions'/(key+'.json'))
    if digest(value)!=key or value.get('kind')!='approve-scope' or value['scope']!=digest(scope):raise Refused('This answer belongs to another scope')
    if value.get('menu_version')==2:
        _verify_menu(value,source)
    elif 'disclosure' in value:
        preview=_home(root)/'scopes'/value['scope']/'scope.md' if decline else None
        _verify_display(value,source,need_disclosure=not decline,preview=preview)
    from .authority import action_text
    answer=action_text(source['prompt'])
    if decline:
        if answer!=TAKE_OVER.casefold():
            raise Refused('This answer does not decline the presented scope')
    elif answer not in (value.get('label','Approve this scope').casefold(),'yes','yes please'):
        raise Refused('This answer does not approve the presented scope')
    if 'disclosure' in value:return
    from .authority import question_text,presented_question_at
    question=question_text(source.get('question',''))
    shown_at=source.get('question_at') if source.get('via')=='question' else presented_question_at(source,value['question'])
    if (question!=question_text(value['question']) if source.get('via')=='question' else shown_at is None):
        raise Refused('This answer does not approve the presented scope')
    from .authority import newer
    if not newer(shown_at,value['created_at']):raise Refused('This question predates the prepared scope')
