"""Register explicit native workflow entry without custom command or menu handling."""
from .storage import Refused


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
    value={'saved_work':saved_work(root)['saved_work'],'checkout':checkout,'base':base,
            'authority':'Observation only. Saved labels are historical; inspect execution/ownership before deciding what can continue. '
                        'A newer base does not make local changes disposable. Use native Git to inspect full diffs and local commits; '
                        'the displayed paths are bounded. Fetching refs grants no discard, task, continuation or publication authority.'}
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
