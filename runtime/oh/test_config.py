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
        register(self.root,'Fixture')

    def test_published_schema_matches_the_settings_oh_validates(self):
        self.assertEqual(json.loads((HOME/'config/oh.schema.json').read_text()),schema())

    def test_repository_settings_apply_and_errors_name_the_file_and_setting(self):
        repo=self.root/'oh.json'
        repo.write_text(json.dumps({'$schema':SCHEMA_URL,'tasks_per_batch':12,'models':{'claude':{'review':{'effort':'max'}}}}))
        atomic_json(profile_path(self.root,'config.local.json'),{'review_rounds':7})
        config=load(self.root)
        self.assertEqual((config['tasks_per_batch'],config['review_rounds'],config['models']['claude']['review']['effort']),(12,7,'max'))
        listed={item['key']:item for item in describe(self.root)['settings']}
        self.assertEqual((listed['tasks_per_batch']['source'],listed['review_rounds']['source'],listed['max_escalations']['source']),('project','personal','default'))
        for bad,words in (({'tasks_per_batch':0},'tasks_per_batch must be whole number from 1 to 100'),({'taskz':1},'Unknown setting: taskz'),
                          ({'models':{'codex':{'review':{'effort':'huge'}}}},'models.codex.review.effort must be one of')):
            repo.write_text(json.dumps(bad))
            with self.assertRaisesRegex(Refused,str(repo)+'.*'+words):load(self.root)
        repo.write_text('{"tasks_per_batch": 3,')
        with self.assertRaisesRegex(Refused,'not valid JSON'):load(self.root)

    def test_change_is_the_only_writer_and_never_writes_an_invalid_file(self):
        with self.assertRaisesRegex(Refused,'--location repo'):change(self.root,'tasks_per_batch','15')
        with self.assertRaisesRegex(Refused,'Unknown setting: tasks'):change(self.root,'tasks','15',location='repo')
        self.assertFalse((self.root/'oh.json').exists())
        result=change(self.root,'tasks_per_batch','15',location='repo')
        self.assertEqual((result['from'],result['to']),(5,15));self.assertIn('Commit oh.json',result['note'])
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
        with self.assertRaisesRegex(Refused,'both'):load(self.root)


if __name__=='__main__':unittest.main()
