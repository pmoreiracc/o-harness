from __future__ import annotations

import os
from pathlib import Path
import plistlib
import subprocess
import sys
from .storage import Refused,state_home

LABEL='dev.o-harness.dashboard'


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
    domain=f'gui/{os.getuid()}'
    running=subprocess.run(['launchctl','print',domain+'/'+LABEL],capture_output=True).returncode==0
    if running and previous is None:raise Refused('The running dashboard has no saved registration; restore its plist before upgrading')
    def publish(data):
        temporary=path.with_suffix('.pending')
        with temporary.open('wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        temporary.replace(path)
        from .backup import sync_parent
        sync_parent(path)
    replacement_attempted=False
    try:
        publish(plistlib.dumps(value))
        if running:subprocess.run(['launchctl','bootout',domain+'/'+LABEL],check=True,capture_output=True)
        replacement_attempted=True
        subprocess.run(['launchctl','bootstrap',domain,str(path)],check=True,capture_output=True)
    except (OSError,subprocess.CalledProcessError) as exc:
        # Failed bootstrap can still leave the replacement registered. A label's
        # existence cannot tell us whether it is the old or new service.
        present=replacement_attempted and subprocess.run(['launchctl','print',domain+'/'+LABEL],capture_output=True).returncode==0
        if present:
            stopped=subprocess.run(['launchctl','bootout',domain+'/'+LABEL],capture_output=True)
            if stopped.returncode:
                if previous is not None:publish(previous)
                raise Refused('Dashboard rollback could not remove the current registration. Run launchctl bootout '+domain+'/'+LABEL+' and restore the saved registration before reinstalling.') from exc
        if previous is None:
            path.unlink(missing_ok=True)
            from .backup import sync_parent
            sync_parent(path)
        else:
            publish(previous)
            if running and (replacement_attempted or subprocess.run(['launchctl','print',domain+'/'+LABEL],capture_output=True).returncode!=0):
                recovery=subprocess.run(['launchctl','bootstrap',domain,str(path)],capture_output=True)
                if recovery.returncode:raise Refused('Dashboard install failed; prior registration restored but could not restart. Run launchctl bootstrap '+domain+' '+str(path)+' after repairing launchd: '+recovery.stderr.decode(errors='replace')) from exc
        raise Refused('Dashboard install failed; previous registration and running service were restored when present') from exc
    return {'url':'http://localhost:4318','service':str(path)}


def uninstall():
    if sys.platform!='darwin':raise Refused('macOS service only')
    subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{LABEL}'],capture_output=True)
    (Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist').unlink(missing_ok=True)
    return {'status':'stopped','data':'preserved'}
