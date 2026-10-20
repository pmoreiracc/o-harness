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
    def test_owned_command_cannot_execute_before_its_identity_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker=Path(tmp)/'executed'
            command=[sys.executable,'-c','from pathlib import Path;import sys;Path(sys.argv[1]).touch()',str(marker)]
            def refuse(child):
                self.assertIsNotNone(system.process_identity(child.pid))
                time.sleep(.1)
                self.assertFalse(marker.exists())
                raise OSError('Cannot save ownership')
            with self.assertRaisesRegex(OSError,'Cannot save ownership'):
                system.spawn(command,on_spawn=refuse)
            self.assertFalse(marker.exists())

    @unittest.skipIf(os.name=='nt','POSIX process-group recovery; Windows uses named jobs')
    def test_recovery_refuses_reused_identity_and_cleans_identified_descendants(self):
        with tempfile.TemporaryDirectory() as tmp:
            beat=Path(tmp)/'beat'
            descendant='import signal,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN)\nwhile True:\n open(sys.argv[1],"a").write(".");time.sleep(.02)'
            leader='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]]);time.sleep(30)'
            child=system.spawn([sys.executable,'-c',leader,descendant,str(beat)])
            try:
                until=time.monotonic()+5
                while not beat.exists() and time.monotonic()<until:time.sleep(.02)
                self.assertTrue(beat.exists())
                identity=system.process_identity(child.pid)
                self.assertIsNone(system.recover_process({'process':{'pid':child.pid,'identity':'wrong'}}))
                self.assertIsNone(child.poll())
                proof=system.recover_process({'process':{'pid':child.pid,'identity':identity}})
                self.assertEqual(proof['source'],'owned-process-group-cleaned')
                size=beat.stat().st_size;time.sleep(.1)
                self.assertEqual(beat.stat().st_size,size)
            finally:
                system.stop(child,force=True);child.wait(timeout=5)
        with patch.object(system,'boot_time',return_value=200):
            self.assertIsNone(system.recover_process({'started':'1970-01-01T00:05:00+00:00'}))
            self.assertEqual(system.recover_process({'started':'1970-01-01T00:01:00+00:00'})['source'],'kernel-reboot')
        self.assertEqual(system.recover_process({'gated':True})['source'],'command-never-released')

    def test_explicit_command_deadline_still_cancels(self):
        from .processes import capture
        with tempfile.TemporaryDirectory() as tmp:
            result,reasons=capture(Path(tmp),[sys.executable,'-c','import time;time.sleep(30)'],timeout=.1)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(reasons,['timeout'])

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
