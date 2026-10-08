from functools import lru_cache
import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
from .storage import Refused


def codex_models(root):
    from .hosts import executable
    binary=executable('codex',root)
    info=Path(binary).stat()
    return _codex_models(binary,info.st_mtime_ns,info.st_size)


@lru_cache(maxsize=1)
def _codex_models(binary,modified,size):
    # A CLI upgrade must invalidate discovery even inside a long-lived runner.
    from .hosts import subscription_env
    child=subprocess.Popen([binary,'app-server'],env=subscription_env(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL,text=True)
    def send(value):child.stdin.write(json.dumps(value)+'\n');child.stdin.flush()
    # A reader thread instead of select(), which Windows supports only on sockets, not pipes.
    lines=queue.Queue()
    def read():
        try:
            for line in iter(child.stdout.readline,''):lines.put(line)
        finally:lines.put('')
    threading.Thread(target=read,daemon=True).start()
    models={};deadline=time.monotonic()+20
    try:
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'o-harness','version':'0.1'}}})
        while time.monotonic()<deadline:
            try:line=lines.get(timeout=.5)
            except queue.Empty:continue
            if not line:break
            message=json.loads(line)
            if message.get('error'):raise Refused('Codex capability discovery failed: '+str(message['error']))
            if message.get('id')==1:
                send({'method':'initialized'});send({'id':2,'method':'model/list','params':{'includeHidden':True}})
            elif message.get('id')==2:
                for model in message['result']['data']:
                    models[model['model']]={e['reasoningEffort'] for e in model['supportedReasoningEfforts']}
                cursor=message['result'].get('nextCursor')
                if cursor:send({'id':2,'method':'model/list','params':{'cursor':cursor,'includeHidden':True}})
                else:return models
        raise Refused('Timed out discovering Codex model capabilities; no model call was made')
    finally:
        child.terminate()
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.kill();child.wait()


RECOVERY='Update with `npm install -g @openai/codex@latest` or choose another model with `$oh-config` (new OH runs).'


def model_version(name):
    match=re.fullmatch(r'gpt-([0-9]+(?:\.[0-9]+){0,2})-([a-z][a-z0-9-]*)',name)
    if not match:return None
    parts=tuple(int(p) for p in match[1].split('.'))
    return parts+(0,)*(3-len(parts)),match[2]


def select_profile(host,profile,root):
    """Resolve before admission; retain configured settings and the requested effort."""
    if host!='codex':return profile,None
    supported=codex_models(root)
    if profile['model'] in supported:
        validate_profile(host,profile,root)
        return profile,None
    requested=model_version(profile['model'])
    candidates=[]
    for name,efforts in supported.items():
        version=model_version(name)
        if requested and version and version[1]==requested[1] and version[0]<requested[0] and profile['effort'] in efforts:
            candidates.append((version[0],name))
    if not candidates:
        validate_profile(host,profile,root)  # no compatible earlier model: retain the explicit failure
    actual=profile|{'model':max(candidates)[1]}
    notice=(f"Your installed Codex CLI doesn't list {profile['model']}. "
            f"Continuing with {actual['model']} / {actual['effort']}. {RECOVERY}")
    return actual,{'requested':profile,'actual':actual,'notice':notice}


def validate_profile(host,profile,root):
    """root is the run's project: OH never trusts a codex found inside it (its own folder isn't the project)."""
    if host=='codex':
        supported=codex_models(root)
        if profile['model'] not in supported:
            raise Refused(f"Your installed Codex CLI doesn't list {profile['model']}, and no compatible earlier model was selected. {RECOVERY} Available models: {', '.join(supported)}.")
        if profile['effort'] not in supported[profile['model']]:
            raise Refused(f"The configured effort is unsupported for {profile['model']}. Choose a supported effort with `$oh-config` (new OH runs).")
