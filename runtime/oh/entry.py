"""Explicit host commands; an ordinary prompt has no OH side effects."""
import re
from .storage import Refused

CHOICES={'continue','pr','stop','resume','retry','grant review','fix concerns','dismiss scope',
         'fix concerns and route scope','fix concerns and dismiss scope','accept concerns and dismiss scope','accept concerns','route scope','accept concerns and route scope','approve','reconsider'}
REFINE=r'refine:\s*\S.*'  # refine: <what to change>, the person's own words for the next proposal
PREFIX=r'[$/](?:o-harness:)?'


def command(prompt):
    if not isinstance(prompt,str):return None
    prompt=prompt.strip()
    match=re.fullmatch(PREFIX+r'oh-(start|pause|resume|stop|propose|design|deliver)(?:\s+(.*))?',prompt,re.S)
    # Workflow skills are invoked as oh-propose/oh-design/oh-deliver; internally they keep their workflow names.
    if match:return (match[1] if match[1] in ('propose','design','deliver') else 'oh-'+match[1]),match[2] or ''
    if prompt in CHOICES or re.fullmatch(REFINE,prompt,re.S):return 'choice',prompt
    return None


def receive(root,host,payload):
    import os
    if os.environ.get('OH_CHILD_ATTEMPT'):return None
    parsed=command(payload.get('prompt'))
    from .authority import drop_waiting,stage,waiting_for
    if not parsed:
        # The one plain message OH reads: the answer to what it asked for (a bare command's argument). It uses the
        # question up, so any later message is ordinary chat again.
        if found:=waiting_for(root,host,payload.get('session_id')):
            drop_waiting(payload.get('session_id'))
            return stage(root,host,payload,idea=found['command'])
        return None
    drop_waiting(payload.get('session_id'))  # another OH command, or /oh-stop, replaces what OH waited for
    from .workflow import load_run
    name,args=parsed
    if name=='choice':
        try:_,state=load_run(root)
        except (Refused,FileNotFoundError):return None
        if state['human']['session']!=payload.get('session_id') or state['host']!=host:return None
    elif name in ('oh-pause','oh-stop'):
        if args:raise Refused('Control takes no inferred project or run; select its checkout explicitly')
        from .controls import request
        return request(root,name[3:])
    if name!='choice':
        from .registry import lookup
        try:lookup(root)
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
        exact_request=re.fullmatch(r'request:[0-9a-f]{64}',args)
        design_request=re.fullmatch(r'[0-9]{4}(?:\s+[a-zA-Z0-9_-]+)?\s+request:[0-9a-f]{64}',args)
        if name=='deliver':
            from .delivery import parse,listing
            selected=parse(args)
            if selected['kind']=='list':return listing(root)
            if selected['kind']=='quick_fix':return stage(root,host,payload)
            design_request=selected['kind']=='design'
        from .plans import SLUG
        design=args.strip() if name=='design' else (re.fullmatch(r'design\s+(.*)',args,re.S) or [None,None])[1] if name=='oh-start' else None
        if design and not re.fullmatch(SLUG,design.strip()):
            return {'authorized':False,'next':'Name one roadmap initiative by its slug: /oh-design <slug>. New ideas start with /oh-propose.'}
        planning=name=='propose' or design is not None or (name=='oh-start' and re.fullmatch(r'propose\s+\S.*',args,re.S))
        binding=planning or (name=='oh-start' and not args) or (name in ('deliver','oh-start') and exact_request) or (name=='deliver' and design_request) or (name=='oh-resume' and not args)
        if not binding:
            return {'authorized':False,'prepare':True,'next':'Select propose/design with an explicit intent, or prepare agreed delivery scope and present its exact trigger. A fresh human invocation grants that prepared scope.'}
    return stage(root,host,payload)
