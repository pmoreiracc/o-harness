"""Compatibility entry spelling; there is only one live task execution engine."""
from .storage import Refused
from .workflow import load_run
from .runner import run as execute
from .hosts import invoke


def run(root, doc, track='', host=None, call=invoke):
    _,state=load_run(root)
    if state.get('design')!=doc or (track and state.get('track')!=track):
        raise Refused('The current native run is bound to another design or track')
    if host and host!=state['host']:raise Refused('Run belongs to another host')
    return execute(root,call)
