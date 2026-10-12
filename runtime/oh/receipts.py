"""Readable, deterministic views of retained evidence; these views never grant authority."""
import os
from pathlib import Path
import tempfile
from .storage import Refused, digest, read_json, sync_directory
from .system import replace


def save(path, text, *, immutable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = text.encode('utf-8')
    if path.is_symlink():raise Refused('A readable receipt cannot be a symlink')
    if immutable and path.exists():
        if path.read_bytes() != data:raise Refused('The original readable receipt was changed; authoritative JSON is retained')
        return
    fd, temporary = tempfile.mkstemp(prefix='.receipt-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        if immutable:os.link(temporary, path)
        else:replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def seconds(value):
    return f'{value/1000:.1f}s' if isinstance(value, (int, float)) else 'not recorded'


def finding(finding):
    from html import escape
    finding={k:escape(v) if isinstance(v,str) else v for k,v in finding.items()}
    claim=finding['description'].splitlines() or ['Not recorded.']
    lines = [f"### [{finding['severity'].upper()}] {claim[0]}", *('> '+line for line in claim[1:]), '']
    for title, key in (('Anchor', 'anchor'), ('Where', 'path'), ('Failure', 'failure'), ('Resolve', 'fix'),
                       ('Family', 'family'), ('Relation', 'relation')):
        value = finding.get(key) or 'Not recorded in this receipt.'
        lines.extend([f'**{title}:**', *('> '+line for line in str(value).splitlines()), ''])
    return '\n'.join(lines)


def request(directory, admission):
    packet = read_json(admission['task_context']['path'])
    task = packet['task']
    lines = [f"# Task {task['id']} — {admission['role']} request", '',
             f"**Task:** {task['title']}", f"**HEAD:** {admission['head']}",
             f"**Working tree:** {admission['tree']}",
             f"**Reviewed Git tree:** {admission.get('git_tree') or 'Not applicable.'}",
             f"**Context SHA-256:** {admission['task_context']['hash']}", '',
             '## Approved scope', '', task['instructions'], '', '## Current work', '']
    current = packet['current_work']
    lines.append(current['summary'] if current else 'No earlier author report for this task.')
    readiness = current.get('readiness') if current else None
    if isinstance(readiness, dict):
        labels = {'requirements':'Requirements covered', 'rules':'Rules checked', 'surfaces':'Affected surfaces',
                  'proof':'Claims and proof', 'self_review':'Adversarial self-review', 'family_closure':'Defect-family closure',
                  'prior_findings':'Prior finding dispositions', 'verification':'Verification', 'repairs':'Check repairs', 'limits':'Limits'}
        for key, title in labels.items():
            lines.extend(['', '## '+title, ''])
            items = readiness.get(key)
            if items is None:lines.append('Not recorded by this older author report.')
            elif not items:lines.append('None reported.')
            else:
                for item in items:
                    lines.append('- '+(f"{item['id']} | {item['disposition']} | {item['proof']}" if isinstance(item, dict) else item))
    lines.extend(['', '## Remaining work', '', packet['remaining_work'] or 'Complete the approved task and required checks.', '',
                  '## Evidence', '', '[Task context](task-context.json) · [Finding index](finding-index.json) · [Native admission](request.json)', '',
                  'Author readiness contains claims to verify. The journal and native evidence govern authority.', ''])
    save(Path(directory)/'request.md', '\n'.join(lines), immutable=True)


def completed(directory, admission, result, record, state):
    role = record['role']
    rounds = sum(a['task'] == record['task'] and a['role'] == 'review' for a in state['attempts'])
    title = f'Review {rounds}' if role == 'review' else role.capitalize()+' report'
    profile = admission.get('profile') or {}
    lines = [f"# Task {record['task']} — {title}", '',
        f"**Branch:** {state['branch']}", f"**OH revision:** {admission.get('harness_version', 'Not recorded')}", f"**Outcome at return:** {record['outcome']}",
        f"**Model:** {profile.get('model', 'Not recorded')} / {profile.get('effort', 'Not recorded')}",
        f"**Elapsed:** {seconds(record.get('duration_ms'))}", f"**HEAD:** {admission['head']}",
        f"**Reviewed tree:** {admission.get('git_tree') or admission['tree']}",
        f"**Attempt:** {record['id']}", f"**Result SHA-256:** {digest(read_json(Path(directory)/'result.json'))}", '']
    if role == 'review':
        lines.extend(['## Findings', ''])
        lines.extend(finding(f) for f in record.get('findings', []))
        if not record.get('findings'):lines.append('No findings.' if record['outcome'] == 'clean' else 'No completed verdict; inspect the retained result.')
    lines.extend(['', '## Summary', '', record.get('human_summary') or record.get('summary') or 'Not recorded.'])
    value = result.get('structured') or {}
    if isinstance(value, dict) and isinstance(value.get('evidence'), dict):
        for key in ('anchors', 'lenses', 'attacks', 'limits'):
            lines.extend(['', '## '+key.capitalize(), ''])
            evidence = value['evidence'].get(key, [])
            if isinstance(evidence, dict):lines.extend(f'- **{k}:** {v}' for k,v in evidence.items())
            else:lines.extend('- '+str(v) for v in evidence)
    lines.extend(['', '[Request](request.md) · [Original result](result.json)', '',
                  'This immutable view records the attempt at return. Later dispositions appear in the run index; only native evidence authorizes completion.', ''])
    save(Path(directory)/('review.md' if role == 'review' else 'report.md'), '\n'.join(lines), immutable=True)


def index(journal, state):
    lines = [f"# {state.get('name', 'Project')} — {state.get('workflow', 'deliver')}", '',
             f"**Branch:** {state['branch']}", f"**Current state:** {state['status']}",
             f"**Completed tasks:** {', '.join(state['done']) or 'None'}", '']
    for task in state['tasks']:
        attempts = [a for a in state['attempts'] if a['task'] == task['id']]
        if not attempts:continue
        lines.extend([f"## Task {task['id']}: {task['title']}", '',
                      '| Attempt | Model | Outcome | Elapsed |', '|---|---|---|---|'])
        rounds = 0
        for attempt in attempts:
            role = attempt['role']
            if role == 'review':rounds += 1
            label = f'Review {rounds}' if role == 'review' else role.capitalize()
            filename = 'review.md' if role == 'review' else 'report.md'
            relative = f"attempts/{attempt['id']}/{filename}"
            if not (journal.path/relative).is_file():relative = f"attempts/{attempt['id']}/result.json"
            profile = attempt.get('profile') or {}
            lines.append(f"| [{label}]({relative}) | {profile.get('model', 'Not recorded')} | {attempt.get('outcome', 'Running')} | {seconds(attempt.get('duration_ms'))} |")
            resolution = state.get('resolutions', {}).get(attempt['id'])
            scope = state.get('scope_records', {}).get(attempt['id'])
            if resolution:lines.append(f"| Decision | | {resolution['choice']} | |")
            if scope:lines.append(f"| Scope | | {scope['action']} | |")
        lines.append('')
        from .handoff import finding_index
        findings=finding_index(state,task['id'])
        if findings['families']:
            lines.extend(['### Finding dispositions', '', 'Author repair claims are separate from the last independent review and human decisions.', ''])
            from html import escape
            for family in findings['families']:
                for item in family['occurrences']:
                    original=item['id'].split('#')[0]
                    lines.append(f"- [{escape(item['id'])}](attempts/{original}/result.json): **{item['disposition']}** ({escape(family['family'])}).")
                    if item.get('reviewed_by'):
                        lines.append(f"  Confirmed by [review](attempts/{item['reviewed_by']}/result.json).")
                    if claim:=item.get('author_claim'):
                        lines.append(f"  Author [claim](attempts/{claim['attempt']}/result.json): {escape(claim['disposition'])} — {escape(claim['proof'])}.")
            lines.append('')
    lines.extend(['This index is a current view. Original requests, results and receipts remain unchanged.', ''])
    save(journal.path/'index.md', '\n'.join(lines))
