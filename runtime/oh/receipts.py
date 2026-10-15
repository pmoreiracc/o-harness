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
    packet_path = Path(admission['task_context']['path'])
    packet = read_json(packet_path)
    if packet.get('details'):
        details = packet['details']
        detail_path = Path(details['path'])
        if not detail_path.is_absolute():detail_path = packet_path.parent / detail_path
        full = read_json(detail_path)
        if digest(full) != details['hash']:raise Refused('Retained task details changed')
        packet = full
    task = packet['task']
    standalone=admission.get('purpose')=='standalone'
    lines = [('# Standalone review request' if standalone else f"# Task {task['id']} — {admission['role']} request"), '',
             f"**Purpose:** {admission.get('purpose','workflow')}",
             f"**{'Subject' if standalone else 'Task'}:** {task['title']}", f"**HEAD:** {admission['head']}",
             f"**Working tree:** {admission['tree']}",
             f"**{'Checkout guard Git tree' if standalone else 'Reviewed Git tree'}:** {admission.get('git_tree') or 'Not applicable.'}",
             f"**Context SHA-256:** {admission['task_context']['hash']}", '',
             '## Approved scope', '', task['instructions'], '', '## Current work', '']
    if standalone:
        selected=packet.get('standalone_subject') or {}
        lines.extend(['**Selected revision:** '+str(selected.get('revision') or selected.get('head') or 'Working changes'),
                      '**Selected Git tree:** '+str(selected.get('git_tree') or 'Not recorded'), ''])
    if original:=packet.get('included_original_work'):
        lines.extend(['## Included original PR work','',original.get('url',''),
                      'Review the original range `'+original['review_base']+'..'+original['head']+'` together with the repair candidate.',
                      'Included original commits: '+', '.join(original.get('covers',[]))+'.',''])
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
    remaining=packet['remaining_work'] or ('Independently review the current task and its verification evidence.' if admission['role']=='review'
                                         else 'Complete the approved task and required checks.')
    lines.extend(['', '## Remaining work', '', remaining, '',
                  '## Evidence', '', '[Task context](task-context.json) · [Finding index](finding-index.json) · [Native admission](request.json)', '',
                  'Author readiness contains claims to verify. The journal and native evidence govern authority.', ''])
    save(Path(directory)/'request.md', '\n'.join(lines), immutable=True)


