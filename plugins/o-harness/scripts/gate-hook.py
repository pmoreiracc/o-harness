#!/usr/bin/env python3
"""Claude's question tool on an OH menu. Before it runs, refuse answers the model filled in itself; after the
person clicks, hand the call's location to OH, which reads the click from Claude's own transcript.
Questions that aren't OH menus pass untouched."""
import json
import os
from pathlib import Path
import subprocess
import sys
payload=json.loads(sys.stdin.buffer.read())
request=payload.get('tool_input') if isinstance(payload.get('tool_input'),dict) else {}
questions=request.get('questions') if isinstance(request.get('questions'),list) else []
if not any(isinstance(q,dict) and 'OH gate ' in str(q.get('question','')) for q in questions):raise SystemExit(0)
if sys.argv[1]=='pre':
    reason=('OH menus take answers only from the person\'s click. Ask again without an answers field.' if 'answers' in request else
            'An OH menu is one question on its own. Ask it again exactly as OH gave it.' if len(questions)!=1 else None)
    if reason:
        print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':reason}}))
    raise SystemExit(0)
if os.environ.get('OH_CHILD_ATTEMPT'):raise SystemExit(0)
entry=Path(__file__).resolve().with_name('oh')
result=subprocess.run([sys.executable,'-I',str(entry),'--root',payload.get('cwd',os.getcwd()),'plugin-click','--host','claude'],
    input=json.dumps(payload),capture_output=True,encoding='utf-8',errors='replace')
text=('OH: '+result.stdout.strip()) if not result.returncode else 'OH could not record this click: '+result.stderr.strip()
print(json.dumps({'hookSpecificOutput':{'hookEventName':'PostToolUse','additionalContext':text}}))
