import subprocess
import io
import json
import os
import stat
from pathlib import Path
import unittest
from unittest.mock import patch
from . import test_fixtures_workflow as fixtures
from .storage import Refused


class BranchIdentityTest(unittest.TestCase):
    setUp=fixtures.WorkflowFixture.setUp
    git=fixtures.WorkflowFixture.git

    def origin(self):
        origin=Path(self.temp.name)/'origin.git'
        self.git('clone','--bare',str(self.root),str(origin))
        self.git('remote','add','origin',str(origin))
        self.git('fetch','origin','main')
        return origin

    def test_entry_fetches_stale_base_without_changing_local_work_on_both_interfaces(self):
        from .cli import main
        from .mcp_server import command
        self.origin();old=self.git('rev-parse','HEAD')
        (self.root/'product.txt').write_text('merged decisions and progress',newline='\n')
        self.git('commit','-qam','remote progress');new=self.git('rev-parse','HEAD')
        self.git('push','origin','HEAD:main');self.git('reset','--hard',old)
        self.git('update-ref','refs/remotes/origin/main',old)
        (self.root/'product.txt').write_text('valuable local edit',newline='\n')
        (self.root/'notes.txt').write_text('untracked work',newline='\n')
        nested=self.root/'.claude/worktrees/held'
        self.git('worktree','add','-qb','held',str(nested))
        before=self.git('status','--porcelain');branch=self.git('branch','--show-current')
        for arguments in (['entry'],command('entry',{},self.root)):
            with patch('sys.stdout',new=io.StringIO()) as output:main(['--root',str(self.root),*arguments])
            facts=json.loads(output.getvalue())
            self.assertEqual(facts['base']['freshness'],'fetched')
            self.assertEqual(facts['base']['commit'],new)
            self.assertEqual(facts['checkout']['head'],old)
            self.assertEqual(facts['checkout']['behind'],1)
            self.assertEqual(set(facts['checkout']['paths']),{'product.txt','notes.txt'})
            self.assertEqual(facts['checkout']['nested_worktrees'],['.claude/worktrees/held'])
            self.assertEqual(facts['saved_work'],[])
        self.assertEqual(self.git('status','--porcelain'),before)
        self.assertEqual(self.git('branch','--show-current'),branch)
        self.assertEqual((self.root/'product.txt').read_text(),'valuable local edit')
        self.assertEqual((self.root/'notes.txt').read_text(),'untracked work')
        self.assertTrue((nested/'product.txt').is_file())

    def test_failed_fetch_exposes_cached_base_without_claiming_freshness(self):
        from .branches import run_git,fetched
        from .entry import inspect
        self.origin();old=self.git('rev-parse','HEAD')
        def offline(root,*args,**kwargs):
            return subprocess.CompletedProcess(args,1,'','offline fixture') if args[0]=='fetch' else run_git(root,*args,**kwargs)
        with patch('oh.branches.run_git',side_effect=offline):
            facts=inspect(self.root)
            self.assertEqual(facts['base']['freshness'],'unavailable')
            self.assertEqual(facts['base']['commit'],old)
            self.assertIn('offline fixture',facts['base']['reason'])
            with self.assertRaisesRegex(Refused,'Could not refresh.*offline fixture'):fetched(self.root,'main')
        self.assertEqual(self.git('rev-parse','HEAD'),old)

    def test_entry_keeps_large_observations_external_and_local_only_is_explicit(self):
        from .entry import inspect
        from .storage import read_json,digest,encode
        fixtures.configure(self.root,context={'result_chars':1000})
        for number in range(40):(self.root/(str(number)+'x'*90)).write_text('local',newline='\n')
        facts=inspect(self.root)
        self.assertLessEqual(len(encode(facts)),1000)
        reference=facts['observation'];full=read_json(reference['path'])
        self.assertEqual(digest(full),reference['hash'])
        self.assertEqual(full['checkout']['path_count'],40)
        self.assertEqual(full['base']['freshness'],'local_only')
        self.assertFalse(Path(reference['path']).is_relative_to(self.root))

    def test_base_branch_precedence_remote_only_checkout_and_checks(self):
        # docs/usage.md: detect origin/HEAD, allow project/global overrides, and explain the source.
        from .branches import base_branch,from_main,main_ref,trunk
        from .checks import selected
        from .config import change,describe
        self.assertEqual(base_branch(self.root),{'name':'main','ref':'main','source':'fallback'})
        for name in ('main','master','team/develop'):
            self.git('update-ref','refs/remotes/origin/'+name,'HEAD')
        self.git('symbolic-ref','refs/remotes/origin/HEAD','refs/remotes/origin/master')
        self.assertEqual(base_branch(self.root),{'name':'master','ref':'origin/master','source':'origin/HEAD'})
        self.assertEqual(describe(self.root)['base_branch']['source'],'origin/HEAD')
        change(self.root,'base_branch','main',scope='global')
        self.assertEqual(describe(self.root)['base_branch']['source'],'global')
        change(self.root,'base_branch','team/develop')
        self.assertEqual(describe(self.root)['base_branch'],{'name':'team/develop','ref':'origin/team/develop','source':'project'})
        fixtures.configure(self.root,base_branch='team/develop',checks=[{'name':'base','command':['git','diff','{base}']}])
        self.assertEqual(selected(self.root)[0]['command'],['git','diff','origin/team/develop'])
        self.assertEqual(selected(self.root,'main')[0]['command'],['git','diff','main'])
        from_main(self.root)
        self.assertEqual(self.git('branch','--show-current'),'team/develop')
        self.assertEqual(self.git('rev-parse','HEAD'),self.git('rev-parse','origin/team/develop'))
        for invalid in ('-bad','refs/heads/main','a..b','@{-1}','origin/HEAD:bad'):
            with self.subTest(invalid),self.assertRaises(Refused):change(self.root,'base_branch',invalid)
        change(self.root,'base_branch','missing')
        with self.assertRaisesRegex(Refused,'fetch origin missing'):trunk(self.root)
        change(self.root,'base_branch',None)
        self.assertEqual(trunk(self.root),'main')  # unsetting inherits the global override
        change(self.root,'base_branch',None,scope='global')
        self.assertEqual(trunk(self.root),'master')
        self.git('symbolic-ref','refs/remotes/origin/HEAD','refs/remotes/origin/missing')
        self.assertEqual(main_ref(self.root),'origin/main')
        self.git('update-ref','-d','refs/remotes/origin/main');self.git('branch','-D','main')
        self.assertEqual(main_ref(self.root),'origin/master')


