"""Register explicit native workflow entry without custom command or menu handling."""
import re
from .storage import Refused


def request_description(source):
    if source.get('via')=='question':return source.get('question','')+' Answer: '+source['prompt']
    if source.get('via')=='plan':return 'Continue the already accepted scope preview from this conversation.'
    return source['prompt']


def request_source(root,locator,after=None):
    """Carry an invocation only across its recorded, accepted prerequisite decision."""
    from . import authority,native
    from .storage import checkout_id,digest,read_json
    from .workflow import load_run
    if after is None:return authority.native_human(root,locator)
    if not isinstance(after,str) or not re.fullmatch('[0-9a-f]{64}',after):
        raise Refused('Use the prepared prerequisite decision identity')
    prepared=read_json(native._home(root)/'decisions'/(after+'.json'))
    if digest(prepared)!=after or prepared.get('kind') not in ('recover','resume','stop','setup-plans') or not prepared.get('entry_request'):
        raise Refused('This decision did not retain the initiating request; preserve its answer and inspect its original prepared effect')
    original=authority.native_human(root,locator,latest=False)
    if any(original.get(k)!=prepared['entry_request'].get(k) for k in ('host','session','turn','prompt','message_id','question_call','record_hashes')):
        raise Refused('The prerequisite belongs to a different initiating request')
    if prepared['kind']=='setup-plans':
        if prepared['checkout']!=checkout_id(root):raise Refused('This plan setup belongs to another checkout')
        record=setup_receipt(root,after)
        if not record.is_file():raise Refused('Bind the actual plan location answer before continuing the retained request')
        accepted=read_json(record)
        answer=authority.native_human(root,accepted['locator'])
        if answer['record_hashes']!=accepted['human']['record_hashes']:
            raise Refused('The retained setup answer changed; use the original native reply')
        from .config import load
        settings=load(root)['plans']
        if settings['location']!=accepted['location'] or plan_locations(root,settings)!=prepared['locations']:
            raise Refused('The plan location changed after setup. Inspect the current plans before continuing.')
        return original|{'prerequisite_human':answer,'prerequisite':after}
    journal,state=load_run(root,prepared['run'])
    accepted=[]
    for key in state['decisions']:
        path=journal.path/'decisions'/(key+'.json')
        if not path.exists():continue
        record=read_json(path)
        if record.get('prepared')==prepared and record.get('human') and record.get('locator'):
            accepted.append(record)
    if len(accepted)!=1:raise Refused('Bind the actual prerequisite answer before continuing the retained request')
    answer=authority.native_human(root,accepted[0]['locator'])
    if answer['record_hashes']!=accepted[0]['human']['record_hashes']:
        raise Refused('The retained prerequisite answer changed; preserve its original native evidence')
    if (answer['host'],answer['session'])!=(original['host'],original['session']) or not authority.newer(answer.get('at'),original.get('at')):
        raise Refused('Continue the initiating request from its own native conversation after the accepted prerequisite')
    return original|{'prerequisite_human':answer,'prerequisite':after}


def setup_receipt(root, key):
    from .native import _home
    return _home(root)/'decisions'/(key+'.accepted.json')


def plan_locations(root, settings):
    from .plans import private_base
    from .storage import project
    owner=project(root)
    if owner.get('design_profile')=='consumer-v1':
        raise Refused('This project keeps its plans in the repository under its document profile')
    private=owner.get('private_plans_path') or private_base(settings['private_folder'],owner.get('private_plans_name',owner['name']))
    return {'repo':str(root),'private':str(private)}


