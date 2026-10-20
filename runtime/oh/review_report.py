"""Small review decisions; the accompanying receipt is never interpreted as control data."""
import json
import re

PREFIX = 'OH-REVIEW-DECISION: '
SEVERITIES = ('blocking', 'concern', 'scope')


def read(text):
    # A native hand-back may introduce the decision with a short summary. Quoted
    # examples are receipt content, and competing decisions are never first/last-wins.
    lines=text.splitlines(keepends=True);decisions=[];fence=None
    for index,line in enumerate(lines):
        stripped=line.strip()
        marker=re.match(r'^ {0,3}(`{3,}|~{3,})',line)
        if marker:
            token=marker[1]
            if fence is None:fence=token
            elif token[0]==fence[0] and len(token)>=len(fence):fence=None
            continue
        if fence is None and (index==0 or len(line)-len(line.lstrip(' '))<=3 and not line.startswith('\t')) and stripped.startswith(PREFIX):decisions.append(index)
    if len(decisions)>1:
        return {'summary':text,'findings':[]}, ['Multiple review decisions; preserve the complete report and resolve the ambiguity.']
    structured=bool(decisions)
    index=decisions[0] if structured else 0
    header=lines[index].strip() if lines else ''
    receipt=''.join(lines[:index]+lines[index+1:]) if structured else ''
    candidate = header[len(PREFIX):] if structured else text.strip()
    # Compatibility with explicit JSON reports already used by native hosts.
    if candidate.startswith('```json\n') and candidate.endswith('\n```'):
        candidate = candidate[len('```json\n'):-len('\n```')]
    try:value = json.loads(candidate)
    except (ValueError, TypeError):value = None
    if not isinstance(value, dict):
        return {'summary': text, 'findings': []}, ['Missing structured review decision; keep the full receipt and check the decision before finishing.']
    report = dict(value)
    report.pop('decision_format', None)
    if structured:report.update(decision_format=1, receipt=receipt)
    findings = report.get('findings')
    issues = []
    if not isinstance(findings, list):issues.append('Decision findings must be a list.')
    else:
        for number, finding in enumerate(findings, 1):
            if not isinstance(finding, dict) or finding.get('severity') not in SEVERITIES or not isinstance(finding.get('description'), str) or not finding['description'].strip():
                issues.append(f'Finding #{number} needs a severity and a concrete description.')
            elif structured and (not isinstance(finding.get('family'), str) or not finding['family'].strip()):
                issues.append(f'Finding #{number} needs a stable family identifier.')
    verdict = report.get('verdict')
    # Existing JSON producers expressed findings directly, without a separate verdict.
    if not structured and verdict is None and isinstance(findings, list) and findings:
        report['verdict'] = verdict = 'findings'
    allowed = ('clean', 'findings', 'incomplete') + (() if structured else SEVERITIES)
    if verdict not in allowed:issues.append('Decision verdict must be clean, findings or incomplete.')
    elif (verdict == 'clean' and findings) or (verdict == 'findings' and not findings):
        issues.append('Decision verdict and finding list disagree.')
    if structured and not ''.join(lines[index+1:]).strip():issues.append('Keep the full review receipt after the decision line.')
    return report, issues


def check(text):
    _, issues = read(text)
    return {'valid': not issues, 'issues': issues,
            'next': 'Return this complete report as the native final result.' if not issues else 'Correct the decision in this reviewer turn, then check again. No new reviewer or allowance is needed.'}
