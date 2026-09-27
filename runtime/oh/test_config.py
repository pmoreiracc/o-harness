import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from . import config
from .config import change, config_home, describe, load, project_checks, schema, settings_file
from .registry import register, rename
import shutil
from .storage import Refused, state_home


class ConfigTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.temp=Path(temp.name)
        self.root=self.temp/'project';self.root.mkdir()
        env=patch.dict(os.environ,{'OH_DATA_HOME':str(self.temp/'state')});env.start();self.addCleanup(env.stop)
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        register(self.root,'Fixture')

    def write(self,value):
        settings_file().parent.mkdir(parents=True,exist_ok=True)
        settings_file().write_text(value if isinstance(value,str) else json.dumps(value))

    def read(self):return json.loads(settings_file().read_text())

    def test_settings_live_outside_every_repository_in_one_file_per_user(self):
        self.assertEqual(config_home(),state_home()/'config')  # a separate data folder (a test, say) never touches yours
        home=self.temp/'home'
        with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,{'OH_DATA_HOME':str(home/'.local/share/o-harness'),'XDG_CONFIG_HOME':''}):
            self.assertEqual(config_home(),home/'.config/o-harness')  # the dashboard service names the default data folder
            with patch.dict(os.environ,{'XDG_CONFIG_HOME':str(self.temp/'xdg')}):self.assertEqual(config_home(),self.temp/'xdg/o-harness')
        self.assertFalse(any(p.name.startswith(('oh.json','settings')) for p in self.root.iterdir()))

    def test_every_project_then_this_project_and_errors_name_the_exact_key(self):
        self.write({'tasks_per_batch':12,'review_rounds':4,'models':{'claude':{'review':{'effort':'max'}}},
                    'projects':{'Fixture':{'review_rounds':7,'checks':[{'name':'tests','command':['true']}]},'Other':{'review_rounds':9}}})
        value=load(self.root)
        self.assertEqual((value['tasks_per_batch'],value['review_rounds'],value['models']['claude']['review']['effort']),(12,7,'max'))
        self.assertEqual(project_checks(self.root),[{'name':'tests','command':['true']}])
        listed={item['key']:item for item in describe(self.root)['settings']}
        self.assertEqual([listed[k]['source'] for k in ('tasks_per_batch','review_rounds','max_escalations')],['global','project','default'])
        self.assertIn('No OH project on this machine is named Other',describe(self.root)['note'])
        for bad,words in (({'projects':{'Fixture':{'tasks_per_batch':0}}},'projects.Fixture.tasks_per_batch must be whole number from 1 to 100'),
                          ({'taskz':1},'Unknown setting: taskz'),({'checks':[]},'checks belong to one project'),
                          ({'projects':{'Fixture':{'models':{'codex':{'review':{'effort':'huge'}}}}}},'projects.Fixture.models.codex.review.effort must be one of'),
                          ({'projects':{'Fixture':{'checks':[{'name':'x','command':['true'],'env':{}}]}}},'Unknown check field: projects.Fixture.checks\\[0\\].env'),
                          ({'projects':{'Fixture':{'checks':[{'name':'x','command':['true'],'inputs':['../up']}]}}},'repository-relative'),
                          ({'projects':[]},'projects must be an object'),({'context':5},'context must be an object')):
            self.write(bad)
            with self.assertRaisesRegex(Refused,re.escape(str(settings_file()))+': .*'+words):load(self.root)
        self.write('{"tasks_per_batch": 3,')
        with self.assertRaisesRegex(Refused,'not valid JSON'):load(self.root)
        self.write('{"review_rounds": 3, "review_rounds": 50}')
        with self.assertRaisesRegex(Refused,'"review_rounds" appears twice'):load(self.root)

    def test_change_is_the_only_writer_and_never_writes_an_invalid_value(self):
        result=change(self.root,'tasks_per_batch','15')
        self.assertEqual((result['scope'],result['from'],result['to']),('projects.Fixture',5,15))
        change(self.root,'review_rounds','6',scope='global')
        self.assertEqual(self.read(),{'$schema':'./settings.schema.json','review_rounds':6,'projects':{'Fixture':{'tasks_per_batch':15}}})
        written=settings_file().read_text()
        for key,value in (('review_rounds','101'),('review_rounds','three'),('models.claude.review.effort','ultra'),('tasks','15'),
                          ('checks','[{"name": "x"}]'),('checks','npm test'),('models.claude.review.model','null')):
            with self.assertRaises(Refused):change(self.root,key,value)
            self.assertEqual(settings_file().read_text(),written)
        with self.assertRaisesRegex(Refused,'belong to one project'):change(self.root,'checks','[]',scope='global')
        self.assertTrue(change(self.root,'tasks_per_batch','15')['unchanged']);self.assertTrue(change(self.root,'max_escalations',None)['unchanged'])
        self.assertEqual(settings_file().read_text(),written)
        change(self.root,'tasks_per_batch','9',scope='global')
        self.assertIn('projects.Fixture sets its own value',change(self.root,'tasks_per_batch','8',scope='global')['note'])
        change(self.root,'tasks_per_batch',None)
        self.assertEqual(load(self.root)['tasks_per_batch'],8)
        for key in ('projects','projects.Fixture','$schema'):
            with self.assertRaisesRegex(Refused,'not a setting'):change(self.root,key,None,scope='global')
        change(self.root,'models.claude.review.model','opus',scope='global')
        with self.assertRaisesRegex(Refused,'groups several settings'):change(self.root,'models.claude',None,scope='global')
        self.assertIn('Fixture',self.read()['projects'])
        other=self.temp/'other';subprocess.run(['git','init','-q',str(other)],check=True)
        with self.assertRaisesRegex(Refused,'not an OH project: add --global'):change(other,'review_rounds','4')
        self.assertEqual(change(other,'review_rounds','4',scope='global')['scope'],'your settings for every project')
        checks='[{"name": "tests", "command": ["npm", "test"], "toolchain": [["node", "--version"]]}]'
        self.assertEqual(change(self.root,'checks',checks)['to'],json.loads(checks))
        self.assertIn('"command": ["npm", "test"]',settings_file().read_text())  # short lists stay on one line

    def test_a_broken_file_is_repaired_one_setting_at_a_time(self):
        self.write({'taskz':1,'review_rounds':0,'projects':{'Fixture':{'retired':True}}})
        change(self.root,'taskz',None,scope='global')
        self.assertEqual(change(self.root,'review_rounds','4',scope='global')['to'],4)  # still broken: reported from the file
        with self.assertRaisesRegex(Refused,'Unknown setting: projects.Fixture.retired'):load(self.root)
        with self.assertRaisesRegex(Refused,'Unknown setting: nothing'):change(self.root,'nothing',None)
        change(self.root,'retired',None)
        self.assertEqual(load(self.root)['review_rounds'],4)
        self.write({'projects':{'Fixture':5}})
        with self.assertRaisesRegex(Refused,'projects.Fixture must be an object'):change(self.root,'review_rounds','4')

    def legacy(self,root=None):
        home=state_home();return home/'projects'/next(p.name for p in (home/'projects').iterdir()
                                                       if json.loads((p/'profile.json').read_text())['name']==(root or 'Fixture'))

    def test_settings_from_older_versions_move_into_the_file_once_with_backups(self):
        home=state_home();project=self.legacy()
        (home/'settings').mkdir();(home/'settings/defaults.json').write_text('{"max_escalations": 2, "review_rounds": 3, "tasks_per_batch": 15}')
        # An import copied every default: a project value equal to OH's default still beats the shared value.
        (project/'config.json').write_text(json.dumps(config.defaults()|{'tasks_per_batch':9}))
        (project/'config.local.json').write_text('{"tasks_per_batch": 11}')
        (project/'checks.json').write_text('[{"name": "tests", "command": ["true"]}]')
        for path in project.glob('c*.json'):path.chmod(0o444)
        value=load(self.root)
        self.assertEqual((value['max_escalations'],value['tasks_per_batch'],value['review_rounds']),(1,11,3))  # as before the move
        self.assertEqual({k:v for k,v in self.read().items() if k!='projects'},{'$schema':'./settings.schema.json','max_escalations':2,'tasks_per_batch':15})
        self.assertEqual(self.read()['projects']['Fixture'],{'max_escalations':1,'tasks_per_batch':11,'checks':[{'name':'tests','command':['true']}]})
        self.assertFalse(config.legacy_files())
        moved=list((config_home()/'backups').glob('*-moved-into-settings/projects/*/checks.json'))
        self.assertEqual(len(moved),1)
        # A file an interrupted move left behind is already in settings.json: it only moves to backups.
        (project/'checks.json').write_text('[{"name": "other", "command": ["false"]}]')
        (home/'settings-moved.json').write_text(json.dumps([project.name]))
        self.assertEqual(project_checks(self.root),[{'name':'tests','command':['true']}])
        self.assertFalse(config.legacy_files());self.assertFalse((home/'settings-moved.json').exists())
        # Any other older file must match the section every project with this name shares.
        (project/'checks.json').write_text('[{"name": "tests", "command": ["true"]}]')
        with self.assertRaisesRegex(Refused,'differs from .*checks.json in projects.Fixture.max_escalations, projects.Fixture.tasks_per_batch'):load(self.root)
        self.assertTrue((project/'checks.json').exists())

    def test_one_project_per_name_so_a_section_is_never_shared(self):
        home=state_home();clone=self.temp/'clone';subprocess.run(['git','clone','-q',str(self.root),str(clone)],check=True,capture_output=True)
        with self.assertRaisesRegex(Refused,'already named Fixture'):register(clone,'Fixture')
        with patch('oh.registry.free'):register(clone,'Fixture')  # two registrations named alike, from before this rule
        first,second=(self.legacy_by(self.root),self.legacy_by(clone))
        (first/'config.local.json').write_text('{"tasks_per_batch": 5}');(second/'config.json').write_text('{"review_rounds": 9}')
        for root in (self.root,clone):
            with self.assertRaisesRegex(Refused,'More than one OH project is named Fixture.*rename'):load(root)
        rename(clone,'Fixture clone')
        with self.assertRaisesRegex(Refused,'already named Fixture'):rename(clone,'Fixture')
        self.assertEqual((load(self.root)['review_rounds'],load(clone)['review_rounds']),(3,9))  # each keeps what it had
        self.assertEqual(sorted(self.read()['projects']),['Fixture','Fixture clone'])
        rename(clone,'Second');self.assertEqual(self.read()['projects']['Second'],{'review_rounds':9})  # the section follows
        # A replaced registration no longer counts; nor does a deleted checkout whose name a present project uses.
        retired=home/'projects/retired-project';retired.mkdir()
        (retired/'profile.json').write_text(json.dumps({'id':'retired-project','name':'Fixture','kind':'product','schema_version':1}))
        (retired/'config.json').write_text('{"tasks_per_batch": 20}')
        gone=self.temp/'gone';subprocess.run(['git','init','-q',str(gone)],check=True)
        with patch('oh.registry.free'):register(gone,'Fixture')
        (self.legacy_by(gone)/'checks.json').write_text('[{"name": "old", "command": ["true"]}]');shutil.rmtree(gone)
        self.assertEqual((load(self.root)['tasks_per_batch'],project_checks(self.root)),(5,[]))
        kept=config_home()/'backups'
        self.assertTrue(list(kept.glob('*-unused-project-settings/projects/retired-project/config.json')))
        self.assertEqual(len(list(kept.glob('*-unused-project-settings/projects/*/checks.json'))),1)

    def test_rename_never_takes_over_other_settings(self):
        change(self.root,'review_rounds','7')
        self.write(self.read()|{'projects':self.read()['projects']|{'Site':{'tasks_per_batch':40,'checks':[{'name':'x','command':['rm','-rf','build']}]},
                                                                  'Same':{'review_rounds':7}}})
        with self.assertRaisesRegex(Refused,'projects.Site already holds settings'):rename(self.root,'Site')
        self.assertEqual((load(self.root)['review_rounds'],project_checks(self.root)),(7,[]))  # nothing changed
        self.assertEqual(rename(self.root,'Same')['section'],'projects.Fixture is now projects.Same')
        self.assertNotIn('Fixture',self.read()['projects']);self.assertEqual(load(self.root)['review_rounds'],7)
        other=self.temp/'other';subprocess.run(['git','init','-q',str(other)],check=True);register(other,'Site')
        self.assertIn('those settings apply',config.ensure_project(other)['note'])  # a section left behind is announced
        with patch('oh.config.write_file',side_effect=PermissionError(13,'Permission denied')):
            with self.assertRaisesRegex(Refused,'Cannot write .*Permission denied'):rename(self.root,'Renamed')
        self.assertEqual(config.project_name(self.root),'Same')  # the profile went back with the settings

    def legacy_by(self,root):
        from .registry import lookup
        return state_home()/'projects'/lookup(root)['project']

    def test_a_missing_settings_file_is_only_recreated_when_you_ask(self):
        change(self.root,'review_rounds','4',scope='global');settings_file().rename(self.temp/'moved.json')
        other=self.temp/'other';subprocess.run(['git','init','-q',str(other)],check=True)
        from .cli import main
        from .registry import index_path
        with self.assertRaises(SystemExit):main(['--root',str(other),'init','--name','Other'])
        self.assertFalse(index_path(other).exists())  # refused before registering anything
        with self.assertRaisesRegex(Refused,'is missing'):change(self.root,'review_rounds',None,scope='global')
        self.assertFalse(settings_file().exists())
        with patch('oh.config.launch'):config.open_settings(self.root)
        self.assertEqual(load(self.root)['review_rounds'],3)

    def test_the_repair_tools_work_on_broken_files(self):
        for broken in ('{"review_rounds": 3,','{"a": 1, "a": 2}','{"projects": []}','{"projects": {"Fixture": 5}}'):
            self.write(broken)
            with patch('oh.config.launch') as opener:config.open_settings(self.root)
            opener.assert_called_once();self.assertEqual(settings_file().read_text(),broken)  # opened as it is
        self.write({'projects':[]})
        other=self.temp/'other';subprocess.run(['git','init','-q',str(other)],check=True)
        from .cli import main
        from .registry import index_path
        with self.assertRaises(SystemExit):main(['--root',str(other),'init','--name','Other'])
        self.assertFalse(index_path(other).exists())  # init refuses before registering
        self.assertEqual(change(self.root,'review_rounds','4',scope='global')['to'],4)
        with self.assertRaisesRegex(Refused,'projects must be an object'):change(self.root,'review_rounds','4')
        self.write({'checks':[],'context':5,'projects':{'Fixture':{'$schema':'x','checks':[{'name':'unit','command':['true']}]}}})
        change(self.root,'checks',None,scope='global');change(self.root,'context',None,scope='global');change(self.root,'$schema',None)
        self.assertEqual(project_checks(self.root),[{'name':'unit','command':['true']}])

    def test_an_older_file_that_cannot_move_stops_only_its_own_project(self):
        other=self.temp/'other';subprocess.run(['git','init','-q',str(other)],check=True);register(other,'Other')
        for text,words in (('[{"name": "t", "command": ["true"], "description": "kept"}]','Unknown check field'),
                           ('{"name": "t"}','must contain a JSON list'),('[{"name": "t", "command": ["true"]}',"Cannot move")):
            (self.legacy()/'checks.json').write_text(text)
            (self.legacy('Other')/'checks.json').write_text('[{"name": "other", "command": ["true"]}]')
            with self.assertRaisesRegex(Refused,words):load(self.root)
            self.assertEqual(project_checks(other),[{'name':'other','command':['true']}])  # moved; Fixture's file stays
            self.assertTrue((self.legacy()/'checks.json').exists())
        (self.legacy()/'checks.json').unlink()
        self.write({'models':{'claude':{'review':{'effort':'max'}}},'projects':{'Other':{'checks':[{'name':'other','command':['true']}]}}})
        (state_home()/'settings').mkdir();(state_home()/'settings/defaults.json').write_text('{"models": {"codex": {"review": {"effort": "low"}}}}')
        self.assertEqual(load(self.root)['models']['codex']['review']['effort'],'low')  # different keys under models agree
        (state_home()/'settings/defaults.json').write_text('[1, 2]')
        with self.assertRaisesRegex(Refused,'must contain a JSON object'):load(other)

    def test_renamed_settings_are_moved_once_with_a_backup(self):
        self.write({'review_rounds':4,'projects':{'Fixture':{'review_rounds':6}}})
        with patch.dict(config.RENAMED,{'review_rounds':'tasks_per_batch'}):
            self.assertEqual(load(self.root)['tasks_per_batch'],6)
        self.assertEqual(self.read(),{'$schema':'./settings.schema.json','tasks_per_batch':4,'projects':{'Fixture':{'tasks_per_batch':6}}})
        backup,=(config_home()/'backups').glob('*-settings/settings.json')
        self.assertEqual(json.loads(backup.read_text())['review_rounds'],4)

    def test_editors_get_a_schema_for_the_running_version(self):
        change(self.root,'review_rounds','4')
        written=json.loads((config_home()/'settings.schema.json').read_text())
        self.assertEqual(written,schema())
        project=written['properties']['projects']['additionalProperties']['properties']
        self.assertIn('checks',project);self.assertNotIn('checks',written['properties'])
        for key,_,_ in config.rules():
            node=written
            for part in key.split('.'):node=node['properties'][part]
            self.assertIn('description',node)

    @unittest.skipIf(os.name=='nt','Creating symlinks needs extra rights on Windows')
    def test_a_dotfiles_link_keeps_pointing_at_your_file_and_workers_cannot_write_either(self):
        dotfiles=self.temp/'dotfiles';dotfiles.mkdir();(dotfiles/'settings.json').write_text('{}')
        config_home().mkdir(parents=True);settings_file().symlink_to(dotfiles/'settings.json')
        change(self.root,'review_rounds','4')
        self.assertTrue(settings_file().is_symlink());self.assertIn('review_rounds',(dotfiles/'settings.json').read_text())
        self.assertLessEqual({str(config_home()),str(dotfiles.resolve())},set(config.protected_paths()))

    def test_claude_workers_cannot_write_the_settings_folder(self):
        from .hosts import command
        with patch('oh.hosts.executable',return_value='claude'):
            args=command('claude',{'model':'opus','effort':'high'},self.root,'implementation',None,60000)
        sandbox=json.loads(args[args.index('--settings')+1])
        self.assertIn(str(config_home()),sandbox['sandbox']['filesystem']['denyWrite'])
        self.assertIn(f'Edit(/{config_home()}/**)',sandbox['permissions']['deny'])

    def test_a_process_that_looks_elsewhere_is_refused_instead_of_using_defaults(self):
        change(self.root,'review_rounds','4')
        from .backup import backup
        with patch('oh.config.config_home',return_value=self.temp/'elsewhere'):
            with self.assertRaisesRegex(Refused,'Your settings are in'):backup(self.temp/'backup')
        if os.name!='nt':  # the same file through a symlinked folder is the same settings
            (self.temp/'alias').symlink_to(config_home(),target_is_directory=True)
            with patch('oh.config.config_home',return_value=self.temp/'alias'):self.assertEqual(load(self.root)['review_rounds'],4)
        elsewhere=self.temp/'elsewhere'
        with patch('oh.config.config_home',return_value=elsewhere):
            with self.assertRaisesRegex(Refused,'Your settings are in .*settings.json, but OH now reads'):load(self.root)
        moved=self.temp/'moved';moved.mkdir();settings_file().rename(moved/'settings.json')
        with patch('oh.config.config_home',return_value=moved):
            self.assertEqual(load(self.root)['review_rounds'],4)  # a moved file is followed
            with patch('oh.config.config_home',return_value=elsewhere):
                with self.assertRaisesRegex(Refused,'but this OH process reads'):load(self.root)

    @unittest.skipIf(os.name=='nt','Read-only folders work differently on Windows')
    def test_a_read_only_settings_folder_never_stops_oh(self):
        change(self.root,'review_rounds','4');(config_home()/'settings.schema.json').write_text('{}')
        config_home().chmod(0o555);self.addCleanup(config_home().chmod,0o755)
        self.assertEqual(load(self.root)['review_rounds'],4)

    def test_open_creates_the_file_and_asks_the_system_to_open_it(self):
        with patch('oh.config.launch') as opener:result=config.open_settings(self.root)
        opener.assert_called_once_with(str(settings_file()))
        self.assertEqual(self.read()['projects'],{'Fixture':{}});self.assertTrue(result['opened'])
        with patch('subprocess.Popen') as popen,patch('sys.platform','darwin'):config.launch('x.json')
        self.assertEqual(popen.call_args[0][0],['open','x.json'])
        with patch('oh.config.launch',side_effect=OSError):self.assertIn('in your editor',config.open_settings(self.root)['note'])

    def test_backups_carry_your_settings_and_restore_never_overwrites_them(self):
        from .backup import backup,restore
        mine=self.temp/'mine'
        with patch('oh.config.config_home',return_value=mine):
            change(self.root,'review_rounds','4')
            (state_home()/'config').mkdir()  # a stray folder never breaks a backup
            self.assertEqual(backup(self.temp/'backup')['settings'],'user-settings/settings.json')
            settings_file().unlink()
            with patch.dict(os.environ,{'OH_DATA_HOME':str(self.temp/'fresh')}):
                restore(self.temp/'backup')
                self.assertEqual(self.read()['projects']['Fixture'],{'review_rounds':4})
                self.assertFalse((self.temp/'fresh/user-settings').exists())
            change(self.root,'review_rounds','5')
            with patch.dict(os.environ,{'OH_DATA_HOME':str(self.temp/'again')}):
                self.assertIn('Kept your current settings.json',restore(self.temp/'backup')['note'])
            self.assertEqual(load(self.root)['review_rounds'],5)
        # A backup of a separate data folder carries its settings and their history to where you keep yours.
        (state_home()/'config').rmdir();(mine/'settings.json').unlink()
        with self.assertRaisesRegex(Refused,'settings.json is missing'):load(self.root)
        change(self.root,'review_rounds','6');change(self.root,'review_rounds','7')
        keep=config_home()/'backups/20000101-000000-settings';keep.mkdir(parents=True);(keep/'settings.json').write_text('{}')
        backup(self.temp/'inside')
        home=self.temp/'home'
        with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,{'OH_DATA_HOME':str(home/'.local/share/o-harness'),'XDG_CONFIG_HOME':''}):
            restore(self.temp/'inside')
            self.assertEqual(self.read()['projects']['Fixture'],{'review_rounds':7})
            self.assertTrue(list((config_home()/'backups').glob('*-restored-history/20000101-000000-settings/settings.json')))
            self.assertFalse((state_home()/'config').exists())

    def test_an_imported_profile_keeps_only_what_differs_from_your_settings(self):
        from .profiles import export_profile,import_profile
        change(self.root,'review_rounds','4',scope='global');change(self.root,'tasks_per_batch','9');change(self.root,'review_rounds','4')
        exported=self.temp/'profile.json';export_profile(self.root,exported)
        clone=self.temp/'clone';subprocess.run(['git','clone','-q',str(self.root),str(clone)],check=True,capture_output=True)
        with self.assertRaisesRegex(Refused,'already named Fixture'):import_profile(clone,exported)
        change(self.root,'review_rounds','6',scope='global')
        import_profile(clone,exported,'Fixture clone')
        self.assertEqual(self.read()['projects']['Fixture clone'],{'tasks_per_batch':9,'review_rounds':4})
        # A section left by an earlier project of that name is reused only when it holds the same settings.
        self.write(self.read()|{'projects':self.read()['projects']|{'Old':{'tasks_per_batch':9,'review_rounds':4,'checks':[]}}})
        for name,root in (('Old','old'),('Other','other')):subprocess.run(['git','init','-q',str(self.temp/root)],check=True)
        import_profile(self.temp/'old',exported,'Old')  # an empty checks list is no checks
        self.write(self.read()|{'projects':self.read()['projects']|{'Other':{'tasks_per_batch':3}}})
        with self.assertRaisesRegex(Refused,'already has different settings under projects.Other'):import_profile(self.temp/'other',exported,'Other')

    def test_every_approval_names_its_limits(self):
        from .prepared import limits
        self.assertEqual(limits(12,{'tasks_per_batch':5,'review_rounds':3}),
                         'Runs 5 of 12 tasks, then asks you to continue, up to 3 review rounds each. Change this with /oh-config.')
        self.assertEqual(limits(1,{'tasks_per_batch':5,'review_rounds':1}),'Runs 1 task, up to 1 review round each. Change this with /oh-config.')


if __name__=='__main__':unittest.main()
