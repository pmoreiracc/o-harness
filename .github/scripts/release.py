"""Owner-started version PR, protected merge, and exact-commit release selection.

No token can bypass required checks; GitHub performs the final merge authorization.
"""
import base64
import json
import os
import re
import subprocess
import time
from pathlib import Path


MANIFESTS = [f'plugins/o-harness/.{host}-plugin/plugin.json' for host in ('claude', 'codex')]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def number(version):
    require(re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version),
            'Use a numeric version such as 0.4.0, without leading zeroes.')
    return tuple(map(int, version.split('.')))


def authorize(env):
    require(env.get('GITHUB_REPOSITORY') == 'pmoreiracc/o-harness'
            and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and env.get('GITHUB_REF') == 'refs/heads/main'
            and env.get('GITHUB_ACTOR_ID') == '154069128'
            and env.get('GITHUB_TRIGGERING_ACTOR') == 'pmoreiracc',
            'Only Pedro may start or rerun Release, on main.')


class GitHubError(RuntimeError):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


class GitHub:
    def __init__(self, repo):
        self.repo = repo

    def __call__(self, method, path, data=None, missing=False):
        command = ['gh', 'api', '-H', 'X-GitHub-Api-Version: 2026-03-10', '--method', method, f'repos/{self.repo}/{path}']
        if data is not None:
            command += ['--input', '-']
        result = subprocess.run(command, input=json.dumps(data) if data is not None else None,
                                text=True, capture_output=True, check=False)
        if result.returncode:
            if missing and '(HTTP 404)' in result.stderr:
                return None
            status = re.search(r'\(HTTP (\d{3})\)', result.stderr)
            raise GitHubError(f'GitHub {method} {path}: {result.stderr.strip()}',
                              int(status[1]) if status else None)
        return json.loads(result.stdout) if result.stdout.strip() else None


def content(api, path, ref):
    data = api('GET', f'contents/{path}?ref={ref}')
    return base64.b64decode(data['content']).decode('utf-8')


def manifests(api, ref):
    texts = {path: content(api, path, ref) for path in MANIFESTS}
    versions = [json.loads(text)['version'] for text in texts.values()]
    require(len(set(versions)) == 1, 'The Claude and Codex versions differ.')
    number(versions[0])
    return versions[0], texts


def updated(text, version):
    data = json.loads(text)
    data['version'] = version
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def ancestor(api, older, newer):
    comparison = api('GET', f'compare/{older}...{newer}')
    require(comparison['status'] in ('ahead', 'identical'), 'Release source is not on main.')


def validate_branch(api, sha, version, main):
    commit = api('GET', f'commits/{sha}')
    require(len(commit['parents']) == 1, 'The release branch must contain one version commit.')
    parent = commit['parents'][0]['sha']
    ancestor(api, parent, main)
    previous, texts = manifests(api, parent)
    require(number(version) > number(previous), 'The release branch does not increase the version.')
    files = commit['files']
    require(len(files) == 2 and {f['filename'] for f in files} == set(MANIFESTS)
            and all(f['status'] == 'modified' for f in files),
            'The release branch contains changes other than the two versions.')
    for path, text in texts.items():
        require(content(api, path, sha) == updated(text, version),
                'The release branch contains changes other than the requested version.')


def validate_pr(pr, sha, bot):
    require(pr['head']['sha'] == sha and pr['head']['repo']['full_name'] == 'pmoreiracc/o-harness'
            and pr['base']['ref'] == 'main' and pr['user']['login'] == bot and not pr['draft'],
            'The release PR changed or was not created by the release App. Inspect it before retrying.')


def merge_pr(api, pr, sha, bot, pause=time.sleep, attempts=120):
    for _ in range(attempts):
        current = api('GET', f'pulls/{pr["number"]}')
        validate_pr(current, sha, bot)
        if current['merged']:
            return current['merge_commit_sha']
        require(current['state'] == 'open', 'The release PR was closed without merging.')
        require(current.get('mergeable_state') != 'dirty',
                'The release PR conflicts with main. Close it, delete its branch, and run Release again.')
        if current.get('mergeable') is True:
            # Conflict-free does not mean the required checks have passed.
            # GitHub's merge endpoint enforces required checks and the pinned SHA;
            # 405 means not mergeable yet. Never bypass checks or retry other errors.
            try:
                result = api('PUT', f'pulls/{pr["number"]}/merge',
                             {'sha': sha, 'merge_method': 'merge'})
            except GitHubError as error:
                if error.status != 405:
                    raise
            else:
                require(result.get('merged'), 'GitHub refused the protected release merge.')
                return result['sha']
        pause(15)
    raise RuntimeError('Release PR did not become mergeable in 30 minutes. Check its checks and repository rules, then rerun Release.')


