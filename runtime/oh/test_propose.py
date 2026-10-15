import unittest
from unittest.mock import patch
from . import plans
from . import test_workflow as fixtures
from .config import change
from .hosts import PROPOSAL_SCHEMA
from .storage import Refused
from .workflow import load_run

DESIGN = '''---
type: design
status: approved
last-verified: 2026-09-27
---

# 0001 — Sign-in

## 1. Tasks

### Core track

- [ ] **1.** Add the credential store.
- [ ] **2.** Add the sign-in endpoint. Depends on task 1.
'''


def idea(route='roadmap', **values):
    value = {key: '' for key in PROPOSAL_SCHEMA['required']} | {'depends': []}
    value |= {'route': route, 'understanding': 'Search across notes.', 'reason': 'New area with several PRs.',
              'evidence': 'Read docs/roadmap.md.', 'text': 'Full-text search over notes', 'summary': 'A new search row in M1.'}
    if route == 'roadmap':value |= {'slug': 'search', 'milestone': 'M1'}
    if route == 'task':value |= {'design': '0001', 'track': 'Core', 'text': 'Rate-limit sign-in attempts. Read §1.', 'depends': ['2']}
    return value | values


class ProposeTest(unittest.TestCase):
    setUp_workflow = fixtures.WorkflowTest.setUp
    git = fixtures.WorkflowTest.git
    event = fixtures.WorkflowTest.event

    def setUp(self):
        self.setUp_workflow()
        self.git('switch', '-q', 'main')
        change(self.root, 'plans.location', 'repo')
        self.where = plans.layout(self.root)
        plans.start_roadmap(self.where, 'Fixture')
        plans.add_milestone(self.root, self.where, 'M1', 'First slice', 'A person can sign in')
        plans.add_initiative(self.root, self.where, 'M1', 'auth', 'Sign-in with passkeys', [])
        self.where['designs'].mkdir(parents=True);(self.where['designs'] / '0001-auth.md').write_text(DESIGN)
        plans.claim(self.root, self.where, 'auth', '0001')
        self.git('add', '.');self.git('commit', '-qm', 'plans')
        self.calls, self.turn = [], 10

    def test_task_prose_cannot_inject_dependencies_or_blocked_state(self):
        for text in ('Add rate limiting. Depends on task 1.','Add rate limiting. Blocked on §4.'):
            with self.assertRaisesRegex(Refused,'Task prose cannot contain'):
                plans.add_task(self.root,self.where,'0001','Core',text,[])
        self.assertEqual(self.git('status','--porcelain'),'')

    @unittest.skipIf(__import__('os').name=='nt','Symlink creation requires Windows privileges')

    def test_proposal_output_symlinks_are_refused_before_branch_or_write(self):
        from pathlib import Path
        cases=[(self.where['designs']/'0001-auth.md',idea('task')),
               (self.where['decisions']/'README.md',idea(decision_title='Which index?',
                decision_context='Context',decision_alternatives='Alternatives',decision_consequences='Effects'))]
        for path,value in cases:
            with self.subTest(path=path):
                target=Path(self.temp.name)/'external.md'
                target.write_bytes(path.read_bytes() if path.exists() else b'Human log\n')
                target.chmod(0o600);before=target.read_bytes();mode=target.stat().st_mode & 0o777
                path.parent.mkdir(parents=True,exist_ok=True);path.unlink(missing_ok=True);path.symlink_to(target)
                self.git('add','.');self.git('commit','-qm','linked output')
                with self.assertRaisesRegex(Refused,'ordinary file'):
                    plans.render_proposal(self.root,value,lambda intent:self.fail('must not record intent'),
                                          lambda topic:self.fail('must not create a branch'))
                if value['route']=='task':
                    with self.assertRaisesRegex(Refused,'ordinary file'):
                        plans.add_task(self.root,self.where,'0001','Core','Add a task',[])
                self.assertTrue(path.is_symlink());self.assertEqual(target.read_bytes(),before)
                self.assertEqual(target.stat().st_mode & 0o777,mode)
                self.assertEqual(self.git('status','--porcelain'),'')
                path.unlink();path.write_bytes(before)
                self.git('add','.');self.git('commit','-qm','restore ordinary output')

    def test_answers_carry_prose_and_a_route_only(self):
        for value, words in ((idea(route='essay'), 'route must be'), (idea(slug='Search'), 'kebab-case'),
                             (idea(summary='S' * 1001), 'longer than 1000'), (idea(decision_title='A | B'), 'cannot contain'),
                             (idea(decision_title='Contested?'), 'needs its decision title, context'),
                             (idea('task', depends=['two']), 'task numbers')):
            with self.subTest(words):
                with self.assertRaisesRegex(Refused, words):plans.proposal(value)

    def test_contested_proposal_keeps_decision_sections_owned_by_oh(self):
        value=idea(decision_title='Which index?',decision_context='Context',decision_alternatives='Alternatives',decision_consequences='Consequences')
        for key in ('decision_context','decision_alternatives','decision_consequences','summary'):
            with self.subTest(key=key):
                with self.assertRaisesRegex(Refused,'structural headings'):plans.proposal(value|{key:'## Decision\nUse mine'})
        with self.assertRaisesRegex(Refused,'recommendation'):plans.proposal(value|{'summary':''})


if __name__ == '__main__':
    unittest.main()
