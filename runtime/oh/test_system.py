import os
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from . import system
from .storage import Refused, lock, snapshot_guard
from . import hosts


class SystemTest(unittest.TestCase):
    def attempt_directory(self,tmp):
        directory=Path(tmp)/'attempt';directory.mkdir()
        # The host lifecycle fixtures do not call checks, but start/close their real native service.
        (directory/'request.json').write_text(json.dumps({'role':'implementation','verification_timeout':60}),newline='\n')
        return directory

    def test_workers_relay_public_focus_without_repetition_over_thirteen_minutes(self):
        """docs/usage.md: both hosts expose only fresh bounded public focus at a sparse cadence."""
        for host in ('codex','claude'):
            with self.subTest(host=host),tempfile.TemporaryDirectory() as tmp:
                def public(text):
                    return ({'type':'item.completed','item':{'type':'agent_message','text':text}} if host=='codex'
                            else {'type':'assistant','message':{'content':[{'type':'text','text':text}]}})
                report={'status':'completed','readiness':{'requirements':['Fixture output -> file -> read'], 'self_review':['Read -> expected fixture'], 'repairs':[], 'limits':[]},'summary':'Finished fixture','found_along_way':[],'obstacle':None}
                private=({'type':'item.completed','item':{'type':'reasoning','text':'private reasoning'}} if host=='codex'
                         else {'type':'assistant','message':{'content':[{'type':'thinking','thinking':'private reasoning'}]}})
                tool=({'type':'item.completed','item':{'type':'command_execution','aggregated_output':'private tool output'}} if host=='codex'
                      else {'type':'user','message':{'content':[{'type':'tool_result','content':'private tool output'}]}})
                final=(public(json.dumps(report)) if host=='codex' else
                       {'type':'result','result':json.dumps(report),'structured_output':report,'is_error':False})
                events=[public('Starting the fixture.'),public('Adding selection rows.'),public('Adding selection rows.'),
                        public('Connecting capabilities.'),public('Binding preview and save.'),private,
                        public('Checking the stale preview regression.'),tool,final]
                script='import sys;sys.stdin.read();'+';'.join('print('+repr(json.dumps(e))+',flush=True)' for e in events)
                output=io.StringIO();directory=self.attempt_directory(tmp)
                with patch('oh.hosts.authentication'),patch('oh.capabilities.validate_profile'), \
                     patch('oh.hosts.command',return_value=[sys.executable,'-c',script]), \
                     patch('oh.hosts.time') as clock,contextlib.redirect_stderr(output):
                    clock.monotonic.side_effect=[0,0,60,210,240,420,421,600,630,780,780]
                    result=hosts.invoke(host,Path(tmp),{},'work','implementation',directory,
                        {'project':'fixture','attempt':'worker','standalone':True},schema=hosts.WORK_SCHEMA)
                self.assertFalse(result['failed'],result);self.assertEqual(result['duration_ms'],780000)
                self.assertEqual(result['structured'],report)
                self.assertEqual(output.getvalue().splitlines(),[
                    'The implementation agent: Adding selection rows.',
                    'The implementation agent: Binding preview and save.',
                    'The implementation agent: Checking the stale preview regression.'])
                focus=json.loads((directory/'focus.json').read_text())
                self.assertEqual(focus['message'],'Checking the stale preview regression.')
                self.assertNotIn('private',json.dumps(focus));self.assertNotIn('Finished fixture',json.dumps(focus))
                # Large public text stays bounded; repeated text does not manufacture a fresh timestamp.
                focus=hosts.worker_focus(host,public('x'*1000),directory,focus)
                self.assertEqual(len(focus['message']),600)
                self.assertIs(hosts.worker_focus(host,public('x'*1000),directory,focus),focus)
                with patch('oh.hosts.atomic_json',side_effect=OSError('visibility unavailable')):
                    self.assertEqual(hosts.worker_focus(host,public('Continuing implementation.'),directory,focus)['message'],
                                     'Continuing implementation.')

    def test_workers_outlive_elapsed_time_and_close_descendants_output(self):
        # docs/usage.md: elapsed task time is not failure; worker exit must still end the output stream.
        for host in ('codex','claude'):
            with self.subTest(host=host),tempfile.TemporaryDirectory() as tmp:
                event=({'type':'item.completed','item':{'type':'agent_message','text':'finished'}} if host=='codex'
                       else {'type':'result','result':'finished','is_error':False})
                late=({'type':'item.completed','item':{'type':'agent_message','text':'descendant survived'}} if host=='codex'
                      else {'type':'result','result':'descendant survived','is_error':False})
                descendant='import time;time.sleep(.5);print('+repr(json.dumps(late))+',flush=True)'
                script=('import subprocess,sys,time;sys.stdin.read();time.sleep(.2);'
                        'subprocess.Popen([sys.executable,"-c",'+repr(descendant)+']);'
                        'print('+repr(json.dumps(event))+',flush=True)')
                with patch('oh.hosts.authentication'),patch('oh.capabilities.validate_profile'), \
                     patch('oh.hosts.command',return_value=[sys.executable,'-c',script]), \
                     patch('oh.processes.time') as clock:
                    clock.monotonic.side_effect=[0]+[3600]*100
                    result=hosts.invoke(host,Path(tmp),{},'work','implementation',self.attempt_directory(tmp),
                                        {'project':'fixture','attempt':'worker','standalone':True})
                self.assertFalse(result['failed'],result)
                self.assertEqual(result['text'],'finished')
                self.assertEqual(result['cancellation'],[])

    def test_explicit_command_deadline_still_cancels(self):
        from .processes import capture
        with tempfile.TemporaryDirectory() as tmp:
            result,reasons=capture(Path(tmp),[sys.executable,'-c','import time;time.sleep(30)'],timeout=.1)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(reasons,['timeout'])

    @unittest.skipIf(system.WINDOWS,'Windows contains detached commands in the worker job object')
    def test_worker_cancellation_interrupts_the_host_to_clean_detached_commands(self):
        # Codex starts shell tools in separate sessions; SIGTERM skips its interrupt cleanup.
        for host in ('codex','claude'):
            with self.subTest(host=host),tempfile.TemporaryDirectory() as tmp:
                closed=Path(tmp)/'command-closed'
                script='''import signal,subprocess,sys,time
from pathlib import Path
command=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'],
    start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def interrupt(signum,frame):
    command.terminate();command.wait(timeout=2)
    Path(sys.argv[1]).touch()
    raise SystemExit(130)
signal.signal(signal.SIGINT,interrupt)
sys.stdin.read()
time.sleep(10)
'''
                with patch('oh.hosts.authentication'),patch('oh.capabilities.validate_profile'), \
                     patch('oh.hosts.command',return_value=[sys.executable,'-c',script,str(closed)]):
                    result=hosts.invoke(host,Path(tmp),{},'work','implementation',self.attempt_directory(tmp),
                        {'project':'fixture','attempt':'worker','standalone':True},timeout=1)
                self.assertTrue(closed.exists(),'Host did not finish cleaning its detached command')
                self.assertEqual(result['cancellation'],['timeout'])
                self.assertTrue(result['failed'])

    def test_state_writers_share_the_snapshot_lock_and_a_backup_waits_for_all_of_them(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
            together=threading.Barrier(3,timeout=5);release=threading.Event()
            def writer():
                with snapshot_guard():together.wait();release.wait(5)
            writers=[threading.Thread(target=writer) for _ in range(2)]
            for thread in writers:thread.start()
            try:
                together.wait()  # A run and a pause request hold it at the same time.
                with self.assertRaises(Refused):
                    with snapshot_guard(exclusive=True):pass
            finally:
                release.set()
                for thread in writers:thread.join()
            with snapshot_guard(exclusive=True):pass

    def test_checkout_lock_refuses_without_waiting_and_otherwise_waits_for_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'oh-control.lock';acquired=threading.Event()
            def waiter():
                with lock(path):acquired.set()
            with lock(path):
                with self.assertRaises(Refused):
                    with lock(path,wait=False):pass
                thread=threading.Thread(target=waiter);thread.start()
                self.assertFalse(acquired.wait(.5))
            self.assertTrue(acquired.wait(5));thread.join()

    def test_windows_bash_uses_native_tools_and_preserves_explicit_interpreters(self):
        # docs/usage.md: bare bash never silently enters WSL; explicit interpreters and PowerShell are kept.
        with tempfile.TemporaryDirectory() as tmp,patch.object(system,'WINDOWS',True):
            root=Path(tmp);wsl=root/'Windows'/'System32'/'bash.exe'
            native=root/'Git with spaces'/'bin'/'bash.exe';git=native.parent.parent/'cmd'/'git.exe'
            alias=root/'Local'/'Microsoft'/'WindowsApps'/'bash.exe'
            for path in (wsl,alias,native,git):path.parent.mkdir(parents=True,exist_ok=True);path.touch()
            env={'SystemRoot':str(wsl.parent.parent),'LOCALAPPDATA':str(alias.parents[2]),'PATH':str(wsl.parent)}
            found={'bash':str(wsl),'bash.exe':str(wsl),'git':str(git),'powershell':'chosen-powershell'}
            with patch.object(system.shutil,'which',side_effect=lambda name,path=None:found.get(name)):
                self.assertEqual(system.executable('bash',env=env),str(native))
                self.assertEqual(system.executable('bash.exe',env=env),str(native))
                found['bash']=str(alias)
                self.assertEqual(system.executable('bash',env=env),str(native))
                self.assertEqual(system.executable(str(alias),env=env),str(alias))
                self.assertEqual(system.executable(str(wsl),env=env),str(wsl))
                self.assertEqual(system.executable('powershell',env=env),'chosen-powershell')
                portable=root/'portable'/'bash.exe';portable.parent.mkdir();portable.touch()
                env['PATH']+=os.pathsep+str(portable.parent)
                self.assertEqual(system.executable('bash',env=env),str(portable))
                portable.unlink();native.unlink()
                with self.assertRaisesRegex(FileNotFoundError,'Git for Windows'):
                    system.executable('bash',env=env)
        with patch.object(system,'WINDOWS',False):self.assertEqual(system.executable('bash'),'bash')

    def test_stop_ends_descendants_after_the_leader_has_exited(self):
        with tempfile.TemporaryDirectory() as tmp:
            beat=Path(tmp)/'beat'
            grandchild='import sys,time\nwhile True:\n    open(sys.argv[1],"a").write(".");time.sleep(.05)'
            leader='import subprocess,sys;subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]])'
            child=system.spawn([sys.executable,'-c',leader,grandchild,str(beat)])
            try:
                system.wait_for_exit(child)
                deadline=time.monotonic()+15
                while not (beat.exists() and beat.stat().st_size>2) and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(beat.exists())
            finally:
                system.stop(child,force=True);child.wait(timeout=10)
            time.sleep(.3);size=beat.stat().st_size
            time.sleep(.5)
            self.assertEqual(beat.stat().st_size,size)


if __name__=='__main__':unittest.main()
