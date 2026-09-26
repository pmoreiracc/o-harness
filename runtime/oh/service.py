from __future__ import annotations

import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
from .storage import Refused,state_home

LABEL='dev.o-harness.dashboard'


def gone(target,tries=30,pause=0.1):
    # bootout returns before launchd finishes teardown; bootstrapping the label before then fails with EIO.
    for _ in range(tries):
        if subprocess.run(['launchctl','print',target],capture_output=True).returncode:return True
        time.sleep(pause)
    return False


def said(result,fallback=''):
    stderr=getattr(result,'stderr',None)
    return (stderr.decode(errors='replace').strip() if isinstance(stderr,bytes) else '') or fallback


def install():
    if sys.platform!='darwin':raise Refused('Local auto-start currently supports macOS; run oh serve under your service manager on other systems')
    # The stable launcher resolves the active core, so a restart picks up an upgrade.
    launcher=state_home()/'bin/oh'
    if not launcher.is_file():raise Refused('OH is not set up. Run the plugin scripts/oh setup first.')
    path=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
    path.parent.mkdir(parents=True,exist_ok=True)
    logs=state_home()/'logs';logs.mkdir(exist_ok=True)
    value={'Label':LABEL,'ProgramArguments':[sys.executable,'-I',str(launcher),'serve'],
      'WorkingDirectory':str(state_home()),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,
      'StandardOutPath':str(logs/'dashboard.log'),'StandardErrorPath':str(logs/'dashboard-error.log'),
      'EnvironmentVariables':{'PATH':os.environ.get('PATH','/usr/bin:/bin'),'OH_DATA_HOME':str(state_home()),'OH_SERVICE_FOLLOWS_ACTIVE':'1'}}
    previous=path.read_bytes() if path.exists() else None
    domain=f'gui/{os.getuid()}';target=domain+'/'+LABEL
    running=subprocess.run(['launchctl','print',target],capture_output=True).returncode==0
    if running and previous is None:raise Refused('The running dashboard has no saved registration; restore its plist before upgrading')
    def publish(data):
        temporary=path.with_suffix('.pending')
        with temporary.open('wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        temporary.replace(path)
        from .backup import sync_parent
        sync_parent(path)
    replacement_attempted=False;stopped=None
    try:
        publish(plistlib.dumps(value))
        if running:
            # None: old service untouched; False: bootout failed, maybe mid-teardown; True: bootout succeeded.
            stopped=False
            subprocess.run(['launchctl','bootout',target],check=True,capture_output=True)
            stopped=True
            if not gone(target):raise OSError('launchd still lists '+target+' after bootout')
        replacement_attempted=True
        subprocess.run(['launchctl','bootstrap',domain,str(path)],check=True,capture_output=True)
    except (OSError,subprocess.CalledProcessError) as exc:
        # Failed bootstrap can still leave the replacement registered. A label's
        # existence cannot tell us whether it is the old or new service.
        present=replacement_attempted and subprocess.run(['launchctl','print',target],capture_output=True).returncode==0
        if present:
            removal=subprocess.run(['launchctl','bootout',target],capture_output=True)
            if removal.returncode or not gone(target):
                if previous is not None:publish(previous)
                raise Refused('Dashboard rollback could not remove the current registration ('+said(removal,'exit '+str(removal.returncode) if removal.returncode else 'still listed after bootout')+'). Run launchctl bootout '+target+(', then launchctl bootstrap '+domain+' '+str(path)+' to restart the previous dashboard' if running else ' before reinstalling' if previous is not None else ' and remove '+str(path)+' before reinstalling')+'.') from exc
        if previous is None:
            path.unlink(missing_ok=True)
            from .backup import sync_parent
            sync_parent(path)
        else:
            publish(previous)
            # A bootout, even a failed one, may still be tearing the old service down; wait before judging it.
            if running and (replacement_attempted or (stopped is not None and gone(target))):
                recovery=subprocess.run(['launchctl','bootstrap',domain,str(path)],capture_output=True)
                if recovery.returncode:raise Refused('Dashboard install failed; prior registration restored but could not restart. Run launchctl bootstrap '+domain+' '+str(path)+' after repairing launchd: '+said(recovery,'exit '+str(recovery.returncode))) from exc
            elif stopped is not None:raise Refused('Dashboard install failed ('+said(exc,str(exc))+'); the previous dashboard '+('was stopped' if stopped else 'may still be stopping')+' and launchd still lists '+target+'. Once launchctl print '+target+' fails, run launchctl bootstrap '+domain+' '+str(path)) from exc
        raise Refused('Dashboard install failed ('+said(exc,str(exc))+'); previous registration and running service were restored when present') from exc
    return {'url':'http://localhost:4318','service':str(path)}


def uninstall():
    if sys.platform!='darwin':raise Refused('macOS service only')
    subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{LABEL}'],capture_output=True)
    (Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist').unlink(missing_ok=True)
    return {'status':'stopped','data':'preserved'}