def verified(api, sha, pause=time.sleep, attempts=60):
    for _ in range(attempts):
        runs = api('GET', f'actions/workflows/verify.yml/runs?event=push&head_sha={sha}&per_page=100')['workflow_runs']
        runs = [run for run in runs if run['head_sha'] == sha and run['event'] == 'push'
                and run['head_branch'] == 'main']
        if runs:
            latest = max(runs, key=lambda run: run['id'])
            if latest['status'] == 'completed':
                require(latest['conclusion'] == 'success', f'main verification failed for {sha}. Fix it before releasing.')
                return
        pause(10)
    raise RuntimeError(f'main verification did not finish for {sha} in 10 minutes. Rerun Release after it passes.')


def prepare(api, version, bot, pause=time.sleep):
    requested = number(version)
    main = api('GET', 'git/ref/heads/main')['object']['sha']
    current, texts = manifests(api, main)
    require(requested >= number(current), 'Cannot release an older version than main.')
    tag = api('GET', f'git/ref/tags/v{version}', missing=True)
    if tag:
        require(version == current, 'An existing tag cannot be reused for a new version.')
        obj = tag['object']
        while obj['type'] == 'tag':
            obj = api('GET', f'git/tags/{obj["sha"]}')['object']
        require(obj['type'] == 'commit', 'The release tag does not identify a commit.')
        sha = obj['sha']
        ancestor(api, sha, main)
        require(manifests(api, sha)[0] == version, 'The tag and plugin versions differ.')
        verified(api, sha, pause)
        return sha  # A retry always uses the original tagged, verified source.
    if version == current:
        verified(api, main, pause)
        return main  # Before publication, a retry can include a fix merged to main.

    branch = f'release/{version}'
    existing = api('GET', f'git/ref/heads/{branch}', missing=True)
    if existing:
        sha = existing['object']['sha']
        validate_branch(api, sha, version, main)
    else:
        base = api('GET', f'git/commits/{main}')['tree']['sha']
        tree = api('POST', 'git/trees', {'base_tree': base, 'tree': [
            {'path': path, 'mode': '100644', 'type': 'blob', 'content': updated(text, version)}
            for path, text in texts.items()]})['sha']
        sha = api('POST', 'git/commits', {'message': f'Release {version}', 'tree': tree, 'parents': [main]})['sha']
        api('POST', 'git/refs', {'ref': f'refs/heads/{branch}', 'sha': sha})
    prs = api('GET', f'pulls?state=open&head=pmoreiracc:{branch}&base=main')
    require(len(prs) <= 1, 'Multiple release PRs found; inspect them before retrying.')
    if prs:
        pr = prs[0]
    else:
        notes = api('POST', 'releases/generate-notes', {'tag_name': f'v{version}', 'target_commitish': main})['body']
        pr = api('POST', 'pulls', {'base': 'main', 'head': branch, 'title': f'Release {version}',
            'body': f'Pedro requested **{version}** in the Release workflow. The release App merges only this version change after required checks pass. Full Windows and installation checks still gate publication.\n\n{notes}'})
    print(f'Release PR: {pr["html_url"]}', flush=True)
    sha = merge_pr(api, pr, sha, bot, pause)
    require(manifests(api, sha)[0] == version, 'The merged plugin versions differ from the request.')
    verified(api, sha, pause)
    return sha


def main():
    authorize(os.environ)
    version = os.environ['VERSION']
    sha = prepare(GitHub(os.environ['GITHUB_REPOSITORY']), version, os.environ['RELEASE_BOT'])
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
        stream.write(f'tag=v{version}\ncommit={sha}\n')
    print(f'Release v{version} is pinned to {sha}.')


if __name__ == '__main__':
    main()
