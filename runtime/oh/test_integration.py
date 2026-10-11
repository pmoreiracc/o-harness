from .registry import register
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
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp,'PATH':tmp}):
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

    def test_host_binary_is_trusted_automatically_and_followed_across_updates(self):
        from . import hosts
        from .storage import read_json
        binaries={'claude':'v1'}
        def identity(path,root=None):
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
            with self.assertRaises(Refused):hosts.executable('claude')

    def test_trust_records_from_before_automatic_trust_keep_working(self):
        from . import hosts
        from .storage import atomic_json,read_json
        identity=lambda path,root=None:{'path':str(path),'sha256':'same'}
        probe=subprocess.CompletedProcess([],0,'codex-cli 0.154.0','')
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp}),\
             patch.object(hosts,'binary_identity',side_effect=identity),patch.object(hosts.subprocess,'run',return_value=probe):
            record=Path(tmp)/'hosts/codex.json'
            atomic_json(record,{'path':'/opt/native/codex','sha256':'same'})
            # PATH has no usable codex: the old record stays in use, now as a pin.
            with patch.object(hosts,'locate',side_effect=Refused('not found')):
                self.assertEqual(hosts.executable('codex'),'/opt/native/codex')
            self.assertTrue(read_json(record)['pinned'])
            atomic_json(record,{'path':'/opt/native/codex','sha256':'same'})
            # PATH has another codex: OH follows it and says how to keep the old one.
            with patch.object(hosts,'locate',return_value=Path('/usr/local/bin/codex')),patch('sys.stderr') as err:
                self.assertEqual(hosts.executable('codex'),str(Path('/usr/local/bin/codex')))
            self.assertIn('oh trust-host codex /opt/native/codex',''.join(c.args[0] for c in err.write.call_args_list))


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
