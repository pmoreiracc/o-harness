from .registry import register
import contextlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from .storage import Refused


class IntegrationTest(unittest.TestCase):
    @staticmethod
    def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL,text=True).strip()

    def test_missing_codex_model_uses_only_an_earlier_compatible_family(self):
        from .capabilities import select_profile
        requested={'model':'gpt-6.11-sol','effort':'high'}
        catalog={'gpt-6.2-sol':{'high'},'gpt-6.10-sol':{'high'},'gpt-6.12-sol':{'high'},
                 'gpt-6.10-astra':{'high'},'gpt-6.10-sol-special':{'high'},'gpt-6.10.1-sol':{'low'}}
        with patch('oh.capabilities.codex_models',return_value=catalog) as discover:
            actual,fallback=select_profile('codex',requested,Path('/project'))
            self.assertEqual(actual,{'model':'gpt-6.10-sol','effort':'high'})
            self.assertEqual(requested,{'model':'gpt-6.11-sol','effort':'high'})
            self.assertEqual((fallback['requested'],fallback['actual']),(requested,actual))
            self.assertIn('Continuing with gpt-6.10-sol / high',fallback['notice'])
            self.assertIn('npm install -g @openai/codex@latest',fallback['notice'])
            self.assertIn('$oh-config',fallback['notice'])
            self.assertEqual(select_profile('codex',actual,Path('/project')),(actual,None))
            # Present models never silently change effort; other families, newer versions and
            # unversioned names do not create a compatible predecessor.
            for profile in ({'model':'gpt-6.10-sol','effort':'ultra'},
                            {'model':'gpt-6-sol','effort':'high'},
                            {'model':'custom-sol','effort':'high'}):
                with self.subTest(profile=profile),self.assertRaises(Refused):select_profile('codex',profile,Path('/project'))
            discover.reset_mock()
            claude={'model':'opus','effort':'high'}
            self.assertEqual(select_profile('claude',claude,Path('/project')),(claude,None))
            discover.assert_not_called()

    def test_path_spoof_cannot_select_host_executable(self):
        from .hosts import executable,trust
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp,'PATH':tmp,'LOCALAPPDATA':tmp}):
            os.environ.pop('CODEX_CLI_PATH',None)
            fake=Path(tmp)/'codex';fake.write_text('#!/bin/sh\necho codex-cli fake\n');fake.chmod(0o755)
            with self.assertRaises(Refused):executable('codex')
            with self.assertRaises(Refused):trust('codex',fake)

    def test_generic_deliver_branch_does_not_require_numbered_product_design(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp+'/state'}):
            root=Path(tmp)/'consumer';root.mkdir();self.git(root,'init','-qb','deliver/release');self.git(root,'config','user.name','Fixture');self.git(root,'config','user.email','fixture@example.invalid')
            register(root,'Generic');(root/'product.txt').write_text('fixture')
            self.git(root,'add','.');self.git(root,'commit','-qm','initial')
            # Ordinary work does not install or call OH Git hooks.
            (root/'manual.txt').write_text('normal coding')
            self.git(root,'add','manual.txt')
            self.git(root,'commit','-qm','Release ordinary work')
            self.assertEqual(self.git(root,'log','-1','--format=%s'),'Release ordinary work')
            self.assertFalse((root/'.oh').exists())

    @unittest.skipIf(os.name=='nt','POSIX npm layout: a symlinked Node wrapper')
    def test_trust_host_finds_the_native_codex_binary_behind_an_npm_wrapper(self):
        from .hosts import locate
        with tempfile.TemporaryDirectory() as tmp:
            package=Path(tmp)/'lib/node_modules/@openai/codex'
            wrapper=package/'bin/codex.js';wrapper.parent.mkdir(parents=True);wrapper.write_text('#!/usr/bin/env node\n');wrapper.chmod(0o755)
            native=package/'node_modules/@openai/codex-test/vendor/arch/bin/codex';native.parent.mkdir(parents=True);native.write_bytes(b'\x7fELF');native.chmod(0o755)
            bin_dir=Path(tmp)/'bin';bin_dir.mkdir();(bin_dir/'codex').symlink_to(wrapper)
            with patch.dict(os.environ,{'PATH':str(bin_dir)}):
                self.assertEqual(locate('codex',Path(tmp)/'elsewhere'),native.resolve())

    @unittest.skipUnless(os.name=='nt','Windows npm layout: a .cmd shim beside node_modules')
    def test_trust_host_finds_the_native_codex_binary_behind_the_windows_npm_shim(self):
        from .hosts import locate
        with tempfile.TemporaryDirectory() as tmp:
            npm=Path(tmp)/'npm';npm.mkdir();(npm/'codex.cmd').write_text('@ECHO off\r\nnode "%~dp0\\node_modules\\@openai\\codex\\bin\\codex.js" %*\r\n')
            package=npm/'node_modules/@openai/codex';(package/'bin').mkdir(parents=True);(package/'bin/codex.js').write_text('#!/usr/bin/env node\n')
            native=package/'node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
            native.parent.mkdir(parents=True);native.write_bytes(b'MZ')
            with patch.dict(os.environ,{'PATH':str(npm)}):
                self.assertEqual(locate('codex',Path(tmp)/'elsewhere'),native.resolve())

    def test_codex_is_found_through_its_windows_app_across_app_updates(self):
        import sys
        from types import SimpleNamespace
        from . import hosts
        with tempfile.TemporaryDirectory() as tmp,patch.object(hosts,'WINDOWS',True):
            tmp=Path(tmp);(tmp/'empty').mkdir();bin_dir=tmp/'OpenAI/Codex/bin'
            with patch.dict(os.environ,{'LOCALAPPDATA':str(tmp),'PATH':str(tmp/'empty'),'ProgramW6432':str(tmp/'pf')}):
                os.environ.pop('CODEX_CLI_PATH',None)
                # Not found is its own refusal: the updater gives it remedies instead of repeating install advice.
                with self.assertRaisesRegex(hosts.NotFound,'Install it or open the Codex app once'):hosts.locate('codex')
                def copy(folder,names=hosts.CODEX_APP_FILES):
                    for name in names:(bin_dir/folder).mkdir(parents=True,exist_ok=True);(bin_dir/folder/name).write_bytes(b'MZ'+name.encode())
                    return bin_dir/folder/'codex.exe'
                # The app's staging folders and other tools' copies are not CLI copies.
                for folder in ('.staging-2d3d1264c27dcfe3-x','not-a-hash-folder'):copy(folder)
                copy('0000000000000001',('rg.exe',))
                old=copy('0123456789abcdef')
                self.assertEqual(hosts.locate('codex'),old.resolve())
                # A copy still in use survives the app's cleanup; the registered package names the current one.
                package=tmp/'pf/WindowsApps/OpenAI.Codex_26.1.0.0_x64__2p2nqsd0c76g0';resources=package/'app/resources'
                resources.mkdir(parents=True)
                for name in hosts.CODEX_APP_FILES:(resources/name).write_bytes(b'MZ'+name.encode())
                current=copy('2d3d1264c27dcfe3')
                registered={}
                class Key(str):
                    def __enter__(self):return self
                    def __exit__(self,*args):pass
                def enum(key,index):
                    if index>=len(registered):raise OSError('no more keys')
                    return list(registered)[index]
                winreg=SimpleNamespace(HKEY_CURRENT_USER='HKCU',OpenKey=lambda parent,name:Key(name),EnumKey=enum,
                                       QueryValueEx=lambda key,name:(str(registered[key]),1))
                with patch.dict(sys.modules,{'winreg':winreg}):
                    undecided='several command-line copies'
                    with self.assertRaisesRegex(Refused,undecided):hosts.locate('codex')
                    registered['Other.Codex_26.1.0.0_x64__2p2nqsd0c76g0']=package
                    registered['OpenAI.Codex_26.1.0.0_x64__otherpublisher']=package
                    registered['OpenAI.Codex_26.1.0.0_x64__2p2nqsd0c76g0']=tmp/'elsewhere'
                    with self.assertRaisesRegex(Refused,undecided):hosts.locate('codex')
                    registered['OpenAI.Codex_26.1.0.0_x64__2p2nqsd0c76g0']=package
                    self.assertEqual(hosts.locate('codex'),current.resolve())
                    # The app's own override names its CLI; a missing one leaves the app's copies in use.
                    with patch.dict(os.environ,{'CODEX_CLI_PATH':str(old)}):self.assertEqual(hosts.locate('codex'),old.resolve())
                    with patch.dict(os.environ,{'CODEX_CLI_PATH':str(tmp/'gone.exe')}):
                        self.assertEqual(hosts.locate('codex'),current.resolve())
                    with contextlib.chdir(tmp),patch.dict(os.environ,{'CODEX_CLI_PATH':str(old.relative_to(tmp))}):
                        self.assertEqual(hosts.locate('codex'),current.resolve())
                    registered['OpenAI.Codex_26.2.0.0_x64__2p2nqsd0c76g0']=package
                    with self.assertRaisesRegex(Refused,undecided):hosts.locate('codex')
                    # A package moved to another drive is registered under that volume's WindowsApps.
                    registered.clear();moved=Path(tmp.anchor)/'WindowsApps/OpenAI.Codex_26.1.0.0_x64__2p2nqsd0c76g0'
                    registered['OpenAI.Codex_26.1.0.0_x64__2p2nqsd0c76g0']=moved
                    self.assertEqual(hosts.codex_package(),moved/'app/resources')
                # A copy the app removes between lookup and use asks for a retry, not an OS error.
                with patch.object(hosts,'installed',return_value=bin_dir/'fedcba9876543210/codex.exe'):
                    with self.assertRaisesRegex(Refused,'Retry the command'):hosts.locate('codex')
                # So does one removed at any later identity check: after lookup, against the record, or while trusting.
                probe=subprocess.CompletedProcess([],0,'codex-cli 0.154.0','')
                with patch.dict(os.environ,{'OH_DATA_HOME':str(tmp/'state')}),patch.object(hosts,'locate',return_value=current),\
                     patch.object(hosts.subprocess,'run',return_value=probe):
                    (tmp/'state/hosts').mkdir(parents=True)
                    (tmp/'state/hosts/codex.json').write_text(json.dumps({'path':str(old),'sha256':'old','pinned':False}))
                    for failing in (1,2,3):
                        checked=[]
                        def identity(path,root=None,**options):
                            checked.append(path)
                            if len(checked)==failing:raise FileNotFoundError(path)
                            return {'path':str(path),'sha256':'new'}
                        with patch.object(hosts,'binary_identity',side_effect=identity):
                            with self.assertRaisesRegex(Refused,'Retry the command'):hosts.executable('codex')
                        self.assertEqual(len(checked),failing)
                    # Claude has no app that replaces its binary, so it keeps main's behavior.
                    with patch.object(hosts,'binary_identity',side_effect=FileNotFoundError('gone')):
                        with self.assertRaises(FileNotFoundError):hosts.executable('claude')
                    # A copy removed during the Windows permission check, including through trust-host, is a retry too;
                    # a named binary, Claude, or a component that still exists keeps the permission refusal.
                    found=Path(sys.executable).resolve();unreadable='cannot read who may change'
                    with patch.object(hosts,'locate',return_value=found),patch('oh.system.untrusted',side_effect=FileNotFoundError(2,'gone')):
                        with self.assertRaisesRegex(Refused,unreadable):hosts.executable('codex')
                        with patch.object(type(found),'exists',return_value=False):
                            with self.assertRaisesRegex(Refused,'Retry the command'):hosts.executable('codex')
                            with self.assertRaisesRegex(Refused,'Retry the command'):hosts.trust('codex')
                            with self.assertRaisesRegex(Refused,unreadable):hosts.trust('codex',found)
                            with self.assertRaisesRegex(Refused,unreadable):hosts.executable('claude')
                    # A copy removed just after its path is resolved is reported as removed, not as not executable.
                    with patch.object(type(found),'exists',return_value=False),patch.object(type(found),'is_file',return_value=False):
                        with self.assertRaises(FileNotFoundError):hosts.binary_identity(found,removable=True)
                        with self.assertRaisesRegex(Refused,'not executable'):hosts.binary_identity(found)
            # A profile behind a junction or symlink still recognizes the app's copies once paths are resolved.
            real=tmp/'profile';(real/'OpenAI/Codex/bin/0123456789abcdef').mkdir(parents=True)
            if os.name=='nt':
                import _winapi
                _winapi.CreateJunction(str(real),str(tmp/'linked'))
            else:(tmp/'linked').symlink_to(real)  # windows-ok: Windows uses a junction above
            with patch.dict(os.environ,{'LOCALAPPDATA':str(tmp/'linked')}):
                self.assertTrue(hosts.in_codex_app((real/'OpenAI/Codex/bin/0123456789abcdef/codex.exe').resolve()))
                self.assertFalse(hosts.in_codex_app(real/'npm/codex.exe'))

    def test_host_binary_is_trusted_automatically_and_followed_across_updates(self):
        from . import hosts
        from .storage import read_json
        binaries={'claude':'v1'}
        def identity(path,root=None,**options):
            if Path(path).name=='gone':raise FileNotFoundError(path)
            return {'path':str(path),'sha256':binaries.get(Path(path).name,'pinned')}
        probe=subprocess.CompletedProcess([],0,'2.1.0 (Claude Code)','')
        opt,pinned=str(Path('/opt/claude')),str(Path('/custom/pinned'))
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp}),\
             patch.object(hosts,'binary_identity',side_effect=identity),patch.object(hosts,'locate',return_value=Path('/opt/claude')),\
             patch.object(hosts.subprocess,'run',return_value=probe) as run:
            record=Path(tmp)/'hosts/claude.json'
            self.assertEqual(hosts.executable('claude'),opt)
            self.assertEqual(read_json(record)['sha256'],'v1');self.assertFalse(read_json(record)['pinned'])
            self.assertEqual(hosts.executable('claude'),opt);self.assertEqual(run.call_count,1)
            # A self-updated CLI is checked again and recorded without a manual step.
            binaries['claude']='v2'
            self.assertEqual(hosts.executable('claude'),opt);self.assertEqual(read_json(record)['sha256'],'v2')
            self.assertEqual(run.call_count,2)
            # A version check failure refuses the new binary.
            binaries['claude']='v3';run.return_value=subprocess.CompletedProcess([],0,'something else','')
            with self.assertRaises(Refused):hosts.executable('claude')
            self.assertEqual(read_json(record)['sha256'],'v2')
            # An explicitly named path stays pinned, and a missing pin is refused clearly.
            run.return_value=probe
            hosts.trust('claude',Path('/custom/pinned'))
            self.assertEqual(hosts.executable('claude'),pinned)
            (record).write_text('{"path":"/custom/gone","sha256":"x","pinned":true}')
            with self.assertRaisesRegex(hosts.NotFound,'you pinned is gone'):hosts.executable('claude')

    def test_trust_records_from_before_automatic_trust_keep_working(self):
        from . import hosts
        from .storage import atomic_json,read_json
        identity=lambda path,root=None,**options:{'path':str(path),'sha256':'same'}
        probe=subprocess.CompletedProcess([],0,'codex-cli 0.154.0','')
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp}),\
             patch.object(hosts,'binary_identity',side_effect=identity),patch.object(hosts.subprocess,'run',return_value=probe):
            record=Path(tmp)/'hosts/codex.json'
            atomic_json(record,{'path':'/opt/native/codex','sha256':'same'})
            # PATH has no usable codex: the old record stays in use, now as a pin.
            with patch.object(hosts,'locate',side_effect=Refused('not found')),patch.object(hosts,'WINDOWS',False):
                self.assertEqual(hosts.executable('codex'),'/opt/native/codex')
            self.assertTrue(read_json(record)['pinned'])
            atomic_json(record,{'path':'/opt/native/codex','sha256':'same'})
            # PATH has another codex: OH follows it and says how to keep the old one.
            with patch.object(hosts,'locate',return_value=Path('/usr/local/bin/codex')),patch('sys.stderr') as err,\
                 patch.object(hosts,'WINDOWS',False):
                self.assertEqual(hosts.executable('codex'),str(Path('/usr/local/bin/codex')))
            self.assertIn('oh trust-host codex /opt/native/codex',''.join(c.args[0] for c in err.write.call_args_list))
            # On Windows neither a removed old binary nor a Codex app copy the app will replace is offered as a pin.
            app_copy=Path(tmp)/'OpenAI/Codex/bin/0123456789abcdef/codex.exe';app_copy.parent.mkdir(parents=True);app_copy.write_text('')
            with patch.object(hosts,'WINDOWS',True),patch.dict(os.environ,{'LOCALAPPDATA':tmp}):
                for old in (Path(tmp)/'removed/codex.exe',app_copy):
                    atomic_json(record,{'path':str(old),'sha256':'same'})
                    with patch.object(hosts,'locate',return_value=Path('/usr/local/bin/codex')),patch('sys.stderr') as err:
                        self.assertEqual(hosts.executable('codex'),str(Path('/usr/local/bin/codex')))
                    self.assertNotIn('oh trust-host',''.join(c.args[0] for c in err.write.call_args_list))
                # Without another usable copy, an existing app copy keeps working but stays unpinned.
                atomic_json(record,{'path':str(app_copy),'sha256':'same'})
                with patch.object(hosts,'locate',side_effect=Refused('not found')):
                    self.assertEqual(hosts.executable('codex'),str(app_copy))
                self.assertFalse(read_json(record)['pinned'])
                # A removed app copy keeps the lookup's own explanation rather than becoming a pin or a retry.
                atomic_json(record,{'path':str(app_copy.parent.parent/'fedcba9876543210/codex.exe'),'sha256':'same'})
                with patch.object(hosts,'locate',side_effect=Refused('not found')):
                    with self.assertRaisesRegex(Refused,'^not found$'):hosts.executable('codex')
                self.assertNotIn('pinned',read_json(record))
                # Elsewhere an existing old binary still becomes a pin; a removed one keeps the lookup's reason.
                native=Path(tmp)/'npm/codex.exe';native.parent.mkdir();native.write_text('')
                for old,expected in ((native,None),(Path(tmp)/'npm/removed.exe','several copies')):
                    atomic_json(record,{'path':str(old),'sha256':'same'})
                    with patch.object(hosts,'locate',side_effect=hosts.Undecided('several copies')):
                        if expected is None:self.assertEqual(hosts.executable('codex'),str(old))
                        else:
                            with self.assertRaisesRegex(hosts.Undecided,expected):hosts.executable('codex')
                    self.assertEqual(read_json(record).get('pinned'),True if expected is None else None)
                # Claude has no replacing app, so its legacy records keep main's messages on Windows too.
                claude=Path(tmp)/'hosts/claude.json';atomic_json(claude,{'path':str(Path(tmp)/'removed/claude.exe'),'sha256':'same'})
                with patch.object(hosts,'locate',return_value=Path('/usr/local/bin/claude')),patch('sys.stderr') as err,\
                     patch.object(hosts.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'2.1.0 (Claude Code)','')):
                    hosts.executable('claude')
                self.assertIn('To keep using',''.join(c.args[0] for c in err.write.call_args_list))


