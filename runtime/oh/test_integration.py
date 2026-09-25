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

    def test_trust_host_finds_the_native_codex_binary_behind_an_npm_wrapper(self):
        from .hosts import locate
        with tempfile.TemporaryDirectory() as tmp:
            package=Path(tmp)/'lib/node_modules/@openai/codex'
            wrapper=package/'bin/codex.js';wrapper.parent.mkdir(parents=True);wrapper.write_text('#!/usr/bin/env node\n');wrapper.chmod(0o755)
            native=package/'node_modules/@openai/codex-test/vendor/arch/bin/codex';native.parent.mkdir(parents=True);native.write_bytes(b'\x7fELF');native.chmod(0o755)
            bin_dir=Path(tmp)/'bin';bin_dir.mkdir();(bin_dir/'codex').symlink_to(wrapper)
            with patch.dict(os.environ,{'PATH':str(bin_dir)}):
                self.assertEqual(locate('codex',Path(tmp)/'elsewhere'),native.resolve())

    def test_host_binary_is_trusted_automatically_and_followed_across_updates(self):
        from . import hosts
        from .storage import read_json
        binaries={'claude':'v1'}
        def identity(path,root=None):
            if Path(path).name=='gone':raise FileNotFoundError(path)
            return {'path':str(path),'sha256':binaries.get(Path(path).name,'pinned')}
        probe=subprocess.CompletedProcess([],0,'2.1.0 (Claude Code)','')
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'OH_DATA_HOME':tmp}),\
             patch.object(hosts,'binary_identity',side_effect=identity),patch.object(hosts,'locate',return_value=Path('/opt/claude')),\
             patch.object(hosts.subprocess,'run',return_value=probe) as run:
            record=Path(tmp)/'hosts/claude.json'
            self.assertEqual(hosts.executable('claude'),'/opt/claude')
            self.assertEqual(read_json(record)['sha256'],'v1');self.assertFalse(read_json(record)['pinned'])
            self.assertEqual(hosts.executable('claude'),'/opt/claude');self.assertEqual(run.call_count,1)
            # A self-updated CLI is checked again and recorded without a manual step.
            binaries['claude']='v2'
            self.assertEqual(hosts.executable('claude'),'/opt/claude');self.assertEqual(read_json(record)['sha256'],'v2')
            self.assertEqual(run.call_count,2)
            # A version check failure refuses the new binary.
            binaries['claude']='v3';run.return_value=subprocess.CompletedProcess([],0,'something else','')
            with self.assertRaises(Refused):hosts.executable('claude')
            self.assertEqual(read_json(record)['sha256'],'v2')
            # An explicitly named path stays pinned, and a missing pin is refused clearly.
            run.return_value=probe
            hosts.trust('claude',Path('/custom/pinned'))
            self.assertEqual(hosts.executable('claude'),'/custom/pinned')
            (record).write_text('{"path":"/custom/gone","sha256":"x","pinned":true}')
            with self.assertRaises(Refused):hosts.executable('claude')
