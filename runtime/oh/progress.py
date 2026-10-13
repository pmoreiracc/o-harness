"""Bounded, read-only public observation. No worker launch, gate rendering or journal writes."""
import json
import time
from .storage import digest


def snapshot(root,run_id):
    from .workflow import load_run,running_progress
    from .controls import busy
    journal,state=load_run(root)
    if state['id']!=run_id:
        return {'run':run_id,'status':'replaced','done':True,'message':'The observed run is no longer active.'}
    progress=running_progress(state,journal.path).get('progress',{})
    phase=progress.get('phase',state['status'])
    value={'run':run_id,'status':state['status'],'phase':phase,'done':not busy(root)}
    value.update({k:progress[k] for k in ('task','title','attempt','focus') if k in progress})
    labels={'implementation':'implementation agent','analysis':'planning agent','assessment':'assessment agent','review':'independent reviewer agent'}
    label=labels.get(phase,'OH')
    focus=progress.get('focus',{})
    value['message']=('OH execution returned; read its saved result and next action.' if value['done'] else
                      f"OH is {state['status']}; the current work is still settling." if state['status'] in ('stopping','pausing') else
                      f"The {label}: {focus['message']}" if focus else
                      f"The {label} is working on task {progress['task']}: {progress['title']}" if phase in labels else
                      'OH returned a decision or completed phase; read the execution result.')
    return value


def observe(root,run_id,*,after='',wait=60):
    deadline=time.monotonic()+wait
    while True:
        value=snapshot(root,run_id);cursor=digest(value)
        if cursor!=after or value['done'] or time.monotonic()>=deadline:
            return value|{'cursor':cursor,'changed':cursor!=after}
        time.sleep(min(1,max(0,deadline-time.monotonic())))


def follow(root,run_id,*,seconds=1800):
    """For Claude Monitor: native phase changes immediately, latest new focus at most every 210s.
    A host watch may expire earlier. Expiry only ends this observer; execution stays owned by its call.
    """
    deadline=time.monotonic()+seconds;cursor='';phase=None;focus=None;reported=0
    while time.monotonic()<deadline:
        value=observe(root,run_id,after=cursor,wait=min(60,max(0,deadline-time.monotonic())))
        cursor=value['cursor'];current=(value.get('attempt'),value.get('phase'),value['status'])
        next_focus=(value.get('focus') or {}).get('id')
        if current!=phase or value['done'] or next_focus!=focus and time.monotonic()-reported>=210:
            print(json.dumps(value,ensure_ascii=False),flush=True)
            phase=current;focus=next_focus;reported=time.monotonic()
        if value['done']:return
    print(json.dumps({'run':run_id,'observer':'expired','done':False,
                      'message':'Observation expired; renew it if the execution call is still active.'}),flush=True)
