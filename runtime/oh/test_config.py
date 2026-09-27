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
from .registry import register
from .storage import Refused, state_home


class ConfigTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.temp=Path(temp.name)
        self.root=self.temp/'project';self.root.mkdir()
        env=patch.dict(os.environ,{'OH_DATA_HOME':str(self.temp/'state')});env.start();self.addCleanup(env.stop)
        os.environ.pop('OH_CONFIG_HOME',None)
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        register(self.root,'Fixture')

    def write(self,value):
        settings_file().parent.mkdir(parents=True,exist_ok=True)
        settings_file().write_text(value if isinstance(value,str) else json.dumps(value))

    def read(self):return json.loads(settings_file().read_text())

    def test_settings_live_outside_every_repository_in_one_file_per_user(self):
        self.assertEqual(config_home(),state_home()/'config')  # a separate data folder keeps its own settings
        with patch.dict(os.environ,{'OH_CONFIG_HOME':str(self.temp/'mine')}):self.assertEqual(config_home(),self.temp/'mine')
        home=self.temp/'home'
        with patch('pathlib.Path.home',return_value=home),patch.dict(os.environ,{'OH_DATA_HOME':str(home/'.local/share/o-harness'),'XDG_CONFIG_HOME':''}):
            self.assertEqual(config_home(),home/'.config/o-harness')  # the dashboard service names the default data folder
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

    def test_settings_from_older_versions_move_into_the_file_once_with_backups(self):
        home=state_home();project=home/'projects'/next(p.name for p in (home/'projects').iterdir())
        (home/'settings').mkdir();(home/'settings/defaults.json').write_text('{"max_escalations": 2, "review_rounds": 3}')
        (project/'config.json').write_text(json.dumps(config.defaults()|{'tasks_per_batch':9}))  # an import copied every default
        (project/'config.local.json').write_text('{"tasks_per_batch": 11}')
        (project/'checks.json').write_text('[{"name": "tests", "command": ["true"]}]')
        for path in project.glob('c*.json'):path.chmod(0o444)
        value=load(self.root)
        self.assertEqual((value['max_escalations'],value['tasks_per_batch']),(2,11))
        self.assertEqual(self.read()['max_escalations'],2);self.assertNotIn('review_rounds',self.read())
        self.assertEqual(self.read()['projects']['Fixture'],{'tasks_per_batch':11,'checks':[{'name':'tests','command':['true']}]})
        self.assertFalse(config.legacy_files())
        moved=list((config_home()/'backups').glob('*-moved-into-settings/projects/*/checks.json'))
        self.assertEqual(len(moved),1)
        # A copy left behind by an interrupted move, or put back by an older OH, moves again only when it agrees.
        (project/'checks.json').write_text('[{"name": "tests", "command": ["true"]}]')
        load(self.root);self.assertFalse(config.legacy_files())
        (project/'checks.json').write_text('[{"name": "other", "command": ["false"]}]')
        with self.assertRaisesRegex(Refused,'both set projects.Fixture'):load(self.root)

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
        with patch.dict(os.environ,{'OH_CONFIG_HOME':str(mine)}):
            change(self.root,'review_rounds','4')
            self.assertIn('settings',backup(self.temp/'backup'))
            settings_file().unlink()
            with patch.dict(os.environ,{'OH_DATA_HOME':str(self.temp/'fresh')}):
                restore(self.temp/'backup')
                self.assertEqual(self.read()['projects']['Fixture'],{'review_rounds':4})
                self.assertFalse((self.temp/'fresh/config').exists())
            change(self.root,'review_rounds','5')
            with patch.dict(os.environ,{'OH_DATA_HOME':str(self.temp/'again')}):
                self.assertIn('Kept your current settings.json',restore(self.temp/'backup')['note'])
            self.assertEqual(load(self.root)['review_rounds'],5)

    def test_an_imported_profile_keeps_only_what_differs_from_your_settings(self):
        from .profiles import export_profile,import_profile
        change(self.root,'review_rounds','4',scope='global');change(self.root,'tasks_per_batch','9')
        exported=self.temp/'profile.json';export_profile(self.root,exported)
        clone=self.temp/'clone';subprocess.run(['git','clone','-q',str(self.root),str(clone)],check=True,capture_output=True)
        import_profile(clone,exported)  # same name on this machine: the section is shared
        self.assertEqual(self.read()['projects']['Fixture'],{'tasks_per_batch':9})
        value=json.loads(exported.read_text());value['profile']['name']='Moved'
        (self.temp/'moved.json').write_text(json.dumps(value))
        other=self.temp/'other';subprocess.run(['git','init','-q',str(other)],check=True)
        change(self.root,'review_rounds','6',scope='global')
        import_profile(other,self.temp/'moved.json')
        self.assertEqual(self.read()['projects']['Moved'],{'tasks_per_batch':9,'review_rounds':4})
        value['config']['tasks_per_batch']=3;(self.temp/'clash.json').write_text(json.dumps(value))
        third=self.temp/'third';subprocess.run(['git','init','-q',str(third)],check=True)
        with self.assertRaisesRegex(Refused,'already has other settings for Moved'):import_profile(third,self.temp/'clash.json')

    def test_every_approval_names_its_limits(self):
        from .prepared import limits
        self.assertEqual(limits(12,{'tasks_per_batch':5,'review_rounds':3}),
                         'Runs 5 of 12 tasks, then asks you to continue, up to 3 review rounds each. Change this with /oh-config.')
        self.assertEqual(limits(1,{'tasks_per_batch':5,'review_rounds':1}),'Runs 1 task, up to 1 review round each. Change this with /oh-config.')


if __name__=='__main__':unittest.main()
