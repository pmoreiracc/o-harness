import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from . import test_workflow as fixtures
from .entry import receive
from .authority import pending_file
from .config import HOME
from .storage import atomic_json,digest,read_json,Refused
from .workflow import start
from .runner import run


class PluginTransitions(unittest.TestCase):
    setUp=fixtures.WorkflowTest.setUp
    git=fixtures.WorkflowTest.git
    event=fixtures.WorkflowTest.event
    fake=fixtures.WorkflowTest.fake

    def test_first_use_and_unprepared_work_do_not_block_a_later_exact_trigger(self):
        payload={'hook_event_name':'UserPromptSubmit','session_id':'s','turn_id':'1','cwd':str(self.root),'prompt':'$o-harness:oh-deliver implement the agreed change'}
        hook=HOME/'plugins/o-harness/scripts/human-event.py'
        result=subprocess.run(['python3',str(hook),'codex'],input=json.dumps(payload),text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('onboarding',result.stdout)
        self.assertFalse(receive(self.root,'codex',payload)['authorized'])
        self.assertFalse(pending_file(self.root).exists())
        self.assertFalse(receive(self.root,'codex',payload|{'prompt':'$o-harness:oh-start'})['authorized'])
        self.assertTrue(receive(self.root,'codex',payload|{'turn_id':'2','prompt':'$o-harness:oh-deliver request:'+'a'*64})['pending'])

    def test_unprefixed_prose_is_not_an_invocation(self):
        payload={'hook_event_name':'UserPromptSubmit','session_id':'s','turn_id':'1','cwd':str(self.root)}
        for prompt in ('design a new logo','propose a name','deliver it today','oh-stop','/design a logo','/deliver it','oh start request:'+'a'*64,'$oh request:'+'a'*64):
            self.assertIsNone(receive(self.root,'codex',payload|{'prompt':prompt}))
        self.assertFalse(pending_file(self.root).exists())

    def test_bare_choices_get_no_onboarding_before_setup(self):
        hook=HOME/'plugins/o-harness/scripts/human-event.py'
        with __import__('tempfile').TemporaryDirectory() as home:
            def send(prompt):
                return subprocess.run(['python3',str(hook),'claude'],input=json.dumps({'prompt':prompt,'cwd':str(self.root)}),
                    text=True,capture_output=True,env=os.environ|{'OH_DATA_HOME':home},check=True).stdout
            self.assertEqual(send('continue'),'')
            self.assertIn('onboarding',send('/oh-propose a plan'))

    def test_launcher_pins_only_unfinished_runs_after_an_upgrade(self):
        home=Path(os.environ['OH_DATA_HOME']);key=digest(str(self.root.resolve()))
        checkout=read_json(home/'registry/checkouts'/(key+'.json'))['checkout']
        atomic_json(home/'runtime/active.json',{'revision':'v2'})
        for revision in ('v1','v2'):
            path=home/'versions'/revision/'oh';path.parent.mkdir(parents=True)
            path.write_text('print('+repr(revision)+')')
        atomic_json(home/'checkout-state'/checkout/'oh-active-run.json',{'project':self.project_id,'run':'fixture'})
        journal=home/'projects'/self.project_id/'runs/fixture'
        atomic_json(journal/'000001.json',{'kind':'run.started','data':{'harness_version':'v1'}})
        entry=HOME/'plugins/o-harness/scripts/oh'
        def call():return subprocess.check_output([str(entry),'--root',str(self.root),'start'],text=True).strip()
        self.assertEqual(call(),'v1')
        for terminal in ('completed','stopped','pr'):
            atomic_json(journal/'000002.json',{'kind':'transition','data':{'events':[{'kind':'run.status','data':{'status':terminal}}]}})
            self.assertEqual(call(),'v2')
        (home/'versions/v1/oh').unlink()
        self.assertEqual(call(),'v2')

    def test_repair_review_retains_prior_family_and_exact_subject(self):
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        manifests=[]
        def review(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            if args[4]=='review':
                request=read_json(args[5]/'request.json');binding=request['prior_reviews'];prior=read_json(Path(binding['path']))
                self.assertEqual(digest(prior),binding['hash']);manifests.append(prior)
                if len(manifests)==1:
                    value['structured'].update(verdict='blocking',findings=[{'severity':'blocking','description':'Fix both sibling paths','path':'output.txt','family':'sibling-paths','relation':'original'}])
            return value
        self.assertEqual(run(self.root,review)['completed'],1)
        self.assertEqual(manifests[0],[])
        self.assertEqual(manifests[1][0]['findings'][0]['family'],'sibling-paths')
        self.assertTrue(manifests[1][0]['git_tree'])

    def tracked_script(self):
        script=self.root/'checks.sh';script.write_text('#!/bin/sh\nexit 0\n')
        self.git('add','checks.sh');self.git('commit','-qm','Add verification script')
        return script

    def test_portable_profile_contains_no_identity_or_authority_and_import_is_fresh(self):
        from .profiles import export_profile,import_profile
        from .registry import lookup,profile_path
        self.tracked_script()
        atomic_json(profile_path(self.root,'checks.json'),[{'name':'review-only','command':['bash','checks.sh','{base}'],'modes':['review'],'inputs':['.'],'when':['*.py'],'toolchain':[['python3','--version']],'timeout_seconds':30}])
        destination=Path(self.temp.name)/'portable.json'
        export_profile(self.root,destination);value=read_json(destination)
        self.assertEqual(set(value),{'schema_version','profile','config','checks'})
        self.assertNotIn('id',value['profile'])
        clone=Path(self.temp.name)/'clone'
        subprocess.run(['git','clone','-q',str(self.root),str(clone)],check=True)
        imported=import_profile(clone,destination)
        self.assertFalse(imported['authorized'])
        self.assertNotEqual(lookup(clone)['checkout'],lookup(self.root)['checkout'])
        self.assertNotEqual(imported['profile']['id'],self.project_id)
        self.assertEqual(read_json(profile_path(clone,'checks.json')),value['checks'])
        self.assertFalse(pending_file(clone).exists())
        self.assertFalse((clone/'.oh').exists())
        subprocess.run(['bash','checks.sh','main'],cwd=clone,check=True)
        with self.assertRaises(Refused):import_profile(clone,destination)

    def test_portable_checks_refuse_secret_arguments_and_invalid_supported_fields(self):
        from .profiles import export_profile,import_profile,validate_document
        from .registry import profile_path
        destination=Path(self.temp.name)/'portable.json'
        self.tracked_script()
        atomic_json(profile_path(self.root,'checks.json'),[{'name':'check','command':['bash','checks.sh']}])
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
                atomic_json(profile_path(self.root,'checks.json'),candidate['checks'])
                target=Path(self.temp.name)/'refused.json'
                with self.assertRaises(Refused):export_profile(self.root,target)
                self.assertFalse(target.exists())
                atomic_json(target,candidate)
                with self.assertRaises(Refused):import_profile(self.root,target)
                target.unlink()

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

    def test_imported_direct_script_runs_the_tracked_file_even_with_a_path_collision(self):
        from .profiles import export_profile,import_profile
        from .registry import profile_path
        from .verification import verify
        script=self.tracked_script();script.chmod(0o755)
        self.git('add','checks.sh');self.git('commit','-qm','Make verification executable')
        checks=[{'name':'direct','command':['./checks.sh']}]
        atomic_json(profile_path(self.root,'checks.json'),checks)
        destination=Path(self.temp.name)/'direct.json';export_profile(self.root,destination)
        clone=Path(self.temp.name)/'direct-clone'
        subprocess.run(['git','clone','-q',str(self.root),str(clone)],check=True)
        imported=import_profile(clone,destination)
        shadow=Path(self.temp.name)/'shadow';shadow.mkdir()
        wrong=shadow/'checks.sh';wrong.write_text('#!/bin/sh\nexit 97\n');wrong.chmod(0o755)
        search=[str(shadow)]+[p for p in os.environ['PATH'].split(os.pathsep) if p and p!='.' and Path(p).resolve() not in (clone.resolve(),self.root.resolve())]
        with patch.dict(os.environ,{'PATH':os.pathsep.join(search)}):
            results=verify(clone,read_json(profile_path(clone,'checks.json')),imported['profile']['id'])
        self.assertEqual(results[0]['returncode'],0)
