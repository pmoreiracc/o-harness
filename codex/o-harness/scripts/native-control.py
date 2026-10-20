#!/usr/bin/env python3
"""Forward bounded native control events. Never grants permissions or launches agents."""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    payload = json.load(sys.stdin)
    if not payload.get('session_id') or not isinstance(payload.get('cwd'), str):
        return
    command = [sys.executable, '-I', *(['-X', 'utf8'] if os.name == 'nt' else []),
               str(Path(__file__).with_name('oh')), '--root', payload['cwd'],
               'native-control', sys.argv[1]]
    done = subprocess.run(command, input=json.dumps(payload), capture_output=True,
                          text=True, encoding='utf-8', timeout=2.5)
    if done.returncode:
        print('OH could not verify native Stop control: ' + done.stderr.strip()[-500:], file=sys.stderr)
    elif done.stdout.strip():
        print(done.stdout.strip())


try:
    main()
except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
    print('OH native control is unavailable: ' + str(exc), file=sys.stderr)
