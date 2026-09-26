import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from .storage import Refused
from .service import install,LABEL

def result(args,code,kwargs,stderr=b'Bootstrap failed: 5: Input/output error'):
    # Real launchctl only raises through subprocess when the caller passes check=True.
    if kwargs.get('check'):raise subprocess.CalledProcessError(code,args,stderr=stderr)
    return subprocess.CompletedProcess(args,code,stderr=stderr)

def launcher(tmp):
    path=Path(tmp)/'state/bin/oh';path.parent.mkdir(parents=True);path.write_text('')

@unittest.skipIf(os.name=='nt','The launchd service is macOS only')
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
                if state['loaded']:return result(args,5,kwargs)
                state['loaded']=path.read_bytes();return subprocess.CompletedProcess(args,0)
            with patch('oh.service.subprocess.run',side_effect=launch),patch('oh.service.time.sleep'):install()
            self.assertEqual(calls.count('bootstrap'),1);self.assertIn(b'serve',state['loaded']);self.assertNotEqual(path.read_bytes(),b'prior')

    def test_failed_upgrade_restores_prior_registration_and_running_service(self):
        with tempfile.TemporaryDirectory() as tmp,patch('oh.service.sys.platform','darwin'),patch('pathlib.Path.home',return_value=Path(tmp)),patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
            path=self.installed(tmp);state={'loaded':b'prior'}
            def launch(args,**kwargs):
                if args[1]=='print':return subprocess.CompletedProcess(args,0 if state['loaded'] else 1)
                if args[1]=='bootout':state['loaded']=None;return subprocess.CompletedProcess(args,0)
                if path.read_bytes()!=b'prior':return result(args,5,kwargs)
                state['loaded']=path.read_bytes();return subprocess.CompletedProcess(args,0)
            with patch('oh.service.subprocess.run',side_effect=launch),patch('oh.service.time.sleep'):
                with self.assertRaisesRegex(Refused,'Input/output error'):install()
            self.assertEqual(path.read_bytes(),b'prior');self.assertEqual(state['loaded'],b'prior')

    def test_slow_teardown_restarts_the_prior_service_or_says_it_is_stopped(self):
        # launchd releases the old label only after `clears` polls, or never; bootout itself may report failure mid-teardown.
        for clears,refused in ((40,None),(2,36),(None,None),(None,36)):
            with self.subTest(clears=clears,refused=refused),tempfile.TemporaryDirectory() as tmp,patch('oh.service.sys.platform','darwin'),patch('pathlib.Path.home',return_value=Path(tmp)),patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
                path=self.installed(tmp);state={'label':True,'alive':b'prior','polls':None};waited=[]
                def launch(args,**kwargs):
                    if args[1]=='print':
                        if state['polls'] is not None:
                            state['polls']+=1
                            if clears is not None and state['polls']>clears:state['label']=False
                        return subprocess.CompletedProcess(args,0 if state['label'] else 1)
                    if args[1]=='bootout':
                        state.update(polls=0,alive=None)
                        if refused:return result(args,refused,kwargs,b'Boot-out failed: 36: Operation now in progress')
                        return subprocess.CompletedProcess(args,0)
                    if state['label']:return result(args,5,kwargs)
                    state.update(label=True,alive=path.read_bytes());return subprocess.CompletedProcess(args,0)
                with patch('oh.service.subprocess.run',side_effect=launch),patch('oh.service.time.sleep',side_effect=waited.append):
                    with self.assertRaises(Refused) as caught:install()
                self.assertEqual(path.read_bytes(),b'prior');self.assertLessEqual(sum(waited),10)
                if clears is None:
                    self.assertIn('launchctl bootstrap',str(caught.exception));self.assertNotIn('restored',str(caught.exception))
                else:self.assertEqual(state['alive'],b'prior')

    def test_rollback_that_cannot_remove_the_replacement_fails_within_bound(self):
        with tempfile.TemporaryDirectory() as tmp,patch('oh.service.sys.platform','darwin'),patch('pathlib.Path.home',return_value=Path(tmp)),patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
            path=self.installed(tmp);calls=[];waited=[]
            def launch(args,**kwargs):
                calls.append(args[1])
                if args[1]=='bootstrap':return result(args,5,kwargs)
                # The old label clears after the first bootout; the failed replacement then stays listed.
                return subprocess.CompletedProcess(args,1 if args[1]=='print' and calls.count('bootout')==1 and 'bootstrap' not in calls else 0)
            with patch('oh.service.subprocess.run',side_effect=launch),patch('oh.service.time.sleep',side_effect=waited.append):
                with self.assertRaisesRegex(Refused,'could not remove.*still listed.*once launchctl print .* fails, run launchctl bootstrap'):install()
            self.assertEqual(path.read_bytes(),b'prior');self.assertLessEqual(sum(waited),5)

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
