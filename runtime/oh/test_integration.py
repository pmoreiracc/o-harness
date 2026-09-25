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
