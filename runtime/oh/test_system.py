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
    @unittest.skipUnless(os.name=='nt','Actual Windows shell working directory')
    def test_owned_command_keeps_native_shell_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with system.spawn([os.environ['ComSpec'],'/d','/c','cd'],cwd=system.Path(tmp),
                              stdout=system.subprocess.PIPE,stderr=system.subprocess.PIPE,text=True) as child:
                output,error=child.communicate(timeout=5)
                self.assertEqual(child.returncode,0,error)
            self.assertEqual(Path(output.strip()),Path(tmp))
            self.assertEqual(error,'')

    def test_long_paths_preserve_evidence_identity_atomicity_and_cleanup(self):
        from .storage import atomic_json, read_json, Journal, identifier
        from .receipts import save
        from .authority import _records
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        # Remove only this fixture, using the native filesystem spelling for deep children.
        self.addCleanup(system.shutil.rmtree,system.Path(temp.name))
        # macOS may spell its temporary root through the /var -> /private/var alias.
        folder=system.Path(temp.name).resolve()/('long data '+ 'a'*80)/('b'*90)/('c'*90)
        self.assertGreater(len(str(folder)),260)
        with patch.dict(os.environ,{'OH_DATA_HOME':str(folder)}):
            path=folder/'evidence.json'
            original={'path':str(path),'value':'original'}
            atomic_json(str(path),original,immutable=True)
            with system.temporary_directory(dir=folder) as scratch:
                scratch=system.Path(scratch)
                (scratch/'probe').write_text('temporary')
                self.assertEqual((scratch/'probe').read_text(),'temporary')
            self.assertFalse(scratch.exists())
            self.assertEqual(read_json(str(path)),original)
            with self.assertRaises(FileExistsError):atomic_json(str(path),{'value':'replacement'},immutable=True)
            self.assertEqual(read_json(str(path)),original)
            self.assertEqual(str(path.resolve()),str(path))
            self.assertEqual(system.Path(os.fspath(path)),path)
            self.assertNotIn('\\\\?\\',str(path))
            if os.name=='nt':
                unc=system.Path(r'\\server\share\folder')
                self.assertEqual(os.fspath(unc),r'\\?\UNC\server\share\folder')
                self.assertEqual(system.Path(os.fspath(unc)),unc)
            receipt=folder/'report.md'
            save(str(receipt),'original',immutable=True)
            save(str(receipt),'original',immutable=True)
            with self.assertRaises(Refused):save(str(receipt),'replacement',immutable=True)
            save(str(receipt),'updated')
            self.assertEqual(receipt.read_text(),'updated')
            journal=Journal(identifier(),identifier())
            journal.append('test',original)
            self.assertEqual(Journal(journal.path.parent.parent.name,journal.path.name).records()[0]['data'],original)
            self.assertEqual(list(_records(str(path))),[original])
            self.assertFalse(list(folder.rglob('.pending-*')))
            self.assertFalse(list(folder.rglob('.receipt-*')))

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
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.addCleanup(system.shutil.rmtree,system.Path(temp.name))
        path=system.Path(temp.name)/('a'*90)/('b'*90)/('c'*90)/'oh-control.lock'
        acquired=threading.Event()
        def waiter():
            with lock(str(path)):acquired.set()
        with lock(path):
            with self.assertRaises(Refused):
                with lock(str(path),wait=False):pass
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
