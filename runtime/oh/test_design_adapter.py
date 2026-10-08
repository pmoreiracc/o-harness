import unittest
from . import test_workflow as fixtures
from .registry import profile_path
from .storage import atomic_json, read_json, Refused
from .design_adapter import manifest
from .workflow import start, choose, load_run
from .runner import run


class DesignAdapterTest(unittest.TestCase):
    git=fixtures.WorkflowTest.git
    event=fixtures.WorkflowTest.event
    fake=fixtures.WorkflowTest.fake

    def setUp(self):
        fixtures.WorkflowTest.setUp(self)
        path=profile_path(self.root)
        atomic_json(path,read_json(path)|{'design_profile':'consumer-v1'})
        fixtures.configure(self.root,tasks_per_batch=1)
        directory=self.root/'docs/design';directory.mkdir(parents=True)
        self.design=directory/'0900-fixture.md'
        self.design.write_text('---\ntype: design\nstatus: approved\nlast-verified: 2026-09-25\n---\n# Fixture\n## Tasks\n### Code track\n- [ ] **1.** Implement first behavior.\n- [ ] **2.** Implement second behavior. *Depends on task 1.*\n',newline='\n')
        (self.root/'docs/roadmap.md').write_text('### M1 — Fixture\n\n| Slug | Initiative | Depends | Design |\n|---|---|---|---|\n| `fixture` | Fixture | — | [0900](./design/0900-fixture.md) |\n',newline='\n')
        self.git('add','.');self.git('commit','-qm','approved design')
        self.git('update-ref','refs/remotes/origin/main','HEAD')

    def test_design_uses_same_batch_and_reviews_actual_final_document_before_commit(self):
        data=manifest(self.root,'0900')
        start(self.root,data,self.event())
        observed=[]
        def review_final(*args,**kwargs):
            if args[4]=='review':observed.append(self.design.read_text())
            return self.fake(*args,**kwargs)
        self.assertEqual(run(self.root,review_final)['status'],'checkpoint')
        self.assertIn('- [x] **1.**',observed[0])
        self.assertIn('- [ ] **2.**',observed[0])
        self.assertIn('status: approved',observed[0])
        choose(self.root,'continue',self.event('2','continue'))
        self.assertEqual(run(self.root,review_final)['status'],'completed')
        self.assertIn('status: frozen',observed[1])
        self.assertIn('delivered: M1',observed[1])
        self.assertEqual(self.git('show','HEAD:docs/design/0900-fixture.md'),observed[1].strip())
        self.assertEqual([x[0] for x in self.calls],['implementation','review','implementation','review'])

    def test_unapproved_or_blocked_design_cannot_become_native_task_scope(self):
        # docs/usage.md: a local approved label cannot replace the merged origin base.
        self.git('update-ref','-d','refs/remotes/origin/main')
        with self.assertRaisesRegex(Refused,'Fetch origin/main'):manifest(self.root,'0900')
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        self.design.write_text(self.design.read_text().replace('status: approved','status: draft'),newline='\n')
        self.git('add','.');self.git('commit','-qm','draft');self.git('update-ref','refs/remotes/origin/main','HEAD')
        with self.assertRaises(Refused):manifest(self.root,'0900')
        self.design.write_text(self.design.read_text().replace('status: draft','status: approved').replace('Implement first behavior.','Implement first behavior. *Blocked on upstream.*'),newline='\n')
        self.git('add','.');self.git('commit','-qm','blocked');self.git('update-ref','refs/remotes/origin/main','HEAD')
        with self.assertRaises(Refused):manifest(self.root,'0900')
