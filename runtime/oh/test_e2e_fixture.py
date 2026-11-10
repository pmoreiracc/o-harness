"""Fixture isolation checks; never start a model or change normal host settings."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .config import HOME
from .storage import git_env

spec = importlib.util.spec_from_file_location('e2e_fixture', str(HOME / 'integrations/e2e_fixture.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class E2EFixtureTest(unittest.TestCase):
    def test_prepare_defaults_to_sanity_and_accepts_explicit_catalog(self):
        command = ['e2e_fixture.py', 'prepare', '--codex-model', 'test', '--claude-model', 'test']
        for extra, suite in (([], 'sanity'), (['--suite', 'catalog'], 'catalog')):
            with self.subTest(suite=suite), patch.object(sys, 'argv', command + extra), patch.object(fixture, 'prepare') as prepare:
                fixture.main()
                prepare.assert_called_once_with('test', 'test', suite)

    def test_publication_observation_counts_short_first_answers_and_recovery(self):
        from types import SimpleNamespace
        from . import authority
        label='Open PR to example/project → main'
        offer={'question':'Publish the greeting change?', 'choices':{'continue':'Start task 2','publish':label,'stop':'Stop and take over'},
               'menu_options':['Start task 2',label,'Stop and take over']}
        receipt={'prepared':offer,'human':{'host':'codex','session':'s','transcript_path':'native.jsonl'}}
        journal=SimpleNamespace(path=Path('fixture-run'))
        state={'publication':{'source':'actual-human'}}
        with patch('oh.storage.read_json',return_value=receipt), patch.object(authority,'question_calls',return_value=(Path('native.jsonl'),[])), \
                patch.object(authority,'codex_history',return_value=(None,None,[{'prompt':'Open PR'}],None)):
            self.assertEqual(fixture.sanity_publication(Path('.'),journal,state)['answers'],1)
        # A later successful recovery cannot hide the rejected first actual answer.
        with patch('oh.storage.read_json',return_value=receipt), patch.object(authority,'question_calls',return_value=(Path('native.jsonl'),['retry'])), \
                patch.object(authority,'codex_history',return_value=(None,None,[{'prompt':'Open PR'}],None)), \
                patch.object(authority,'native_human',return_value={'prompt':label}):
            with self.assertRaisesRegex(ValueError,'observed 2'):
                fixture.sanity_publication(Path('.'),journal,state)

    def test_foreign_git_and_agent_context_cannot_select_another_project(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            roots = [base / name for name in ('codex-choice', 'claude-choice', 'other')]
            for root in roots:
                subprocess.run(['git', 'init', '-q', str(root)], env=git_env(), check=True)
            (base / 'trial.json').write_text(json.dumps({
                'kind': 'oh-cli-acceptance', 'root': str(base), 'build': str(base / 'snapshot'),
                'models': {'codex': 'fixture', 'claude': 'fixture'}, 'effort': 'low',
            }), encoding='utf-8', newline='\n')
            previous = Path.cwd()
            try:
                with patch.dict(os.environ, {
                    'GIT_DIR': str(roots[2] / '.git'), 'OH_CHILD_ATTEMPT': 'foreign-attempt',
                    'CODEX_SESSION_ID': 'foreign-parent', 'OPENAI_API_KEY': 'fixture-only',
                    'ANTHROPIC_API_KEY': 'fixture-only',
                }), patch.object(sys, 'path', list(sys.path)):
                    self.assertEqual(Path(fixture.git(roots[0], 'rev-parse', '--absolute-git-dir')).resolve(), roots[0] / '.git')
                    for host, root in zip(('codex', 'claude'), roots):
                        with self.subTest(host=host), patch.object(fixture.os, 'execvpe') as execute:
                            fixture.launch(base, host, 'choice', 'actual answer', 'saved-session')
                            program, arguments, environment = execute.call_args.args
                            self.assertEqual(program, host)
                            self.assertEqual(Path.cwd(), root)
                            self.assertEqual(environment['OH_DATA_HOME'], str(base / 'data'))
                            for key in ('GIT_DIR', 'OH_CHILD_ATTEMPT', 'CODEX_SESSION_ID', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
                                self.assertNotIn(key, environment)
                            self.assertIn('actual answer', arguments)
                            self.assertFalse(any('bypass' in argument for argument in arguments))
                            if host == 'claude':
                                self.assertEqual(arguments[arguments.index('--effort') + 1], 'low')
                                self.assertEqual(arguments[arguments.index('--setting-sources') + 1], 'project,local')
            finally:
                os.chdir(previous)

    def test_acceptance_profile_is_shared_but_wrong_candidate_cannot_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / 'acceptance'
            home.mkdir()
            trial = root / 'trial'
            config = trial / 'codex-home/config.toml'
            config.parent.mkdir(parents=True)
            config.write_text('model = "fixture"\n', encoding='utf-8', newline='\n')
            value = {'build': str(root / 'build'), 'candidate': {'version': 'fixture'},
                     'codex_profile': 'acceptance'}
            old = {'pluginId': 'o-harness@oh-dev', 'enabled': True, 'version': 'old',
                   'source': {'path': str(root / 'old')}}
            selected = old | {'version': 'fixture', 'source': {'path': str(root / 'build/codex/plugins/o-harness')}}
            with patch.object(fixture, 'acceptance_home', return_value=home), patch.object(
                    fixture, 'trial', return_value=(trial, value)), patch.dict(os.environ, {
                        'CODEX_HOME': str(root / 'personal'), 'CODEX_ACCESS_TOKEN': 'fixture-only'}):
                self.assertEqual(fixture.codex_home(root / 'another-trial', value), home)
                env = fixture.codex_environment(home)
                self.assertEqual(env['CODEX_HOME'], str(home))
                self.assertNotIn('CODEX_ACCESS_TOKEN', env)
                with patch.object(subprocess, 'check_output', return_value=json.dumps({'installed': [old]})):
                    with self.assertRaisesRegex(ValueError, 'selected this snapshot'):
                        fixture.check_codex_candidate(value, env)
                with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess(
                        [], 0, 'Logged in using ChatGPT', '')) as run, patch.object(
                        subprocess, 'check_output', return_value=json.dumps({'installed': [selected]})):
                    fixture.setup_codex(trial)
                    self.assertEqual(run.call_args_list[0].args[0], ['codex', 'login', 'status'])
                    self.assertEqual(run.call_args_list[-1].kwargs['env']['CODEX_HOME'], str(home))
                self.assertEqual((home / 'config.toml').read_bytes(), config.read_bytes())
