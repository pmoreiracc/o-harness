#!/usr/bin/env python3
"""Narrow prompt translation. Ordinary prompts never launch OH or alter a project."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
payload=json.load(sys.stdin)
prompt=payload.get('prompt','')
if not isinstance(prompt,str):raise SystemExit(0)
prompt=prompt.strip()
choices={'continue','pr','stop','resume','retry','grant review','fix concerns','fix scope','fix findings','accept concerns','route scope','accept concerns and route scope'}
if prompt not in choices and not re.match(r'^(?:[$/](?:o-harness:)?oh-(?:start|pause|resume|stop|propose|design|deliver))(?:\s|$)',prompt):
    raise SystemExit(0)
if os.environ.get('OH_CHILD_ATTEMPT'):raise SystemExit(0)
entry=Path(__file__).resolve().with_name('oh')
host=sys.argv[1]
result=subprocess.run([str(entry),'--root',payload.get('cwd',os.getcwd()),'plugin-hook','--host',host],
    input=json.dumps(payload),text=True,capture_output=True)
if result.returncode:
    print(result.stderr,file=sys.stderr)
    raise SystemExit(2)
value=json.loads(result.stdout) if result.stdout.strip() else None
if value is not None:
    print(json.dumps({'hookSpecificOutput':{'hookEventName':'UserPromptSubmit','additionalContext':'OH: '+json.dumps(value)}}))
