"""Native agents call ordinary focused check/admission helpers; no execution proxy."""
from pathlib import Path
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
        if not attempt.get('native_child'):
            import os
            caller=os.environ.get('CODEX_THREAD_ID') or os.environ.get('OH_NATIVE_SESSION_ID')
            _bind(root,journal,state,attempt,{'child_session':caller} if caller else {})
    result={k:request[k] for k in ('id','role','task','profile','head','tree','git_tree')}
    if request.get('standalone_subject'):
        result['standalone_subject']=request['standalone_subject']
        result['checkout_guard']={k:request[k] for k in ('head','tree','git_tree')}
    return result


def run(root):
    from .native import verify
    return verify(root)
