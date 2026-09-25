#!/usr/bin/env -S python3 -I
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
committed=subprocess.check_output(['git','-C',str(root),'show','HEAD:.oh/harness.lock.json'],text=True,env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')})
if (root/'.oh/harness.lock.json').read_text()!=committed:raise SystemExit('Commit the reviewed OH pin before installation')
lock=json.loads(committed)
revision=lock['revision'];repository=lock['repository']
if not re.fullmatch('[0-9a-f]{40}',revision):raise SystemExit('Invalid pinned revision')
if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git',repository):raise SystemExit('Invalid repository URL')
parent=Path.home()/'.local/share/o-harness/versions';parent.mkdir(parents=True,exist_ok=True)
final=parent/revision
if final.is_symlink():raise SystemExit('Existing OH installation is a symlink. Preserve it by moving '+str(final)+' to a separate recovery location, then rerun setup. No files were deleted.')
if final.exists():
    try:
        env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
        head=subprocess.check_output(['git','-C',str(final),'rev-parse','HEAD'],text=True,stderr=subprocess.PIPE,env=env).strip()
        dirty=subprocess.check_output(['git','-C',str(final),'status','--porcelain','--untracked-files=all'],text=True,stderr=subprocess.PIPE,env=env).strip()
        if not (final/'.git').exists() or head!=revision or dirty:raise ValueError('not the clean pinned checkout')
    except (OSError,ValueError,subprocess.CalledProcessError):
        import shlex
        raise SystemExit('Existing OH installation is invalid. Preserve it by moving '+shlex.quote(str(final))+' to a separate recovery directory, then rerun this setup command. No files were deleted.')
if not final.exists():
    temporary=Path(tempfile.mkdtemp(prefix='.install-',dir=parent))
    try:
        subprocess.run(['git','clone','--no-checkout',repository,str(temporary)],check=True)
        subprocess.run(['git','-C',str(temporary),'checkout','--detach',revision],check=True)
        if subprocess.check_output(['git','-C',str(temporary),'rev-parse','HEAD'],text=True).strip()!=revision:
            raise RuntimeError('Pinned revision mismatch')
        temporary.rename(final)
    finally:
        if temporary.exists():shutil.rmtree(temporary)
print('Installed OH '+revision)
print('Project entry point: '+str(root/'.oh/oh'))