def completed(directory, admission, result, record, state):
    role = record['role']
    rounds = sum(a['task'] == record['task'] and a['role'] == 'review' for a in state['attempts'])
    standalone=admission.get('purpose')=='standalone'
    title = 'Standalone review' if standalone else f'Review {rounds}' if role == 'review' else role.capitalize()+' report'
    profile = admission.get('profile') or {}
    lines = [('# Standalone review' if standalone else f"# Task {record['task']} — {title}"), '',
        '**Purpose:** '+admission.get('purpose','workflow'),
        f"**Branch:** {state['branch']}", f"**OH revision:** {admission.get('harness_version', 'Not recorded')}", f"**Outcome at return:** {record['outcome']}",
        f"**Host:** {admission.get('host', state['host'])}",
        f"**Model:** {profile.get('model', 'Not recorded')} / {profile.get('effort', 'Not recorded')}",
        f"**Elapsed:** {seconds(record.get('duration_ms'))}", f"**HEAD:** {admission['head']}",
        f"**{'Checkout guard tree' if standalone else 'Reviewed tree'}:** {admission.get('git_tree') or admission['tree']}",
        f"**Attempt:** {record['id']}", f"**Result SHA-256:** {digest(read_json(Path(directory)/'result.json'))}", '']
    if standalone:
        selected=state.get('standalone_subject') or {}
        lines.extend(['**Selected revision:** '+str(selected.get('revision') or selected.get('head') or 'Working changes'),
                      '**Selected Git tree:** '+str(selected.get('git_tree') or 'Not recorded'), ''])
    if role == 'review':
        lines.extend(['## Findings', ''])
        lines.extend(finding(f) for f in record.get('findings', []))
        if not record.get('findings'):lines.append('No findings.' if record['outcome'] == 'clean' else 'No completed verdict; inspect the retained result.')
    lines.extend(['', '## Summary', '', record.get('human_summary') or record.get('summary') or 'Not recorded.'])
    if record.get('report_issues'):
        lines.extend(['','## Report limitations','',*('- '+item for item in record['report_issues'])])
    if record.get('review_fragments'):
        import json
        lines.extend(['','## Unclassified findings','',*('    '+json.dumps(item,ensure_ascii=False) for item in record['review_fragments'])])
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
    def artifact(label, relative):
        return f'[{label}]({relative})' if (journal.path/relative).is_file() else label+' (not yet available)'
    standalone=state.get('workflow')=='review'
    lines = [f"# {state.get('name', 'Project')} — "+('Standalone review' if standalone else state.get('workflow','deliver')), '',
             f"**Branch:** {state['branch']}", f"**Current state:** {'published' if state.get('published') else state['status']}",
             (f"**Subject:** {state['subject']['description']}" if standalone else f"**Completed tasks:** {', '.join(state['done']) or 'None'}"), '']
    if published:=state.get('published'):
        lines.extend([f"**Delivery finished:** [PR #{published['number']}]({published['url']})",
                      f"Publication verified at {published['verified_at']}; reviewed commit `{published['approved_head']}`. Current PR checks and later commits are separate from this receipt.", ''])
    for task in state['tasks']:
        attempts = [a for a in state['attempts'] if a['task'] == task['id']]
        if not attempts:continue
        lines.extend([('## Standalone review' if state.get('workflow')=='review' else f"## Task {task['id']}: {task['title']}"), '',
                      '| Attempt | Host / model | Outcome | Elapsed |', '|---|---|---|---|'])
        rounds = 0
        for attempt in attempts:
            role = attempt['role']
            if role == 'review':rounds += 1
            label = ('Standalone review' if attempt.get('purpose')=='standalone' else f'Review {rounds}') if role == 'review' else role.capitalize()
            filename = 'review.md' if role == 'review' else 'report.md'
            relative = f"attempts/{attempt['id']}/{filename}"
            if not (journal.path/relative).is_file():relative = f"attempts/{attempt['id']}/result.json"
            link=artifact(label,relative) if attempt.get('finished') else label
            profile = attempt.get('profile') or {}
            outcome=attempt.get('outcome', 'Incomplete' if attempt.get('finished') else 'Running')
            lines.append(f"| {link} | {attempt.get('host', 'Not recorded')} / {profile.get('model', 'Not recorded')} | {outcome} | {seconds(attempt.get('duration_ms'))} |")
            resolution = state.get('resolutions', {}).get(attempt['id'])
            scope = state.get('scope_records', {}).get(attempt['id'])
            if resolution:lines.append(f"| Decision | | {resolution['choice']} | |")
            if scope:lines.append(f"| Scope | | {scope['action']} | |")
            if attempt.get('normalized_report'):
                lines.append(f"| Handoff correction | | "+artifact('Unambiguous legacy references',f"attempts/{attempt['id']}/normalized-report.json")+"; original outcome retained | |")
        lines.append('')
        from .handoff import finding_index
        findings=finding_index(state,task['id'])
        if findings['incomplete_reviews']:
            lines.extend(['### Incomplete review evidence',''])
            for item in findings['incomplete_reviews']:
                link=f"[Original review](attempts/{item['attempt']}/result.json)" if item.get('report') else f"Review {item['attempt']} (result unavailable)"
                lines.append(f"- {link}: "+'; '.join(item.get('issues') or [item['note']]))
            lines.append('')
        if findings['families']:
            lines.extend(['### Finding dispositions', '', 'Author repair claims are separate from the last independent review and human decisions.', ''])
            from html import escape
            for family in findings['families']:
                for item in family['occurrences']:
                    original=item['id'].split('#')[0]
                    label=item['disposition']
                    if label=='still-open' and item.get('author_claim',{}).get('disposition')=='fixed':label='Awaiting review confirmation'
                    if label=='fixed' and item.get('reviewed_by'):label='Confirmed by review'
                    relative=f"attempts/{original}/result.json"
                    link=f"[{escape(item['id'])}]({relative})" if (journal.path/relative).is_file() else escape(item['id'])+' (result unavailable)'
                    lines.append(f"- {link}: **{label}** ({escape(family['family'])}).")
                    if item.get('reviewed_by'):
                        lines.append('  Confirmed by '+artifact('review',f"attempts/{item['reviewed_by']}/result.json")+'.')
                    if claim:=item.get('author_claim'):
                        lines.append('  Implementer '+artifact('claim',f"attempts/{claim['attempt']}/result.json")+f": {escape(claim['disposition'])} — {escape(claim['proof'])}.")
            lines.append('')
    lines.extend(['This index is a current view. Original requests, results and receipts remain unchanged.', ''])
    save(journal.path/'index.md', '\n'.join(lines))
