import os
import json
import subprocess
from .config import HOME
from .legacy import environment
from .storage import Refused,project


def dispatch(root,host,entry,args,payload):
    if entry=='user-prompt-submit':
        if os.environ.get('OH_CHILD_ATTEMPT'):return None
        prompt=payload.get('prompt','')
        import re
        choices={'resume','retry','fix findings','fix scope','accept concerns and route scope','continue','pr','stop','grant review','fix concerns','accept concerns','route scope','dismiss scope','grant next review window','stop and take it over','stop and escalate to the pr','review again'}
        relevant=prompt in choices or prompt.startswith(('oh start ','$oh ','/oh ','$deliver ','/deliver ','oh deliver '))
        if not relevant:return None
        from .authority import stage
        stage(root,host,payload)
        return {'hookSpecificOutput':{'hookEventName':'UserPromptSubmit','additionalContext':
            'OH captured a pending human choice. Run the pinned OH runner to verify the native user transcript and apply it. No task/review authority is granted until that check succeeds.'}}
    p=project(root)
    product_checks={'adr-immutability.sh','doc-frontmatter.sh','adr-log-index.sh','adr-write-detector.sh'}
    if p.get('design_profile')!='consumer-v1' and (entry in product_checks or (entry=='edit' and args and args[0] in product_checks)):
        return None
    env=environment(root)
    if host=='codex':
        script=HOME/'adapters/codex/run.sh';arguments=[entry,*args]
    else:
        script=(HOME/'core/hooks'/entry).resolve();arguments=args
        if not script.is_relative_to(HOME/'core/hooks') or not script.is_file():raise Refused('Unknown Claude hook')
    output=subprocess.run(['/bin/bash',str(script),*arguments],cwd=root,env=env,input=json.dumps(payload),text=True,capture_output=True)
    if output.stderr:
        import sys
        print(output.stderr,end='',file=sys.stderr)
    if output.returncode:raise SystemExit(output.returncode)
    if output.stdout:
        try:return json.loads(output.stdout)
        except ValueError:
            import sys
            print(output.stdout,end='',file=sys.stderr)
    return None


def dispatch_legacy_choice(root,host,payload):
    # Host-native provenance has already been verified by authority.materialize.
    # The shared Codex dispatcher consumes a UserPromptSubmit shape for both hosts.
    translated=dict(payload)
    if host=='claude':translated['turn_id']=payload['prompt_id']
    return dispatch(root,'codex','user-prompt-submit.sh',[],translated)
