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
            findings = [] if verdict == 'clean' else [{'severity': 'concern' if verdict == 'concern' else 'blocking', 'description': 'Duplicates auth', 'path': 'docs/roadmap.md',
                                                      'family': 'route', 'relation': 'original'}]
            return {'failed': False, 'returncode': 0, 'duration_ms': 1, 'text': 'review',
                    'structured': {'verdict': verdict, 'summary': 'Reviewed', 'findings': findings, 'evidence': fixtures.EVIDENCE}, 'usage_observed': False}
        return invoke

    def propose(self, text='Search my notes'):
        return host_hook(self.root, 'codex', {'prompt': f'/oh-propose {text}'}, verified=self.event('1', f'/oh-propose {text}'))

    def test_a_row_is_shown_first_then_written_reviewed_and_committed(self):
        import sys
        from pathlib import Path
        ran = Path(self.temp.name) / 'check-ran'  # plans run no project checks: OH checks the plan files itself
        fixtures.configure(self.root, checks=[{'name': 'tests', 'command': [sys.executable, '-c', f'open({str(ran)!r}, "w"); raise SystemExit(1)']}])
        self.propose()
        self.assertEqual(load_run(self.root)[1]['tasks'][0]['difficulty'], 'complex')  # a wrong placement isn't caught later
        result = run(self.root, self.worker([idea()]))
        self.assertEqual(result['status'], 'approval_checkpoint')
        self.assertEqual(result['proposal']['lines'], ['| `search` | Full-text search over notes | — | — |'])
        self.assertEqual(result['proposal']['choices'], ['approve', 'refine: <what to change>', 'reconsider'])
        self.assertEqual((self.git('branch', '--show-current'), self.git('status', '--porcelain')), ('main', ''))  # nothing written yet
        self.assertEqual([c[0] for c in self.calls], ['analysis'])
        self.assertIn('Routing an idea', self.calls[0][1]);self.assertEqual(self.calls[0][2], PROPOSAL_SCHEMA)
        self.say('approve')
        self.assertEqual(run(self.root, self.worker([]))['status'], 'completed')
        self.assertEqual([c[0] for c in self.calls], ['analysis', 'review'])
        self.assertIn('The subject is a proposal', self.calls[1][1]);self.assertIn('Search across notes.', self.calls[1][1])
        self.assertEqual(self.git('branch', '--show-current'), 'propose/search')
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'propose: | `search` | Full-text search over notes | — | — |')
        self.assertEqual(self.git('diff', '--name-only', 'main', 'HEAD'), 'docs/roadmap.md')
        self.assertFalse(ran.exists())
        self.say('pr')
        self.assertEqual(load_run(self.root)[1]['status'], 'pr')

    def test_a_review_that_moves_the_idea_asks_the_person_again(self):
        self.propose();run(self.root, self.worker([idea()]));self.say('approve')
        result = run(self.root, self.worker([idea('task')], reviews=['blocking']))
        self.assertEqual(result['status'], 'approval_checkpoint')
        self.assertEqual(result['proposal']['lines'], ['- [ ] **3.** Rate-limit sign-in attempts. Read §1. Depends on task 2.'])
        self.assertEqual([c[0] for c in self.calls], ['analysis', 'review', 'analysis'])
        self.assertEqual((self.git('branch', '--show-current'), self.git('status', '--porcelain')), ('main', ''))
        self.assertNotIn('propose/search', self.git('branch', '--list'))

    def test_a_repair_that_moves_the_row_to_another_milestone_asks_again(self):
        plans.add_milestone(self.root, self.where, 'M2', 'Second slice', 'A person finds notes');self.git('commit', '-qam', 'M2')
        self.propose();run(self.root, self.worker([idea()]));self.say('approve')
        result = run(self.root, self.worker([idea(milestone='M2')], reviews=['blocking']))
        self.assertEqual((result['status'], result['proposal']['writes']['milestone']), ('approval_checkpoint', 'M2'))
        self.assertEqual(result['proposal']['lines'], ['| `search` | Full-text search over notes | — | — |'])  # same line, other place

    def test_a_repair_that_writes_the_approved_lines_needs_no_second_approval(self):
        self.propose();run(self.root, self.worker([idea()]));self.say('approve')
        self.assertEqual(run(self.root, self.worker([idea(evidence='Read docs/roadmap.md twice.')], reviews=['blocking']))['status'], 'completed')
        self.assertEqual([c[0] for c in self.calls], ['analysis', 'review', 'analysis', 'review'])
        self.assertEqual(self.where['roadmap'].read_text().count('`search`'), 1)

    def test_a_new_milestone_and_a_contested_choice_are_written_too(self):
        self.propose()
        answer = idea(milestone='M2', milestone_title='Find things', milestone_done_when='A person finds any note in a second',
                      decision_title='One search index or one per space?', decision_context='Spaces are separate.',
                      decision_alternatives='One index: simple. Per space: isolated.', decision_consequences='The store follows.',
                      summary='Recommend one index per space.')
        result = run(self.root, self.worker([answer]))
        self.assertEqual(result['proposal']['lines'][0], '### M2 — Find things')
        self.assertIn('Decision record 0001 (proposed)', result['proposal']['lines'][-1])
        writes = result['proposal']['writes']  # what the lines don't say is shown, and approved, too
        self.assertEqual((writes['done_when'], writes['decision']['recommendation']), ('A person finds any note in a second', 'Recommend one index per space.'))
        self.assertFalse(self.where['decisions'].exists())
        self.say('approve');run(self.root, self.worker([]))
        record = (self.where['decisions'] / '0001-one-search-index-or-one-per-space.md').read_text()
        self.assertIn('status: proposed', record);self.assertIn('## Recommendation\n\nRecommend one index per space.', record)

    def test_a_human_mode_change_during_review_is_kept(self):
        self.propose();run(self.root,self.worker([idea()]));self.say('approve')
        path=self.where['roadmap'];reviewer=self.worker([])
        modes=[]
        def invoke(host,root,profile,prompt,role,directory,context,**kwargs):
            path.chmod(0o444);modes.append(path.stat().st_mode & 0o777)
            return reviewer(host,root,profile,prompt,role,directory,context,**kwargs)
        try:
            with self.assertRaisesRegex(Refused,'file type, mode or content'):run(self.root,invoke)
            kept=path.stat().st_mode & 0o777
            self.assertEqual(kept,modes[0])
        finally:path.chmod(0o600)
        self.assertEqual(self.git('rev-parse','HEAD'),self.git('rev-parse','main'))

    def test_render_and_failed_render_keep_existing_permissions(self):
        path=self.where['roadmap'];before=path.read_bytes();path.chmod(0o600)
        mode=path.stat().st_mode & 0o777
        with patch('oh.plans.add_initiative',side_effect=Refused('render failed')):
            with self.assertRaisesRegex(Refused,'render failed'):
                plans.render_proposal(self.root,idea(milestone='M2',milestone_title='New',milestone_done_when='Done'),lambda intent:None,lambda topic:None)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(path.stat().st_mode & 0o777,mode)
        self.propose();run(self.root,self.worker([idea()]));self.say('approve')
        self.assertEqual(run(self.root,self.worker([]))['status'],'completed')
        self.assertEqual(path.stat().st_mode & 0o777,mode)

    def test_contested_proposal_controls_return_as_feedback(self):
        bad=idea(decision_title='Choice?',decision_context='A\x00B',decision_alternatives='Options',decision_consequences='Effects')
        self.propose();run(self.root,self.worker([bad,idea()]))
        self.assertIn('control characters',[c[1] for c in self.calls if c[0]=='analysis'][1])
        self.assertFalse(self.where['decisions'].exists())

    def test_a_task_joins_an_approved_design(self):
        self.propose('Rate-limit sign-in')
        result = run(self.root, self.worker([idea('task')]))
        self.assertEqual(result['proposal']['lines'], ['- [ ] **3.** Rate-limit sign-in attempts. Read §1. Depends on task 2.'])
        self.say('approve');run(self.root, self.worker([]))
        self.assertEqual(self.git('branch', '--show-current'), 'propose/design-0001')
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

    def test_an_improvement_or_unclear_idea_is_shown_with_no_review(self):
        for route in ('improvement', 'unclear'):
            with self.subTest(route=route):
                self.calls.clear()
                self.propose(f'Make the sign-in button bigger ({route})')
                result = run(self.root, self.worker([idea(route, text='Make the sign-in button 48px tall')]))
                self.assertEqual((result['status'], result['proposal']['route'], result['proposal']['lines']), ('approval_checkpoint', route, []))
                self.say('approve')
                self.assertEqual(run(self.root, self.worker([]))['status'], 'completed')
                self.assertEqual([c[0] for c in self.calls], ['analysis'])
                self.assertEqual((self.git('branch', '--show-current'), self.git('status', '--porcelain')), ('main', ''))
                with self.assertRaisesRegex(Refused, 'nothing to publish'):self.say('pr')
                self.say('stop')

    def test_refine_asks_again_with_the_person_s_words(self):
        """docs/usage.md: Refine asks for words only after selection; closing it applies nothing."""
        import io
        from .mcp_server import Server
        self.propose()
        run(self.root, self.worker([idea()]))
        with self.assertRaisesRegex(Refused, 'Say what to change'):self.say('refine:  ')
        server=Server(io.StringIO(),io.StringIO());server.client={'capabilities':{'elicitation':{}}}
        def refine(answer, before_answer=None):
            forms=[]
            def respond(message,schema,call):
                forms.append(schema)
                if len(forms)==1:return {'result':{'action':'accept','content':{'choice':'refine','changes':'ignore unrequested words'}}}
                if before_answer:before_answer()
                return {'result':answer}
            with patch.object(server,'elicit',side_effect=respond):result=server.choose(self.root,'s','call')
            self.assertEqual([set(f['properties']) for f in forms],[{'choice'},{'answer'}])
            return result
        for answer in ({'action':'cancel'},{'action':'accept','content':{'answer':' '}}):
            self.assertIn('nothing was recorded',refine(answer))
            self.assertEqual(load_run(self.root)[1]['status'],'approval_checkpoint')
        words='put it in a new milestone M2 called Find things\nKeep  this spacing.'
        self.assertIn('Recorded',refine({'action':'accept','content':{'answer':words}}))
        self.assertEqual(load_run(self.root)[1]['proposal_answers'][-1]['feedback'],words)
        result = run(self.root, self.worker([idea(milestone='M2', milestone_title='Find things', milestone_done_when='Found')]))
        prompts = [c[1] for c in self.calls if c[0] == 'analysis']
        self.assertIn('Keep  this spacing.', prompts[1])
        self.assertNotIn('ignore unrequested words',prompts[1])
        self.assertEqual(result['proposal']['lines'][0], '### M2 — Find things')
        # A run may be stopped while the second question is open: the original gate still must match.
        with self.assertRaisesRegex(Refused,'out of date'):
            refine({'action':'accept','content':{'answer':'Too late'}},before_answer=lambda:self.say('reconsider'))
        self.assertEqual(load_run(self.root)[1]['status'],'stopped')
        self.assertEqual((self.git('branch', '--show-current'), self.git('status', '--porcelain')), ('main', ''))

    def test_new_milestone_number_is_assigned_by_code(self):
        self.propose()
        result=run(self.root,self.worker([idea(milestone='M99',milestone_title='Find things',milestone_done_when='Found')]))
        self.assertIn('### M2 — Find things',result['proposal']['lines'])
        self.assertNotIn('M99',self.where['roadmap'].read_text())

    def test_task_prose_cannot_inject_dependencies_or_blocked_state(self):
        for text in ('Add rate limiting. Depends on task 1.','Add rate limiting. Blocked on §4.'):
            with self.assertRaisesRegex(Refused,'Task prose cannot contain'):
                plans.add_task(self.root,self.where,'0001','Core',text,[])
        self.assertEqual(self.git('status','--porcelain'),'')

    def test_putting_back_a_moved_proposal_recovers_each_step_without_new_analysis(self):
        from .storage import git,Journal
        self.propose();run(self.root,self.worker([idea()]));self.say('approve')
        original=Journal.append
        def fail_switch(root,*args,**kwargs):
            if args[:1]==('switch',):raise OSError('switch interrupted')
            return git(root,*args,**kwargs)
        with patch('oh.workflow.git',fail_switch):
            with self.assertRaisesRegex(OSError,'switch interrupted'):run(self.root,self.worker([idea('unclear')],reviews=['blocking']))
        human=self.root/'human.txt';human.write_text('keep me')
        with self.assertRaisesRegex(Refused,'Preserve unrelated edits'):run(self.root,self.worker([]))
        self.assertEqual(human.read_text(),'keep me');human.unlink()
        def fail_delete(root,*args,**kwargs):
            if args[:2]==('update-ref','-d'):raise OSError('delete interrupted')
            return git(root,*args,**kwargs)
        with patch('oh.workflow.git',fail_delete):
            with self.assertRaisesRegex(OSError,'delete interrupted'):run(self.root,self.worker([]))
        self.assertEqual(self.git('branch','--show-current'),'main')
        def fail_record(journal,kind,data):
            if kind=='proposal.discarded':raise OSError('record interrupted')
            return original(journal,kind,data)
        with patch.object(Journal,'append',fail_record):
            with self.assertRaisesRegex(OSError,'record interrupted'):run(self.root,self.worker([]))
        self.assertNotIn('propose/search',self.git('branch','--list'))
        self.assertEqual(run(self.root,self.worker([]))['status'],'approval_checkpoint')
        self.assertEqual([c[0] for c in self.calls],['analysis','review','analysis'])
        self.say('reconsider');self.assertEqual(load_run(self.root)[1]['status'],'stopped')
        self.assertEqual((self.git('branch','--show-current'),self.git('status','--porcelain')),('main',''))

    def test_reconsider_writes_nothing_and_asks_what_the_person_meant(self):
        self.propose()
        run(self.root, self.worker([idea()]))
        self.say('reconsider')
        result = load_run(self.root)[1]
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual((self.git('branch', '--show-current'), self.git('status', '--porcelain')), ('main', ''))
        self.assertNotIn('propose/search', self.git('branch', '--list'))
        from .workflow import checkpoint
        self.assertEqual(checkpoint(self.root)['waiting']['ask'], 'What did you mean?')
        # The person's next message is the new idea, for the same command.
        reply = 'I meant searching inside attachments'
        from .entry import receive
        receive(self.root, 'codex', {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': '12', 'prompt': reply})
        result = host_hook(self.root, 'codex', {'prompt': reply}, verified=self.event('12', reply), idea='propose')
        self.assertEqual(result['status'], 'running');self.assertNotIn('waiting', result)
        self.assertIn(reply, load_run(self.root)[1]['tasks'][0]['instructions'])

    def test_a_bare_command_waits_for_the_person_s_next_message(self):
        from .authority import pending_file
        from .entry import receive
        from .storage import read_json
        payload = lambda session, turn, prompt: {'hook_event_name': 'UserPromptSubmit', 'session_id': session, 'turn_id': turn, 'prompt': prompt}
        self.assertIsNone(receive(self.root, 'codex', payload('s', '0', 'Search my notes')))  # ordinary text never reaches OH
        result = host_hook(self.root, 'codex', {'prompt': '/oh-propose'}, verified=self.event('1', '/oh-propose'))
        self.assertEqual(result['waiting']['ask'], "What's the idea?");self.assertEqual(self.calls, [])
        self.assertIsNone(receive(self.root, 'codex', payload('other', '2', 'Search my notes')))  # another conversation can't answer
        from .cli import main
        import io, json
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):main(['--root', str(self.root), 'status'])
        self.assertEqual(json.loads(out.getvalue())['waiting']['ask'], "What's the idea?")
        receive(self.root, 'codex', payload('s', '3', 'Search my notes'))
        self.assertEqual(read_json(pending_file(self.root))['idea'], 'propose')
        self.assertIsNone(receive(self.root, 'codex', payload('s', '3b', 'and tags')))  # the first reply used the question up
        result = host_hook(self.root, 'codex', {'prompt': 'Search my notes'}, verified=self.event('3', 'Search my notes'), idea='propose')
        self.assertEqual(result['status'], 'running');self.assertNotIn('waiting', result)
        self.assertIn('Search my notes', load_run(self.root)[1]['tasks'][0]['instructions'])
        self.say('stop')
        # A bare /oh-design offers the rows without a design; another command replaces the wait.
        plans.add_initiative(self.root, self.where, 'M1', 'tags', 'Tag notes', []);self.git('commit', '-qam', 'tags')
        result = host_hook(self.root, 'codex', {'prompt': '/oh-design'}, verified=self.event('5', '/oh-design'))
        self.assertEqual(result['waiting']['initiatives'], [{'slug': 'tags', 'milestone': 'M1', 'depends': []}])
        receive(self.root, 'codex', payload('s', '6', 'the tagging one'))
        result = host_hook(self.root, 'codex', {'prompt': 'the tagging one'}, verified=self.event('6', 'the tagging one'), idea='design')
        self.assertIn('not one of those rows', result['note'])  # asked again, so the next reply answers
        receive(self.root, 'codex', payload('s', '7', '/oh-deliver'))
        self.assertIsNone(receive(self.root, 'codex', payload('s', '8', 'tags')))  # another command replaced the question
        host_hook(self.root, 'codex', {'prompt': '/oh-design'}, verified=self.event('9', '/oh-design'))
        from .authority import cancel
        cancel(self.root)  # stop and cancel drop it too, however they were given
        self.assertIsNone(receive(self.root, 'codex', payload('s', '10', 'tags')))

    def test_proposals_start_from_main_wherever_the_checkout_was(self):
        self.git('switch','-qc','feature/work')
        self.propose()
        self.assertEqual(self.git('branch','--show-current'),'main')
        self.assertEqual(load_run(self.root)[1]['branch'],'main')

    def test_branch_transition_recovers_after_switch_without_another_worker(self):
        from .storage import Journal
        original=Journal.append
        def fail(journal,kind,data):
            if kind=='branch.moved':raise OSError('publication interrupted')
            return original(journal,kind,data)
        self.propose();run(self.root,self.worker([idea()]));self.say('approve')
        with patch.object(Journal,'append',fail):
            with self.assertRaisesRegex(OSError,'publication interrupted'):run(self.root,self.worker([]))
        self.assertEqual(self.git('branch','--show-current'),'propose/search')
        self.assertIn('branch_move',load_run(self.root)[1])
        self.assertEqual(run(self.root,self.worker([]))['status'],'completed')
        self.assertEqual([c[0] for c in self.calls],['analysis','review'])
        self.assertNotIn('branch_move',load_run(self.root)[1])
        self.assertEqual(self.where['roadmap'].read_text().count('`search`'),1)

    def test_branch_creation_recovers_after_ref_write_without_another_worker(self):
        from . import runner
        original=runner.git
        def interrupt(root,*args,**kwargs):
            result=original(root,*args,**kwargs)
            if args[0]=='update-ref':raise KeyboardInterrupt('killed after ref creation')
            return result
        self.propose();run(self.root,self.worker([idea()]));self.say('approve')
        with patch.object(runner,'git',interrupt):
            with self.assertRaises(KeyboardInterrupt):run(self.root,self.worker([]))
        self.assertIn('branch_creation',load_run(self.root)[1])
        self.assertEqual(self.git('branch','--show-current'),'main')
        self.assertEqual(run(self.root,self.worker([]))['status'],'completed')
        self.assertEqual([c[0] for c in self.calls],['analysis','review'])
        self.assertEqual(self.git('branch','--list','propose/*'),'* propose/search')

    def test_stop_prevents_pending_branch_creation_recovery(self):
        from .storage import Journal
        original=Journal.append
        def interrupt(journal,kind,data):
            result=original(journal,kind,data)
            if kind=='branch.creating':raise KeyboardInterrupt('killed before creation')
            return result
        self.propose();run(self.root,self.worker([idea()]));self.say('approve')
        with patch.object(Journal,'append',interrupt):
            with self.assertRaises(KeyboardInterrupt):run(self.root,self.worker([]))
        self.say('stop')
        self.assertEqual(run(self.root,self.worker([]))['status'],'stopped')
        self.assertEqual(self.git('branch','--list','propose/*'),'')
        self.assertEqual(self.git('branch','--show-current'),'main')

    def test_failed_creation_cleanup_preserves_a_concurrent_human_commit(self):
        from .storage import Journal
        original=Journal.append
        human=self.git('commit-tree','HEAD^{tree}','-p','HEAD','-m','Human work')
        def fail(journal,kind,data):
            if kind=='branch.moving':
                self.git('update-ref','refs/heads/'+data['branch'],human)
                raise OSError('publication failed')
            return original(journal,kind,data)
        self.propose();run(self.root,self.worker([idea()]));self.say('approve')
        with patch.object(Journal,'append',fail):
            with self.assertRaisesRegex(Refused,'changed during cleanup'):
                run(self.root,self.worker([]))
        self.assertEqual(self.git('rev-parse','propose/search'),human)
        self.assertEqual(self.git('branch','--show-current'),'main')
        with self.assertRaisesRegex(Refused,'changed or created elsewhere'):
            run(self.root,self.worker([]))
        self.assertEqual(self.git('rev-parse','propose/search'),human)
        self.assertEqual([c[0] for c in self.calls],['analysis'])

    def test_putting_back_a_proposal_preserves_a_ref_changed_after_switch(self):
        from .storage import git
        self.propose();run(self.root,self.worker([idea()]));self.say('approve')
        human=self.git('commit-tree','HEAD^{tree}','-p','HEAD','-m','Human work')
        def race(root,*args,**kwargs):
            result=git(root,*args,**kwargs)
            if args==('switch','main'):self.git('update-ref','refs/heads/propose/search',human)
            return result
        with patch('oh.workflow.git',race):
            with self.assertRaisesRegex(Refused,'changed during cleanup'):run(self.root,self.worker([idea('unclear')],reviews=['blocking']))
        self.assertEqual(self.git('rev-parse','propose/search'),human)
        self.assertEqual(self.git('branch','--show-current'),'main')
        self.assertIn('discard',load_run(self.root)[1])
        with self.assertRaisesRegex(Refused,'proposal branch changed'):run(self.root,self.worker([]))
        self.assertEqual(self.git('rev-parse','propose/search'),human)
        self.assertEqual([c[0] for c in self.calls],['analysis','review','analysis'])

    def test_oversized_slug_returns_feedback_before_the_person_sees_it(self):
        from .storage import Journal
        original=Journal.append;created=[]
        def record(journal,kind,data):
            if kind=='branch.creating':created.append(data['branch'])
            return original(journal,kind,data)
        self.propose()
        with patch.object(Journal,'append',record):
            self.assertEqual(run(self.root,self.worker([idea(slug='x'*300),idea(slug='x'*60)]))['status'],'approval_checkpoint')
            self.assertIn('at most 60 characters',[c[1] for c in self.calls if c[0]=='analysis'][1])
            self.assertEqual(created,[])
            self.say('approve');run(self.root,self.worker([]))
        self.assertEqual(created,['propose/'+'x'*60])
        self.assertEqual([c[0] for c in self.calls],['analysis','analysis','review'])

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

    def test_branch_identity_failure_removes_only_the_unpublished_branch(self):
        from .branches import incarnation
        self.propose();run(self.root,self.worker([idea()]));self.say('approve')
        def fail(root,branch,**kwargs):
            if branch.startswith('propose/'):raise OSError('identity unavailable')
            return incarnation(root,branch,**kwargs)
        with patch('oh.branches.incarnation',fail):
            with self.assertRaisesRegex(OSError,'identity unavailable'):run(self.root,self.worker([]))
        self.assertEqual(self.git('branch','--show-current'),'main')
        self.assertNotIn('propose/search',self.git('branch','--list'))
        self.assertEqual(run(self.root,self.worker([]))['status'],'completed')
        self.assertEqual([c[0] for c in self.calls],['analysis','review'])

    def test_pending_branch_transition_preserves_new_human_edits(self):
        from .storage import Journal
        original=Journal.append
        def fail(journal,kind,data):
            if kind=='branch.moved':raise OSError('publication interrupted')
            return original(journal,kind,data)
        self.propose();run(self.root,self.worker([idea()]));self.say('approve')
        with patch.object(Journal,'append',fail):
            with self.assertRaises(OSError):run(self.root,self.worker([]))
        path=self.root/'human.txt';path.write_text('keep this')
        with self.assertRaisesRegex(Refused,'Restore the unchanged proposal branches'):
            run(self.root,self.worker([]))
        self.assertEqual(path.read_text(),'keep this')
        self.assertEqual([c[0] for c in self.calls],['analysis'])

    def test_reconsider_never_touches_a_human_edit(self):
        self.propose();run(self.root,self.worker([idea()]))
        path=self.where['roadmap'];path.write_text(path.read_text()+'\nHuman note\n')
        self.say('reconsider')
        self.assertIn('Human note',path.read_text())
        self.assertEqual(load_run(self.root)[1]['status'],'stopped')

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
