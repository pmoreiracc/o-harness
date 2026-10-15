import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from . import test_workflow as fixtures
from .config import HOME, project_checks
from .test_workflow import configure, write_settings
from .storage import atomic_json,digest,read_json,Refused
# POSIX users run OH's scripts directly, so tests do too; Windows needs the interpreter.
RUN=[sys.executable,'-I'] if os.name=='nt' else []


class PluginTransitions(unittest.TestCase):
    setUp=fixtures.WorkflowTest.setUp
    git=fixtures.WorkflowTest.git
    event=fixtures.WorkflowTest.event
    fake=fixtures.WorkflowTest.fake

    def test_launcher_selects_current_helpers_without_restarting_a_retired_executor(self):
        home=Path(os.environ['OH_DATA_HOME']);key=digest(str(self.root.resolve()))
        checkout=read_json(home/'registry/checkouts'/(key+'.json'))['checkout']
        for revision in ('old-runner','current'):
            path=home/'versions'/revision/'oh';path.parent.mkdir(parents=True)
            path.write_text('print('+repr(revision)+')',newline='\n')
        atomic_json(home/'runtime/active.json',{'revision':'current'})
        atomic_json(home/'checkout-state'/checkout/'oh-active-run.json',{'project':self.project_id,'run':'fixture'})
        journal=home/'projects'/self.project_id/'runs/fixture'
        atomic_json(journal/'000001.json',{'kind':'run.started','data':{'harness_version':'old-runner'}})
        entry=HOME/'plugins/o-harness/scripts/oh'
        for status in ('running','prepared_checkpoint','paused','review_checkpoint','stopped','completed','pr'):
            atomic_json(journal/'000002.json',{'kind':'run.status','data':{'status':status}})
            for command in ('status','resume'):
                self.assertEqual(subprocess.check_output([*RUN,str(entry),'--root',str(self.root),command],text=True).strip(),'current')
        # Runtime selection is not permission to adopt or launch the retained unfinished work.
        (home/'versions/old-runner/oh').unlink()
        self.assertEqual(subprocess.check_output([*RUN,str(entry),'--root',str(self.root),'status'],text=True).strip(),'current')

    def tracked_script(self):
        script=self.root/'checks.sh';script.write_text('#!/bin/sh\nexit 0\n',newline='\n')
        self.git('add','checks.sh');self.git('commit','-qm','Add verification script')
        return script

    def test_portable_profile_contains_no_identity_or_authority_and_import_is_fresh(self):
        from .profiles import export_profile,import_profile
        from .registry import lookup,profile_path
        self.tracked_script()
        configure(self.root,checks=[{'name':'review-only','command':['bash','checks.sh','{base}'],'modes':['review'],'inputs':['.'],'when':['*.py'],'toolchain':[['python3','--version']],'timeout_seconds':30}])
        destination=Path(self.temp.name)/'portable.json'
        export_profile(self.root,destination);value=read_json(destination)
        self.assertEqual(set(value),{'schema_version','profile','config','checks'})
        self.assertNotIn('id',value['profile'])
        clone=Path(self.temp.name)/'clone'
        subprocess.run(['git','clone','-q',str(self.root),str(clone)],check=True)
        imported=import_profile(clone,destination,'Fixture clone')
        self.assertFalse(imported['authorized'])
        self.assertNotEqual(lookup(clone)['checkout'],lookup(self.root)['checkout'])
        self.assertNotEqual(imported['profile']['id'],self.project_id)
        self.assertEqual(project_checks(clone),value['checks'])
        self.assertFalse((clone/'.oh').exists())
        subprocess.run([shutil.which('bash'),'checks.sh','main'],cwd=clone,check=True)
        with self.assertRaises(Refused):import_profile(clone,destination,'Fixture clone')

    def test_this_repository_s_own_profile_imports(self):
        # CONTRIBUTING tells contributors to import it; a check it names that import refuses would strand them.
        from .config import HOME
        from .profiles import validate_document
        validate_document(read_json(HOME/'integrations/oh-profile.json'),HOME)

    def test_portable_checks_refuse_secret_arguments_and_invalid_supported_fields(self):
        from .profiles import export_profile,import_profile,validate_document
        from .registry import profile_path
        destination=Path(self.temp.name)/'portable.json'
        self.tracked_script()
        configure(self.root,checks=[{'name':'check','command':['bash','checks.sh']}])
        export_profile(self.root,destination);value=read_json(destination)
        bad_checks=[
            {'command':['tool','--token','secret-value']},
            {'command':['bash','checks.sh','--password=secret-value']},
            {'command':['python3','-c','print("secret-value")']},
            {'command':['bash','checks.sh','unlabelled-secret']},
            {'toolchain':[['tool','--token','secret-value']]},
            {'toolchain':'python3 --version'}, {'inputs':'src'}, {'inputs':['../private']},
            {'when':'*.py'}, {'modes':'review'}, {'modes':['unsupported']},
            {'timeout_seconds':True}, {'timeout_seconds':float('inf')}, {'timeout_seconds':0},
        ]
        for change in bad_checks:
            with self.subTest(change=change):
                candidate=value|{'checks':[value['checks'][0]|change]}
                with self.assertRaises(Refused):validate_document(candidate,self.root)
                write_settings(self.root,{'checks':candidate['checks']})  # some are only refused on export, others on every read
                target=Path(self.temp.name)/'refused.json'
                with self.assertRaises(Refused):export_profile(self.root,target)
                self.assertFalse(target.exists())
                atomic_json(target,candidate)
                with self.assertRaises(Refused):import_profile(self.root,target)
                target.unlink()

    @unittest.skipIf(os.name=='nt','Windows runs no script directly by its executable bit and shebang')
    def test_portable_scripts_must_exist_be_tracked_and_not_follow_symlinks(self):
        from .profiles import portable_command
        script=self.tracked_script()
        portable_command(['bash','checks.sh'],self.root)
        for path in ('sentinel-secret.py','not/a/repository/script.sh'):
            with self.assertRaises(Refused):portable_command(['bash',path],self.root)
        other=self.root/'untracked.sh';other.write_text('exit 0\n')
        with self.assertRaises(Refused):portable_command(['bash','untracked.sh'],self.root)
        link=self.root/'linked.sh';link.symlink_to(script)
        self.git('add','linked.sh')
        with self.assertRaises(Refused):portable_command(['bash','linked.sh'],self.root)
        directory=self.root/'nested';directory.mkdir();(directory/'check.sh').write_text('exit 0\n')
        self.git('add','nested/check.sh')
        (self.root/'alias').symlink_to(directory,target_is_directory=True)
        with self.assertRaises(Refused):portable_command(['bash','alias/check.sh'],self.root)
        with self.assertRaises(Refused):portable_command(['./checks.sh'],self.root)
        script.chmod(0o755);self.git('add','checks.sh')
        with self.assertRaises(Refused):portable_command(['checks.sh'],self.root)
        portable_command(['./checks.sh'],self.root)
        subprocess.run(['./checks.sh'],cwd=self.root,check=True,env=os.environ|{'PATH':''})
        script.unlink()
        with self.assertRaises(Refused):portable_command(['./checks.sh'],self.root)

    @unittest.skipIf(os.name=='nt','Windows runs no script directly by its executable bit and shebang')
    def test_imported_direct_script_runs_the_tracked_file_even_with_a_path_collision(self):
        from .profiles import export_profile,import_profile
        from .registry import profile_path
        from .verification import verify
        script=self.tracked_script();script.chmod(0o755)
        self.git('add','checks.sh');self.git('commit','-qm','Make verification executable')
        checks=[{'name':'direct','command':['./checks.sh']}]
        configure(self.root,checks=checks)
        destination=Path(self.temp.name)/'direct.json';export_profile(self.root,destination)
        clone=Path(self.temp.name)/'direct-clone'
        subprocess.run(['git','clone','-q',str(self.root),str(clone)],check=True)
        imported=import_profile(clone,destination,'Fixture clone')
        shadow=Path(self.temp.name)/'shadow';shadow.mkdir()
        wrong=shadow/'checks.sh';wrong.write_text('#!/bin/sh\nexit 97\n');wrong.chmod(0o755)
        search=[str(shadow)]+[p for p in os.environ['PATH'].split(os.pathsep) if p and p!='.' and Path(p).resolve() not in (clone.resolve(),self.root.resolve())]
        with patch.dict(os.environ,{'PATH':os.pathsep.join(search)}):
            results=verify(clone,project_checks(clone),imported['profile']['id'])
        self.assertEqual(results[0]['returncode'],0)
