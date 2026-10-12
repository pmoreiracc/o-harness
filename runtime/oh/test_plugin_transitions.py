import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from . import test_workflow as fixtures
from .entry import receive
from .authority import pending_file
from .config import HOME, project_checks
from .test_workflow import configure, write_settings
from .storage import atomic_json,digest,read_json,Refused
from .workflow import start
from .runner import run
# POSIX users run OH's scripts directly, so tests do too; Windows needs the interpreter.
RUN=[sys.executable,'-I'] if os.name=='nt' else []


class PluginTransitions(unittest.TestCase):
    setUp=fixtures.WorkflowTest.setUp
    git=fixtures.WorkflowTest.git
    event=fixtures.WorkflowTest.event
    fake=fixtures.WorkflowTest.fake

    def test_first_use_and_unprepared_work_do_not_block_a_later_exact_trigger(self):
        payload={'hook_event_name':'UserPromptSubmit','session_id':'s','turn_id':'1','cwd':str(self.root),'prompt':'$o-harness:oh-deliver implement the agreed change'}
        hook=HOME/'plugins/o-harness/scripts/human-event.py'
        result=subprocess.run([sys.executable,str(hook),'codex'],input=json.dumps(payload),text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('onboarding',result.stdout)
        from .workflow import active_file
        # Preparation is staged for native approval; neither entry point grants a run.
        for prompt in (payload['prompt'],'$o-harness:oh-start'):
            self.assertTrue(receive(self.root,'codex',payload|{'prompt':prompt})['pending'])
            self.assertEqual(read_json(pending_file(self.root))['payload']['prompt'],prompt)
            self.assertFalse(active_file(self.root).exists())
        exact='$o-harness:oh-deliver request:'+'a'*64
        self.assertTrue(receive(self.root,'codex',payload|{'turn_id':'2','prompt':exact})['pending'])
        self.assertEqual(read_json(pending_file(self.root))['payload']['prompt'],exact)
        # The first command typed in a new checkout registers it, as init would, and carries on.
        fresh=Path(self.temp.name)/'fresh';fresh.mkdir();subprocess.run(['git','init','-q',str(fresh)],check=True)
        self.assertTrue(receive(fresh,'codex',payload|{'cwd':str(fresh),'prompt':'$o-harness:oh-propose an idea'})['pending'])

    def test_unprefixed_prose_is_not_an_invocation(self):
        payload={'hook_event_name':'UserPromptSubmit','session_id':'s','turn_id':'1','cwd':str(self.root)}
        for prompt in ('design a new logo','propose a name','deliver it today','oh-stop','/design a logo','/deliver it','oh start request:'+'a'*64,'$oh request:'+'a'*64):
            self.assertIsNone(receive(self.root,'codex',payload|{'prompt':prompt}))
        self.assertFalse(pending_file(self.root).exists())

    def test_bare_choices_get_no_onboarding_before_setup(self):
        hook=HOME/'plugins/o-harness/scripts/human-event.py'
        with __import__('tempfile').TemporaryDirectory() as home:
            def send(prompt):
                return subprocess.run([sys.executable,str(hook),'claude'],input=json.dumps({'prompt':prompt,'cwd':str(self.root)}),
                    text=True,capture_output=True,env=os.environ|{'OH_DATA_HOME':home},check=True).stdout
            self.assertEqual(send('continue'),'')
            self.assertIn('onboarding',send('/oh-propose a plan'))

    def test_launcher_pins_only_unfinished_runs_after_an_upgrade(self):
        home=Path(os.environ['OH_DATA_HOME']);key=digest(str(self.root.resolve()))
        checkout=read_json(home/'registry/checkouts'/(key+'.json'))['checkout']
        atomic_json(home/'runtime/active.json',{'revision':'v2'})
        for revision in ('v1','v2','v3'):
            path=home/'versions'/revision/'oh';path.parent.mkdir(parents=True)
            path.write_text('print('+repr(revision)+')')
        atomic_json(home/'checkout-state'/checkout/'oh-active-run.json',{'project':self.project_id,'run':'fixture'})
        journal=home/'projects'/self.project_id/'runs/fixture'
        atomic_json(journal/'000001.json',{'kind':'run.started','data':{'harness_version':'v1'}})
        entry=HOME/'plugins/o-harness/scripts/oh'
        def call(command='start'):return subprocess.check_output([*RUN,str(entry),'--root',str(self.root),command],text=True).strip()
        self.assertEqual(call(),'v1')
        for terminal in ('completed','stopped','pr'):
            atomic_json(journal/'000002.json',{'kind':'transition','data':{'events':[{'kind':'run.status','data':{'status':terminal}}]}})
            self.assertEqual(call(),'v2')
        # docs/architecture.md: an explicit stopped-task continuation pins its newer runtime,
        # while a later plugin upgrade still cannot switch the live execution underneath it.
        atomic_json(journal/'000003.json',{'kind':'transition','data':{'events':[
            {'kind':'delivery.continued','data':{'version':'v2'}},
            {'kind':'run.status','data':{'status':'running'}}]}})
        atomic_json(journal/'000004.json',{'kind':'run.status','data':{'status':'review_checkpoint'}})
        atomic_json(home/'runtime/active.json',{'revision':'v3'})
        for command in ('start','run','resume','pause','stop'):
            self.assertEqual(call(command),'v2')
        self.assertEqual(call('deliver'),'v3')  # the explicit command can adopt this unchanged waiting checkpoint
        atomic_json(journal/'000005.json',{'kind':'run.status','data':{'status':'running'}})
        self.assertEqual(call('deliver'),'v2')  # a live execution never switches underneath its worker
        atomic_json(journal/'000006.json',{'kind':'run.status','data':{'status':'stopped'}})
        self.assertEqual(call(),'v3')
        (home/'versions/v1/oh').unlink()
        self.assertEqual(call(),'v3')

    def test_repair_review_retains_prior_family_and_exact_subject(self):
        start(self.root,{'tasks':self.tasks[:1]},self.event())
        manifests=[]
        repair_history=[]
        def review(*args,**kwargs):
            value=self.fake(*args,**kwargs)
            if args[4]=='implementation':
                request=read_json(args[5]/'request.json')
                if (packet:=read_json(request['task_context']['path'])).get('current_work'):
                    binding=packet['findings'];prior=read_json(binding['path'])
                    self.assertEqual(digest(prior),binding['hash']);repair_history.append(prior)
            if args[4]=='review':
                request=read_json(args[5]/'request.json');packet=read_json(request['task_context']['path']);binding=packet['findings'];prior=read_json(Path(binding['path']))
                self.assertEqual(digest(prior),binding['hash']);manifests.append(prior)
                if len(manifests)==1:
                    value['structured'].update(verdict='blocking',findings=[{'severity':'blocking','description':description,'path':'output.txt','family':'sibling-paths','relation':'original'} for description in ('Fix first sibling path','Fix second sibling path')])
            return value
        self.assertEqual(run(self.root,review)['completed'],1)
        self.assertEqual(manifests[0]['families'],[])
        self.assertEqual(manifests[1]['families'][0]['family'],'sibling-paths')
        from .handoff import finding_ids
        self.assertEqual(finding_ids(repair_history[0]),finding_ids(manifests[1]))
        family=manifests[1]['families'][0]
        self.assertEqual(len(family['cases']),2)  # same family never erases a distinct original failure
        self.assertTrue(all(f['disposition']=='still-open' and f['author_claim']['disposition']=='fixed' for f in family['occurrences']))
        self.assertTrue(manifests[1]['families'][0]['occurrences'][0]['tree'])
        from .workflow import load_run
        journal,state=load_run(self.root)
        request=read_json(journal.path/'attempts'/state['attempts'][-1]['id']/'request.json')
        packet=read_json(request['task_context']['path'])
        self.assertEqual(packet['schema'],2)
        self.assertEqual(packet['current_work']['attempt'],state['attempts'][-2]['id'])
        self.assertNotIn('implementer_reports',request)
        self.assertEqual(len(packet['current_work']['readiness']['prior_findings']),2)
        from .handoff import prepare,validate_readiness,finding_ids
        older=next(a for a in state['attempts'] if a['role']=='implementation')
        expanded=state|{'attempts':[older|{'id':'retained-'+str(n)} for n in range(50)]+state['attempts']}
        ref,index=prepare(expanded,state['tasks'][0],'review',journal.path/'context-check',request)
        self.assertEqual(read_json(ref['path'])['current_work'],packet['current_work'])
        self.assertIsNone(validate_readiness(packet['current_work']['readiness'],finding_ids(index)))
        self.assertIsNotNone(validate_readiness(packet['current_work']['readiness']|{'prior_findings':[]},finding_ids(index)))
        self.assertTrue(all(f['disposition']=='fixed' and f['reviewed_by']==state['attempts'][-1]['id'] for f in index['families'][0]['occurrences']))
        interrupted=older|{'id':'interrupted','outcome':'interrupted','evidence':str(journal.path/'attempts'/'interrupted')}
        missing,_=prepare(state|{'attempts':state['attempts']+[interrupted]},state['tasks'][0],'implementation',journal.path/'interrupted-context',request)
        self.assertFalse(read_json(missing['path'])['current_work']['report']['available'])
        receipt=journal.path/'attempts'/state['attempts'][-1]['id']/'review.md'
        saved=receipt.read_bytes()
        self.assertIn(b'No findings.',saved)
        self.assertIn(b'Result SHA-256',saved)
        self.assertIn('Review 2',(journal.path/'index.md').read_text())
        self.assertIn('Confirmed by [review]',(journal.path/'index.md').read_text())
        run(self.root,self.fake)
        self.assertEqual(receipt.read_bytes(),saved)

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
        self.assertFalse(pending_file(clone).exists())
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
