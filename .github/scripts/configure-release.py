"""Apply the release permissions after installing the private release GitHub App.

Run as Pedro with gh authenticated. Does not read or print the App private key.
"""
import argparse
import json
import subprocess

from release import GitHub, require


REPO = 'pmoreiracc/o-harness'
OWNER_ID = 154069128
OWNER = {'actor_id': OWNER_ID, 'actor_type': 'User', 'bypass_mode': 'pull_request'}


def upsert(api, collection, body, key='name'):
    entries = api('GET', collection)
    if isinstance(entries, dict):
        entries = entries['policies']
    match = next((entry for entry in entries if entry[key] == body[key]), None)
    return api('PUT' if match else 'POST', f'{collection}/{match["id"]}' if match else collection, body)


def configure(app_id, publication=True, client_id=None):
    user = json.loads(subprocess.check_output(['gh', 'api', 'user'], text=True))
    require(user['id'] == OWNER_ID, 'Run this setup as pmoreiracc.')
    if publication:
        require(app_id and client_id, 'Provide --app-id and --client-id from the release App settings.')
    api = GitHub(REPO)
    # Both Pedro and the release App must satisfy main's existing PR and checks.
    # Do not add a restrict-updates ruleset: it forces normal merges to use bypass.
    protection = api('GET', 'branches/main/protection')
    require(protection.get('enforce_admins', {}).get('enabled')
            and protection.get('required_pull_request_reviews') is not None
            and {check['context'] for check in protection['required_status_checks']['checks']}
                >= {'checks (native)', 'checks (syntax)', 'windows'},
            'Restore main PR/check protections before enabling release automation.')
    actors = [OWNER]
    if app_id:
        require(app_id > 0, 'Use the numeric ID of the App installed on this repository.')
        actors.append({'actor_id': app_id, 'actor_type': 'Integration', 'bypass_mode': 'pull_request'})
    api('PUT', 'environments/release', {'deployment_branch_policy': {'protected_branches': False, 'custom_branch_policies': True}})
    policies = api('GET', 'environments/release/deployment-branch-policies')['branch_policies']
    require(all(p['name'] == 'main' and p['type'] == 'branch' for p in policies),
            'Remove non-main branch/tag permissions from the release environment.')
    if not policies:
        api('POST', 'environments/release/deployment-branch-policies', {'name': 'main', 'type': 'branch'})
    if not publication:
        print('Prepared release environment. Publication settings await the App and merged PR.')
        return
    variable = 'environments/release/variables/RELEASE_APP_CLIENT_ID'
    existing = api('GET', variable, missing=True)
    api('PATCH' if existing else 'POST', variable if existing else 'environments/release/variables',
        {'name': 'RELEASE_APP_CLIENT_ID', 'value': client_id})
    api('GET', 'environments/release/secrets/RELEASE_APP_PRIVATE_KEY')  # Metadata only, never the secret value.
    owners_only = ['.github/workflows/release.yml', '.github/workflows/prepare-release.yml',
                   '.github/workflows/full.yml', '.github/workflows/install-check.yml']
    upsert(api, 'actions/policies', {'name': 'Only Pedro can run release workflows', 'enforcement': 'active',
        'conditions': {'workflow_path': {'include': owners_only, 'exclude': []}},
        'rules': [{'type': 'restrict_actions_actors', 'parameters': {'allowed_actors': [{'id': OWNER_ID, 'type': 'User'}]}}]})
    upsert(api, 'actions/policies', {'name': 'Other workflows run automatically only', 'enforcement': 'active',
        'conditions': {'workflow_path': {'include': ['~ALL'], 'exclude': owners_only}},
        'rules': [{'type': 'restrict_action_events', 'parameters': {'allowed_events': ['pull_request', 'push', 'schedule', 'workflow_call']}}]})
    publishers = [actor | {'bypass_mode': 'always'} for actor in actors]
    for name, target, pattern in [('Only release publishers may update dist', 'branch', 'refs/heads/dist'),
                                  ('Only release publishers may create tags', 'tag', 'refs/tags/v*')]:
        rules = [{'type': 'creation'}]
        if target == 'branch':
            rules += [{'type': 'update'}, {'type': 'deletion'}]
        upsert(api, 'rulesets', {'name': name, 'target': target, 'enforcement': 'active',
            'conditions': {'ref_name': {'include': [pattern], 'exclude': []}}, 'bypass_actors': publishers, 'rules': rules})
    upsert(api, 'rulesets', {'name': 'Published version tags cannot move', 'target': 'tag', 'enforcement': 'active',
        'conditions': {'ref_name': {'include': ['refs/tags/v*'], 'exclude': []}}, 'bypass_actors': [],
        'rules': [{'type': 'update'}, {'type': 'deletion'}]})
    api('PUT', 'actions/permissions/workflow', {'default_workflow_permissions': 'read', 'can_approve_pull_request_reviews': True})
    print('Release permissions configured. Only Pedro can start Release; the App can merge its version PR under the existing checks.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-id', type=int)
    parser.add_argument('--client-id')
    parser.add_argument('--prepare', action='store_true', help='Set up release environment without changing existing publication permissions')
    args = parser.parse_args()
    require(args.prepare or (args.app_id and args.client_id),
            'Provide --app-id and --client-id, or use --prepare before App setup.')
    configure(args.app_id, publication=not args.prepare, client_id=args.client_id)
