"""Explicit host commands; an ordinary prompt has no OH side effects."""
import re
from .storage import Refused

CHOICES={'continue','pr','stop','resume','retry','grant review','fix concerns','fix scope',
         'fix findings','accept concerns','route scope','accept concerns and route scope'}
PREFIX=r'[$/](?:o-harness:)?'


def command(prompt):
    if not isinstance(prompt,str):return None
    prompt=prompt.strip()
    match=re.fullmatch(PREFIX+r'oh-(start|pause|resume|stop|propose|design|deliver)(?:\s+(.*))?',prompt,re.S)
    # Workflow skills are invoked as oh-propose/oh-design/oh-deliver; internally they keep their workflow names.
    if match:return (match[1] if match[1] in ('propose','design','deliver') else 'oh-'+match[1]),match[2] or ''
    if prompt in CHOICES:return 'choice',prompt
    return None


def receive(root,host,payload):
    import os
    if os.environ.get('OH_CHILD_ATTEMPT'):return None
    parsed=command(payload.get('prompt'))
    if not parsed:return None
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
        except Refused as exc:
            return {'authorized':False,'onboarding':str(exc),'next':'Complete explicit setup/registration, prepare the scope if needed, then submit a fresh workflow invocation.'}
        exact_request=re.fullmatch(r'request:[0-9a-f]{64}',args)
        design_request=re.fullmatch(r'[0-9]{4}(?:\s+[a-zA-Z0-9_-]+)?\s+request:[0-9a-f]{64}',args)
        planning=(name in ('propose','design') and bool(args.strip())) or (name=='oh-start' and re.fullmatch(r'(?:propose|design)\s+\S.*',args,re.S))
        binding=planning or (name in ('deliver','oh-start') and exact_request) or (name=='deliver' and design_request) or (name=='oh-resume' and not args)
        if not binding:
            return {'authorized':False,'prepare':True,'next':'Select propose/design with an explicit intent, or prepare agreed delivery scope and present its exact trigger. A fresh human invocation grants that prepared scope.'}
    from .authority import stage
    return stage(root,host,payload)
