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

class ServiceTest(unittest.TestCase):
    def installed(self,tmp):
        launcher(tmp)
        path=Path(tmp)/'Library/LaunchAgents'/f'{LABEL}.plist';path.parent.mkdir(parents=True);path.write_bytes(b'prior');return path

    def test_replacement_bootstraps_only_after_launchd_releases_the_label(self):
        with tempfile.TemporaryDirectory() as tmp,patch('oh.service.sys.platform','darwin'),patch('pathlib.Path.home',return_value=Path(tmp)),patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
            path=self.installed(tmp);state={'loaded':'prior','teardown':None};calls=[]
            def launch(args,**kwargs):
                calls.append(args[1])
                if args[1]=='print':
                    if state['teardown'] is not None:
                        state['teardown']-=1
                        if state['teardown']<0:state['loaded']=None
                    return subprocess.CompletedProcess(args,0 if state['loaded'] else 1)
                if args[1]=='bootout':state['teardown']=3;return subprocess.CompletedProcess(args,0)
                if state['loaded']:raise subprocess.CalledProcessError(5,args,stderr=b'Bootstrap failed: 5: Input/output error')
                state['loaded']=path.read_bytes();return subprocess.CompletedProcess(args,0)
            with patch('oh.service.subprocess.run',side_effect=launch),patch('oh.service.time.sleep'):install()
            self.assertEqual(calls.count('bootstrap'),1);self.assertIn(b'serve',state['loaded']);self.assertNotEqual(path.read_bytes(),b'prior')

    def test_failed_upgrade_restores_prior_registration_and_running_service(self):
        with tempfile.TemporaryDirectory() as tmp,patch('oh.service.sys.platform','darwin'),patch('pathlib.Path.home',return_value=Path(tmp)),patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
            path=self.installed(tmp);state={'loaded':b'prior'}
            def launch(args,**kwargs):
                if args[1]=='print':return subprocess.CompletedProcess(args,0 if state['loaded'] else 1)
                if args[1]=='bootout':state['loaded']=None;return subprocess.CompletedProcess(args,0)
                if path.read_bytes()!=b'prior':raise subprocess.CalledProcessError(5,args,stderr=b'Bootstrap failed: 5: Input/output error')
                state['loaded']=path.read_bytes();return subprocess.CompletedProcess(args,0)
            with patch('oh.service.subprocess.run',side_effect=launch),patch('oh.service.time.sleep'):
                with self.assertRaisesRegex(Refused,'Input/output error'):install()
            self.assertEqual(path.read_bytes(),b'prior');self.assertEqual(state['loaded'],b'prior')

    def test_label_that_never_clears_fails_within_bound(self):
        for stage in ('replacement','rollback'):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as tmp,patch('oh.service.sys.platform','darwin'),patch('pathlib.Path.home',return_value=Path(tmp)),patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
                path=self.installed(tmp);calls=[];waited=[]
                def launch(args,**kwargs):
                    calls.append(args[1])
                    if args[1]=='bootstrap':raise subprocess.CalledProcessError(5,args,stderr=b'Bootstrap failed: 5: Input/output error')
                    # Rollback stage: the old label clears, then the failed replacement stays listed.
                    return subprocess.CompletedProcess(args,1 if stage=='rollback' and calls.count('bootout')==1 and 'bootstrap' not in calls else 0)
                with patch('oh.service.subprocess.run',side_effect=launch),patch('oh.service.time.sleep',side_effect=waited.append):
                    with self.assertRaisesRegex(Refused,'still li') as caught:install()
                self.assertEqual(path.read_bytes(),b'prior');self.assertLessEqual(sum(waited),5)
                self.assertEqual('bootstrap' in calls,stage=='rollback')
                if stage=='rollback':self.assertIn('could not remove',str(caught.exception))

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
