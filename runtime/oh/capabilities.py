from functools import lru_cache
import json
import queue
import subprocess
import threading
import time
from .storage import Refused


@lru_cache(maxsize=1)
def codex_models():
    from .hosts import executable,subscription_env
    from pathlib import Path
    child=subprocess.Popen([executable('codex',Path.cwd()),'app-server'],env=subscription_env(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL,text=True)
    def send(value):child.stdin.write(json.dumps(value)+'\n');child.stdin.flush()
    # A reader thread instead of select(), which Windows supports only on sockets, not pipes.
    lines=queue.Queue()
    threading.Thread(target=lambda:[lines.put(line) for line in iter(child.stdout.readline,'')]+[lines.put('')],daemon=True).start()
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
                send({'method':'initialized'});send({'id':2,'method':'model/list','params':{}})
            elif message.get('id')==2:
                for model in message['result']['data']:
                    models[model['model']]={e['reasoningEffort'] for e in model['supportedReasoningEfforts']}
                cursor=message['result'].get('nextCursor')
                if cursor:send({'id':2,'method':'model/list','params':{'cursor':cursor}})
                else:return models
        raise Refused('Timed out discovering Codex model capabilities; no model call was made')
    finally:
        child.terminate()
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.kill();child.wait()


def validate_profile(host,profile):
    if host=='codex':
        supported=codex_models()
        if profile['model'] not in supported:
            raise Refused(f"Codex CLI does not advertise {profile['model']}; supported: {', '.join(supported)}. Change the OH profile before starting a new run.")
        if profile['effort'] not in supported[profile['model']]:
            raise Refused('The configured effort is unsupported for this Codex model')
