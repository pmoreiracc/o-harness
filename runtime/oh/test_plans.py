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

    def approve(self,path):path.write_text(path.read_text().replace('status: draft','status: approved'))

    def repo(self,**folders):
        change(self.root,'plans.location','repo')
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
                number,path=plans.write_design(self.root,where,'store','The store',TASKS,'approved')
                self.assertEqual((number,path.name),('0001','0001-store.md'))
                plans.claim(self.root,where,'store',number)
                self.assertEqual(roadmap(self.root,'',where).split('\x1f')[-1].strip(),'0001')
                self.assertEqual(len(plan(self.root,'0001',where).strip('\n').split('\n')),2)
                self.assertEqual(plans.check(self.root,where),{'location':'repo','initiatives':1,'milestones':1,'designs':1})
                self.assertEqual(plans.write_design(self.root,where,'other','Other',TASKS,'approved')[0],'0002')
                with self.assertRaisesRegex(Refused,'0002-other.md is approved but no roadmap row names it'):plans.check(self.root,where)
                with self.assertRaisesRegex(Refused,'already names design doc 0001'):plans.claim(self.root,where,'store','0002')

    def test_design_checks_find_broken_task_lists(self):
        where=self.repo()
        for body,words in ((TASKS.replace('task 2','task 9'),'depends on task 9'),(TASKS.replace('§3','§4'),'not an open-questions section'),
                           (TASKS.replace('*Blocked on §3.*','Depends on task 1.'),'cycle')):
            with self.subTest(words):
                for doc in where['designs'].glob('*.md'):doc.unlink()
                self.approve(plans.write_design(self.root,where,'store','The store',body,'draft')[1])
                with self.assertRaisesRegex(Refused,words):plans.verify_design(self.root,where)

    def test_a_failed_edit_leaves_every_file_exactly_as_it_was(self):
        where=self.repo();plans.start_roadmap(where,'Fixture')
        plans.add_milestone(self.root,where,'M1','Slice','Done')
        where['roadmap'].write_bytes(where['roadmap'].read_bytes().replace(b'\n',b'\r\n'))
        clean=where['roadmap'].read_bytes()
        # A rule already broken (a row naming a missing design) makes every edit fail after writing.
        where['roadmap'].write_bytes(clean+b'| `old` | Old | \xe2\x80\x94 | [0009](./design/0009-old.md) |\r\n')
        before=where['roadmap'].read_bytes()
        for edit in (lambda:plans.add_initiative(self.root,where,'M1','a','A',[]),lambda:plans.add_milestone(self.root,where,'M2','T','D')):
            with self.assertRaisesRegex(Refused,'0009, which does not exist'):edit()
            self.assertEqual(where['roadmap'].read_bytes(),before)
        where['roadmap'].write_bytes(clean)
        plans.add_initiative(self.root,where,'M1','a','A',[])
        self.assertNotIn(b'\n',where['roadmap'].read_bytes().replace(b'\r\n',b''))  # keeps the file's own line endings
        (where['decisions']).mkdir(parents=True);(where['decisions']/'README.md').write_text('# Decisions\n\nNo table here.\n')
        with self.assertRaisesRegex(Refused,'no decision log table'):plans.write_decision(self.root,where,'Pick X','C','A','C')
        self.assertEqual([p.name for p in where['decisions'].iterdir()],['README.md'])
        for bad in ('A\rB','A\u2028B',''):
            with self.assertRaisesRegex(Refused,'one non-empty line'):plans.add_initiative(self.root,where,'M1','b',bad,[])
        with self.assertRaisesRegex(Refused,'four-digit'):plans.claim(self.root,where,'a','00?1')

    def test_new_milestones_join_the_milestones_not_later_sections(self):
        where=self.repo();plans.start_roadmap(where,'Fixture')
        plans.add_milestone(self.root,where,'M1','Slice','Done')
        where['roadmap'].write_text(where['roadmap'].read_text()+'\n## Deliberately deferred\n\n| Idea | Why |\n|---|---|\n| x | later |\n')
        plans.add_milestone(self.root,where,'M2','Next','Also done')
        text=where['roadmap'].read_text()
        self.assertLess(text.index('### M2'),text.index('## Deliberately deferred'))
        where['decisions'].mkdir(parents=True)
        (where['decisions']/'README.md').write_text('# D\n\n## The log\n\n| # | Decision | Date | Status |\n|---|---|---|---|\n'
            '| [0001](./0001-a.md) | A | 2026-01-01 | accepted |\n\n## Superseded\n\n| Old | By |\n|---|---|\n| [0001](./0001-a.md) | x |\n')
        (where['decisions']/'0001-a.md').write_text('x')
        plans.write_decision(self.root,where,'B','C','A','C','Do B.')
        log=(where['decisions']/'README.md').read_text()
        self.assertLess(log.index('[0002]'),log.index('## Superseded'))

    def test_code_blocks_never_receive_new_structure(self):
        where=self.repo();plans.start_roadmap(where,'Fixture')
        text=where['roadmap'].read_text()+'\n## Deliberately deferred\n\n| Idea | Why |\n|---|---|\n'
        where['roadmap'].write_text(text)
        plans.add_milestone(self.root,where,'M1','Slice','Done')  # the first milestone goes before later sections
        self.assertLess(where['roadmap'].read_text().index('### M1'),where['roadmap'].read_text().index('## Deliberately'))
        where['roadmap'].write_text(where['roadmap'].read_text().replace('|---|---|---|---|\n','|---|---|---|---|\n\nExample:\n\n```md\nsome example\n```\n',1))
        plans.add_milestone(self.root,where,'M2','Next','Done');plans.add_initiative(self.root,where,'M1','a','A',[])
        text=where['roadmap'].read_text()
        self.assertLess(text.index('```\n'),text.index('### M2'));self.assertLess(text.index('| `a` |'),text.index('```md'))
        where['decisions'].mkdir(parents=True)
        (where['decisions']/'README.md').write_text('# D\n\nFormat:\n\n```md\n| # | Decision | Date | Status |\n|---|---|---|---|\n| [0000](./x.md) | Example | - | - |\n```\n\n'
            '## The log\n\n| # | Decision | Date | Status |\n|---|---|---|---|\n')
        plans.write_decision(self.root,where,'B','C','A','C','Do B.')
        log=(where['decisions']/'README.md').read_text()
        self.assertGreater(log.index('[0001]'),log.index('## The log'))

    def test_roadmap_code_blocks_that_read_as_structure_are_refused(self):
        where=self.repo();plans.start_roadmap(where,'Fixture');plans.add_milestone(self.root,where,'M1','One','Done')
        clean=where['roadmap'].read_text()
        for example in ('```md\n### M2 — Example\n```\n','```md\n| `search` | Example | — | — |\n```\n','```md\n**Done when:** example\n```\n'):
            with self.subTest(example):
                where['roadmap'].write_text(clean.replace('|---|---|---|---|\n','|---|---|---|---|\n\n'+example,1))
                with self.assertRaisesRegex(Refused,'in a code block'):plans.add_initiative(self.root,where,'M1','a','A',[])
                with self.assertRaisesRegex(Refused,'in a code block'):plans.verify_roadmap(self.root,where)
        # Outside milestones the parser reads only milestone headings and slug rows, so other examples are fine there.
        where['roadmap'].write_text(clean.replace('# Fixture — Roadmap\n','# Fixture — Roadmap\n\n```md\n## 1. Problem\n```\n')
            +'\n## Deliberately deferred\n\n```md\n| Thing | Until |\n```\n')
        plans.add_initiative(self.root,where,'M1','a','A',[])
        self.assertEqual(plans.verify_roadmap(self.root,where),{'initiatives':1,'milestones':1})

    def test_the_checks_read_milestones_exactly_as_the_parser_does(self):
        where=self.repo()
        with self.assertRaisesRegex(Refused,'Start the roadmap first'):plans.add_initiative(self.root,where,'M1','a','A',[])
        plans.start_roadmap(where,'Fixture');plans.add_milestone(self.root,where,'M1','One','Done')
        plans.add_initiative(self.root,where,'M1','a','A',[])
        text=where['roadmap'].read_text().replace('| `a` | A | — |','| `a` | A | `M2` |')
        where['roadmap'].write_text(text+'\n### M2\u00a0— Two\n\n**Done when:** x\n\n| Slug | Initiative | Depends | Design |\n|---|---|---|---|\n')
        with self.assertRaisesRegex(Refused,'neither a slug nor a milestone'):plans.verify_roadmap(self.root,where)

    def test_windows_line_endings_are_read_exactly_as_the_parser_reads_them(self):
        where=self.repo();plans.start_roadmap(where,'Fixture');plans.add_milestone(self.root,where,'M1','One','Done')
        text=where['roadmap'].read_text().replace('**Done when:** Done','##\n**Done when:** Done')
        where['roadmap'].write_bytes(text.replace('\n','\r\n').encode())
        with self.assertRaisesRegex(Refused,'M1 has no "Done when:"'):plans.verify_roadmap(self.root,where)
        path=plans.write_design(self.root,where,'x','X',TASKS,'draft')[1]
        path.write_text(path.read_text().replace('status: draft','status:\u00a0approved'))
        with self.assertRaisesRegex(Refused,'has status'):plans.verify_design(self.root,where,orphans=False)

    def test_design_numbers_stay_four_digits(self):
        where=self.repo();where['designs'].mkdir(parents=True);(where['designs']/'9999-last.md').write_text('x')
        with self.assertRaisesRegex(Refused,'every four-digit number'):plans.write_design(self.root,where,'next','Next','x','draft')

    def test_a_draft_is_written_while_the_roadmap_is_still_empty(self):
        where=self.repo();plans.start_roadmap(where,'Fixture')
        (where['designs']).mkdir(parents=True);(where['designs']/'template.md').write_text('x')
        self.assertEqual(plans.write_design(self.root,where,'idea','Idea','Later.','draft')[0],'0001')

    def test_the_first_milestone_never_enters_the_frontmatter(self):
        where=self.repo();where['roadmap'].parent.mkdir(parents=True)
        for front in ('---\ntype: plan\n---\n## Intro\n','---\n---\n\n## Intro\n'):
            where['roadmap'].write_text(front)
            plans.add_milestone(self.root,where,'M1','One','Done')
            self.assertTrue(where['roadmap'].read_text().startswith(front.split('## Intro')[0].rstrip('\n')))

    def test_quoted_fences_and_windows_line_endings_are_read_correctly(self):
        where=self.repo()
        nested=TASKS.replace('## 3. Open — the storage choice','````md\n```md\n## 3. Open — example\n```\n````\n\n## 3. Scope')
        path=plans.write_design(self.root,where,'store','Store',TASKS,'approved')[1]
        path.write_bytes(path.read_bytes().replace(b'\n',b'\r\n'))
        self.assertEqual(plans.verify_design(self.root,where,orphans=False),{'designs':1})
        path.write_text(path.read_text().replace('## 3. Open — the storage choice',nested.split('## 4.')[0].strip()))
        with self.assertRaisesRegex(Refused,'not an open-questions section'):plans.verify_design(self.root,where,orphans=False)

    def test_a_new_design_that_breaks_the_task_rules_is_never_written(self):
        where=self.repo()
        for body in (TASKS.replace('task 2','task 9'),TASKS.replace('Build the index','Build\x1fthe index')):
            with self.assertRaises(Refused):plans.write_design(self.root,where,'store','Store',body,'approved')
        self.assertEqual(list(where['designs'].glob('*.md')),[])

    def test_roadmap_checks_match_geoffreys_on_duplicates_and_milestone_cycles(self):
        where=self.repo();plans.start_roadmap(where,'Fixture')
        plans.add_milestone(self.root,where,'M1','One','Done');plans.add_milestone(self.root,where,'M2','Two','Done')
        plans.add_initiative(self.root,where,'M1','alpha','A',[]);plans.add_initiative(self.root,where,'M2','beta','B',['alpha'])
        text=where['roadmap'].read_text()
        where['roadmap'].write_text(text.replace('| `alpha` | A | — |','| `alpha` | A | `M2` |'))
        with self.assertRaisesRegex(Refused,'cycle'):plans.verify_roadmap(self.root,where)
        where['roadmap'].write_text(text.replace('| `beta` | B |','| `alpha` | B |'))
        with self.assertRaisesRegex(Refused,'duplicate slug alpha'):plans.verify_roadmap(self.root,where)

    def test_drafts_and_abandoned_designs_are_allowed_loose_ends(self):
        where=self.repo()
        plans.write_design(self.root,where,'idea','An idea','No tasks yet.','draft')
        path=plans.write_design(self.root,where,'old','Old','No tasks.','draft')[1]
        path.write_text(path.read_text().replace('status: draft','status: abandoned'))
        self.assertEqual(plans.verify_design(self.root,where),{'designs':2})
        fenced=TASKS.replace('## 3. Open — the storage choice','```md\n## 3. Open — example\n```\n\n## 3. Scope')
        self.approve(plans.write_design(self.root,where,'store','Store',fenced,'draft')[1])
        with self.assertRaisesRegex(Refused,'not an open-questions section'):plans.verify_design(self.root,where)

    def test_plans_settings_stay_inside_their_location(self):
        for key,value in (('designs','../x'),('designs','a/..'),('designs','/abs'),('roadmap','docs/roadmap'),('decisions','x\n')):
            with self.assertRaises(Refused):change(self.root,'plans.'+key,value)
        change(self.root,'plans.location','repo');change(self.root,'plans.decisions','docs/design/adr')
        with self.assertRaisesRegex(Refused,'overlap'):plans.layout(self.root)

    def test_geoffreys_document_profile_keeps_plans_in_the_repository(self):
        from .registry import profile_path
        from .storage import atomic_json, read_json
        path=profile_path(self.root);value=read_json(path)|{'design_profile':'consumer-v1'}
        path.unlink();atomic_json(path,value)
        self.assertEqual(plans.layout(self.root)['designs'],self.root/'docs/design')
        change(self.root,'plans.location','private')
        with self.assertRaisesRegex(Refused,'document profile'):plans.layout(self.root)

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
