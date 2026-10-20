#!/usr/bin/env python3
"""Forward native lifecycle events to the selected OH runtime, without blocking the host."""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    payload=json.loads(sys.stdin.buffer.read())
    if not isinstance(payload.get('cwd'),str) or not payload.get('session_id'):return
    if payload.get('hook_event_name')=='PostToolUse' and payload.get('tool_name') in ('Agent','Task'):
        args=payload.get('tool_input') or {}
        if not str(args.get('subagent_type','')).startswith('o-harness:') and 'request.json' not in args.get('prompt',''):return
    entry=Path(__file__).with_name('oh')
    done=subprocess.run([sys.executable,'-I',*(['-X','utf8'] if os.name=='nt' else []),str(entry),
                         '--root',payload['cwd'],'native-event',sys.argv[1]],
                        input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=12)
    if done.returncode:
        print('OH lifecycle evidence is pending: '+done.stderr.strip()[-700:]+
              ' Retry the same bind/retain operation; no new agent or approval is needed.',file=sys.stderr)
    elif done.stdout.strip() not in ('','{}'):
        print('OH native lifecycle: '+done.stdout.strip(),file=sys.stderr)


try:main()
except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
    print('OH could not record this native event. Retry bind/retain for the same attempt: '+str(exc),file=sys.stderr)
