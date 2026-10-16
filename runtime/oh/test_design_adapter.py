import json
import unittest
from pathlib import Path
from . import test_workflow as fixtures
from .registry import profile_path
from .storage import atomic_json, read_json, Refused
from .design_adapter import manifest
from .workflow import load_run


class DesignAdapterTest(fixtures.NativeFixture,unittest.TestCase):
    git=fixtures.WorkflowTest.git
    event=fixtures.WorkflowTest.event
    fake=fixtures.WorkflowTest.fake

    def setUp(self):
        fixtures.NativeFixture.setUp(self)
        path=profile_path(self.root)
        atomic_json(path,read_json(path)|{'design_profile':'consumer-v1'})
        fixtures.configure(self.root,tasks_per_batch=1)
        directory=self.root/'docs/design';directory.mkdir(parents=True)
        self.design=directory/'0900-fixture.md'
        self.design.write_text('---\ntype: design\nstatus: approved\nlast-verified: 2026-09-25\n---\n# Fixture\n## Tasks\n### Code track\n- [ ] **1.** Implement first behavior.\n- [ ] **2.** Implement second behavior. *Depends on task 1.*\n',newline='\n')
        (self.root/'docs/roadmap.md').write_text('### M1 — Fixture\n\n| Slug | Initiative | Depends | Design |\n|---|---|---|---|\n| `fixture` | Fixture | — | [0900](./design/0900-fixture.md) |\n',newline='\n')
        self.git('add','.');self.git('commit','-qm','approved design')
        self.git('update-ref','refs/remotes/origin/main','HEAD')

    def test_candidate_contains_provisional_progress_and_commits_the_exact_final_document(self):
        from . import native
        prepared=native.prepare_scope(self.root,doc='0900')
        native.approve_scope(self.root,prepared['scope_id'],self.human())
        origin=self.git('rev-parse','HEAD');self.assess();self.implement()
        native.candidate(self.root)
        first=self.design.read_text()
        self.assertIn('- [x] **1.**',first);self.assertIn('- [ ] **2.**',first)
        self.assertEqual(load_run(self.root)[1]['done'],[])
        native.verify(self.root)
        finding={'severity':'scope','description':'Logout cleanup belongs to a later task.','family':'logout','path':'logout.py'}
        review=self.finish_attempt('review',{'verdict':'concern','summary':'Retain later work in the mutable design.','findings':[finding]})
        before=load_run(self.root)[1]
        native.decision(self.root,'route-scope',self.human('route scope'),attempt=review['id'])
        routed=self.design.read_text()
        self.assertIn('## Open review scope',routed)
        self.assertIn('> '+finding['description'],routed)
        self.assertIn('> Evidence: logout.py',routed)
        state=load_run(self.root)[1]
        self.assertEqual(state['granted'],before['granted'])
        self.assertEqual(state['scope_records'][review['id']]['findings'],[finding])
        self.assertEqual(state['scope_records'][review['id']]['destination']['design'],str(self.design))
        with self.assertRaises(fixtures.Refused):native.complete(self.root,review['id'])
        native.candidate(self.root);native.verify(self.root)
        review=self.finish_attempt('review',{'verdict':'clean','summary':'Checked the routed exact candidate.','findings':[]})
        self.assertEqual(len(load_run(self.root)[1].get('review_grants',[])),len(before.get('review_grants',[])))
        first=self.design.read_text()
        native.complete(self.root,review['id'])
        self.assertEqual(self.git('show','HEAD:docs/design/0900-fixture.md'),first.strip())
        native.decision(self.root,'continue',self.human('continue'))
        self.assess();self.implement(edit=lambda:(self.root/'output.txt').write_text('Second behavior.',newline='\n'))
        roadmap=self.root/'docs/roadmap.md'
        roadmap.write_text(roadmap.read_text()+'\nThe sign-in flow is now implemented and verified.\n',newline='\n')
        candidate=native.candidate(self.root)
        final=self.design.read_text()
        self.assertIn('status: frozen',final);self.assertIn('delivered: M1',final)
        self.assertEqual(load_run(self.root)[1]['done'],['1'])
        native.verify(self.root)
        admitted=native.admit(self.root,'review')
        packet=read_json(admitted['task_context']['path'])
        self.assertEqual(read_json(packet['scope_snapshot']['path'])['base'],origin)
        self.assertEqual([task['id'] for task in packet['completed_tasks']],['1'])
        native.bind(self.root,admitted['id'],{})
        self.native_results[admitted['id']]={'text':json.dumps({'verdict':'clean','findings':[],'summary':'Clean. No findings.'}),'status':'completed'}
        native.retain(self.root,admitted['id'],{})
        native.complete(self.root,admitted['id'])
        self.assertEqual(self.git('show','HEAD:docs/design/0900-fixture.md'),final.strip())
        self.assertEqual(self.git('rev-parse','HEAD^{tree}'),candidate['git_tree'])
        self.assertEqual(load_run(self.root)[1]['done'],['1','2'])

    def test_living_prose_is_allowed_but_approved_tasks_and_unearned_progress_are_not(self):
        from . import native
        prepared=native.prepare_scope(self.root,doc='0900')
        native.approve_scope(self.root,prepared['scope_id'],self.human())
        self.assess();self.implement();original=self.design.read_text()
        for changed in (original.replace('Implement first behavior.','Expand the approved scope.'),
                        original.replace('- [ ] **2.**','- [x] **2.**')):
            self.design.write_text(changed,newline='\n')
            with self.assertRaises(Refused):native.candidate(self.root)
            self.design.write_text(original,newline='\n')
        self.design.write_text(original+'\n## Delivery notes\n\nThe task also updates the required roadmap status prose.\n',newline='\n')
        candidate=native.candidate(self.root)
        self.assertEqual(candidate['task'],'1')
        self.assertIn('required roadmap status prose',self.design.read_text())

    def test_unapproved_or_blocked_design_cannot_become_native_task_scope(self):
        from . import native
        from .workflow import active_file
        with self.assertRaises(Refused):
            native.prepare_scope(self.root,doc='0900',human=self.human('/oh-review changes'))
        self.assertFalse(active_file(self.root).exists())
        admitted=native.prepare_scope(self.root,doc='0900',human=self.human('/oh-deliver 0900'))
        self.assertEqual(admitted['granted'],['1'])
        # docs/usage.md: a local approved label cannot replace the merged origin base.
        self.git('update-ref','-d','refs/remotes/origin/main')
        with self.assertRaisesRegex(Refused,'Fetch origin/main'):manifest(self.root,'0900')
        self.git('update-ref','refs/remotes/origin/main','HEAD')
        approved=self.design.read_bytes()
        self.design.write_bytes(approved.replace(b'\n',b'\r\n'))
        self.assertEqual(len(manifest(self.root,'0900')['tasks']),2)
        self.design.write_bytes(self.design.read_bytes().replace(b'Implement first behavior.',b'Unapproved behavior.'))
        with self.assertRaisesRegex(Refused,'approved .* revision'):manifest(self.root,'0900')
        self.design.write_bytes(approved)
        self.design.write_text(self.design.read_text().replace('status: approved','status: draft'),newline='\n')
        self.git('add','.');self.git('commit','-qm','draft');self.git('update-ref','refs/remotes/origin/main','HEAD')
        with self.assertRaises(Refused):manifest(self.root,'0900')
        self.design.write_text(self.design.read_text().replace('status: draft','status: approved').replace('Implement first behavior.','Implement first behavior. *Blocked on upstream.*'),newline='\n')
        self.git('add','.');self.git('commit','-qm','blocked');self.git('update-ref','refs/remotes/origin/main','HEAD')
        with self.assertRaises(Refused):manifest(self.root,'0900')
