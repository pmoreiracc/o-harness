import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from .registry import register, lookup, checkout_state, profile
from .storage import Refused


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
        (self.root / 'dirty.txt').write_text('manual work')
        before = self.inventory()
        value = register(self.root, 'Fixture')
        first = lookup(self.root)
        self.assertEqual(register(self.root, 'Fixture'), value)
        self.assertEqual(profile(self.root), value)
        self.assertTrue(checkout_state(self.root).is_relative_to(self.base / 'state'))
        self.assertEqual(lookup(self.root), first)
        self.assertEqual(self.inventory(), before)

    def test_clones_and_sibling_worktrees_cannot_borrow_checkout_authority(self):
        original = register(self.root, 'Fixture')
        clone = self.base / 'clone'
        self.git('clone', '-q', str(self.root), str(clone))
        with self.assertRaises(Refused):
            register(clone, 'Fixture', attach=original['id'])
        with self.assertRaisesRegex(Refused, 'already named Fixture'): register(clone, 'Fixture')  # names pick settings
        other = register(clone, 'Fixture clone')
        self.assertNotEqual(original['id'], other['id'])
        sibling = self.base / 'sibling'
        self.git('worktree', 'add', '-qb', 'sibling', str(sibling))
        register(sibling, 'Fixture', attach=original['id'])
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

    def test_import_refuses_an_old_active_binding(self):
        from .storage import identifier
        (self.root/'.git/oh-active-run.json').write_text('{}')
        with self.assertRaises(Refused):register(self.root,'Fixture',imported={'id':identifier()})
        self.assertFalse((self.base/'state/registry/checkouts').exists())


if __name__ == '__main__': unittest.main()
