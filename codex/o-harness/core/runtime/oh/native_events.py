"""Native lifecycle notifications reuse checked binding/retention; never launch work."""
from pathlib import Path
from subprocess import CalledProcessError
from .storage import Refused, git
from .workflow import load_run, NO_RUN


def handle(root,host,payload):
    if host!='claude':return {}
    event=payload.get('hook_event_name')
    if event not in ('PostToolUse','SubagentStop'):return {}
    if event=='PostToolUse' and payload.get('tool_name') not in ('Agent','Task','SubagentHandback'):return {}
    if event=='PostToolUse' and payload.get('tool_name') in ('Agent','Task'):
        args=payload.get('tool_input') or {}
        if not str(args.get('subagent_type','')).startswith('o-harness:') and 'request.json' not in args.get('prompt',''):return {}
    try:root=Path(git(root,'rev-parse','--show-toplevel'))
    except CalledProcessError:return {}
    try:journal,state=load_run(root)
    except Refused as exc:
        if str(exc)==NO_RUN or 'not registered' in str(exc):return {}
        raise
    parent=payload.get('session_id')
    if state['host']!=host or state['human']['session']!=parent:return {}
    if git(root,'branch','--show-current')!=state['branch']:return {}
    attempts=[a for a in state['attempts'] if not a.get('finished') and a.get('host',host)==host
              and a.get('parent',state['human']).get('session')==parent]
    if len(attempts)!=1:return {}
    attempt=attempts[0];locator={}
    if event=='PostToolUse' and payload.get('tool_name') in ('Agent','Task'):
        args=payload.get('tool_input') or {};result=payload.get('tool_response') or {}
        if attempt['id'] not in args.get('prompt',''):return {}
        locator={'child_session':result.get('agentId'),'tool_use_id':payload.get('tool_use_id')}
    else:
        locator={'child_session':payload.get('agent_id')}
    if not locator.get('child_session'):return {}
    if attempt.get('native_child') and attempt['native_child']['child_session']!=locator['child_session']:return {}
    from . import native
    with native._locked(root):
        journal,state=load_run(root);attempt=native._attempt(state,attempt['id'])
        if attempt.get('finished'):return {}
        if not attempt.get('native_child'):native._bind(root,journal,state,attempt,locator)
    if event=='SubagentStop' or payload.get('tool_name')=='SubagentHandback' or (payload.get('tool_response') or {}).get('status') in ('completed','cancelled','failed'):
        # A hook is a wakeup, never proof of quiescence or a source of verdict prose.
        retained=native.retain(root,attempt['id'],locator)
        return {'attempt':attempt['id'],'outcome':retained['outcome']}
    return {'attempt':attempt['id'],'binding':'saved'}
