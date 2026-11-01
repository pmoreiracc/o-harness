import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from .registry import register, lookup, checkout_state, profile
from .storage import Refused


def legacy_registration(root, *, remounted=False, birth=True):
    """A schema-1 registration from before Git-history checkout identity."""
    from .registry import index_path
    from .storage import read_json, atomic_json
    old=read_json(index_path(root))
    legacy=old | {'schema_version':1,'identity':{k:v for k,v in old['identity'].items() if k!='commit'}}
    for key in ('root','admin','common'):
        st=Path(legacy['identity'][key]).stat()
        stamp={'device':st.st_dev+int(remounted),'inode':st.st_ino}
        if birth and hasattr(st,'st_birthtime'):stamp['birth']=st.st_birthtime
        legacy['identity'][key+'_identity']=stamp
    atomic_json(index_path(root),legacy)
    return legacy


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.env = patch.dict(os.environ, {'OH_DATA_HOME': str(self.base / 'state')})
        self.env.start(); self.addCleanup(self.env.stop)
        self.root = self.base / 'consumer'
        self.git('init', '-q', str(self.root), root=self.base)
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.root / 'product.txt').write_text('product')
        self.git('add', '.'); self.git('commit', '-qm', 'initial')

    def git(self, *args, root=None):
        return subprocess.check_output(['git', '-C', str(root or self.root), *args], stderr=subprocess.DEVNULL).decode().strip()

    def inventory(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_registration_status_and_dirty_checkout_leave_every_consumer_byte_unchanged(self):
        # Combined Git path queries must preserve spaces, Unicode and POSIX newlines without changing identity.
        named = self.base / ('consumer with spaces-é' + ('\nline' if os.name != 'nt' else ''))
        self.root.rename(named);self.root = named
        (self.root / 'dirty.txt').write_text('manual work')
        before = self.inventory()
        value = register(self.root, 'Fixture')
        first = lookup(self.root)
        self.assertEqual(register(self.root, 'Fixture'), value)
        self.assertEqual(profile(self.root), value)
        self.assertTrue(checkout_state(self.root).is_relative_to(self.base / 'state'))
        self.assertEqual(lookup(self.root), first)
        self.assertEqual(self.inventory(), before)
        # Reboot may renumber the mounted filesystem without changing any Git data.
        from types import SimpleNamespace
        original_stat = Path.stat
        def remounted(path, *args, **kwargs):
            st = original_stat(path, *args, **kwargs)
            if path in (self.root, self.root / '.git'):
                fields = {k: getattr(st, k) for k in dir(st) if k.startswith('st_')}
                fields['st_dev'] += 1
                return SimpleNamespace(**fields)
            return st
        with patch.object(Path, 'stat', remounted):
            self.assertEqual(lookup(self.root), first)
            self.assertEqual(profile(self.root), value)
        # Normal commits, remote edits and branch switches do not replace a registration.
        self.git('commit', '--allow-empty', '-qm', 'ordinary work')
        self.git('remote', 'add', 'origin', 'https://example.invalid/one.git')
        self.git('remote', 'set-url', 'origin', 'https://example.invalid/two.git')
        self.git('checkout', '-qb', 'another', 'HEAD~1')
        self.assertEqual(lookup(self.root), first)
        from .registry import identity
        child = self.root / 'folder';child.mkdir()
        with self.assertRaisesRegex(Refused, 'repository root'):identity(child)

    def test_clones_and_sibling_worktrees_cannot_borrow_checkout_authority(self):
        original = register(self.root, 'Fixture')
        legacy_registration(self.root)
        clone = self.base / 'clone'
        self.git('clone', '-q', str(self.root), str(clone))
        from .registry import index_path
        # A copied OH index must not make another clone borrow the original's grants.
        index_path(clone).write_bytes(index_path(self.root).read_bytes())
        with self.assertRaises(Refused):lookup(clone)
        index_path(clone).unlink()
        with self.assertRaises(Refused):
            register(clone, 'Fixture', attach=original['id'])
        with self.assertRaisesRegex(Refused, 'already named Fixture'): register(clone, 'Fixture')  # names pick settings
        other = register(clone, 'Fixture clone')
        self.assertNotEqual(original['id'], other['id'])
        sibling = self.base / 'sibling with spaces'
        self.git('worktree', 'add', '-qb', 'sibling', str(sibling))
        from .storage import read_json
        self.assertEqual(read_json(index_path(self.root))['schema_version'],1)
        register(sibling, 'Fixture', attach=original['id'])
        from .registry import identity
        current = identity(sibling)
        self.assertEqual(current['root'], str(sibling.resolve()))
        self.assertEqual(current['admin'], str(Path(self.git('rev-parse', '--absolute-git-dir', root=sibling)).resolve()))
        self.assertEqual(current['common'], str((self.root / '.git').resolve()))
        self.assertEqual(profile(sibling)['id'], original['id'])
        self.assertNotEqual(lookup(sibling)['checkout'], lookup(self.root)['checkout'])

    def test_move_requires_explicit_reattachment_and_replacement_cannot_reuse_grants(self):
        register(self.root, 'Fixture')
        old = lookup(self.root)
        moved = self.base / 'moved'
        self.root.rename(moved)
        with self.assertRaises(Refused): lookup(moved)
        register(moved, 'Fixture', reattach=old['checkout'])
        self.assertEqual(lookup(moved)['checkout'], old['checkout'])
        self.git('init', '-q', str(self.root), root=self.base)
        with self.assertRaises(Refused): lookup(self.root)
        with self.assertRaises(Refused): register(self.root, 'Replacement', reattach=old['checkout'])

    def test_reinitialized_git_admin_does_not_silently_resume_old_run(self):
        register(self.root, 'Fixture')
        (self.root / '.git').rename(self.base / 'old-git')
        self.git('init', '-q')
        with self.assertRaises(Refused): lookup(self.root)

    def test_explicit_replacement_archives_identity_and_never_reuses_grants(self):
        original=register(self.root,'Fixture');old=lookup(self.root)
        (self.root/'.git').rename(self.base/'old-git');self.git('init','-q')
        with self.assertRaises(Refused):register(self.root,'Replacement')
        new=register(self.root,'Replacement',replace=True)
        self.assertNotEqual(new['id'],original['id'])
        self.assertNotEqual(lookup(self.root)['checkout'],old['checkout'])
        self.assertEqual(len(list((self.base/'state/registry/retired').glob('*.json'))),1)

    def test_a_name_is_checked_before_a_replacement_changes_anything(self):
        from .registry import index_path
        register(self.root,'Fixture')
        other=self.base/'other';self.git('init','-q',str(other),root=self.base);register(other,'Taken')
        (self.root/'.git').rename(self.base/'old-git');self.git('init','-q')
        with self.assertRaisesRegex(Refused,'already named Taken'):register(self.root,'Taken',replace=True)
        self.assertTrue(index_path(self.root).exists())  # refused before anything changed
        self.assertEqual(register(self.root,'Fixture',replace=True)['name'],'Fixture')  # the replaced registration doesn't hold it

    def test_worktrees_join_their_project_even_when_recreated_or_restored(self):
        project=register(self.root,'Fixture')['id']
        sibling=self.base/'sibling';self.git('worktree','add','-qb','sibling',str(sibling))
        joined=register(sibling,'Fixture')  # a worktree that asks for its project's name joins it
        self.assertEqual((joined['id'],joined['joined']),(project,'Fixture'))
        sibling_id=lookup(sibling)['checkout']
        self.git('worktree','remove',str(sibling));self.git('worktree','add','-q',str(sibling),'sibling')
        self.assertEqual(register(sibling,'Fixture')['id'],project)
        self.assertEqual(lookup(sibling)['checkout'],sibling_id)
        old=lookup(self.root)['checkout']
        # Restoring the same Git repository to the same path preserves the logical workspace.
        import shutil,stat
        copy=self.base/'copy';shutil.copytree(self.root,copy,symlinks=True)
        shutil.rmtree(self.root,onexc=lambda remove,path,_:(os.chmod(path,stat.S_IWRITE),remove(path)))  # Git's read-only files, on Windows
        copy.rename(self.root)
        self.git('worktree','repair',str(sibling))
        restored=register(self.root,'Fixture')
        self.assertEqual((restored['id'],lookup(self.root)['checkout']),(project,old))
        self.assertEqual(register(sibling,'Fixture')['id'],restored['id'])

    def test_a_project_known_only_through_a_worktree_keeps_its_identity(self):
        self.known_only_through_a_worktree('Planner')

    def known_only_through_a_worktree(self,name):
        from .config import describe
        from .storage import identifier
        main=self.base/('repo-'+name.replace(' ','-'))  # a repository of its own, so rounds never see each other
        self.git('init','-q',str(main),root=self.base)
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-q','--allow-empty','-m','initial',root=main)
        sibling=self.base/name.replace(' ','-');self.git('worktree','add','-qb',sibling.name,str(sibling),root=main)
        project=register(sibling,name,imported={'id':identifier(),'design_profile':'consumer-v1'})['id']
        self.git('worktree','remove',str(sibling),root=main);self.git('worktree','add','-q',str(sibling),sibling.name,root=main)
        again=register(sibling,name)  # its surviving Git history shows the repository
        self.assertEqual((again['id'],again['design_profile']),(project,'consumer-v1'))
        self.git('worktree','remove',str(sibling),root=main)
        self.assertEqual(describe(main)['join'],name)  # the main checkout learns which project it belongs to
        self.assertEqual(register(main,name)['id'],project)
        clone=self.base/('clone-'+sibling.name);self.git('clone','-q',str(main),str(clone),root=self.base)
        with self.assertRaisesRegex(Refused,'already named'):register(clone,name)  # another repository never joins

    def test_legacy_registration_upgrades_in_place_and_preserves_settings_and_files(self):
        from .registry import index_path
        from .storage import read_json, atomic_json
        from .config import change, project_checks
        original=register(self.root,'Fixture',kind='harness');old=lookup(self.root)
        change(self.root,'checks','[{"name":"tests","command":["true"]}]')
        legacy=legacy_registration(self.root)
        (checkout_state_path:=self.base/'state/checkout-state'/old['checkout']).mkdir(parents=True)
        (checkout_state_path/'oh-active-run.json').write_text('{"old":"saved evidence"}')
        before=self.inventory()
        self.assertEqual(lookup(self.root),old)
        self.assertEqual(register(self.root,'Fixture'),original)
        self.assertEqual(profile(self.root),original)
        self.assertEqual(checkout_state(self.root),checkout_state_path)
        self.assertTrue((checkout_state_path/'oh-active-run.json').is_file())
        self.assertEqual(project_checks(self.root),[{'name':'tests','command':['true']}])
        self.assertEqual(self.inventory(),before)
        upgrades=list((self.base/'state/registry/upgrades').glob('*.json'))
        self.assertEqual([read_json(p) for p in upgrades],[legacy])
        self.assertFalse((self.base/'state/registry/retired').exists())

    def test_registration_upgrade_retries_after_interruption_and_concurrent_readers(self):
        from concurrent.futures import ThreadPoolExecutor
        from .registry import index_path
        from .storage import atomic_json,read_json
        register(self.root,'Fixture');old=lookup(self.root)
        legacy=legacy_registration(self.root,birth=False)
        path=index_path(self.root)
        def interrupted(destination,value,**kwargs):
            if destination==path:raise OSError('interrupted before publishing registration')
            return atomic_json(destination,value,**kwargs)
        with patch('oh.registry.atomic_json',side_effect=interrupted):
            with self.assertRaisesRegex(OSError,'interrupted'):lookup(self.root)
        self.assertEqual(read_json(path),legacy)
        with ThreadPoolExecutor(max_workers=2) as readers:
            self.assertEqual(list(readers.map(lookup,[self.root,self.root])),[old,old])
        backups=list((self.base/'state/registry/upgrades').glob('*.json'))
        self.assertEqual([read_json(p) for p in backups],[legacy])
        self.assertEqual(read_json(path),old)

    def test_legacy_worktree_join_and_settings_edit_do_not_require_registration_reset(self):
        from .config import change,project_checks,load
        from .storage import identifier
        from .registry import rename
        original=register(self.root,'Fixture',kind='harness')
        legacy_registration(self.root)
        sibling=self.base/'sibling';self.git('worktree','add','-qb','sibling',str(sibling))
        # Earlier runtimes treated the legacy main checkout as absent and created
        # a second profile. Recovery must not merge their histories or grants.
        with patch('oh.registry.free'),patch('oh.registry.repository_projects',return_value=set()):
            separate=register(sibling,'Fixture',imported={'id':identifier()})
        sibling_id=lookup(sibling)['checkout']
        self.assertNotEqual(separate['id'],original['id'])
        change(self.root,'checks','[{"name":"tests","command":["true"]}]')
        self.assertEqual(profile(self.root),original)
        self.assertEqual(project_checks(sibling),[{'name':'tests','command':['true']}])
        self.assertEqual(profile(sibling),separate)
        fresh=self.base/'fresh';self.git('worktree','add','-qb','fresh',str(fresh))
        self.assertEqual(register(fresh)['id'],original['id'])
        change(sibling,'review_rounds','7')
        # Historical profiles can share private settings while only the main
        # profile owns the folder. Renaming the sibling must select its own name.
        from .config import settings_file
        from .private_storage import reserve,owned
        from .plans import layout
        folder=self.base/'private';main_plans=folder/'Fixture'
        reserve(main_plans,original);main_plans.mkdir(parents=True)
        document=main_plans/'notes.md';document.write_text('original plans')
        data=json.loads(settings_file().read_text())
        data['projects']['Fixture']['plans']={'location':'private','private_folder':str(folder)}
        settings_file().write_text(json.dumps(data))
        rename(sibling,'Separate')
        self.assertEqual((load(self.root)['review_rounds'],load(sibling)['review_rounds']),(7,7))
        self.assertEqual(project_checks(sibling),project_checks(self.root))
        self.assertEqual((profile(sibling)['id'],lookup(sibling)['checkout']),(separate['id'],sibling_id))
        self.assertEqual(layout(self.root)['base'],main_plans)
        self.assertEqual(layout(sibling)['base'],folder/'Separate')
        self.assertTrue(owned(main_plans,original))
        self.assertTrue(owned(folder/'Separate',profile(sibling)))
        self.assertEqual(document.read_text(),'original plans')
        # A profile with its own legacy documents keeps those, even when its
        # shared-name folder belongs to the main profile. Later explicit paths
        # retain the same location across another rename.
        from .registry import profile_path
        from .storage import atomic_json
        atomic_json(profile_path(sibling),separate)
        legacy=self.base/'state/projects'/separate['id']/'plans';legacy.mkdir()
        (legacy/'notes.md').write_text('sibling plans')
        for name in ('WithLegacy','WithExplicitPath'):
            rename(sibling,name)
            self.assertEqual(layout(sibling)['base'],legacy)
            self.assertTrue(owned(legacy,profile(sibling)))
            self.assertEqual((legacy/'notes.md').read_text(),'sibling plans')
            self.assertEqual(document.read_text(),'original plans')

    def test_unverifiable_legacy_registration_and_future_versions_are_not_reset(self):
        from .registry import index_path
        from .storage import atomic_json,read_json
        register(self.root,'Fixture');legacy=legacy_registration(self.root)
        path=index_path(self.root)
        (self.root/'.git').rename(self.base/'old-git');self.git('init','-q')
        with self.assertRaisesRegex(Refused,'could not verify'):lookup(self.root)
        self.assertEqual(read_json(path),legacy)
        future=legacy | {'schema_version':99}
        atomic_json(path,future)
        with self.assertRaisesRegex(Refused,'Update OH'):lookup(self.root)
        self.assertEqual(read_json(path),future)
        self.assertFalse((self.base/'state/registry/upgrades').exists())

    def test_legacy_history_must_be_verified_and_registration_cannot_move_to_a_clone(self):
        from .registry import index_path
        from .storage import Journal,identifier,read_json
        register(self.root,'Fixture');old=lookup(self.root)
        run=identifier();journal=Journal(old['project'],run)
        journal.append('run.started',{'id':run,'project':old['project'],'checkout':old['checkout'],
                                     'base':old['identity']['commit']})
        legacy=legacy_registration(self.root,remounted=True,birth=False)
        clone=self.base/'clone';self.git('clone','-q',str(self.root),str(clone))
        index_path(clone).write_bytes(index_path(self.root).read_bytes())
        with self.assertRaisesRegex(Refused,'another checkout'):lookup(clone)
        # A valid prior record cannot authorize a different Git history at the old path.
        (self.root/'.git').rename(self.base/'old-git');self.git('init','-q')
        with self.assertRaisesRegex(Refused,'recorded Git history'):lookup(self.root)
        self.assertEqual(read_json(index_path(self.root)),legacy)
        self.assertFalse((self.base/'state/registry/upgrades').exists())

    def test_empty_repository_binds_its_first_commit_before_work(self):
        from .entry import enroll
        empty=self.base/'empty';self.git('init','-q',str(empty),root=self.base)
        register(empty,'Empty');old=lookup(empty)
        self.assertIsNone(old['identity']['commit'])
        self.git('-c','user.name=F','-c','user.email=f@example.invalid','commit','-q','--allow-empty','-m','initial',root=empty)
        self.assertIsNone(enroll(empty))
        anchored=lookup(empty)
        self.assertEqual(anchored['checkout'],old['checkout'])
        self.assertEqual(anchored['identity']['commit'],self.git('rev-parse','HEAD',root=empty))
        (empty/'.git').rename(self.base/'empty-old-git');self.git('init','-q',root=empty)
        with self.assertRaises(Refused):lookup(empty)

    def test_older_same_name_projects_of_the_repository_never_block_a_worktree(self):
        from .storage import identifier
        main=register(self.root,'Fixture')['id']
        for number in range(2):
            old=self.base/f'old{number}';self.git('worktree','add','-qb',f'old{number}',str(old))
            with patch('oh.registry.free'),patch('oh.registry.repository_projects',return_value=set()):
                register(old,'Fixture',imported={'id':identifier()})  # separate projects, from before names were unique
            self.git('worktree','remove',str(old))
        fresh=self.base/'fresh';self.git('worktree','add','-qb','fresh',str(fresh))
        from .config import describe
        self.assertEqual(describe(fresh)['join'],'Fixture')  # the name register accepts, once
        self.assertEqual(register(fresh,'Fixture')['id'],main)

    def test_a_project_is_named_after_its_repository_unless_you_choose(self):
        first=register(self.root)
        self.assertEqual(first['name'],self.root.name)
        sibling=self.base/'sibling';self.git('worktree','add','-qb','sibling',str(sibling))
        self.assertEqual(register(sibling)['id'],first['id'])  # a worktree joins, whatever its folder is called
        other=self.base/'other';self.git('init','-q',str(other),root=self.base)
        self.assertEqual(register(other,'Chosen')['name'],'Chosen')
        old=lookup(other)['checkout'];moved=self.base/'moved';other.rename(moved)
        self.assertEqual(register(moved,reattach=old)['name'],'Chosen')  # a moved checkout needs no name
        from .config import change,project_checks
        change(moved,'checks','[{"name": "tests", "command": ["true"]}]')
        (moved/'.git').rename(self.base/'chosen-git');self.git('init','-q',root=moved)
        self.assertEqual(register(moved,replace=True)['name'],'Chosen')  # a re-cloned checkout keeps its project's name
        self.assertEqual(project_checks(moved),[{'name':'tests','command':['true']}])  # and its checks
        with patch('oh.registry.joinable',return_value=['Alpha','Beta']):
            fresh=self.base/'fresh';self.git('worktree','add','-qb','fresh',str(fresh))
            with self.assertRaisesRegex(Refused,'pass --name'):register(fresh)  # never a silent third project

    def test_a_path_reused_by_another_repository_joins_that_repository(self):
        from .config import describe
        register(self.root,'Alpha');slot=self.base/'slot';self.git('worktree','add','-qb','slot',str(slot));register(slot)
        self.git('worktree','remove',str(slot))
        bravo=self.base/'bravo';self.git('init','-q',str(bravo),root=self.base)
        self.git('-c','user.name=F','-c','user.email=f@example.invalid','commit','-q','--allow-empty','-m','initial',root=bravo)
        register(bravo,'Bravo');self.git('worktree','add','-qb','slot',str(slot),root=bravo)
        self.assertEqual(register(slot,replace=True)['name'],'Bravo')  # not the old registration's Alpha
        taken=self.base/'elsewhere'/'Alpha';taken.parent.mkdir();self.git('init','-q',str(taken),root=self.base)
        self.assertIn('is used by another project',describe(taken)['note'])  # a taken folder name is said up front

    def test_a_moved_checkout_cannot_come_back_to_a_name_taken_meanwhile(self):
        register(self.root,'Fixture');old=lookup(self.root)
        moved=self.base/'moved';self.root.rename(moved)
        other=self.base/'other';self.git('init','-q',str(other),root=self.base);register(other,'Fixture')
        with self.assertRaisesRegex(Refused,'took the name Fixture'):register(moved,'Fixture',reattach=old['checkout'])

    def test_import_refuses_an_old_active_binding(self):
        from .storage import identifier
        (self.root/'.git/oh-active-run.json').write_text('{}')
        with self.assertRaises(Refused):register(self.root,'Fixture',imported={'id':identifier()})
        self.assertFalse((self.base/'state/registry/checkouts').exists())


if __name__ == '__main__': unittest.main()
