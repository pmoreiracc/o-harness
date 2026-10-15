import json
from pathlib import Path
import unittest
from unittest.mock import patch
from . import plans
from .config import change
from .storage import Refused,Journal
from .workflow import load_run
from .test_design import design
from .test_propose import idea
from . import test_design as design_fixtures, test_propose as proposal_fixtures
from . import test_workflow as fixtures


class PrivatePlansTest(unittest.TestCase):
    git=fixtures.WorkflowTest.git
    event=fixtures.WorkflowTest.event

    def setUp(self):
        fixtures.WorkflowTest.setUp(self)
        self.git('switch','-q','main')
        change(self.root,'plans.private_folder',str(Path(self.temp.name)/'visible plans'))
        change(self.root,'plans.location','private')
        self.where=plans.layout(self.root)
        plans.start_roadmap(self.where,'Fixture')
        plans.add_milestone(self.root,self.where,'M1','First slice','Sign-in works')
        plans.add_initiative(self.root,self.where,'M1','auth','Sign-in',[])
        self.calls=[]

    def test_private_paths_refuse_escaping_names_and_checkout_storage(self):
        for name in ('../escape','a/b','a\\b','..','CON','name.'):
            with self.assertRaisesRegex(Refused,'portable folder name'):plans.private_base(self.temp.name,name)
        change(self.root,'plans.private_folder',str(self.root/'private'))
        with self.assertRaisesRegex(Refused,'outside the project'):plans.layout(self.root)

    def test_rename_retains_private_documents_even_if_new_folder_exists(self):
        from .registry import rename
        before=self.where['roadmap'].read_bytes()
        (self.where['base'].parent/'Renamed').mkdir()
        rename(self.root,'Renamed')
        self.assertEqual(plans.layout(self.root)['roadmap'],self.where['roadmap'])
        self.assertEqual(self.where['roadmap'].read_bytes(),before)

    def test_replacement_keeps_private_documents_without_old_approval_authority(self):
        from .registry import register,lookup
        old=lookup(self.root);before=self.where['roadmap'].read_bytes()
        (self.root/'.git').rename(Path(self.temp.name)/'old-git')
        self.git('init','-q')
        new=register(self.root,'Replacement',replace=True)
        change(self.root,'plans.location','private')
        self.assertNotEqual(lookup(self.root)['checkout'],old['checkout'])
        self.assertNotEqual(new['id'],old['project'])
        self.assertEqual(plans.layout(self.root)['roadmap'],self.where['roadmap'])
        self.assertEqual(self.where['roadmap'].read_bytes(),before)
        self.assertFalse(plans.approvals_file(self.root).exists())

    def test_profile_export_explicitly_excludes_private_documents(self):
        from .profiles import export_profile
        change(self.root,'checks','[]')
        target=Path(self.temp.name)/'portable.json'
        result=export_profile(self.root,target)
        self.assertIn('private plan documents and their approvals are excluded',result['contents'])
        self.assertNotIn('Sign-in',target.read_text())

    def other_repository(self,name):
        import subprocess
        path=Path(self.temp.name)/name;path.mkdir()
        subprocess.run(['git','init','-q',str(path)],check=True)
        return path

    def test_renamed_folder_cannot_be_taken_by_a_new_project(self):
        from .registry import rename,register,index_path
        from .config import change
        change(self.root,'plans.private_folder',str(self.where['base'].parent),scope='global')
        change(self.root,'plans.location','private',scope='global')
        rename(self.root,'Renamed')
        other=self.other_repository('other')
        with self.assertRaisesRegex(Refused,'belongs to another project'):register(other,'Fixture')
        self.assertFalse(index_path(other).exists())
        self.assertEqual(plans.layout(self.root)['base'],self.where['base'])

    def test_registration_reserves_unused_folder_before_an_alias_can_register(self):
        from .registry import register,index_path
        change(self.root,'plans.location','private',scope='global')
        change(self.root,'plans.private_folder',str(self.where['base'].parent),scope='global')
        first=self.other_repository('first');second=self.other_repository('second')
        register(first,'Unused')
        self.assertFalse((self.where['base'].parent/'Unused').exists())
        with self.assertRaisesRegex(Refused,'belongs to another project'):register(second,'UNUSED')
        self.assertFalse(index_path(second).exists())
        self.assertEqual(plans.layout(first)['base'],self.where['base'].parent/'Unused')

    def test_rename_rejects_collision_before_moving_profile_or_settings(self):
        from .registry import register,rename,profile
        from .config import read_file,write_file
        other=self.other_repository('other');register(other,'Other')
        data=read_file();data.setdefault('projects',{})['Other']={'plans':{'location':'private','private_folder':str(self.where['base'].parent)}}
        write_file(data)  # also support settings edited directly, before any private command
        before_profile=profile(other);before_settings=read_file()
        with self.assertRaisesRegex(Refused,'belongs to another project'):rename(other,'fixture')
        self.assertEqual(profile(other),before_profile)
        self.assertEqual(read_file(),before_settings)

    def test_rename_retains_reserved_folder_even_before_first_document(self):
        from .registry import register,rename
        change(self.root,'plans.location','private',scope='global')
        change(self.root,'plans.private_folder',str(self.where['base'].parent),scope='global')
        other=self.other_repository('other');register(other,'Unused')
        rename(other,'fixture')
        self.assertEqual(plans.layout(other)['base'],self.where['base'].parent/'Unused')

    def test_failed_registration_rolls_back_folder_reservation(self):
        from .registry import register,index_path
        from .storage import atomic_json,read_json,state_home
        change(self.root,'plans.location','private',scope='global')
        change(self.root,'plans.private_folder',str(self.where['base'].parent),scope='global')
        other=self.other_repository('other');path=state_home()/'registry/private-plans.json'
        before=read_json(path)
        def fail_index(target,*args,**kwargs):
            if target==index_path(other):raise OSError('index publication failed')
            return atomic_json(target,*args,**kwargs)
        with patch('oh.registry.atomic_json',side_effect=fail_index):
            with self.assertRaisesRegex(OSError,'index publication failed'):register(other,'Unused')
        self.assertEqual(read_json(path),before)
        self.assertFalse(index_path(other).exists())
        register(other,'UNUSED')
        self.assertEqual(plans.layout(other)['base'].name,'UNUSED')

    def test_failed_rename_rolls_back_new_reservation(self):
        from .registry import register,rename,profile
        from .storage import read_json,state_home
        other=self.other_repository('other');register(other,'Other')
        change(other,'plans.location','private')
        change(other,'plans.private_folder',str(self.where['base'].parent))
        path=state_home()/'registry/private-plans.json';before=read_json(path)
        with patch('oh.config.write_file',side_effect=PermissionError(13,'Permission denied')):
            with self.assertRaisesRegex(Refused,'Cannot write'):rename(other,'Unused')
        self.assertEqual(read_json(path),before)
        self.assertEqual(profile(other)['name'],'Other')

    def test_enabling_private_reserves_existing_projects_before_new_registration(self):
        from .registry import register,index_path
        first=self.other_repository('first');second=self.other_repository('second')
        register(first,'Alpha')
        change(self.root,'plans.private_folder',str(self.where['base'].parent),scope='global')
        change(self.root,'plans.location','private',scope='global')
        with self.assertRaisesRegex(Refused,'belongs to another project'):register(second,'ALPHA')
        self.assertFalse(index_path(second).exists())
        self.assertEqual(plans.layout(first)['base'].name,'Alpha')

    def test_settings_collision_and_failed_write_preserve_all_reservations(self):
        from .registry import register
        from .config import read_file
        from .storage import read_json,state_home
        first=self.other_repository('first');second=self.other_repository('second')
        register(first,'Alpha');register(second,'ALPHA')
        change(self.root,'plans.private_folder',str(self.where['base'].parent),scope='global')
        path=state_home()/'registry/private-plans.json';before=read_json(path);settings=read_file()
        with self.assertRaisesRegex(Refused,'belongs to another project'):change(self.root,'plans.location','private',scope='global')
        self.assertEqual(read_json(path),before);self.assertEqual(read_file(),settings)
        with patch('oh.config.write_file',side_effect=PermissionError(13,'Permission denied')):
            with self.assertRaisesRegex(Refused,'Cannot write'):change(first,'plans.location','private')
        self.assertEqual(read_json(path),before);self.assertEqual(read_file(),settings)
        change(first,'plans.location','private')
        with self.assertRaisesRegex(Refused,'belongs to another project'):change(second,'plans.location','private')

    def test_changing_or_unsetting_private_folder_cannot_take_another_projects_folder(self):
        from .registry import register
        from .config import read_file
        other=self.other_repository('other');register(other,'fixture')
        change(self.root,'plans.private_folder',str(self.where['base'].parent),scope='global')
        change(other,'plans.private_folder',str(Path(self.temp.name)/'separate'))
        change(other,'plans.location','private');before=read_file()
        with self.assertRaisesRegex(Refused,'belongs to another project'):
            change(other,'plans.private_folder',str(self.where['base'].parent))
        with self.assertRaisesRegex(Refused,'belongs to another project'):change(other,'plans.private_folder')
        self.assertEqual(read_file(),before)
        self.assertEqual(plans.layout(other)['base'].parent,(Path(self.temp.name)/'separate').resolve())

    def test_registration_checks_private_locations_from_manually_edited_settings(self):
        from .registry import register,index_path
        from .config import read_file,write_file
        first=self.other_repository('first');second=self.other_repository('second')
        register(first,'Alpha')
        data=read_file();data['plans']={'location':'private','private_folder':str(self.where['base'].parent)};write_file(data)
        with self.assertRaisesRegex(Refused,'belongs to another project'):register(second,'ALPHA')
        self.assertFalse(index_path(second).exists())
        self.assertEqual(plans.layout(first)['base'].name,'Alpha')

    def test_empty_reserved_replacement_and_failed_publication_are_recoverable(self):
        from .registry import register,lookup,index_path
        from .storage import atomic_json,read_json,state_home
        change(self.root,'plans.private_folder',str(self.where['base'].parent),scope='global')
        change(self.root,'plans.location','private',scope='global')
        other=self.other_repository('other');old=register(other,'Unused');index=read_json(index_path(other))
        self.assertFalse((self.where['base'].parent/'Unused').exists())
        (other/'.git').rename(Path(self.temp.name)/'unused-old-git')
        import subprocess
        subprocess.run(['git','init','-q',str(other)],check=True)
        path=state_home()/'registry/private-plans.json';before=read_json(path)
        def fail_index(target,*args,**kwargs):
            if target==index_path(other):raise OSError('replacement publication failed')
            return atomic_json(target,*args,**kwargs)
        with patch('oh.registry.atomic_json',side_effect=fail_index):
            with self.assertRaisesRegex(OSError,'replacement publication failed'):register(other,replace=True)
        self.assertEqual(read_json(path),before);self.assertEqual(read_json(index_path(other)),index)
        fresh=register(other,replace=True)
        self.assertNotEqual(fresh['id'],old['id'])
        self.assertEqual(plans.layout(other)['base'],self.where['base'].parent/'Unused')
        self.assertFalse(plans.approvals_file(other).exists())
        self.assertNotEqual(lookup(other)['checkout'],index['checkout'])

    def test_reservation_publish_error_restores_ownership_before_registration_retry(self):
        from .registry import register,index_path
        from .storage import atomic_json,read_json,state_home
        change(self.root,'plans.private_folder',str(self.where['base'].parent),scope='global')
        change(self.root,'plans.location','private',scope='global')
        other=self.other_repository('sync-error');path=state_home()/'registry/private-plans.json';before=read_json(path)
        def publish_then_error(target,value,**kwargs):
            atomic_json(target,value,**kwargs)
            raise OSError('sync failed after publication')
        with patch('oh.private_storage.atomic_json',side_effect=publish_then_error):
            with self.assertRaisesRegex(OSError,'sync failed'):register(other,'SyncError')
        self.assertEqual(read_json(path),before)
        self.assertFalse(index_path(other).exists())
        fresh=register(other,'SyncError')
        from .private_storage import canonical
        self.assertEqual(read_json(path)[canonical(plans.layout(other)['base'])]['project'],fresh['id'])

    def test_index_publish_error_keeps_registration_and_replacement_consistent(self):
        from .registry import register,index_path,lookup
        from .storage import atomic_json,read_json,state_home
        from .private_storage import canonical
        change(self.root,'plans.private_folder',str(self.where['base'].parent),scope='global')
        change(self.root,'plans.location','private',scope='global')
        other=self.other_repository('sync-index')
        def publish_then_error(target,value,**kwargs):
            atomic_json(target,value,**kwargs)
            if target==index_path(other):raise OSError('index sync failed after publication')
        for replacing in (False,True):
            with self.subTest(replacing=replacing):
                if replacing:
                    old=lookup(other)
                    (other/'.git').rename(Path(self.temp.name)/'old-sync-git')
                    import subprocess
                    subprocess.run(['git','init','-q',str(other)],check=True)
                with patch('oh.registry.atomic_json',side_effect=publish_then_error):
                    result=register(other,'SyncIndex',replace=replacing)
                self.assertIn('saved',result['note'])
                entry=lookup(other);self.assertEqual(entry['project'],result['id'])
                records=read_json(state_home()/'registry/private-plans.json')
                self.assertEqual(records[canonical(plans.layout(other)['base'])]['project'],result['id'])
                self.assertEqual(register(other,'SyncIndex')['id'],result['id'])
                self.assertFalse(plans.approvals_file(other).exists())
                if replacing:self.assertNotEqual(entry['project'],old['project'])

    def test_profile_publish_error_leaves_registration_and_rename_retryable(self):
        from .registry import register,rename,profile,index_path
        from .storage import atomic_json,read_json,state_home
        from .config import read_file
        change(self.root,'plans.private_folder',str(self.where['base'].parent),scope='global')
        change(self.root,'plans.location','private',scope='global')
        other=self.other_repository('sync-profile');path=state_home()/'registry/private-plans.json';before=read_json(path)
        def publish_then_error(target,value,**kwargs):
            atomic_json(target,value,**kwargs)
            if target.name=='profile.json':raise OSError('profile sync failed after publication')
        with patch('oh.registry.atomic_json',side_effect=publish_then_error):
            with self.assertRaisesRegex(OSError,'profile sync failed'):register(other,'SyncProfile')
        self.assertEqual(read_json(path),before);self.assertFalse(index_path(other).exists())
        original=register(other,'SyncProfile');before=read_json(path);settings=read_file()
        with patch('oh.registry.atomic_json',side_effect=publish_then_error):
            with self.assertRaisesRegex(OSError,'profile sync failed'):rename(other,'RenamedProfile')
        self.assertEqual(profile(other),original);self.assertEqual(read_file(),settings);self.assertEqual(read_json(path),before)
        rename(other,'RenamedProfile')
        self.assertEqual(profile(other)['name'],'RenamedProfile')

    def test_settings_publish_error_keeps_folder_ownership_and_rename_consistent(self):
        from .registry import register,rename,profile
        from .config import write_file,read_file
        from .storage import read_json,state_home
        from .private_storage import canonical
        from contextlib import redirect_stderr
        import io
        other=self.other_repository('sync-settings');register(other,'SyncSettings')
        change(other,'plans.private_folder',str(self.where['base'].parent))
        def publish_then_error(data):
            write_file(data)
            raise OSError('settings error after publication')
        output=io.StringIO()
        with patch('oh.config.write_file',side_effect=publish_then_error),redirect_stderr(output):
            change(other,'plans.location','private')
            rename(other,'RenamedSettings')
        self.assertIn('Settings were saved',output.getvalue())
        owner=profile(other);self.assertEqual(owner['name'],'RenamedSettings')
        self.assertIn('RenamedSettings',read_file()['projects'])
        self.assertNotIn('SyncSettings',read_file()['projects'])
        records=read_json(state_home()/'registry/private-plans.json')
        self.assertEqual(records[canonical(plans.layout(other)['base'])]['project'],owner['id'])
        self.assertEqual(register(other,'RenamedSettings')['id'],owner['id'])

    def test_linked_settings_publish_error_keeps_ownership_and_rename_consistent(self):
        import os
        if os.name=='nt':self.skipTest('Creating symlinks needs extra rights on Windows')
        from .config import settings_file
        target=Path(self.temp.name)/'dotfiles/settings.json';target.parent.mkdir()
        settings_file().rename(target);settings_file().symlink_to(target)
        self.test_settings_publish_error_keeps_folder_ownership_and_rename_consistent()
        self.assertTrue(settings_file().is_symlink())

    def test_private_folder_rejects_cwd_relative_expansion(self):
        import os
        invalid=['~oh_user_that_does_not_exist_927/plans','~relative','relative/plans']
        if os.name!='nt':invalid+=['C:\\plans','C:/plans','~\\plans']
        for folder in invalid:
            with self.subTest(folder=folder):
                with self.assertRaisesRegex(Refused,'absolute folder'):change(self.root,'plans.private_folder',folder)
                with self.assertRaisesRegex(Refused,'absolute folder'):plans.private_base(folder,'Fixture')
        self.assertEqual(plans.private_base('~/oh-plans','Fixture'),Path.home()/'oh-plans/Fixture')

    def test_case_aliases_and_unowned_folders_are_refused(self):
        from .registry import register
        other=self.other_repository('other');register(other,'fixture')
        change(other,'plans.private_folder',str(self.where['base'].parent))
        with self.assertRaisesRegex(Refused,'belongs to another project'):change(other,'plans.location','private')
        folder=Path(self.temp.name)/'existing';(folder/'fixture').mkdir(parents=True)
        change(other,'plans.private_folder',str(folder))
        with self.assertRaisesRegex(Refused,'without ownership'):change(other,'plans.location','private')

    def test_import_does_not_adopt_deleted_projects_private_documents(self):
        from .registry import index_path
        from .profiles import export_profile,import_profile
        import os,shutil,stat
        change(self.root,'checks','[]')
        target=Path(self.temp.name)/'profile.json';export_profile(self.root,target)
        before=self.where['roadmap'].read_bytes()
        shutil.rmtree(self.root,onerror=lambda remove,path,_:(os.chmod(path,stat.S_IWRITE),remove(path)))  # Git's read-only files, on Windows
        self.assertFalse(self.root.exists())
        other=self.other_repository('other')
        with self.assertRaisesRegex(Refused,'belongs to another project'):import_profile(other,target)
        self.assertFalse(index_path(other).exists())
        self.assertEqual(self.where['roadmap'].read_bytes(),before)

    def test_private_edits_use_the_canonical_folder_lock(self):
        from . import private_storage
        from .storage import lock
        expected=private_storage.folder_lock(self.where['base']);seen=[]
        def observe(path,**kwargs):
            seen.append(path)
            return lock(path,**kwargs)
        with patch('oh.storage.lock',observe),plans.editing(self.root):
            with plans.editing(self.root):pass
        self.assertEqual(seen.count(expected),1)
        self.assertEqual(private_storage.canonical(self.where['base']),private_storage.canonical(str(self.where['base']).upper()))