def setup_offer(root, request, after):
    from .config import load
    from .native import _command
    from .storage import checkout_id
    if request is None:raise Refused('Supply the initiating Propose or Design request to prepare plan setup')
    if blocked:=enroll(root):raise Refused(blocked['onboarding'])
    settings=load(root)['plans']
    if settings['location']!='ask':raise Refused('This project already has a plan location. Continue the initiating request.')
    locations=plan_locations(root,settings)
    labels={'repo':'Keep plans in the repository','private':'Keep plans in the private folder','cancel':'Cancel'}
    source=request_source(root,request,after)
    if (command:=_command(source)) and command[0] not in ('oh-propose','oh-design'):
        raise Refused('The initiating command must be Propose or Design')
    value={'kind':'setup-plans','entry_request':{k:v for k,v in source.items() if k not in ('prerequisite_human','prerequisite')},
           'checkout':checkout_id(root),'locations':locations,'menu_options':list(labels.values()),'choices':labels,'menu_version':2}
    return _save_setup_offer(root,value)


def _save_setup_offer(root, value):
    from .native import _home, _immutable
    from .storage import digest, now

    locations=value['locations']
    details=f"Repository location: {locations['repo']}\nPrivate location: {locations['private']}"
    question='Where should OH keep this project’s plans?\n\n'+details
    value=value|{'created_at':now(),'question':question,'disclosure':details}
    key=digest(value)
    _immutable(_home(root)/'decisions'/(key+'.json'),value)
    return {'decision':key,'question':question,'options':value['menu_options'],'disclosure':details,
            'next':'Show question and options exactly as returned. The question already includes both paths. '
                   'Bind the actual answer with decision setup-plans. On success, pass after with the original request.'}


def apply_setup(root, locator):
    from . import authority, config
    from .decisions import _path_shown, _verify_menu
    from .native import _home, _immutable, _locked, _presented
    from .storage import checkout_id,digest,read_json
    key=locator.get('decision')
    if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{64}',key):
        raise Refused('Use the prepared plan location decision with the actual native answer')
    with _locked(root):
        value=read_json(_home(root)/'decisions'/(key+'.json'))
        if digest(value)!=key or value.get('kind')!='setup-plans' or value.get('checkout')!=checkout_id(root):
            raise Refused('This plan location question belongs to a different checkout or decision')
        locator=_presented(root,locator,{'human':value['entry_request'],'host':value['entry_request']['host']})
        answer=authority.native_human(root,locator)
        if ((answer['host'],answer['session'])!=(value['entry_request']['host'],value['entry_request']['session'])
                or authority.newer((answer.get('prepared_offer') or {}).get('exchange_at'),value['created_at'])):
            raise Refused('Newer input interrupted plan setup. Prepare it from the current request.')
        from .authority import action_text
        choice=action_text(answer['prompt'])
        location=next((kind for kind,label in value['choices'].items() if choice==action_text(label)),None)
        if location is None:raise Refused('Choose a location from the prepared plan setup question')
        _verify_menu(value,answer,action=location)
        if location=='cancel':return {'cancelled':True}
        receipt=setup_receipt(root,key)
        record={'locator':locator,'human':answer,'location':location}
        if receipt.is_file():
            if read_json(receipt)!=record:raise Refused('This setup choice was already used; preserve its original answer')
        else:
            shown=' '.join(d['text'] for d in answer.get('question_context',[]) if authority.newer(d.get('at'),value['created_at']))
            shown+=' '+answer.get('question','')+' '+answer.get('option_descriptions','')
            if not all(_path_shown(path.replace('\\','/'),shown.replace('\\','/')) for path in value['locations'].values()):
                settings=config.load(root)['plans']
                if settings['location']!='ask' or plan_locations(root,settings)!=value['locations']:
                    raise Refused('Plan settings changed after the question. Review the current location before continuing.')
                # The latest matching answer granted nothing. Prepare a new offer in this exchange
                # for the same request so the next reply can identify the corrected disclosure.
                return {'retry':_save_setup_offer(root,value),
                        'reason':'The first question omitted a plan path. Show the new question and choices, and wait for a fresh reply.'}
            def confirm_location():
                settings=config.load(root,data=config.read_file(upgrade_first=False))['plans']
                if settings['location'] not in ('ask',location) or plan_locations(root,settings)!=value['locations']:
                    raise Refused('Plan settings changed after the question. Review the current location before continuing.')
            config.change(root,'plans.location',location,before_apply=confirm_location)
            _immutable(receipt,record)
        return {'location':location,'after':key}


