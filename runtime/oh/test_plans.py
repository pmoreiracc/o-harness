import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from . import plans
from .config import change
from .design_parse import plan, roadmap
from .registry import register
from .storage import Refused

TASKS='''## 3. Open — the storage choice

## 4. Tasks

### Core track

- [ ] **1.** Build the store. Depends on task 2.
- [ ] **2.** Build the index. *Blocked on §3.*
'''


class PlansTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)/'project';self.root.mkdir()
        env=patch.dict(os.environ,{'OH_DATA_HOME':str(Path(temp.name)/'state')});env.start();self.addCleanup(env.stop)
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        register(self.root,'Fixture')

    def repo(self,**folders):
        change(self.root,'plans.location','repo',location='private')
        for key,value in folders.items():change(self.root,'plans.'+key,value)
        return plans.layout(self.root)

    def test_plans_live_where_the_project_chose(self):
        with self.assertRaisesRegex(Refused,'Choose where plans live'):plans.layout(self.root)
        self.assertEqual(self.repo()['designs'],self.root/'docs/design')
        change(self.root,'plans.location','private')
        where=plans.layout(self.root)
        self.assertEqual(where['location'],'private');self.assertFalse(where['base'].is_relative_to(self.root))

    def test_roadmap_rows_are_written_by_code_and_follow_the_rules(self):
        where=self.repo()
        plans.start_roadmap(where,'Fixture')
        plans.add_milestone(self.root,where,'M1','First slice','A user can sign in')
        plans.add_milestone(self.root,where,'M2','Second slice','Reports exist')
        plans.add_initiative(self.root,where,'M1','auth','Sign-in with passkeys',[])
        plans.add_initiative(self.root,where,'M1','ledger','Accounts and entries',['auth'])
        plans.add_initiative(self.root,where,'M2','reports','Monthly reports',['ledger','M1'])
        self.assertEqual([r.split('\x1f')[:3] for r in roadmap(self.root,'',where).strip('\n').split('\n')],
                         [['auth','M1',''],['ledger','M1','auth'],['reports','M2','ledger,M1']])
        before=where['roadmap'].read_text()
        for args,words in ((('M1','auth','Again',[]),None),(('M2','auth','Moved',[]),'already exists'),
                           (('M1','x','A | B',[]),'pipe'),(('M1','bad slug','T',[]),'kebab'),
                           (('M3','x','T',[]),'no milestone M3'),(('M1','x','T',['nothing']),'neither a slug')):
            if words:
                with self.assertRaisesRegex(Refused,words):plans.add_initiative(self.root,where,*args)
            else:self.assertTrue(plans.add_initiative(self.root,where,*args)['unchanged'])
        self.assertEqual(where['roadmap'].read_text(),before)
        with self.assertRaisesRegex(Refused,'already has M1'):plans.add_milestone(self.root,where,'M1','Again','x')

    def test_design_docs_are_numbered_claimed_and_checked(self):
        for folders in ({},{'roadmap':'planning/roadmap.md','designs':'planning/designs'}):
            with self.subTest(folders or 'default'):
                self.setUp();where=self.repo(**folders)
                plans.start_roadmap(where,'Fixture');plans.add_milestone(self.root,where,'M1','Slice','Done')
                plans.add_initiative(self.root,where,'M1','store','The store',[])
                number,path=plans.write_design(self.root,where,'store','The store',TASKS)
                self.assertEqual((number,path.name),('0001','0001-store.md'))
                plans.claim(self.root,where,'store',number)
                self.assertEqual(roadmap(self.root,'',where).split('\x1f')[-1].strip(),'0001')
                self.assertEqual(len(plan(self.root,'0001',where).strip('\n').split('\n')),2)
                self.assertEqual(plans.check(self.root,where),{'location':'repo','initiatives':1,'milestones':1,'designs':1})
                self.assertEqual(plans.write_design(self.root,where,'other','Other',TASKS)[0],'0002')
                with self.assertRaisesRegex(Refused,'0002-other.md is approved but no roadmap row names it'):plans.check(self.root,where)
                with self.assertRaisesRegex(Refused,'already names design doc 0001'):plans.claim(self.root,where,'store','0002')

    def test_design_checks_find_broken_task_lists(self):
        where=self.repo()
        for body,words in ((TASKS.replace('task 2','task 9'),'depends on task 9'),(TASKS.replace('§3','§4'),'not an open-questions section'),
                           (TASKS.replace('*Blocked on §3.*','Depends on task 1.'),'cycle')):
            with self.subTest(words):
                for doc in where['designs'].glob('*.md'):doc.unlink()
                plans.write_design(self.root,where,'store','The store',body)
                with self.assertRaisesRegex(Refused,words):plans.verify_design(self.root,where)

    def test_roadmap_checks_find_missing_bars_and_cycles(self):
        where=self.repo();plans.start_roadmap(where,'Fixture')
        plans.add_milestone(self.root,where,'M1','Slice','Done')
        plans.add_initiative(self.root,where,'M1','a','A',[]);plans.add_initiative(self.root,where,'M1','b','B',['a'])
        text=where['roadmap'].read_text()
        where['roadmap'].write_text(text.replace('| `a` | A | — |','| `a` | A | `b` |'))
        with self.assertRaisesRegex(Refused,'cycle'):plans.verify_roadmap(self.root,where)
        where['roadmap'].write_text(text.replace('**Done when:** Done\n',''))
        with self.assertRaisesRegex(Refused,'no "Done when:"'):plans.verify_roadmap(self.root,where)

    def test_decisions_are_numbered_logged_and_proposed_without_a_decision(self):
        where=self.repo()
        number,path=plans.write_decision(self.root,where,'Queue: pg-boss or Redis','Context.','- Redis: another service.','Consequences.')
        self.assertEqual(number,'0001');self.assertIn('status: proposed',path.read_text());self.assertIn('Not decided yet',path.read_text())
        number,path=plans.write_decision(self.root,where,'Money as integers','C.','- Floats: rounding.','C.','Use integer minor units.')
        self.assertEqual(number,'0002');self.assertIn('status: accepted',path.read_text())
        log=(where['decisions']/'README.md').read_text()
        self.assertIn('| [0001](./0001-queue-pg-boss-or-redis.md) | Queue: pg-boss or Redis |',log)
        self.assertLess(log.index('[0001]'),log.index('[0002]'))


if __name__=='__main__':unittest.main()
