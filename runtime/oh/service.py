from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
from .storage import Refused,state_home

LABEL='dev.o-harness.dashboard'
TASK='OH dashboard'
# Task Scheduler starts this at logon without a window. It runs the active core's dashboard and starts it again
# after an upgrade or a crash; its job object ends the dashboard with it when the task is ended.
STARTER='''"""OH dashboard at logon (Task Scheduler). Written by oh service-install."""
import ctypes,json,os,subprocess,time
from ctypes import wintypes
CONFIG=json.loads(%r)
os.environ.update(CONFIG['env'])
kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
kernel32.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];kernel32.CreateJobObjectW.restype=wintypes.HANDLE
kernel32.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
kernel32.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE];kernel32.GetCurrentProcess.restype=wintypes.HANDLE
class Basic(ctypes.Structure):
    _fields_=[('user',ctypes.c_int64),('job',ctypes.c_int64),('flags',wintypes.DWORD),('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),
              ('processes',wintypes.DWORD),('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
class Extended(ctypes.Structure):
    _fields_=[('basic',Basic),('io',ctypes.c_uint64*6),('memory',ctypes.c_size_t*4)]
job=kernel32.CreateJobObjectW(None,None);limits=Extended();limits.basic.flags=0x2000  # kill on job close
kernel32.SetInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits))
kernel32.AssignProcessToJobObject(job,kernel32.GetCurrentProcess())
data=CONFIG['env']['OH_DATA_HOME']
while True:
    revision=json.loads(open(os.path.join(data,'runtime','active.json'),'rb').read())['revision']
    with open(CONFIG['log'],'ab') as out,open(CONFIG['errors'],'ab') as errors:
        code=subprocess.call([CONFIG['python'],'-I','-X','utf8',os.path.join(data,'versions',revision,'oh'),'serve'],
                             stdin=subprocess.DEVNULL,stdout=out,stderr=errors,creationflags=0x08000000)  # no window
    time.sleep(1 if code==0 else 10)
'''


def gone(target,tries=30,pause=0.1):
    # bootout returns before launchd finishes teardown; bootstrapping the label before then fails with EIO.
    for _ in range(tries):
        if subprocess.run(['launchctl','print',target],capture_output=True).returncode:return True
        time.sleep(pause)
    return False


def said(result,fallback=''):
    stderr=getattr(result,'stderr',None)
    return (stderr.decode(errors='replace').strip() if isinstance(stderr,bytes) else '') or fallback


def schtasks(*args,check=True):
    program=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/'schtasks.exe'
    return subprocess.run([str(program),*args],capture_output=True,check=check)


def install_windows():
    """A Task Scheduler task that starts the dashboard at your logon, without admin rights or a window."""
    from xml.sax.saxutils import escape
    if not (state_home()/'bin/oh').is_file():raise Refused('OH is not set up. Run the plugin scripts/oh setup first.')
    logs=state_home()/'logs';logs.mkdir(exist_ok=True)
    python=Path(sys.executable);windowless=python.with_name('pythonw.exe')
    config={'python':str(python),'log':str(logs/'dashboard.log'),'errors':str(logs/'dashboard-error.log'),
            'env':{'OH_DATA_HOME':str(state_home()),'OH_SERVICE_FOLLOWS_ACTIVE':'1','PATH':os.environ.get('PATH','')}|(
                {'XDG_CONFIG_HOME':os.environ['XDG_CONFIG_HOME']} if os.environ.get('XDG_CONFIG_HOME') else {})}
    from .config import write_text
    starter=state_home()/'bin/dashboard.pyw';write_text(starter,STARTER%json.dumps(config))
    user=os.environ.get('USERDOMAIN','')+'\\'+os.environ.get('USERNAME','')
    task=f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>OH dashboard at http://localhost:4318</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escape(user)}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{escape(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(str(windowless if windowless.is_file() else python))}</Command>
    <Arguments>-I "{escape(str(starter))}"</Arguments><WorkingDirectory>{escape(str(state_home()))}</WorkingDirectory></Exec></Actions>
</Task>
'''
    definition=state_home()/'service/dashboard-task.xml';definition.parent.mkdir(parents=True,exist_ok=True)
    definition.write_text(task,encoding='utf-16')
    try:
        schtasks('/Create','/F','/TN',TASK,'/XML',str(definition))
        schtasks('/End','/TN',TASK,check=False)  # a running dashboard ends with its job; the new one starts below
        schtasks('/Run','/TN',TASK)
    except subprocess.CalledProcessError as exc:
        raise Refused('Task Scheduler refused the dashboard task: '+said(exc,str(exc))) from exc
    return {'url':'http://localhost:4318','service':TASK}


def install():
    from .system import WINDOWS
    if WINDOWS:return install_windows()
    if sys.platform!='darwin':raise Refused('Local auto-start supports macOS and Windows; run oh serve under your service manager on other systems')
    # The stable launcher resolves the active core, so a restart picks up an upgrade.
    launcher=state_home()/'bin/oh'
    if not launcher.is_file():raise Refused('OH is not set up. Run the plugin scripts/oh setup first.')
    path=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
    path.parent.mkdir(parents=True,exist_ok=True)
    logs=state_home()/'logs';logs.mkdir(exist_ok=True)
    value={'Label':LABEL,'ProgramArguments':[sys.executable,'-I',str(launcher),'serve'],
      'WorkingDirectory':str(state_home()),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,
      'StandardOutPath':str(logs/'dashboard.log'),'StandardErrorPath':str(logs/'dashboard-error.log'),
      'EnvironmentVariables':{'PATH':os.environ.get('PATH','/usr/bin:/bin'),'OH_DATA_HOME':str(state_home()),'OH_SERVICE_FOLLOWS_ACTIVE':'1'}|(
        {'XDG_CONFIG_HOME':os.environ['XDG_CONFIG_HOME']} if os.environ.get('XDG_CONFIG_HOME') else {})}  # the dashboard reads your settings too
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
                raise Refused('Dashboard rollback could not remove the current registration ('+said(removal,'exit '+str(removal.returncode) if removal.returncode else 'still listed after bootout')+'). Run launchctl bootout '+target+' and, once launchctl print '+target+' fails, '+('run launchctl bootstrap '+domain+' '+str(path)+' to restart the previous dashboard' if running else 'reinstall' if previous is not None else 'remove '+str(path)+' and reinstall')+'.') from exc
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
            elif stopped:raise Refused('Dashboard install failed: the previous dashboard was stopped but launchd still lists '+target+'. Once launchctl print '+target+' fails, run launchctl bootstrap '+domain+' '+str(path)) from exc
            elif stopped is not None:raise Refused('Dashboard install failed ('+said(exc,str(exc))+'); its registration file is back in place and the previous dashboard is probably still running. If launchctl print '+target+' later fails, run launchctl bootstrap '+domain+' '+str(path)) from exc
        raise Refused('Dashboard install failed ('+said(exc,str(exc))+'); previous registration and running service were restored when present') from exc
    return {'url':'http://localhost:4318','service':str(path)}


def uninstall():
    from .system import WINDOWS
    if WINDOWS:
        schtasks('/End','/TN',TASK,check=False);schtasks('/Delete','/F','/TN',TASK,check=False)
        (state_home()/'bin/dashboard.pyw').unlink(missing_ok=True)
        return {'status':'stopped','data':'preserved'}
    if sys.platform!='darwin':raise Refused('macOS and Windows services only')
    subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{LABEL}'],capture_output=True)
    (Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist').unlink(missing_ok=True)
    return {'status':'stopped','data':'preserved'}
