import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from .config import HOME, change, describe, load, schema, SCHEMA_URL
from .registry import register, profile_path
from .storage import Refused, atomic_json


class ConfigTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)/'project';self.root.mkdir()
        env=patch.dict(os.environ,{'OH_DATA_HOME':str(Path(temp.name)/'state')});env.start();self.addCleanup(env.stop)
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        for key,value in (('user.name','OH Test'),('user.email','test@example.invalid')):self.git('config',key,value)
        register(self.root,'Fixture')

    def git(self,*args):return subprocess.run(['git','-C',str(self.root),*args],check=True,capture_output=True,text=True).stdout

    def commit(self,text=None):
        if text is not None:(self.root/'oh.json').write_text(text)
        self.git('add','-A');self.git('commit','-qm','settings')

    def test_published_schema_matches_the_settings_oh_validates(self):
        self.assertEqual(json.loads((HOME/'config/oh.schema.json').read_text()),schema())

    def test_repository_settings_apply_and_errors_name_the_file_and_setting(self):
        repo=self.root/'oh.json'
        self.commit(json.dumps({'$schema':SCHEMA_URL,'tasks_per_batch':12,'models':{'claude':{'review':{'effort':'max'}}}}))
        atomic_json(profile_path(self.root,'config.local.json'),{'review_rounds':7})
        config=load(self.root)
        self.assertEqual((config['tasks_per_batch'],config['review_rounds'],config['models']['claude']['review']['effort']),(12,7,'max'))
        listed={item['key']:item for item in describe(self.root)['settings']}
        self.assertEqual((listed['tasks_per_batch']['source'],listed['review_rounds']['source'],listed['max_escalations']['source']),('project','personal','default'))
        for bad,words in (({'tasks_per_batch':0},'tasks_per_batch must be whole number from 1 to 100'),({'taskz':1},'Unknown setting: taskz'),
                          ({'models':{'codex':{'review':{'effort':'huge'}}}},'models.codex.review.effort must be one of')):
            self.commit(json.dumps(bad))
            with self.assertRaisesRegex(Refused,str(repo)+r' \(last commit\).*'+words):load(self.root)
        self.commit('{"tasks_per_batch": 3,')
        with self.assertRaisesRegex(Refused,'not valid JSON'):load(self.root)

    def test_runs_use_the_committed_settings_only(self):
        self.commit('{"tasks_per_batch": 7}')
        other=self.root.parent/'other';subprocess.run(['git','clone','-q',str(self.root),str(other)],check=True)
        (other/'oh.json').write_text('{"tasks_per_batch": 42}')
        subprocess.run(['git','-C',str(other),'-c','user.name=x','-c','user.email=x@example.invalid','commit','-qam','other'],check=True)
        with patch.dict(os.environ,{'GIT_DIR':str(other/'.git')}):self.assertEqual(load(self.root)['tasks_per_batch'],7)
        for text in ('{"tasks_per_batch": 100}','{"tasks_per_batch": 7}\r\n','not json'):
            (self.root/'oh.json').write_text(text)
            self.assertEqual(load(self.root)['tasks_per_batch'],7)
        self.assertIn('uncommitted',describe(self.root)['note'])
        (self.root/'oh.json').write_text('{"tasks_per_batch": 7}\r\n')
        self.assertNotIn('note',describe(self.root))

    def test_change_is_the_only_writer_and_never_writes_an_invalid_file(self):
        with self.assertRaisesRegex(Refused,'--location repo'):change(self.root,'tasks_per_batch','15')
        with self.assertRaisesRegex(Refused,'Unknown setting: tasks'):change(self.root,'tasks','15',location='repo')
        self.assertFalse((self.root/'oh.json').exists())
        result=change(self.root,'tasks_per_batch','15',location='repo')
        self.assertEqual((result['from'],result['to']),(5,15));self.assertIn('Commit oh.json',result['note'])
        self.assertEqual(load(self.root)['tasks_per_batch'],5);self.commit();self.assertEqual(load(self.root)['tasks_per_batch'],15)
        change(self.root,'models.claude.review.model','opus')
        written=(self.root/'oh.json').read_text()
        self.assertEqual(list(json.loads(written)),['$schema','tasks_per_batch','models'])
        for key,value in (('review_rounds','101'),('review_rounds','three'),('models.claude.review.effort','ultra')):
            with self.assertRaises(Refused):change(self.root,key,value)
            self.assertEqual((self.root/'oh.json').read_text(),written)
        change(self.root,'models.claude.review.model',None)
        self.assertEqual(json.loads((self.root/'oh.json').read_text()),{'$schema':SCHEMA_URL,'tasks_per_batch':15})
        with self.assertRaisesRegex(Refused,'already live in'):change(self.root,'review_rounds','4',location='private')

    def test_private_settings_stay_out_of_the_repository_and_one_location_wins(self):
        change(self.root,'review_rounds','4',location='private')
        self.assertFalse((self.root/'oh.json').exists());self.assertEqual(load(self.root)['review_rounds'],4)
        self.assertEqual(describe(self.root)['location'],'private')
        (self.root/'oh.json').write_text('{}')
        self.assertEqual(load(self.root)['review_rounds'],4)  # an uncommitted file never decides a run's settings
        with self.assertRaisesRegex(Refused,'both'):change(self.root,'review_rounds','5')
        self.commit()
        with self.assertRaisesRegex(Refused,'both'):load(self.root)


    def test_the_writer_repairs_broken_files_and_skips_no_op_writes(self):
        repo=self.root/'oh.json';self.commit('{"tasks_per_batch": 5.0, "retired": 1}')
        change(self.root,'tasks_per_batch','5');self.commit()
        with self.assertRaisesRegex(Refused,'Unknown setting: retired'):load(self.root)
        change(self.root,'retired',None);self.commit()
        self.assertEqual(load(self.root)['tasks_per_batch'],5)
        written=repo.read_text()
        self.assertTrue(change(self.root,'tasks_per_batch','5')['unchanged']);self.assertTrue(change(self.root,'review_rounds',None)['unchanged'])
        self.assertEqual(repo.read_text(),written)
        with self.assertRaisesRegex(Refused,'unset'):change(self.root,'models.claude.review.model','null')
        self.assertEqual(oct(repo.stat().st_mode&0o777),oct(0o666&~self.umask()))

    def umask(self):
        mask=os.umask(0);os.umask(mask);return mask

    def test_settings_files_must_be_plain_and_exactly_named(self):
        for alias in ('OH.json','oh.j\u017fon'):
            (self.root/alias).write_text('{"tasks_per_batch": 9}')
            self.assertIn('Rename',describe(self.root)['note'])
            with self.assertRaisesRegex(Refused,'Rename'):change(self.root,'review_rounds','4',location='repo')
            self.assertEqual(load(self.root)['tasks_per_batch'],5)
            (self.root/alias).unlink()
        (self.root/'team.json').write_text('{}');(self.root/'oh.json').symlink_to('team.json')
        with self.assertRaisesRegex(Refused,'symlink'):change(self.root,'review_rounds','4')

    def test_importing_a_profile_keeps_a_committed_oh_json_as_the_only_project_settings(self):
        from .profiles import export_profile,import_profile
        self.commit('{"tasks_per_batch": 9}')
        exported=Path(self.root.parent)/'profile.json';export_profile(self.root,exported)
        clone=self.root.parent/'clone';subprocess.run(['git','clone','-q',str(self.root),str(clone)],check=True)
        import_profile(clone,exported)
        self.assertEqual((describe(clone)['location'],load(clone)['tasks_per_batch']),('repo',9))


if __name__=='__main__':unittest.main()
