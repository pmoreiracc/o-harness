#!/usr/bin/env python3
"""Claude's question tool on an OH menu. Before it runs, refuse answers the model filled in itself and menus mixed
with other questions; after the click, remind the agent to run OH, which reads the click from Claude's own
transcript. Questions that aren't OH menus pass untouched."""
import json
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
# After the click: OH reads it from this conversation's saved transcript when it next runs; nothing is handed over here.
print(json.dumps({'hookSpecificOutput':{'hookEventName':'PostToolUse','additionalContext':
    'OH: run OH `run` now; it reads this answer from the conversation that owns the run.'}}))
