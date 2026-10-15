import json
import unittest
import unittest.mock
from pathlib import Path
from . import plans
from . import test_workflow as fixtures
from .config import change
from .hosts import DESIGN_SCHEMA
from .storage import Refused, read_json
from .workflow import load_run

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

    def symlink(self,path,target,**kwargs):
        try:path.symlink_to(target,**kwargs)  # windows-ok: only missing symlink privilege skips the case below
        except OSError as exc:
            if getattr(exc,'winerror',None)==1314:self.skipTest('Windows symlink privilege is unavailable')
            raise

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

    def test_task_lines_are_the_parser_s_and_new_tasks_are_open(self):
        for body, words in ((BODY.replace('- [ ] **1.**', '- [x] **1.**'), 'only open tasks'),
                            (BODY + '\n- [ADR-0001](../decisions/0001-a.md)\n', 'unrecognised task line')):
            with self.subTest(words):
                with self.assertRaisesRegex(Refused, words):plans.render(self.root, 'auth', design(body=body), lambda intent: None)
                self.assertEqual(self.git('status', '--porcelain'), '')


    def test_a_broken_roadmap_is_refused_before_the_design_starts(self):
        text = self.where['roadmap'].read_text().replace('| `auth` | Sign-in with passkeys | — |', '| `auth` | Sign-in with passkeys | `ledger` |')
        self.where['roadmap'].write_text(text)
        with self.assertRaisesRegex(Refused, '(?s)Fix the roadmap first.*cycle'):plans.design_manifest(self.root, 'auth')

    def test_ignored_plan_paths_are_refused_before_a_worker_is_paid(self):
        (self.root / '.gitignore').write_text('docs/design/\n');self.git('add', '.gitignore');self.git('commit', '-qm', 'ignore')
        with self.assertRaisesRegex(Refused, 'Git ignores docs/design/0001-auth.md'):plans.design_manifest(self.root, 'auth')

    def test_repository_plan_directory_symlinks_are_refused(self):
        target = Path(self.temp.name) / 'external-designs';target.mkdir()
        self.symlink(self.where['designs'],target,target_is_directory=True)
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

    def test_undo_of_older_symlink_output_never_chmods_its_target(self):
        import hashlib
        target=Path(self.temp.name)/'external-log.md';target.write_text('Human file');target.chmod(0o600)
        mode=target.stat().st_mode & 0o777
        log=self.where['decisions']/'README.md';log.parent.mkdir(parents=True);self.symlink(log,target)
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

if __name__ == '__main__':
    unittest.main()
