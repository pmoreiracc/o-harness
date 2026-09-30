"""Causal authorization and retry coverage for docs/installation.md#releasing-maintainers."""
import base64
import json
import unittest
from unittest.mock import Mock, patch

import release


OWNER = {'GITHUB_REPOSITORY': 'pmoreiracc/o-harness', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
         'GITHUB_REF': 'refs/heads/main', 'GITHUB_ACTOR_ID': '154069128', 'GITHUB_TRIGGERING_ACTOR': 'pmoreiracc'}
BOT = 'oh-release[bot]'


def encoded(version):
    return {'content': base64.b64encode(release.updated('{"name":"o-harness","version":"0.0.0"}', version).encode()).decode()}


def pull(**changes):
    return {'number': 7, 'html_url': 'https://github.com/pmoreiracc/o-harness/pull/7',
            'user': {'login': BOT}, 'base': {'ref': 'main'}, 'head': {'sha': 'version', 'repo': {'full_name': 'pmoreiracc/o-harness'}},
            'draft': False, 'state': 'open', 'merged': False, 'mergeable': True, 'mergeable_state': 'clean', **changes}


class ReleaseTest(unittest.TestCase):
    def fixture(self, current='1.0.0', tag=None):
        calls = []
        def api(method, path, data=None, missing=False):
            calls.append((method, path, data))
            if path == 'git/ref/heads/main': return {'object': {'sha': 'main'}}
            if path.startswith('contents/'):
                ref = path.split('?ref=')[1]
                return encoded(current if ref in ('main', 'parent') else '1.1.0')
            if path.startswith('git/ref/tags/'): return tag
            if path == 'git/ref/heads/release/1.1.0': return None
            if path == 'git/commits/main': return {'tree': {'sha': 'base-tree'}}
            if path == 'git/trees': return {'sha': 'version-tree'}
            if path == 'git/commits': return {'sha': 'version'}
            if path == 'git/refs': return {}
            if path.startswith('pulls?'): return []
            if path == 'releases/generate-notes': return {'body': 'Changes'}
            if path in ('pulls', 'pulls/7'): return pull()
            if path == 'pulls/7/merge': return {'merged': True, 'sha': 'merged'}
            if path.startswith('compare/'): return {'status': 'ahead'}
            if path.startswith('actions/workflows/'):
                sha = path.split('head_sha=')[1].split('&')[0]
                return {'workflow_runs': [{'id': 1, 'head_sha': sha, 'head_branch': 'main', 'event': 'push', 'status': 'completed', 'conclusion': 'success'}]}
            raise AssertionError((method, path, data))
        return api, calls

    def test_only_owner_dispatch_on_main_including_reruns(self):
        release.authorize(OWNER)
        for field, bad in [('GITHUB_REPOSITORY', 'someone/fork'), ('GITHUB_EVENT_NAME', 'push'),
                           ('GITHUB_REF', 'refs/tags/main'), ('GITHUB_ACTOR_ID', '123'),
                           ('GITHUB_TRIGGERING_ACTOR', 'someone')]:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                release.authorize(OWNER | {field: bad})
        for version in ('01.2.3', '1.2', '1.2.3\n', 'v1.2.3', '1.2.3;echo bad'):
            with self.subTest(version=version), self.assertRaises(RuntimeError): release.number(version)

    def test_new_release_only_changes_versions_then_waits_for_exact_main_commit(self):
        api, calls = self.fixture()
        self.assertEqual(release.prepare(api, '1.1.0', BOT, lambda _: None), 'merged')
        tree = next(data for method, path, data in calls if path == 'git/trees')
        self.assertEqual(tree['base_tree'], 'base-tree')
        self.assertEqual({item['path'] for item in tree['tree']}, set(release.MANIFESTS))
        self.assertTrue(all(json.loads(item['content']) == {'name': 'o-harness', 'version': '1.1.0'} for item in tree['tree']))
        self.assertIn(('PUT', 'pulls/7/merge', {'sha': 'version', 'merge_method': 'merge'}), calls)
        self.assertIn(('GET', 'actions/workflows/verify.yml/runs?event=push&head_sha=merged&per_page=100', None), calls)

    def test_retry_before_tag_uses_verified_main_without_another_pr(self):
        api, calls = self.fixture(current='1.1.0')
        self.assertEqual(release.prepare(api, '1.1.0', BOT, lambda _: None), 'main')
        self.assertTrue(all(method == 'GET' for method, _, _ in calls))
        with self.assertRaisesRegex(RuntimeError, 'older'): release.prepare(api, '1.0.0', BOT)

    def test_tagged_retry_pins_original_source_and_rejects_foreign_history(self):
        api, calls = self.fixture(current='1.1.0', tag={'object': {'sha': 'tagged', 'type': 'commit'}})
        self.assertEqual(release.prepare(api, '1.1.0', BOT, lambda _: None), 'tagged')
        self.assertIn(('GET', 'actions/workflows/verify.yml/runs?event=push&head_sha=tagged&per_page=100', None), calls)
        self.assertTrue(all(method == 'GET' for method, _, _ in calls))
        def foreign(method, path, *args, **kwargs):
            return {'status': 'diverged'} if path.startswith('compare/') else api(method, path, *args, **kwargs)
        with self.assertRaisesRegex(RuntimeError, 'not on main'): release.prepare(foreign, '1.1.0', BOT)
        def unverified(method, path, *args, **kwargs):
            result = api(method, path, *args, **kwargs)
            if path.startswith('actions/workflows/'):
                result['workflow_runs'][0]['conclusion'] = 'failure'
            return result
        with self.assertRaisesRegex(RuntimeError, 'verification failed for tagged'):
            release.prepare(unverified, '1.1.0', BOT, lambda _: None)

    def test_merge_waits_and_refuses_changed_or_non_app_prs(self):
        def response(body, status=None):
            return Mock(returncode=1 if status else 0, stdout=json.dumps(body),
                        stderr=f'gh: Merge refused (HTTP {status})' if status else '')
        # GitHub reports "blocked" for the update restriction even for an allowed
        # publisher. The protected merge endpoint decides whether checks are ready.
        responses = [response(pull(mergeable=None)), response(pull(mergeable_state='blocked')),
                     response({}, 405), response(pull(mergeable_state='blocked')),
                     response({'merged': True, 'sha': 'merged'})]
        pause = Mock()
        with patch('release.subprocess.run', side_effect=responses) as command:
            self.assertEqual(release.merge_pr(release.GitHub('pmoreiracc/o-harness'), pull(), 'version', BOT, pause), 'merged')
            self.assertEqual(json.loads(command.call_args.kwargs['input']), {'sha': 'version', 'merge_method': 'merge'})
        self.assertEqual(pause.call_count, 2)
        for status in (403, 409, 429):
            with self.subTest(status=status), patch('release.subprocess.run', side_effect=[response(pull()), response({}, status)]):
                with self.assertRaises(release.GitHubError) as error:
                    release.merge_pr(release.GitHub('pmoreiracc/o-harness'), pull(), 'version', BOT, lambda _: None)
                self.assertEqual(error.exception.status, status)
        with patch('release.subprocess.run', side_effect=[response(pull()), response({}, 405)]):
            with self.assertRaisesRegex(RuntimeError, '30 minutes'):
                release.merge_pr(release.GitHub('pmoreiracc/o-harness'), pull(), 'version', BOT, lambda _: None, attempts=1)
        mutations = [{'user': {'login': 'someone'}}, {'head': {'sha': 'changed', 'repo': {'full_name': 'pmoreiracc/o-harness'}}},
                     {'state': 'closed'}, {'mergeable_state': 'dirty'}, {'base': {'ref': 'other'}}]
        for changes in mutations:
            fake = Mock(return_value=pull(**changes))
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                release.merge_pr(fake, pull(), 'version', BOT, lambda _: None, attempts=1)
            self.assertEqual(fake.call_count, 1)  # Never called the merge endpoint.

    def test_retry_branch_rejects_non_version_changes(self):
        api, _ = self.fixture()
        commit = {'parents': [{'sha': 'parent'}], 'files': [{'filename': path, 'status': 'modified'} for path in release.MANIFESTS]}
        def branch(method, path, *args, **kwargs):
            return commit if path == 'commits/version' else api(method, path, *args, **kwargs)
        release.validate_branch(branch, 'version', '1.1.0', 'main')
        commit['files'].append({'filename': 'runtime/oh/cli.py', 'status': 'modified'})
        with self.assertRaisesRegex(RuntimeError, 'other than'): release.validate_branch(branch, 'version', '1.1.0', 'main')
        commit['files'].pop()
        def changed(method, path, *args, **kwargs):
            if path.startswith('contents/') and path.endswith('?ref=version'):
                return {'content': base64.b64encode(b'{"name":"malicious","version":"1.1.0"}').decode()}
            return branch(method, path, *args, **kwargs)
        with self.assertRaisesRegex(RuntimeError, 'other than'): release.validate_branch(changed, 'version', '1.1.0', 'main')

    def test_main_verification_rejects_failed_wrong_commit_and_wrong_event(self):
        run = {'id': 1, 'head_sha': 'merged', 'head_branch': 'main', 'event': 'push', 'status': 'completed', 'conclusion': 'failure'}
        for changes in ({}, {'head_sha': 'other', 'conclusion': 'success'}, {'event': 'pull_request', 'conclusion': 'success'}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                release.verified(Mock(return_value={'workflow_runs': [run | changes]}), 'merged', lambda _: None, attempts=1)
        release.verified(Mock(return_value={'workflow_runs': [run | {'conclusion': 'success'}]}), 'merged', lambda _: None, attempts=1)


if __name__ == '__main__':
    unittest.main()