class WorkspaceTest(fixtures.NativeFixture):
    def test_round_trip_keeps_index_bytes_untracked_ignored_and_other_stashes(self):
        from . import workspace
        from .verification import tree
        (self.root/'.gitignore').write_text('local.env\n',newline='\n')
        self.git('add','.gitignore');self.git('commit','-qm','ignore local setup')
        self.git('branch','-f','main','HEAD')
        (self.root/'personal.txt').write_text('earlier stash',newline='\n')
        self.git('stash','push','-u','-m','personal saved work')
        personal=self.git('rev-parse','refs/stash')
        (self.root/'product.txt').write_bytes(b'staged\x00binary\r\n')
        if os.name!='nt':(self.root/'product.txt').chmod(0o755)
        self.git('add','product.txt')
        (self.root/'product.txt').write_bytes(b'unstaged\x00binary\r\n')
        if os.name!='nt':(self.root/'product.txt').chmod(0o640)
        (self.root/'new file.txt').write_bytes(b'new\r\nfile')
        (self.root/'run.sh').write_bytes(b'#!/bin/sh\nexit 0\n')
        if os.name!='nt':(self.root/'run.sh').chmod(0o755)
        (self.root/'local.env').write_bytes(b'keep ignored setup')
        before=(tree(self.root),self.git('write-tree'),self.git('status','--porcelain'))
        moved=workspace.switch(self.root,'second','main')
        self.assertTrue(moved['saved']);self.assertFalse(Path(moved['saved']).is_relative_to(self.root))
        self.assertFalse((self.root/'new file.txt').exists())
        self.assertEqual((self.root/'local.env').read_bytes(),b'keep ignored setup')
        (self.root/'second.txt').write_text('second task',newline='\n')
        workspace.switch(self.root,'work')
        self.assertEqual((tree(self.root),self.git('write-tree'),self.git('status','--porcelain')),before)
        self.assertEqual((self.root/'product.txt').read_bytes(),b'unstaged\x00binary\r\n')
        self.assertEqual((self.root/'new file.txt').read_bytes(),b'new\r\nfile')
        self.assertEqual((self.root/'run.sh').read_bytes(),b'#!/bin/sh\nexit 0\n')
        if os.name!='nt':
            self.assertEqual(stat.S_IMODE((self.root/'product.txt').stat().st_mode),0o640)  # windows-ok: POSIX-only assertion inside os.name != 'nt' guard.
            self.assertEqual(stat.S_IMODE((self.root/'run.sh').stat().st_mode),0o755)  # windows-ok: POSIX-only assertion inside os.name != 'nt' guard.
        self.assertFalse((self.root/'second.txt').exists())
        self.assertIn(personal,self.git('stash','list','--format=%H'))
        workspace.switch(self.root,'second')
        self.assertEqual((self.root/'second.txt').read_text(),'second task')
        self.assertEqual(len(self.git('worktree','list','--porcelain').split('worktree ')),2)

    def test_failed_switch_restores_source_and_retry_preserves_saved_work(self):
        from . import workspace
        (self.root/'.gitignore').write_text('collision.txt\n',newline='\n')
        self.git('add','.gitignore');self.git('commit','-qm','ignore local setup')
        self.git('switch','-c','blocked')
        (self.root/'collision.txt').write_text('tracked destination',newline='\n')
        self.git('add','-f','collision.txt');self.git('commit','-qm','destination')
        self.git('switch','work')
        (self.root/'collision.txt').write_text('ignored local data',newline='\n')
        (self.root/'product.txt').write_text('valuable unfinished edit',newline='\n')
        before=self.git('status','--porcelain')
        with self.assertRaisesRegex(Refused,'could not switch'):
            workspace.switch(self.root,'blocked')
        self.assertEqual(self.git('branch','--show-current'),'work')
        self.assertEqual(self.git('status','--porcelain'),before)
        self.assertEqual((self.root/'product.txt').read_text(),'valuable unfinished edit')
        self.assertEqual((self.root/'collision.txt').read_text(),'ignored local data')

    def test_save_and_restore_recover_after_interrupted_result_writes(self):
        from . import workspace
        (self.root/'.gitattributes').write_text('product.txt text eol=lf\n',newline='\n')
        tail=b'unchanged context\n'*10
        (self.root/'product.txt').write_bytes(b'fixture\n'+tail)
        self.git('add','.gitattributes','product.txt');self.git('commit','-qm','text attributes')
        self.git('branch','-f','main','HEAD')
        original=(b'unfinished\n'+tail).replace(b'\n',b'\r\n')
        (self.root/'product.txt').write_bytes(original)
        real=workspace.run_git
        def lost_save(root,*args,**kwargs):
            result=real(root,*args,**kwargs)
            if args[:2]==('stash','push'):raise OSError('save result lost')
            return result
        with patch.object(workspace,'run_git',side_effect=lost_save),self.assertRaisesRegex(OSError,'save result lost'):
            workspace.switch(self.root,'second','main')
        self.assertFalse(self.git('status','--porcelain'))
        stashes=self.git('stash','list','--format=%H');write=workspace._write
        def parked_result_lost(root,state):
            write(root,state)
            if state['branches']['work']['phase']=='parked':raise OSError('parked receipt lost')
        with patch.object(workspace,'_write',side_effect=parked_result_lost),self.assertRaisesRegex(OSError,'parked receipt lost'):
            workspace.switch(self.root,'second','main')
        workspace.switch(self.root,'second','main')
        self.assertEqual(self.git('stash','list','--format=%H'),stashes)
        def lost_restore(root,*args,**kwargs):
            result=real(root,*args,**kwargs)
            if args[:1]==('read-tree',):raise OSError('restore result lost')
            return result
        with patch.object(workspace,'run_git',side_effect=lost_restore),self.assertRaisesRegex(OSError,'restore result lost'):
            workspace.switch(self.root,'work')
        count=self.git('stash','list','--format=%H')
        saved=workspace.parked(self.root,'work')
        intermediate=(self.root/'product.txt').read_bytes()
        competing=intermediate+b'\nnew edit outside the saved hunk\n'
        (self.root/'product.txt').write_bytes(competing)
        with self.assertRaisesRegex(Refused,'new edits.*Preserve and reconcile'):
            workspace.switch(self.root,'work')
        self.assertEqual((self.root/'product.txt').read_bytes(),competing)
        self.assertEqual(self.git('stash','list','--format=%H'),count)
        self.assertTrue(Path(saved['backup']).is_dir())
        self.assertEqual(workspace.parked(self.root,'work')['phase'],'restoring')
        # Reconcile the competing edit, then the same interrupted result recovers.
        (self.root/'product.txt').write_bytes(intermediate)
        if os.name!='nt':
            # POSIX executable-bit edits are Git-visible; Windows chmod is not.
            mode=stat.S_IMODE((self.root/'product.txt').stat().st_mode)
            competing_mode=mode ^ stat.S_IXUSR
            (self.root/'product.txt').chmod(competing_mode)
            with self.assertRaisesRegex(Refused,'new edits.*Preserve and reconcile'):
                workspace.switch(self.root,'work')
            self.assertEqual(stat.S_IMODE((self.root/'product.txt').stat().st_mode),competing_mode)
            self.assertEqual((self.root/'product.txt').read_bytes(),intermediate)
            self.assertEqual(self.git('stash','list','--format=%H'),count)
            self.assertTrue(Path(saved['backup']).is_dir())
            self.assertEqual(workspace.parked(self.root,'work')['phase'],'restoring')
            (self.root/'product.txt').chmod(mode)
        workspace.switch(self.root,'work')
        self.assertEqual((self.root/'product.txt').read_bytes(),original)
        self.assertEqual(self.git('stash','list','--format=%H'),count)
        self.assertIsNone(workspace.parked(self.root,'work'))

    def test_interrupted_restore_accepts_exact_git_line_endings_and_saved_staging(self):
        from . import workspace
        # Explicit attributes exercise Windows checkout conversion on either host.
        real=workspace.run_git
        def lost_restore(root,*args,**kwargs):
            result=real(root,*args,**kwargs)
            if args[:1]==('read-tree',):raise OSError('restore result lost')
            return result
        for eol,raw,mode,mask,filemode in (('lf',b'\r\n',0o600,0o022,True),
                ('crlf',b'\n',0o751,0o077,True),('lf',b'\n',0o640,0o077,True),
                ('lf',b'\r\n',0o751,0o022,False)):
            self.git('config','core.filemode',str(filemode).lower())
            (self.root/'.gitattributes').write_text('product.txt text eol='+eol+'\n',newline='\n')
            # Include an ordinary tracked executable as the saved work's base.
            if os.name!='nt':(self.root/'product.txt').chmod(0o755)
            if not filemode:self.git('update-index','--chmod=-x','product.txt')
            self.git('add','.gitattributes','product.txt');self.git('commit','--allow-empty','-qm','checkout conversion')
            self.git('branch','-f','main','HEAD')
            for staged in (False,True):
                with self.subTest(eol=eol,staged=staged,mode=oct(mode),filemode=filemode):
                    original=b'unfinished'+raw
                    (self.root/'product.txt').write_bytes(original)
                    if os.name!='nt':(self.root/'product.txt').chmod(mode)
                    if staged:self.git('add','product.txt')
                    index=self.git('write-tree')
                    target='second-'+eol+'-'+str(filemode).lower()+'-'+oct(mode)+'-'+str(staged).lower()
                    workspace.switch(self.root,target,'main')
                    # POSIX umask changes Git's non-executable permission bits.
                    previous=os.umask(mask) if os.name!='nt' else None
                    try:
                        with patch.object(workspace,'run_git',side_effect=lost_restore),self.assertRaisesRegex(OSError,'restore result lost'):
                            workspace.switch(self.root,'work')
                    finally:
                        if previous is not None:os.umask(previous)
                    self.assertEqual((self.root/'product.txt').read_bytes(),b'unfinished'+(b'\r\n' if eol=='crlf' else b'\n'))
                    workspace.switch(self.root,'work')
                    self.assertEqual((self.root/'product.txt').read_bytes(),original)
                    if os.name!='nt':self.assertEqual(stat.S_IMODE((self.root/'product.txt').stat().st_mode),mode)
                    self.assertEqual(self.git('write-tree'),index)
                    self.assertIsNone(workspace.parked(self.root,'work'))
                    self.git('reset','--hard','HEAD')

    def test_changed_branch_and_hidden_index_flags_are_rejected_before_saving(self):
        from . import workspace
        (self.root/'product.txt').write_text('parked work',newline='\n')
        workspace.switch(self.root,'second','main')
        record=workspace.parked(self.root,'work')
        (self.root/'second.txt').write_text('new commit',newline='\n')
        self.git('add','.');self.git('commit','-qm','new history')
        self.git('update-ref','refs/heads/work','HEAD')
        (self.root/'later.txt').write_text('keep current work',newline='\n')
        before=self.git('status','--porcelain');stashes=self.git('stash','list','--format=%H')
        with self.assertRaisesRegex(Refused,'moved after'):
            workspace.switch(self.root,'work')
        self.assertEqual(self.git('status','--porcelain'),before)
        self.assertEqual(self.git('stash','list','--format=%H'),stashes)
        self.git('update-ref','refs/heads/work',record['head'])
        # Hidden index flags can hide bytes from stash, so refuse before mutation.
        self.git('update-index','--assume-unchanged','product.txt')
        with self.assertRaisesRegex(Refused,'assume-unchanged'):
            workspace.switch(self.root,'work')
        self.assertEqual((self.root/'later.txt').read_text(),'keep current work')
        self.assertEqual(self.git('stash','list','--format=%H'),stashes)

    def test_changed_ignore_rules_rollback_save_without_losing_ambient_files(self):
        from . import workspace
        (self.root/'.gitignore').write_text('local.env\n',newline='\n')
        (self.root/'local.env').write_text('ignored setup',newline='\n')
        (self.root/'product.txt').write_text('unfinished',newline='\n')
        before=self.git('status','--porcelain')
        with self.assertRaisesRegex(Refused,'could not finish saving'):
            workspace.switch(self.root,'second','main')
        self.assertEqual(self.git('branch','--show-current'),'work')
        self.assertEqual(self.git('status','--porcelain'),before)
        self.assertEqual((self.root/'local.env').read_text(),'ignored setup')
        self.assertEqual((self.root/'product.txt').read_text(),'unfinished')

    def test_file_replaced_by_directory_preserves_ignored_children(self):
        from . import workspace
        (self.root/'.gitignore').write_text('product.txt/*.env\n',newline='\n')
        self.git('add','.gitignore');self.git('commit','-qm','ignore local configuration')
        self.git('branch','-f','main','HEAD')
        (self.root/'product.txt').unlink();(self.root/'product.txt').mkdir()
        (self.root/'product.txt/notes.txt').write_text('new directory contents',newline='\n')
        (self.root/'product.txt/local.env').write_bytes(b'valuable ignored local data\r\n')
        before=self.git('status','--porcelain')
        workspace.switch(self.root,'second','main')
        real=workspace.run_git
        def lost_restore(root,*args,**kwargs):
            result=real(root,*args,**kwargs)
            if args[:1]==('read-tree',):raise OSError('restore result lost')
            return result
        with patch.object(workspace,'run_git',side_effect=lost_restore),self.assertRaisesRegex(OSError,'restore result lost'):
            workspace.switch(self.root,'work')
        workspace.switch(self.root,'work')
        self.assertEqual(self.git('status','--porcelain'),before)
        self.assertEqual((self.root/'product.txt/notes.txt').read_text(),'new directory contents')
        self.assertEqual((self.root/'product.txt/local.env').read_bytes(),b'valuable ignored local data\r\n')

    def test_directory_replaced_by_file_restores_staging_and_refuses_new_ignored_children(self):
        from . import workspace
        (self.root/'.gitignore').write_text('product.txt/*.env\n',newline='\n')
        (self.root/'product.txt').unlink();(self.root/'product.txt').mkdir()
        (self.root/'product.txt/old.txt').write_text('original child',newline='\n')
        self.git('add','-A');self.git('commit','-qm','tracked directory')
        self.git('branch','-f','main','HEAD')
        for staged in (False,True):
            with self.subTest(staged=staged):
                (self.root/'product.txt/old.txt').unlink();(self.root/'product.txt').rmdir()
                (self.root/'product.txt').write_bytes(b'replacement file\r\n')
                if os.name!='nt':(self.root/'product.txt').chmod(0o751)
                if staged:self.git('add','-A')
                before=self.git('status','--porcelain');index=self.git('write-tree')
                workspace.switch(self.root,'second-'+str(staged).lower(),'main')
                (self.root/'product.txt/local.env').write_text('new ignored data',newline='\n')
                with self.assertRaisesRegex(Refused,'extra file'):
                    workspace.switch(self.root,'work')
                self.assertEqual((self.root/'product.txt/local.env').read_text(),'new ignored data')
                self.assertEqual((self.root/'product.txt/old.txt').read_text(),'original child')
                (self.root/'product.txt/local.env').unlink()
                real=workspace.run_git
                def lost_restore(root,*args,**kwargs):
                    result=real(root,*args,**kwargs)
                    if args[:1]==('read-tree',):raise OSError('restore result lost')
                    return result
                with patch.object(workspace,'run_git',side_effect=lost_restore),self.assertRaisesRegex(OSError,'restore result lost'):
                    workspace.switch(self.root,'work')
                workspace.switch(self.root,'work')
                self.assertEqual((self.root/'product.txt').read_bytes(),b'replacement file\r\n')
                if os.name!='nt':self.assertEqual(stat.S_IMODE((self.root/'product.txt').stat().st_mode),0o751)  # windows-ok: POSIX-only assertion guarded on this line.
                self.assertEqual(self.git('status','--porcelain'),before)
                self.assertEqual(self.git('write-tree'),index)
                self.git('reset','--hard','HEAD')

    def test_restore_collisions_keep_both_versions(self):
        from . import workspace
        (self.root/'new.txt').write_text('saved untracked work',newline='\n')
        workspace.switch(self.root,'second','main')
        saved=workspace.parked(self.root,'work')
        # A new ignored file at the restore path must never be overwritten.
        (self.root/'.git/info/exclude').write_text('new.txt\n',newline='\n')
        (self.root/'new.txt').write_text('new ignored local work',newline='\n')
        with self.assertRaisesRegex(Refused,'could not restore'):
            workspace.switch(self.root,'work')
        self.assertEqual((self.root/'new.txt').read_text(),'new ignored local work')
        self.assertTrue(Path(saved['backup']).is_dir())
        self.assertIn(saved['stash'],self.git('stash','list','--format=%H'))
        (self.root/'new.txt').unlink()
        workspace.switch(self.root,'work')
        self.assertEqual((self.root/'new.txt').read_text(),'saved untracked work')

    def test_planning_resume_restores_without_another_gate_and_rejects_stale_or_busy_switches(self):
        from . import native,workspace
        from .config import change
        from .workflow import load_run
        change(self.root,'plans.location','repo')
        for host in ('codex','claude'):
            with self.subTest(host=host):
                native.prepare_scope(self.root,{'tasks':self.tasks[:1],'design':'draft-'+host},workflow='design',
                                     human=self.human('/oh-design draft-'+host,host=host))
                journal,old=load_run(self.root)
                original_branch=old['branch']
                (self.root/'product.txt').write_text('unfinished '+host,newline='\n')
                target='next-'+host
                # Exercise the same native helper through both adapter argument paths.
                request=self.human('Work on another task',host=host)
                native.switch_workspace(self.root,target,request,base='main')
                self.assertEqual(self.git('branch','--show-current'),target)
                self.assertTrue(workspace.parked(self.root,original_branch))
                (self.root/'later.txt').write_text('other task '+host,newline='\n')
                native.resume(self.root,self.resume_choice(run=old['id'],host=host),old['id'])
                resumed=load_run(self.root)[1]
                for key in ('scope_id','granted','attempts','config','done'):
                    self.assertEqual(resumed[key],old[key])
                self.assertEqual((self.root/'product.txt').read_text(),'unfinished '+host)
                self.assertFalse((self.root/'later.txt').exists())
                stashes=self.git('stash','list','--format=%H')
                with self.assertRaisesRegex(Refused,'superseded|predates'):
                    native.switch_workspace(self.root,target,request)
                self.assertEqual(self.git('branch','--show-current'),original_branch)
                self.assertEqual(self.git('stash','list','--format=%H'),stashes)
                # Active writers prevent saving or branch changes.
                admitted=native.admit(self.root,'analysis')
                native.bind(self.root,admitted['id'],{'child_session':'busy-'+host})
                before=self.git('stash','list','--format=%H')
                with self.assertRaisesRegex(Refused,'unsettled'):
                    native.switch_workspace(self.root,'must-not-start',self.human('Another request',host=host),base='main')
                self.assertEqual(self.git('stash','list','--format=%H'),before)
                self.native_results[admitted['id']]={'status':'completed','text':json.dumps({'status':'completed','summary':'Fixture planning scope.'})}
                native.retain(self.root,admitted['id'],{})
                # Finish this subcase without publishing or changing the next one's scope.
                native.decision(self.root,'stop',self.human('stop',host=host))
                self.git('restore','product.txt')
