#!/usr/bin/env python3
"""Refuse a native OH agent launch whose settings differ from its admission, before it starts.
Grants nothing and launches nothing; OH's binding still validates every launched child."""
import json
import re
import sys
from pathlib import Path

REQUEST=re.compile(r'[/\\]attempts[/\\]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})[/\\]request\.json')
ROOT=re.compile(r'(?:^|[\s"\'`(])(?P<root>~[/\\]|/|[A-Za-z]:[/\\]|\\\\)')


def texts(value):
    if isinstance(value,str):yield value
    elif isinstance(value,dict):
        for item in value.values():yield from texts(item)
    elif isinstance(value,list):
        for item in value:yield from texts(item)


def admission(arguments):
    """The admitted request this launch carries, or None for a launch OH did not admit.
    A repair prompt can also cite earlier attempts; the newest admission is the one launched."""
    found={}
    for text in texts(arguments):
        for match in REQUEST.finditer(text):
            # Whitespace can belong to the absolute path, including an unquoted home
            # directory. Try the nearest roots first; only an actual matching request counts.
            for start in reversed(list(ROOT.finditer(text,0,match.start()))):
                reference=text[start.start('root'):match.end()]
                if '\n' in reference or '\r' in reference:break
                path=Path(reference).expanduser()
                if not path.is_absolute():continue
                try:request=json.loads(path.read_text(encoding='utf-8'))
                except (OSError,ValueError):continue
                if isinstance(request,dict) and request.get('id')==match[1] and isinstance(request.get('profile'),dict):
                    found[match[1]]=request
                    break
    named=str(arguments.get('task_name') or '')
    for attempt,request in found.items():
        if named=='oh_'+attempt.replace('-',''):return request
    return max(found.values(),key=lambda r:str(r.get('started_at') or ''),default=None)


def problems(host,arguments,profile):
    model,effort=profile.get('model'),profile.get('effort')
    if host=='codex':
        wrong=[]
        if arguments.get('model')!=model:wrong.append(f'model "{model}"')
        if arguments.get('reasoning_effort')!=effort:wrong.append(f'reasoning_effort "{effort}"')
        if arguments.get('fork_turns')!='none':wrong.append('fork_turns "none"')
        return wrong
    wrong=[]
    if arguments.get('model')!=model:wrong.append(f'model "{model}"')
    if arguments.get('effort')!=effort:wrong.append(f'effort "{effort}"')
    if arguments.get('subagent_type')=='fork' or arguments.get('fork_context'):wrong.append('a named non-fork agent type')
    return wrong


def main():
    try:
        payload=json.loads(sys.stdin.buffer.read())
        arguments=payload.get('tool_input')
        if not isinstance(arguments,dict):return
        request=admission(arguments)
        if request is None:return
        wrong=problems(sys.argv[1] if len(sys.argv)>1 else 'claude',arguments,request['profile'])
    except Exception:  # A guard failure must never block unrelated work; binding still validates.
        return
    if not wrong:return
    reason=(f'OH admitted attempt {request["id"]} with a fixed profile. Launch that same attempt again with '
            +', '.join(wrong)+'. Nothing was launched, so no recovery or new admission is needed.')
    print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny',
                                            'permissionDecisionReason':reason}}))


main()
