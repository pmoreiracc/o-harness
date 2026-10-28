"""Native agents call ordinary focused check/admission helpers; no execution proxy."""
from .system import Path
from .storage import Refused, digest, read_json
from .workflow import load_run


def admission(directory):
    request=read_json(Path(directory)/'request.json')
    root=Path(request['root'])
    from .native import _subject,_locked,_bind
    with _locked(root):
        journal,state=load_run(root)
        attempt=next((a for a in state['attempts'] if a['id']==request['id']),None)
        if not attempt or attempt.get('finished') or digest(request)!=attempt.get('request_hash'):
            raise Refused('This immutable admission is missing, changed or already completed')
        from .cancellation import guard
        guard(root,attempt=attempt['id'])
        current=_subject(root,state)
        if any(current[k]!=request[k] for k in ('head','tree','git_tree','artifacts')):
            raise Refused('The admitted subject changed; retain this attempt and obtain fresh admission')
        packet=read_json(request['task_context']['path'])
        if digest(packet)!=request['task_context']['hash']:
            raise Refused('The immutable task context changed; preserve the evidence and obtain fresh admission')
        if not attempt.get('native_child'):
            import os
            caller=os.environ.get('CODEX_THREAD_ID') or os.environ.get('OH_NATIVE_SESSION_ID')
            _bind(root,journal,state,attempt,{'child_session':caller} if caller else {})
    result={k:request[k] for k in ('id','role','task','profile','head','tree','git_tree')}
    result['task_context']=packet
    if request.get('standalone_subject'):
        result['standalone_subject']=request['standalone_subject']
        result['checkout_guard']={k:request[k] for k in ('head','tree','git_tree')}
    return result


def command_format(root,attempt_id,argv):
    """Render literal shell arguments only. Native tools still approve and execute."""
    if not isinstance(argv,list) or not argv or not all(isinstance(v,str) and '\0' not in v for v in argv):
        raise Refused('Supply the executable and arguments as a nonempty string array')
    from .native import _attempt
    _,state=load_run(root)
    attempt=_attempt(state,attempt_id)
    if attempt.get('finished'):raise Refused('This attempt has ended; do not format more work for it')
    from .cancellation import command_line,guard
    guard(root,attempt=attempt_id)
    return {'bash':command_line(root,attempt_id,argv),
            'powershell':command_line(root,attempt_id,argv,windows=True),
            'instruction':'Run the returned command unchanged in the corresponding native shell tool with its normal permissions. Formatting grants no authority and executes nothing.'}


def run(root):
    from .native import verify
    return verify(root)
