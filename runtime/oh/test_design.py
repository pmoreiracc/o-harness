import json
import unittest
import unittest.mock
from pathlib import Path
from . import plans
from . import test_workflow as fixtures
from .cli import host_hook
from .config import change
from .hosts import DESIGN_SCHEMA
from .runner import run
from .storage import Refused, read_json
from .workflow import choose, load_run

BODY = '''## 1. Why this, and why now

People need to sign in before anything else works.

## 2. Tasks

### Core track

- [ ] **1.** Add the credential store.
- [ ] **2.** Add the sign-in endpoint. Depends on task 1.
'''


def design(title='Sign-in', body=BODY, summary='Two tasks.'):
    return {'kind': 'design', 'title': title, 'body': body, 'context': '', 'alternatives': '', 'consequences': '', 'summary': summary}


def decision():
    return {'kind': 'decision', 'title': 'Passkeys or passwords?', 'body': '', 'context': 'Sign-in needs one method.',
            'alternatives': 'Passkeys: phishing-proof. Passwords: familiar.', 'consequences': 'The store follows the choice.',
            'summary': 'Recommend passkeys.'}


class DesignRunTest(unittest.TestCase):
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
        plans.add_initiative(self.root, self.where, 'M1', 'ledger', 'Accounts and entries', ['auth'])
        self.git('add', '.');self.git('commit', '-qm', 'roadmap')
        self.calls = []

    def worker(self, answers, reviews=None):
        """A fake host: analysis attempts return the next answer, reviews the next verdict (clean by default)."""
        answers, reviews = list(answers), list(reviews or [])
        def invoke(host, root, profile, prompt, role, directory, context, **kwargs):
            self.calls.append((role, prompt, kwargs.get('schema'), (root / 'docs/design').exists() and sorted(p.name for p in (root / 'docs/design').iterdir())))
            if role == 'analysis':
                return {'failed': False, 'returncode': 0, 'duration_ms': 1, 'text': 'answer', 'structured': answers.pop(0), 'usage_observed': False}
            verdict = reviews.pop(0) if reviews else 'clean'
            findings = [] if verdict == 'clean' else [{'severity': 'blocking', 'description': 'Task 2 is really two', 'path': 'docs/design',
                                                      'family': 'size', 'relation': 'original'}]
            return {'failed': False, 'returncode': 0, 'duration_ms': 1, 'text': 'review',
                    'structured': {'verdict': verdict, 'summary': 'Reviewed', 'findings': findings, 'evidence': fixtures.EVIDENCE}, 'usage_observed': False}
        return invoke

    def design_run(self, slug='auth', turn='1'):
        return host_hook(self.root, 'codex', {'prompt': f'/oh-design {slug}'}, verified=self.event(turn, f'/oh-design {slug}'))

    def test_a_failed_start_restores_the_branch_before_a_fresh_command(self):
        from .workflow import active_file
        for failure in ('identity', 'active pointer'):
            with self.subTest(failure=failure):
                target = 'oh.branches.incarnation' if failure == 'identity' else 'oh.workflow.atomic_json'
                with unittest.mock.patch(target, side_effect=OSError('start failed')):
                    with self.assertRaises(OSError):
                        self.design_run(turn=failure)
                self.assertEqual(self.git('branch', '--show-current'), 'main')
                self.assertEqual(self.git('branch', '--list', 'design/auth'), '')
                self.assertFalse(active_file(self.root).exists())
        self.design_run(turn='fresh')
        self.assertEqual(self.git('branch', '--show-current'), 'design/auth')

    def test_failed_start_cleanup_preserves_a_concurrently_updated_branch(self):
        from . import workflow
        original_git=workflow.git
        base=self.git('rev-parse','HEAD').strip()
        human=self.git('commit-tree',base+'^{tree}','-p',base,'-m','Human work').strip()
        def concurrent(root,*args,**kwargs):
            result=original_git(root,*args,**kwargs)
            if args==('switch','main'):
                original_git(root,'update-ref','refs/heads/design/auth',human)
            return result
        with unittest.mock.patch('oh.branches.incarnation',side_effect=RuntimeError('start failed')):
            with unittest.mock.patch('oh.workflow.git',side_effect=concurrent):
                with self.assertRaises(Refused):self.design_run()
        self.assertEqual(self.git('rev-parse','design/auth').strip(),human)
        self.assertEqual(self.git('branch','--show-current').strip(),'main')
        self.assertEqual(self.calls,[])

    def test_a_start_error_after_publishing_the_pointer_keeps_the_run_branch(self):
        from .storage import atomic_json
        def publish_then_fail(*args, **kwargs):
            atomic_json(*args, **kwargs)
            raise OSError('directory sync failed')
        with unittest.mock.patch('oh.workflow.atomic_json', side_effect=publish_then_fail):
            with self.assertRaises(OSError):
                self.design_run()
        self.assertEqual(self.git('branch', '--show-current'), 'design/auth')
        self.assertEqual(load_run(self.root)[1]['branch'], 'design/auth')
        self.design_run()
        self.assertEqual(self.git('branch', '--show-current'), 'design/auth')

    def test_a_design_is_written_by_oh_reviewed_on_its_branch_and_committed(self):
        # docs/usage.md: an explicit development base wins over the release default.
        self.git('switch','-qc','develop')
        self.git('commit','--allow-empty','-qm','development base')
        self.git('update-ref','refs/remotes/origin/main','main')
        self.git('symbolic-ref','refs/remotes/origin/HEAD','refs/remotes/origin/main')
        change(self.root,'base_branch','develop')
        main = self.git('rev-parse', 'develop')
        self.design_run()
        self.assertEqual(self.git('branch', '--show-current'), 'design/auth')
        self.assertEqual(self.git('rev-parse', 'HEAD'), main)
        self.assertEqual(load_run(self.root)[1]['base'], main)
        result = run(self.root, self.worker([design()]))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['plan'], {'kind': 'design', 'number': '0001', 'title': 'Sign-in', 'path': 'docs/design/0001-auth.md', 'tasks': 2,
                                          'summary': 'Two tasks.'})
        (role, prompt, schema, _), (review, review_prompt, _, seen) = self.calls
        self.assertEqual((role, schema, review), ('analysis', DESIGN_SCHEMA, 'review'))
        self.assertIn('Writing a design', prompt);self.assertIn('Sign-in with passkeys', prompt)
        from .runner import prompt_for
        state=load_run(self.root)[1]
        for host in ('codex','claude'):
            for role in ('analysis','review'):
                text=prompt_for(self.root,state|{'host':host},state['tasks'][0],role)
                handoff=json.JSONDecoder().raw_decode(text[text.index('\n{"task":')+1:])[0]
                self.assertEqual(handoff['planning'],{'location':'repo','design_approval':'human_merge'})
        self.assertEqual(seen, ['0001-auth.md']);self.assertIn('The subject is a plan', review_prompt)
        doc = (self.root / 'docs/design/0001-auth.md').read_text()
        self.assertIn('status: approved', doc);self.assertIn('# 0001 — Sign-in', doc)
        self.assertIn('| `auth` | Sign-in with passkeys | — | [0001](./design/0001-auth.md) |', self.where['roadmap'].read_text())
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'design 0001: Sign-in')
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(self.git('diff', '--name-only', 'develop', 'HEAD').split(), ['docs/design/0001-auth.md', 'docs/roadmap.md'])
        change(self.root,'base_branch','main')  # a running batch keeps its approved base
        choose(self.root, 'pr', self.event('2', 'pr'))
        self.assertEqual(load_run(self.root)[1]['publication']['base_branch'],'develop')
        from .publication import render
        self.assertIn('Base branch: `develop`',render(self.root))
        self.assertEqual(load_run(self.root)[1]['status'], 'pr')

    def test_new_plans_start_from_main_brought_up_to_date(self):
        import subprocess
        origin, other = Path(self.temp.name) / 'origin.git', Path(self.temp.name) / 'other'
        subprocess.run(['git', 'clone', '-q', '--bare', str(self.root), str(origin)], check=True)
        self.git('remote', 'add', 'origin', str(origin));self.git('fetch', '-q', 'origin')
        subprocess.run(['git', 'clone', '-q', str(origin), str(other)], check=True)
        subprocess.run(['git', '-C', str(other), '-c', 'user.name=O', '-c', 'user.email=o@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'merged elsewhere'], check=True)
        subprocess.run(['git', '-C', str(other), 'push', '-q', 'origin', 'main'], check=True)
        self.git('switch', '-q', '--detach', 'main')  # the person was somewhere else
        (self.root / 'notes.txt').write_text('mine')
        with self.assertRaisesRegex(Refused, r'uncommitted changes that OH did not make \(notes.txt\)'):self.design_run()
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'main'))  # their edits stay where they are
        (self.root / 'notes.txt').unlink()
        self.design_run()
        self.assertEqual(self.git('branch', '--show-current'), 'design/auth')
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'origin/main'))
        self.assertEqual(self.git('log', '-1', '--format=%s', 'main'), 'merged elsewhere')

    def test_an_answer_oh_cannot_use_goes_back_to_the_worker(self):
        broken = design(body=BODY.replace('- [ ] **2.**', '- [ ] 2.'))
        for index, (bad, words) in enumerate(((None, 'OH could not use the answer'), (broken, 'unrecognised task line'))):
            with self.subTest(words):
                if index:self.setUp()
                self.design_run()
                result = run(self.root, self.worker([bad, design()]))
                self.assertEqual(result['status'], 'completed')
                prompts = [prompt for role, prompt, _, _ in self.calls if role == 'analysis']
                self.assertIn(words, prompts[1])
                self.assertEqual(sorted(p.name for p in (self.root / 'docs/design').iterdir()), ['0001-auth.md'])

    def test_a_repair_rewrites_the_same_doc_from_the_reviewed_parent(self):
        self.design_run()
        result = run(self.root, self.worker([design(), design(title='Sign-in, split')], ['blocking']))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.calls[2][3], ['0001-auth.md'])  # the next worker reads the reviewed doc
        self.assertEqual(sorted(p.name for p in (self.root / 'docs/design').iterdir()), ['0001-auth.md'])
        self.assertIn('# 0001 — Sign-in, split', (self.root / 'docs/design/0001-auth.md').read_text())
        self.assertEqual(self.where['roadmap'].read_text().count('[0001]'), 1)
        # docs/usage.md: planning repairs see history, and reviewers see author reports.
        from .storage import digest
        journal,state=load_run(self.root)
        requests=[read_json(journal.path/'attempts'/a['id']/'request.json') for a in state['attempts']]
        repair=requests[2];history=read_json(repair['prior_reviews']['path'])
        self.assertEqual(history[0]['findings'][0]['family'],'size')
        self.assertEqual(digest(history),repair['prior_reviews']['hash'])
        self.assertIn('whole defect family',repair['prompt'])
        self.assertIn('not additional task scope',repair['prompt'])
        for request,count in ((requests[1],1),(requests[3],2)):
            self.assertEqual(len(request['implementer_reports']),count)
            for report in request['implementer_reports']:
                self.assertEqual(digest(read_json(report['path'])),report['hash'])
                self.assertIn('Sign-in',read_json(report['path'])['structured']['title'])

    def test_an_owed_decision_is_proposed_without_a_design(self):
        self.design_run()
        result = run(self.root, self.worker([decision()]))
        self.assertEqual(result['plan']['kind'], 'decision')
        record = self.root / 'docs/decisions/0001-decision.md'
        self.assertIn('status: proposed', record.read_text());self.assertIn('_Not decided yet.', record.read_text())
        self.assertIn('## Recommendation\n\nRecommend passkeys.', record.read_text())
        self.assertIn('[0001](./0001-decision.md)', (self.root / 'docs/decisions/README.md').read_text())
        self.assertFalse((self.root / 'docs/design').exists())
        self.assertIn('| `auth` | Sign-in with passkeys | — | — |', self.where['roadmap'].read_text())
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'decision 0001: Passkeys or passwords?')

    def test_only_an_unclaimed_roadmap_row_starts_a_design(self):
        from .entry import receive
        refused = receive(self.root, 'codex', {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': 't', 'prompt': '/oh-design a login page'})
        self.assertFalse(refused['authorized']);self.assertIn('/oh-design <slug>', refused['next'])
        with self.assertRaisesRegex(Refused, "no initiative 'login'. Initiatives without a design: auth, ledger"):plans.design_manifest(self.root, 'login')
        self.design_run();run(self.root, self.worker([design()]))
        with self.assertRaisesRegex(Refused, "'auth' already has design doc 0001"):plans.design_manifest(self.root, 'auth')
        change(self.root, 'plans.location', 'private')
        with self.assertRaisesRegex(Refused, 'Start the roadmap first'):plans.design_manifest(self.root, 'ledger')
        change(self.root, 'plans.location', 'ask')
        with self.assertRaisesRegex(Refused, 'Choose where plans live'):plans.design_manifest(self.root, 'ledger')

    def test_a_design_branch_never_reuses_an_existing_branch(self):
        self.git('branch', 'design/auth')
        self.design_run()
        self.assertEqual(self.git('branch','--show-current'),'design/auth-2')

    def test_undo_restores_only_what_oh_wrote_and_never_a_human_edit(self):
        intents = []
        written = plans.render(self.root, 'auth', design(), intents.append)
        self.assertEqual(intents, [['docs/design/0001-auth.md', 'docs/roadmap.md']])
        doc = self.root / 'docs/design/0001-auth.md'
        original = doc.read_bytes()
        doc.write_bytes(original + b'A human note.\n')
        with self.assertRaisesRegex(Refused, 'changed after OH wrote it'):plans.undo(self.root, written)
        self.assertTrue(doc.exists())
        doc.write_bytes(original)  # Undo needs the exact original bytes, including LF on Windows.
        for _ in range(2):plans.undo(self.root, written)  # safe to repeat
        self.assertFalse(doc.exists());self.assertEqual(self.git('status', '--porcelain'), '')
        # A crash between recording the intent and saving the hashes leaves files OH can't prove it wrote: a person decides.
        plans.render(self.root, 'auth', design(), lambda intent: None)
        with self.assertRaisesRegex(plans.Blocked, 'OH was interrupted while writing docs/design/0001-auth.md'):
            plans.undo(self.root, {'intent': intents[0]})
        self.assertTrue(doc.exists())
        self.git('checkout', '--', 'docs/roadmap.md');doc.unlink()
        plans.undo(self.root, {'intent': intents[0]})  # nothing left to undo

    def test_a_design_commit_holds_only_its_plan_files(self):
        (self.root / 'notes.txt').write_text('unrelated')
        with self.assertRaisesRegex(Refused, r"changes OH didn't write \(notes.txt\)"):plans.render(self.root, 'auth', design(), lambda intent: None)
        (self.root / 'notes.txt').unlink()
        (self.root / '.gitignore').write_text('docs/design/\n');self.git('add', '.gitignore');self.git('commit', '-qm', 'ignore')
        with self.assertRaisesRegex(Refused, 'Git ignores docs/design/0001-auth.md'):plans.render(self.root, 'auth', design(), lambda intent: None)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_a_prepared_task_list_cannot_become_a_plan_run(self):
        from .prepared import prepare
        from .registry import profile_path
        from .storage import atomic_json
        path = profile_path(self.root).parent / 'tasks.json'
        for manifest in ({'workflow': 'design', 'plans': {'location': 'repo'}, 'slug': 'auth', 'tasks': [{'id': 'd', 'title': 'D', 'instructions': 'x'}]},
                         {'tasks': [{'id': 'd', 'title': 'D', 'instructions': 'x', 'transition': {'profile': 'plans', 'slug': 'auth'}}]}):
            atomic_json(path, manifest)
            with self.assertRaisesRegex(Refused, 'only tasks and checks'):prepare(self.root, str(path))

    def test_answers_carry_prose_only(self):
        for value, words in ((design() | {'extra': ''}, 'JSON object'), (design(title='Two\nlines'), 'one non-empty line'),
                             (design(body='# 0009 — Mine\n\n' + BODY), 'use ## sections'), (decision() | {'context': ' '}, 'needs context'),
                             (design() | {'kind': 'essay'}, "kind must be"), (design(title='T' * 151), 'longer than 150'),
                             (design(summary='S' * 1001), 'longer than 1000'), (decision() | {'title': 'A | B'}, 'cannot contain')):
            with self.subTest(words):
                with self.assertRaisesRegex(Refused, words):plans.answer(value)
        plans.answer(design(body='## 1. Approach\n\n```sh\n# apply the migration\n```\n\n' + BODY))  # a fenced comment is code

    def test_decision_fields_cannot_supply_human_owned_sections_or_omit_recommendation(self):
        for key in ('context','alternatives','consequences','summary'):
            for text in ('Background\n\n## Decision\n\nUse passwords.', 'Decision\n========\nUse passwords.', '<h2>Decision</h2>\nUse passwords.'):
                with self.subTest(key=key,text=text):
                    with self.assertRaisesRegex(Refused,'structural headings'):plans.answer(decision()|{key:text})
        with self.assertRaisesRegex(Refused,'needs summary'):plans.answer(decision()|{'summary':' '})
        with self.assertRaisesRegex(Refused,'unclosed code fence'):plans.answer(decision()|{'context':'```\nexample'})

    def test_changed_plan_paths_stop_before_a_worker_or_render(self):
        self.design_run()
        before=self.git('status','--porcelain')
        for key,value in (('roadmap','alternate/roadmap.md'),('designs','alternate/design'),('decisions','alternate/decisions')):
            with self.subTest(key=key):
                change(self.root,'plans.'+key,value)
                with self.assertRaisesRegex(Refused,'Plan paths changed'):run(self.root,self.worker([design()]))
                self.assertEqual(self.calls,[])
                self.assertEqual(self.git('status','--porcelain'),before)
                change(self.root,'plans.'+key,plans.DEFAULTS[key])

    def test_task_lines_are_the_parser_s_and_new_tasks_are_open(self):
        for body, words in ((BODY.replace('- [ ] **1.**', '- [x] **1.**'), 'only open tasks'),
                            (BODY + '\n- [ADR-0001](../decisions/0001-a.md)\n', 'unrecognised task line')):
            with self.subTest(words):
                with self.assertRaisesRegex(Refused, words):plans.render(self.root, 'auth', design(body=body), lambda intent: None)
                self.assertEqual(self.git('status', '--porcelain'), '')

    def test_a_manifest_file_never_starts_a_plan_run(self):
        from .prepared import directory
        from .storage import atomic_json, checkout_id, digest, project
        from datetime import datetime, timedelta, timezone
        manifest = {'workflow': 'design', 'plans': {'location': 'repo'}, 'slug': 'auth',
                    'tasks': [{'id': 'd', 'title': 'D', 'instructions': 'x', 'transition': {'profile': 'plans', 'slug': 'auth'}}]}
        value = {'created': (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), 'project': project(self.root)['id'],
                 'checkout': checkout_id(self.root), 'base': self.git('rev-parse', 'HEAD'), 'kind': 'tasks', 'manifest': manifest}
        key = digest(value);atomic_json(directory(self.root) / (key + '.json'), value)
        event = self.event('9', f'$o-harness:oh-deliver request:{key}') | {'at': datetime.now(timezone.utc).isoformat()}
        with self.assertRaisesRegex(Refused, 'only tasks and checks'):host_hook(self.root, 'codex', {'prompt': event['prompt']}, verified=event)
        from .workflow import start
        for bad in (manifest, {'tasks': manifest['tasks']}):
            with self.assertRaisesRegex(Refused, 'cannot choose plan settings'):start(self.root, bad, self.event('8'))
        from .workflow import active_file
        self.assertFalse(active_file(self.root).exists())

    def test_a_refused_command_never_blocks_the_next_one(self):
        from .authority import materialize, pending_file, stage
        payload = lambda turn, prompt: {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': turn, 'prompt': prompt}
        with unittest.mock.patch('oh.authority._attest', side_effect=lambda host, p, root=None, **kwargs: self.event(p['turn_id'], p['prompt']) | {'transcript_path': 'x'}), \
                unittest.mock.patch('oh.transcripts.register'):
            stage(self.root, 'codex', payload('1', '/oh-design login'))
            with self.assertRaisesRegex(Refused, "no initiative 'login'"):materialize(self.root)
            self.assertTrue(pending_file(self.root).exists())  # kept until carried out, so it is never typed again
            with self.assertRaisesRegex(Refused, "no initiative 'login'"):materialize(self.root)
            stage(self.root, 'codex', payload('2', '/oh-design auth'))
            self.assertEqual(materialize(self.root)['status'], 'running')

    def interrupt_review(self):
        """Run until the first review starts, then stop OH the way a crash would."""
        self.design_run()
        def invoke(host, root, profile, prompt, role, directory, context, **kwargs):
            if role == 'review':raise KeyboardInterrupt
            return self.worker([design()])(host, root, profile, prompt, role, directory, context, **kwargs)
        with self.assertRaises(KeyboardInterrupt):run(self.root, invoke)
        return len(self.calls)

    def test_problems_the_worker_cannot_fix_stop_the_run_before_a_worker_is_paid(self):
        calls = self.interrupt_review()
        (self.root / 'notes.txt').write_text('a note')
        with self.assertRaisesRegex(plans.Blocked, r"changes OH didn't write \(notes.txt\)"):run(self.root, self.worker([design()]))
        self.assertEqual(len(self.calls), calls)
        (self.root / 'notes.txt').unlink()
        self.assertEqual(run(self.root, self.worker([design()]))['status'], 'completed')

    def test_a_human_edit_stops_the_run_before_a_worker_is_paid(self):
        calls = self.interrupt_review()
        doc = self.root / 'docs/design/0001-auth.md';doc.write_text(doc.read_text() + 'A human note.\n')
        with self.assertRaisesRegex(plans.Blocked, 'changed after OH wrote it'):run(self.root, self.worker([design()]))
        self.assertEqual(len(self.calls), calls);self.assertIn('A human note.', doc.read_text())

    def test_a_broken_roadmap_is_refused_before_the_design_starts(self):
        text = self.where['roadmap'].read_text().replace('| `auth` | Sign-in with passkeys | — |', '| `auth` | Sign-in with passkeys | `ledger` |')
        self.where['roadmap'].write_text(text)
        with self.assertRaisesRegex(Refused, '(?s)Fix the roadmap first.*cycle'):plans.design_manifest(self.root, 'auth')

    def test_retry_gives_a_design_worker_a_fresh_attempt(self):
        self.design_run()
        self.assertEqual(run(self.root, self.worker([None, None]))['status'], 'needs_attention')
        choose(self.root, 'retry', self.event('2', 'retry'))
        calls = len(self.calls)
        self.assertEqual(run(self.root, self.worker([design()]))['status'], 'completed')
        self.assertEqual([c[0] for c in self.calls[calls:]], ['analysis', 'review'])

    def test_a_branch_named_design_does_not_stop_a_design(self):
        self.git('branch', 'design')
        self.design_run()
        self.assertEqual(self.git('branch', '--show-current'), 'design-auth')


    def test_a_project_without_checks_can_still_design(self):
        fixtures.configure(self.root, checks=[])
        self.design_run()
        self.assertEqual(run(self.root, self.worker([design()]))['status'], 'completed')

    def test_a_refused_start_is_carried_out_once_its_reason_is_fixed(self):
        from .authority import materialize, pending_file, stage
        payload = lambda turn, prompt: {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': turn, 'prompt': prompt}
        with unittest.mock.patch('oh.authority._attest', side_effect=lambda host, p, root=None, **kwargs: self.event(p['turn_id'], p['prompt']) | {'transcript_path': 'x'}), \
                unittest.mock.patch('oh.transcripts.register'):
            (self.root / 'notes.txt').write_text('dirty')
            stage(self.root, 'codex', payload('1', '/oh-design auth'))
            with self.assertRaisesRegex(Refused, 'uncommitted changes'):materialize(self.root)
            (self.root / 'notes.txt').unlink()
            self.assertEqual(materialize(self.root)['status'], 'running')  # not typed again
        self.assertFalse(pending_file(self.root).exists())

    def test_an_unexpected_failure_never_blocks_the_next_command(self):
        from .authority import materialize, pending_file, stage
        self.git('branch', 'design/auth/v2')  # Git can't add design/auth beside it
        payload = lambda turn, prompt: {'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': turn, 'prompt': prompt}
        with unittest.mock.patch('oh.authority._attest', side_effect=lambda host, p, root=None, **kwargs: self.event(p['turn_id'], p['prompt']) | {'transcript_path': 'x'}), \
                unittest.mock.patch('oh.transcripts.register'):
            stage(self.root, 'codex', payload('1', '/oh-design auth'))
            self.assertEqual(materialize(self.root)['status'], 'running')
        self.assertEqual(self.git('branch','--show-current'),'design/auth-2')
        with unittest.mock.patch('oh.cli.host_hook', side_effect=RuntimeError('boom')), \
                unittest.mock.patch('oh.authority._attest', side_effect=lambda host, p, root=None, **kwargs: self.event(p['turn_id'], p['prompt']) | {'transcript_path': 'x'}):
            stage(self.root, 'codex', payload('2', 'stop'))
            with self.assertRaisesRegex(Refused, 'RuntimeError: boom'):materialize(self.root)
            stage(self.root, 'codex', payload('3', 'continue'))  # the newest typed choice replaces it
        self.assertEqual(read_json(pending_file(self.root))['event']['turn'], '3')

    def test_a_design_runs_no_project_checks(self):
        # OH validates every plan write itself; the project's tests have nothing to say about plan files.
        import sys
        ran = Path(self.temp.name) / 'check-ran'
        fixtures.configure(self.root, checks=[{'name': name, 'command': [sys.executable, '-c', f'open({str(ran)!r}, "w"); raise SystemExit(1)']}
                                              | ({'when': ['docs/**']} if name == 'lint' else {}) for name in ('tests', 'lint')])
        self.design_run()
        self.assertEqual(run(self.root, self.worker([design()]))['status'], 'completed')
        self.assertEqual([c[0] for c in self.calls], ['analysis', 'review'])
        self.assertFalse(ran.exists())

    def test_ignored_plan_paths_are_refused_before_a_worker_is_paid(self):
        (self.root / '.gitignore').write_text('docs/design/\n');self.git('add', '.gitignore');self.git('commit', '-qm', 'ignore')
        with self.assertRaisesRegex(Refused, 'Git ignores docs/design/0001-auth.md'):plans.design_manifest(self.root, 'auth')

    def test_decision_directory_is_preflighted_before_start(self):
        (self.root / '.gitignore').write_text('docs/decisions/\n');self.git('add', '.gitignore');self.git('commit', '-qm', 'ignore decisions')
        with self.assertRaisesRegex(Refused, 'Git ignores docs/decisions/'):self.design_run()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.git('branch', '--show-current'), 'main')

    def test_repository_plan_symlinks_never_supply_unbound_scope(self):
        target = Path(self.temp.name) / 'external-roadmap.md'
        target.write_bytes(self.where['roadmap'].read_bytes())
        self.where['roadmap'].unlink();self.where['roadmap'].symlink_to(target)
        self.git('add', '.');self.git('commit', '-qm', 'symlink roadmap')
        with self.assertRaisesRegex(Refused, 'cannot use symlinks'):self.design_run()
        target.write_text(target.read_text().replace('Sign-in with passkeys', 'Send all passwords'))
        with self.assertRaisesRegex(Refused, 'cannot use symlinks'):self.design_run(turn='2')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_repository_plan_directory_symlinks_are_refused(self):
        target = Path(self.temp.name) / 'external-designs';target.mkdir()
        self.where['designs'].symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(Refused, 'cannot use symlinks'):plans.layout(self.root)

    def test_answer_kind_never_discards_nonempty_prose(self):
        for field in ('context', 'alternatives', 'consequences'):
            with self.assertRaisesRegex(Refused, 'empty unused fields'):plans.answer(design() | {field: 'Important requirement'})
        with self.assertRaisesRegex(Refused, 'empty unused fields'):plans.answer(decision() | {'body': 'Important requirement'})
        with self.assertRaisesRegex(Refused, 'needs summary'):plans.answer(design(summary=''))

    def test_html_headings_cannot_be_injected_through_titles_or_prose(self):
        for tag in ('<h2>Decision</h2>', '<h2\t>Decision</h2>', '<h2\n>Decision</h2>', 'Text <H2\f>Decision</H2>'):
            with self.assertRaises(Refused):plans.answer(decision() | {'title': tag})
            with self.assertRaises(Refused):plans.answer(design(title=tag))
            with self.assertRaises(Refused):plans.answer(decision() | {'context': tag})

    def test_design_grammar_has_one_title_and_distinct_one_word_tracks(self):
        for body in ('Extra title\n====\n'+BODY,'<h1>Extra title</h1>\n'+BODY,
                     BODY.replace('Core track','Core API track'),BODY+'\n### Core track\n',
                     BODY.replace('## 2. Tasks','## Tasks')):
            with self.subTest(body=body):
                with self.assertRaises(Refused):plans.answer(design(body=body))
        with self.assertRaises(Refused):plans.answer(design(title='Bad\x00title'))
        with self.assertRaises(Refused):plans.answer(design(body=BODY+'\x00'))

    def test_actual_decision_filename_is_preflighted_before_any_worker(self):
        (self.root/'.gitignore').write_text('docs/decisions/0001-decision.md\n')
        self.git('add','.gitignore');self.git('commit','-qm','ignore exact decision')
        with self.assertRaisesRegex(Refused,'Git ignores docs/decisions/0001-decision.md'):self.design_run()
        self.assertEqual(self.calls,[])

    def test_carriage_returns_cannot_hide_tasks_or_decision_structure(self):
        for ending in ('\r','\r\n','\n\r'):
            with self.subTest(ending=repr(ending)):
                with self.assertRaises(Refused):plans.answer(design(body=BODY+ending+'- [ ] **3.** Visible task.\n'))
                for field in ('context','alternatives','consequences','summary'):
                    text='Prose'+ending+'## Decision'+ending+'Worker choice.'
                    with self.assertRaises(Refused):plans.answer(decision()|{field:text})
                    with self.assertRaises(Refused):plans.section_prose(text)

    def test_raw_html_cannot_hide_tasks_or_human_decision_sections(self):
        hidden='<!--\n### Hidden track\n- [ ] **99.** Hidden task.\n-->\n'
        with self.assertRaisesRegex(Refused,'Raw HTML'):plans.answer(design(body=hidden+BODY))
        for opener in ('<!--','<pre>','<script>','<style>','<div hidden>','<?processing','<![CDATA['):
            with self.subTest(opener=opener):
                with self.assertRaisesRegex(Refused,'Raw HTML'):plans.answer(design(body=BODY+'\n'+opener))
                for field in ('context','alternatives','consequences','summary'):
                    with self.assertRaisesRegex(Refused,'Raw HTML'):plans.answer(decision()|{field:'Background\n'+opener})
                    with self.assertRaisesRegex(Refused,'Raw HTML'):plans.section_prose('Background\n'+opener)
        plans.section_prose('Example:\n```html\n<!--\n<pre>\n```')

    def test_reference_definitions_cannot_hide_tasks_or_tracks(self):
        hidden='### Hidden track\n- [ ] **99.** Hidden task.'
        definitions=[f'[hidden]: /url {opening}\n{hidden}\n{closing}'
                     for opening,closing in [('"','"'),("'","'"),('(',')')]]
        definitions += ['[hidden\n### Hidden track\n]: /url',
                        '[hidden\\]\n### Hidden track\n]: /url',
                        '[hidden\n```\n### Hidden track\n```\n]: /url',
                        '[hidden\\\n### Hidden track\n]: /url',
                        '[hidden]: /url "', '[^footnote]: hidden']
        for definition in definitions:
            for indent in ('','   '):
                with self.subTest(definition=definition,indent=indent):
                    with self.assertRaisesRegex(Refused,'reference definitions'):
                        plans.answer(design(body='## 1. Approach\n\n'+indent+definition+'\n\n'+BODY))
                    for field in ('context','alternatives','consequences','summary'):
                        with self.assertRaisesRegex(Refused,'reference definitions'):
                            plans.answer(decision()|{field:indent+definition})
                    with self.assertRaisesRegex(Refused,'reference definitions'):
                        plans.section_prose(indent+definition)
        safe='[Inline link](https://example.com).\n\n```md\n[example]: /url "title"\n```\n\n'
        plans.section_prose(safe)
        result=plans.render(self.root,'auth',plans.answer(design(body=safe+BODY)),lambda intent:None)
        rows=plans.plan(self.root,result['number']).splitlines()
        self.assertEqual([(row.split(plans.US)[0],row.split(plans.US)[2]) for row in rows],[('1','core'),('2','core')])

    def test_symlinked_decision_log_is_refused_before_start_or_write(self):
        target=Path(self.temp.name)/'external-log.md'
        target.write_text('# Decisions\n\n## The log\n\n| # | Decision | Date | Status |\n|---|---|---|---|\n')
        target.chmod(0o600);before=target.read_bytes();mode=target.stat().st_mode & 0o777
        log=self.where['decisions']/'README.md';log.parent.mkdir(parents=True);log.symlink_to(target)
        self.git('add','.');self.git('commit','-qm','linked decision log')
        with self.assertRaisesRegex(Refused,'ordinary file'):self.design_run()
        self.assertEqual(self.calls,[])
        with self.assertRaisesRegex(Refused,'ordinary file'):
            plans.render(self.root,'auth',decision(),lambda intent:self.fail('must refuse before recording intent'))
        with self.assertRaisesRegex(Refused,'ordinary file'):
            plans.write_decision(self.root,self.where,'Choice','Context','Alternatives','Consequences')
        self.assertTrue(log.is_symlink());self.assertEqual(target.read_bytes(),before)
        self.assertEqual(target.stat().st_mode & 0o777,mode)
        self.assertEqual(list(log.parent.glob('[0-9]*.md')),[])

    def test_undo_of_older_symlink_output_never_chmods_its_target(self):
        import hashlib
        target=Path(self.temp.name)/'external-log.md';target.write_text('Human file');target.chmod(0o600)
        mode=target.stat().st_mode & 0o777
        log=self.where['decisions']/'README.md';log.parent.mkdir(parents=True);log.symlink_to(target)
        self.git('add','.');self.git('commit','-qm','linked decision log')
        prior=plans.file_identity(log);name=log.relative_to(self.root).as_posix()
        log.unlink();log.write_text('Old OH output')
        previous={'intent':[name],'files':{name:hashlib.sha256(log.read_bytes()).hexdigest()},
                  'identities':{name:plans.file_identity(log)},'before_identities':{name:prior}}
        plans.undo(self.root,previous)
        self.assertTrue(log.is_symlink());self.assertEqual(target.read_text(),'Human file')
        self.assertEqual(target.stat().st_mode & 0o777,mode)

    def test_plan_writes_and_rollback_preserve_existing_permissions(self):
        path=self.where['roadmap'];before=path.read_bytes();path.chmod(0o600)
        mode=path.stat().st_mode & 0o777  # Windows preserves only the writable bit, not POSIX owner/group bits.
        plans.write(path,before+b'\n')
        self.assertEqual(path.stat().st_mode & 0o777,mode)
        with self.assertRaisesRegex(RuntimeError,'failed'):
            with plans.all_or_nothing(path):
                path.unlink();plans.write(path,'temporary');raise RuntimeError('failed')
        self.assertEqual(path.read_bytes(),before+b'\n')
        self.assertEqual(path.stat().st_mode & 0o777,mode)

    def test_fenced_structure_and_alternate_headings_cannot_change_visible_tasks(self):
        for marker in ('### API track','## 3. Other','- [ ] **99.** Example only.','-[ ] **99.** Example only.'):
            for fence in ('```md','~~~'):
                body=BODY.replace('- [ ] **1.**',fence+'\n'+marker+'\n'+fence[:3]+'\n\n- [ ] **1.**')
                with self.subTest(marker=marker,fence=fence):
                    with self.assertRaisesRegex(Refused,'parser-significant'):plans.answer(design(body=body))
        for prefix in (' # Extra title','   # Extra title','#','Other section\n---',
                       '<h2>Other section</h2>','Text <H3\n>API track</H3>'):
            with self.subTest(prefix=prefix):
                with self.assertRaises(Refused):plans.answer(design(body=prefix+'\n'+BODY))
        with self.assertRaisesRegex(Refused,'unclosed code fence'):plans.answer(design(body=BODY+'\n```'))
        safe=plans.answer(design(body=BODY.replace('- [ ] **1.**','```sh\n# example comment\n```\n\n- [ ] **1.**')))
        result=plans.render(self.root,'auth',safe,lambda intent:None)
        rows=plans.plan(self.root,result['number']).splitlines()
        self.assertEqual([(row.split(plans.US)[0],row.split(plans.US)[2]) for row in rows],[('1','core'),('2','core')])

    def test_human_mode_only_edit_is_preserved_before_repair(self):
        self.interrupt_review()
        path=self.where['designs']/'0001-auth.md';path.chmod(0o444)
        try:
            with self.assertRaisesRegex(Refused,'file type, mode or content'):run(self.root,self.worker([design()]))
            self.assertEqual(path.stat().st_mode & 0o777,0o444)
        finally:path.chmod(0o600)  # Let Windows remove the temporary fixture.

    def test_a_changed_plans_location_stops_a_repair_before_a_worker_is_paid(self):
        calls = self.interrupt_review()
        change(self.root, 'plans.location', 'private')
        with self.assertRaisesRegex(plans.Blocked, 'plans.location changed to private'):run(self.root, self.worker([design()]))
        self.assertEqual(len(self.calls), calls)

    def test_typing_the_design_again_during_its_run_points_to_the_run(self):
        self.interrupt_review()
        with self.assertRaisesRegex(Refused, 'OH is still working on'):self.design_run(turn='5')

    def test_a_new_design_never_lands_on_another_plan_s_branch(self):
        self.design_run();run(self.root, self.worker([design()]))
        choose(self.root, 'pr', self.event('2', 'pr'))
        self.design_run('ledger', turn='3')  # from main, not from the other plan's branch
        self.assertEqual((self.git('branch', '--show-current'), self.git('rev-parse', 'HEAD')), ('design/ledger', self.git('rev-parse', 'main')))


if __name__ == '__main__':
    unittest.main()
