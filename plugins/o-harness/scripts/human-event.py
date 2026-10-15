#!/usr/bin/env python3
"""Expose a native source locator; never classify choices, grant work or launch OH."""
import json
import sys

payload=json.loads(sys.stdin.buffer.read())
if payload.get('isSidechain') or payload.get('agent_id'):raise SystemExit(0)
session=payload.get('session_id')
if not isinstance(session,str) or not session:raise SystemExit(0)
locator={'host':sys.argv[1],'session':session}
for source,target in (('prompt_id','turn'),('turn_id','turn'),('transcript_path','transcript_path'),('prompt','prompt')):
    if isinstance(payload.get(source),str) and payload[source]:locator[target]=payload[source]
print(json.dumps({'hookSpecificOutput':{'hookEventName':'UserPromptSubmit',
    'additionalContext':'Native conversation locator for OH helpers (not an approval): '+json.dumps(locator)}}))