def inspect(root):
    """Facts for entry reasoning; fetch refs without selecting work or editing the checkout."""
    from .branches import base_branch,fetch_base,holder,run_git
    from .native import saved_work
    from .storage import atomic_json,digest,encode,git,identifier,state_home,status
    selected=base_branch(root)
    base=fetch_base(root,selected['name'])|{'source':selected['source']}
    head=run_git(root,'rev-parse','--verify','--quiet','HEAD').stdout.strip() or None
    paths,nested=status(root)
    checkout={'branch':git(root,'branch','--show-current'),'head':head,
              'paths':paths[:30],'path_count':len(paths),'nested_worktrees':nested}
    if head and base['commit']:
        ahead,behind=map(int,git(root,'rev-list','--left-right','--count',head+'...'+base['commit']).split())
        checkout.update(ahead=ahead,behind=behind)
    checkout['base_checkout']=str(other) if selected['name'] and (other:=holder(root,selected['name'])) else None
    saved=saved_work(root)['saved_work']
    from .delivery import merged_batch
    from .workflow import load_run
    for item in saved:
        state=load_run(root,item['run'])[1]
        if merged:=merged_batch(root,state,base):
            item.update(resumable=False,merged_batch=merged,next_action={'tool':'scope_prepare',
                        'arguments':{'doc':state['design'],'track':state.get('track') or ''},'instruction':merged['next']})
    value={'saved_work':saved,'checkout':checkout,'base':base,
            'authority':'Observation only. Saved labels are historical; inspect execution/ownership before deciding what can continue. '
                        'A newer base does not make local changes disposable. Use native Git to inspect full diffs and local commits; '
                        'the displayed paths are bounded. Fetching refs grants no discard, task, continuation or publication authority.'}
    from .workspace import summary
    if parked:=summary(root):value['parked_work']=parked
    from .config import load,load_global
    from .registry import index_path
    limit=(load(root) if index_path(root).is_file() else load_global())['context']['result_chars']
    if len(encode(value))<=limit:return value
    path=state_home()/'requests'/digest(str(root))/('entry-'+identifier()+'.json')
    atomic_json(path,value,immutable=True)
    reference={'path':str(path),'hash':digest(value)}
    result={'observation':reference,'checkout':{k:checkout[k] for k in ('branch','head','path_count')},
            'base':{k:base[k] for k in ('name','ref','commit','freshness')},
            'next':'Read the complete observation before readiness advice or checkout changes. It grants no authority.'}
    if len(encode(result))>limit:result={'observation':reference,'next':'Read the complete entry observation; it grants no authority.'}
    if len(encode(result))>limit:raise Refused('The observation path exceeds context.result_chars; increase that limit and retry entry')
    return result


def enroll(root):
    """Register an explicit native invocation; preserve moved-checkout recovery."""
    from .registry import lookup, register
    try:
        entry = lookup(root)
        if entry['identity']['commit'] is None:
            from .config import name_of
            register(root, name_of(entry['project']))
    except Refused as unregistered:
        # Typing an OH command in a checkout is the person's choice to use OH here: register it as `init` would,
        # so the command they typed carries on.
        # A checkout that was registered and then moved or recreated keeps lookup's own recovery step.
        from subprocess import CalledProcessError
        from .config import ensure_project
        from .registry import index_path,register
        try:
            if index_path(root).is_file():raise unregistered
            register(root);ensure_project(root)
        except (Refused,CalledProcessError) as exc:  # Git fails outside a repository
            reason=str(exc) if isinstance(exc,Refused) else str(unregistered)
            return {'authorized':False,'onboarding':reason,'next':'Register this checkout with init as the message says, then run the command.'}
