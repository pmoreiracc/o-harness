import unittest
from unittest.mock import patch
from . import plans
from . import test_workflow as fixtures
from .cli import host_hook
from .config import change
from .hosts import PROPOSAL_SCHEMA
from .runner import run
from .storage import Refused
from .workflow import choose, load_run

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

    def say(self, prompt):
        self.turn += 1
        return choose(self.root, prompt, self.event(str(self.turn), prompt))

    def worker(self, answers, reviews=None):
        answers, reviews = list(answers), list(reviews or [])
        def invoke(host, root, profile, prompt, role, directory, context, **kwargs):
            self.calls.append((role, prompt, kwargs.get('schema')))
            if role == 'analysis':
                return {'failed': False, 'returncode': 0, 'duration_ms': 1, 'text': 'answer', 'structured': answers.pop(0), 'usage_observed': False}
            verdict = reviews.pop(0) if reviews else 'clean'
            findings = [] if verdict == 'clean' else [{'severity': 'blocking', 'description': 'Duplicates auth', 'path': 'docs/roadmap.md',
                                                      'family': 'route', 'relation': 'original'}]
            return {'failed': False, 'returncode': 0, 'duration_ms': 1, 'text': 'review',
                    'structured': {'verdict': verdict, 'summary': 'Reviewed', 'findings': findings, 'evidence': fixtures.EVIDENCE}, 'usage_observed': False}
        return invoke

    def propose(self, text='Search my notes'):
        return host_hook(self.root, 'codex', {'prompt': f'/oh-propose {text}'}, verified=self.event('1', f'/oh-propose {text}'))

    def test_a_row_is_written_reviewed_and_waits_for_approval_before_its_commit(self):
        self.propose()
        self.assertEqual(self.git('branch', '--show-current'), 'main')  # nothing is written yet
        result = run(self.root, self.worker([idea()]))
        self.assertEqual(result['status'], 'approval_checkpoint')
        self.assertEqual(self.git('branch', '--show-current'), 'propose/search')
        self.assertEqual(result['proposal']['lines'], ['| `search` | Full-text search over notes | — | — |'])
        self.assertEqual(result['proposal']['choices'], ['approve', 'refine: <what to change>', 'reconsider'])
        self.assertEqual([c[0] for c in self.calls], ['analysis', 'review'])
        self.assertIn('Routing an idea', self.calls[0][1]);self.assertEqual(self.calls[0][2], PROPOSAL_SCHEMA)
        self.assertIn('The subject is a proposal', self.calls[1][1]);self.assertIn('Search across notes.', self.calls[1][1])
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'main'))  # not committed before approval
        self.say('approve')
        self.assertEqual(run(self.root, self.worker([]))['status'], 'completed')
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'propose: | `search` | Full-text search over notes | — | — |')
        self.assertEqual(self.git('diff', '--name-only', 'main', 'HEAD'), 'docs/roadmap.md')
        self.say('pr')
        self.assertEqual(load_run(self.root)[1]['status'], 'pr')

    def test_a_new_milestone_and_a_contested_choice_are_written_too(self):
        self.propose()
        answer = idea(milestone='M2', milestone_title='Find things', milestone_done_when='A person finds any note in a second',
                      decision_title='One search index or one per space?', decision_context='Spaces are separate.',
                      decision_alternatives='One index: simple. Per space: isolated.', decision_consequences='The store follows.',
                      summary='Recommend one index per space.')
        result = run(self.root, self.worker([answer]))
        self.assertEqual(result['proposal']['lines'][0], '### M2 — Find things')
        self.assertIn('Decision record 0001 (proposed)', result['proposal']['lines'][-1])
        record = (self.where['decisions'] / '0001-one-search-index-or-one-per-space.md').read_text()
        self.assertIn('status: proposed', record);self.assertIn('## Recommendation\n\nRecommend one index per space.', record)

    def test_a_task_joins_an_approved_design(self):
        self.propose('Rate-limit sign-in')
        result = run(self.root, self.worker([idea('task')]))
        self.assertEqual(result['proposal']['lines'], ['- [ ] **3.** Rate-limit sign-in attempts. Read §1. Depends on task 2.'])
        self.assertEqual(self.git('branch', '--show-current'), 'propose/design-0001')
        self.say('approve');run(self.root, self.worker([]))
        doc = (self.where['designs'] / '0001-auth.md').read_text()
        self.assertLess(doc.index('**2.**'), doc.index('**3.**'))

    def test_a_design_that_is_not_approved_sends_the_task_back(self):
        path = self.where['designs'] / '0001-auth.md'
        path.write_text(DESIGN.replace('status: approved', 'status: frozen\ndelivered: M1'));self.git('commit', '-qam', 'freeze')
        with self.assertRaisesRegex(Refused, 'only an approved design takes new tasks; a frozen design has shipped'):
            plans.add_task(self.root, self.where, '0001', 'Core', 'More', [])
        self.propose('Rate-limit sign-in')
        result = run(self.root, self.worker([idea('task'), idea()]))
        self.assertIn('frozen design has shipped', [c[1] for c in self.calls if c[0] == 'analysis'][1])
        self.assertEqual(result['proposal']['route'], 'roadmap')

    def test_an_improvement_writes_nothing_and_needs_no_commit(self):
        self.propose('Make the sign-in button bigger')
        result = run(self.root, self.worker([idea('improvement', text='Make the sign-in button 48px tall')]))
        self.assertEqual((result['status'], result['proposal']['lines']), ('approval_checkpoint', []))
        self.assertEqual([c[0] for c in self.calls], ['analysis'])
        self.assertEqual(self.git('branch', '--show-current'), 'main')
        self.say('approve')
        self.assertEqual(run(self.root, self.worker([]))['status'], 'completed')
        with self.assertRaisesRegex(Refused, 'nothing to publish'):self.say('pr')

    def test_refine_asks_again_with_the_person_s_words(self):
        self.propose()
        run(self.root, self.worker([idea()]))
        with self.assertRaisesRegex(Refused, 'Say what to change'):self.say('refine:  ')
        self.say('refine: put it in a new milestone M2 called Find things')
        result = run(self.root, self.worker([idea(milestone='M2', milestone_title='Find things', milestone_done_when='Found')]))
        prompts = [c[1] for c in self.calls if c[0] == 'analysis']
        self.assertIn('put it in a new milestone M2 called Find things', prompts[1])
        self.assertEqual(result['proposal']['lines'][0], '### M2 — Find things')
        self.assertEqual(self.where['roadmap'].read_text().count('`search`'), 1)

    def test_reconsider_writes_nothing_and_leaves_no_branch(self):
        self.propose()
        run(self.root, self.worker([idea()]))
        self.say('reconsider')
        self.assertEqual(load_run(self.root)[1]['status'], 'stopped')
        self.assertEqual((self.git('branch', '--show-current'), self.git('status', '--porcelain')), ('main', ''))
        self.assertNotIn('propose/search', self.git('branch', '--list'))

    def test_proposals_refuse_feature_and_detached_starts_before_recording_a_run(self):
        for branch in ('feature/work',None):
            with self.subTest(branch=branch):
                if branch:self.git('switch','-qc',branch)
                else:self.git('switch','--detach','-q','main')
                with self.assertRaisesRegex(Refused,'Committed proposals must start from main'):
                    self.propose()
                self.assertEqual(self.calls,[])
                self.assertEqual(self.git('status','--porcelain'),'')
                from .workflow import active_file
                self.assertFalse(active_file(self.root).exists())

    def test_branch_transition_recovers_after_switch_without_another_worker(self):
        from .storage import Journal
        original=Journal.append
        def fail(journal,kind,data):
            if kind=='branch.moved':raise OSError('publication interrupted')
            return original(journal,kind,data)
        self.propose()
        with patch.object(Journal,'append',fail):
            with self.assertRaisesRegex(OSError,'publication interrupted'):run(self.root,self.worker([idea()]))
        self.assertEqual(self.git('branch','--show-current'),'propose/search')
        self.assertIn('branch_move',load_run(self.root)[1])
        result=run(self.root,self.worker([]))
        self.assertEqual(result['status'],'approval_checkpoint')
        self.assertEqual([c[0] for c in self.calls],['analysis','review'])
        self.assertNotIn('branch_move',load_run(self.root)[1])
        self.assertEqual(self.where['roadmap'].read_text().count('`search`'),1)

    def test_branch_identity_failure_removes_only_the_unpublished_branch(self):
        from .branches import incarnation
        self.propose()
        def fail(root,branch,**kwargs):
            if branch.startswith('propose/'):raise OSError('identity unavailable')
            return incarnation(root,branch,**kwargs)
        with patch('oh.branches.incarnation',fail):
            with self.assertRaisesRegex(OSError,'identity unavailable'):run(self.root,self.worker([idea()]))
        self.assertEqual(self.git('branch','--show-current'),'main')
        self.assertNotIn('propose/search',self.git('branch','--list'))
        self.assertEqual(run(self.root,self.worker([]))['status'],'approval_checkpoint')
        self.assertEqual([c[0] for c in self.calls],['analysis','review'])

    def test_pending_branch_transition_preserves_new_human_edits(self):
        from .storage import Journal
        original=Journal.append
        def fail(journal,kind,data):
            if kind=='branch.moved':raise OSError('publication interrupted')
            return original(journal,kind,data)
        self.propose()
        with patch.object(Journal,'append',fail):
            with self.assertRaises(OSError):run(self.root,self.worker([idea()]))
        path=self.root/'human.txt';path.write_text('keep this')
        with self.assertRaisesRegex(Refused,'Restore the unchanged proposal branches'):
            run(self.root,self.worker([]))
        self.assertEqual(path.read_text(),'keep this')
        self.assertEqual([c[0] for c in self.calls],['analysis'])

    def test_reconsider_recovers_after_switch_before_branch_deletion(self):
        from .storage import git
        self.propose();run(self.root,self.worker([idea()]))
        def fail(root,*args,**kwargs):
            if args[:2]==('branch','-D'):raise OSError('delete interrupted')
            return git(root,*args,**kwargs)
        with patch('oh.workflow.git',fail):
            with self.assertRaisesRegex(OSError,'delete interrupted'):self.say('reconsider')
        self.assertEqual(self.git('branch','--show-current'),'main')
        state=load_run(self.root)[1]
        self.assertEqual(state['status'],'stopped');self.assertIn('discard',state)
        self.assertEqual(run(self.root,self.worker([]))['status'],'stopped')
        self.assertNotIn('discard',load_run(self.root)[1])
        self.assertNotIn('propose/search',self.git('branch','--list'))
        self.assertEqual(self.git('status','--porcelain'),'')
        self.assertEqual([c[0] for c in self.calls],['analysis','review'])

    def test_reconsider_never_discards_a_human_edit(self):
        self.propose();run(self.root,self.worker([idea()]))
        path=self.where['roadmap'];path.write_text(path.read_text()+'\nHuman note\n')
        with self.assertRaises(Refused):self.say('reconsider')
        self.assertIn('Human note',path.read_text())
        self.assertEqual(load_run(self.root)[1]['status'],'approval_checkpoint')

    def test_the_gate_words_reach_oh_only_while_a_proposal_waits(self):
        from .entry import command
        self.assertEqual(command('refine: smaller scope'), ('choice', 'refine: smaller scope'))
        self.assertIsNone(command('refine the colours'))
        self.propose();run(self.root, self.worker([idea()]))
        self.say('approve')
        with self.assertRaisesRegex(Refused, 'No proposal is waiting'):self.say('approve')

    def test_answers_carry_prose_and_a_route_only(self):
        for value, words in ((idea(route='essay'), 'route must be'), (idea(slug='Search'), 'kebab-case'),
                             (idea(summary='S' * 1001), 'longer than 1000'), (idea(decision_title='A | B'), 'cannot contain'),
                             (idea(decision_title='Contested?'), 'needs its decision title, context'),
                             (idea('task', depends=['two']), 'task numbers')):
            with self.subTest(words):
                with self.assertRaisesRegex(Refused, words):plans.proposal(value)

    def test_proposal_binds_plan_paths_before_paying_the_worker(self):
        self.propose()
        change(self.root,'plans.designs','alternate/design')
        with self.assertRaisesRegex(Refused,'Plan paths changed'):run(self.root,self.worker([idea()]))
        self.assertEqual(self.calls,[])
        self.assertEqual(self.git('branch','--show-current'),'main')

    def test_contested_proposal_keeps_decision_sections_owned_by_oh(self):
        value=idea(decision_title='Which index?',decision_context='Context',decision_alternatives='Alternatives',decision_consequences='Consequences')
        for key in ('decision_context','decision_alternatives','decision_consequences','summary'):
            with self.subTest(key=key):
                with self.assertRaisesRegex(Refused,'structural headings'):plans.proposal(value|{key:'## Decision\nUse mine'})
        with self.assertRaisesRegex(Refused,'recommendation'):plans.proposal(value|{'summary':''})


if __name__ == '__main__':
    unittest.main()
