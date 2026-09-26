import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from .storage import Refused
from .service import install,LABEL

def launcher(tmp):
    path=Path(tmp)/'state/bin/oh';path.parent.mkdir(parents=True);path.write_text('')

@unittest.skipIf(os.name=='nt','The launchd service is macOS only')
class ServiceTest(unittest.TestCase):
    def test_failed_upgrade_restores_prior_registration_and_running_service(self):
        with tempfile.TemporaryDirectory() as tmp,patch('oh.service.sys.platform','darwin'),patch('pathlib.Path.home',return_value=Path(tmp)),patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
            launcher(tmp)
            path=Path(tmp)/'Library/LaunchAgents'/f'{LABEL}.plist';path.parent.mkdir(parents=True);original=b'prior service registration';path.write_bytes(original)
            calls=[]
            def launch(args,**kwargs):
                calls.append(args[1])
                if calls==['print']:return subprocess.CompletedProcess(args,0)
                if calls==['print','bootout']:return subprocess.CompletedProcess(args,0)
                if calls==['print','bootout','bootstrap']:raise subprocess.CalledProcessError(5,args)
                if args[1]=='print':return subprocess.CompletedProcess(args,1)
                self.assertEqual(path.read_bytes(),original);return subprocess.CompletedProcess(args,0)
            with patch('oh.service.subprocess.run',side_effect=launch):
                with self.assertRaises(Refused):install()
            self.assertEqual(path.read_bytes(),original);self.assertEqual(calls,['print','bootout','bootstrap','print','bootstrap'])

    def test_partial_bootstrap_is_removed_before_restoring_prior_state(self):
        for previous in (False,True):
            with self.subTest(previous=previous),tempfile.TemporaryDirectory() as tmp,patch('oh.service.sys.platform','darwin'),patch('pathlib.Path.home',return_value=Path(tmp)),patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
                launcher(tmp)
                path=Path(tmp)/'Library/LaunchAgents'/f'{LABEL}.plist';path.parent.mkdir(parents=True)
                if previous:path.write_bytes(b'prior')
                state={'loaded':'prior' if previous else None,'failed':False}
                def launch(args,**kwargs):
                    command=args[1]
                    if command=='print':return subprocess.CompletedProcess(args,0 if state['loaded'] else 1)
                    if command=='bootout':state['loaded']=None;return subprocess.CompletedProcess(args,0)
                    if command=='bootstrap':
                        if not state['failed']:
                            state.update(loaded='replacement',failed=True);raise subprocess.CalledProcessError(5,args)
                        self.assertEqual(path.read_bytes(),b'prior');self.assertIsNone(state['loaded']);state['loaded']='prior'
                        return subprocess.CompletedProcess(args,0)
                    self.fail(command)
                with patch('oh.service.subprocess.run',side_effect=launch):
                    with self.assertRaises(Refused):install()
                self.assertEqual(state['loaded'],'prior' if previous else None)
                self.assertEqual(path.exists(),previous)