class GitSubjectTest(unittest.TestCase):
    """docs/architecture.md: Git subjects agree across review, staging and supported replacements."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'repo';self.root.mkdir()
        self.git('init','-qb','main');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        self.git('config','core.autocrlf','false');self.git('config','diff.renames','true')
        (self.root/'item').write_bytes(b'original\n')
        self.git('add','.');self.git('commit','-qm','initial')

    def git(self,*args):
        from .storage import git
        return git(self.root,*args)

    def test_git_configuration_agrees_and_inherited_selectors_cannot_choose_a_sibling(self):
        from .storage import git_env,git
        from .verification import tree,candidate_tree
        from .branches import run_git
        from .registry import identity
        global_config=Path(self.temp.name)/'global';global_config.write_bytes(b'[core]\n autocrlf = true\n')
        # Local configuration still overrides global; injected runtime configuration overrides local.
        with patch.dict(os.environ,{'GIT_CONFIG_GLOBAL':str(global_config)}):
            self.assertEqual(self.git('config','core.autocrlf'),'false')
        sibling=Path(self.temp.name)/'sibling'
        self.git('worktree','add','-qb','sibling',str(sibling))
        index=Path(self.git('rev-parse','--path-format=absolute','--git-path','index'))
        before=index.read_bytes()
        env={'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'core.autocrlf','GIT_CONFIG_VALUE_0':'true',
             'GIT_CONFIG_GLOBAL':str(global_config),'GIT_SSH_COMMAND':'fixture ssh',
             'GIT_DIR':str(sibling/'.git'),'GIT_WORK_TREE':str(sibling),'GIT_INDEX_FILE':str(Path(self.temp.name)/'wrong-index')}
        (self.root/'item').write_bytes(b'changed\r\n')
        with patch.dict(os.environ,env):
            selected=git_env()
            for key in ('GIT_CONFIG_COUNT','GIT_CONFIG_KEY_0','GIT_CONFIG_VALUE_0','GIT_CONFIG_GLOBAL','GIT_SSH_COMMAND'):
                self.assertEqual(selected[key],env[key])
            self.assertEqual(run_git(self.root,'config','core.autocrlf').stdout.strip(),'true')
            subject=tree(self.root);candidate=candidate_tree(self.root)
            self.assertEqual(index.read_bytes(),before)
            self.assertEqual(os.environ['GIT_INDEX_FILE'],env['GIT_INDEX_FILE'])
            self.git('add','--all')
            self.assertEqual(candidate,self.git('write-tree'));self.assertEqual(subject,tree(self.root))
            self.assertEqual(git(sibling,'status','--porcelain'),'')
        self.assertFalse(Path(env['GIT_INDEX_FILE']).exists())
        with patch.dict(os.environ,{'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'core.worktree','GIT_CONFIG_VALUE_0':str(sibling)}):
            # Git versions that ignore injected core.worktree still resolve the authoritative root.
            for action in (tree,candidate_tree,identity):
                try:action(self.root)
                except Refused:pass
                else:self.assertEqual(Path(self.git('rev-parse','--show-toplevel')).resolve(),self.root.resolve())
        self.git('config','core.worktree',str(sibling))
        for action in (tree,candidate_tree,identity):
            with self.assertRaises(Refused):action(self.root)


    def test_file_folder_replacements_are_staging_independent_and_children_remain_visible(self):
        from .verification import tree,candidate_tree
        original=tree(self.root)
        (self.root/'item').unlink();(self.root/'item').mkdir()
        (self.root/'item/child').write_bytes(b'original\n')  # Same bytes trigger Git's rename detection.
        before=tree(self.root);candidate=candidate_tree(self.root)
        self.assertNotEqual(original,before)
        self.git('add','--all');self.assertEqual(before,tree(self.root));self.assertEqual(candidate,self.git('write-tree'))
        self.assertTrue(self.git('diff','--name-status','HEAD').startswith('R100'))
        (self.root/'item/child').write_text('changed after review')
        self.assertNotEqual(before,tree(self.root));self.assertNotEqual(candidate,candidate_tree(self.root))
        self.git('add','--all');self.git('commit','-qm','folder')
        (self.root/'item/child').unlink();(self.root/'item').rmdir();(self.root/'item').write_text('changed after review')
        reverse=tree(self.root);candidate=candidate_tree(self.root)
        self.git('add','--all');self.assertEqual(reverse,tree(self.root));self.assertEqual(candidate,self.git('write-tree'))
        self.assertTrue(self.git('diff','--name-status','HEAD').startswith('R100'))
        # Newly ignored tracked files still contribute. Empty and ignored-only folders add no Git content.
        self.git('commit','-qm','file');(self.root/'.gitignore').write_bytes(b'item\nignored/\n')
        (self.root/'empty').mkdir();(self.root/'ignored').mkdir();(self.root/'ignored/child').write_text('ignored')
        before=tree(self.root);(self.root/'item').write_text('tracked edit')
        self.assertNotEqual(before,tree(self.root))
        self.git('add','--all');self.git('commit','-qm','ignore')
        (self.root/'item').unlink();(self.root/'item').mkdir()
        deleted=tree(self.root);self.git('add','--all');self.assertEqual(deleted,tree(self.root))

    def test_real_gitlinks_embedded_repositories_and_nested_worktrees(self):
        from .verification import tree,candidate_tree
        from .storage import git
        baseline=tree(self.root)
        self.git('worktree','add','-qb','nested','nested')
        (self.root/'nested/other').write_text('separate checkout')
        self.assertEqual(baseline,tree(self.root))
        (self.root/'item').unlink()
        child=self.root/'item';child.mkdir();git(child,'init','-qb','main')
        with self.assertRaises(Refused):tree(self.root)  # no child commit; never substitute parent HEAD
        with self.assertRaises(subprocess.CalledProcessError):candidate_tree(self.root)
        git(child,'config','user.name','Fixture');git(child,'config','user.email','fixture@example.invalid')
        (child/'file').write_text('child');git(child,'add','.');git(child,'commit','-qm','child')
        embedded=tree(self.root);self.assertNotEqual(baseline,embedded)
        candidate=candidate_tree(self.root);self.git('add','--all','--','.',':(exclude,top)nested')
        self.assertEqual(embedded,tree(self.root));self.assertEqual(candidate,self.git('write-tree'))
        self.assertTrue(self.git('diff','--name-status','HEAD').startswith('T'))
        (child/'file').write_text('dirty')
        for action in (tree,candidate_tree):
            with self.assertRaises(Refused):action(self.root)
        (child/'file').write_text('child');git(child,'add','.');git(child,'commit','-qm','next','--allow-empty')
        self.assertNotEqual(embedded,tree(self.root))
        # An indexed gitlink whose checkout is absent is a deletion; an uninitialized folder is refused.
        import shutil,stat
        shutil.rmtree(child,onexc=lambda remove,path,_:(os.chmod(path,stat.S_IWRITE),remove(path)))
        tree(self.root);child.mkdir()
        with self.assertRaises(Refused):tree(self.root)

    def test_unmerged_index_is_not_an_arbitrary_review_subject(self):
        from .verification import tree
        blob=self.git('rev-parse','HEAD:item')
        self.git('update-index','--force-remove','item')
        subprocess.run(['git','-C',str(self.root),'update-index','--index-info'],input=f'100644 {blob} 1\titem\n100644 {blob} 2\titem\n'.encode(),check=True)
        with self.assertRaisesRegex(Refused,'Resolve Git conflicts'):tree(self.root)
