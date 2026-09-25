from __future__ import annotations

from .storage import state_writer

import json
from datetime import datetime,timezone
import time
from pathlib import Path
from . import hosts
from .config import HOME
from .storage import Refused, atomic_json, digest, git, identifier, lock
from .telemetry import best_effort
from .verification import tree, verify, candidate_tree
from .workflow import checkpoint, load_run, next_task, reduce, review_limit


def prompt_for(root,state,task,role,feedback=''):
    contracts=[]
    for name in ('.oh/invariants.md','AGENTS.md','CLAUDE.md'):
        if (Path(root)/name).is_file():contracts.append(name)
    limit=state['config']['context']['handoff_chars']
    content={'task':task,'role':role,'project_contracts':contracts,'feedback':feedback,
      'run':state['id'],'config_hash':state['config_hash']}
    text=json.dumps(content,ensure_ascii=False)
    if len(text)>limit:
        raise Refused('Task handoff exceeds configured context bound; split the task or reference files')
    common=('Work only on the supplied task. Read the listed project contracts and relevant source files. '
      'You are not alone in this checkout: preserve other edits. Do not delegate, grant tasks, change OH '
      'configuration/evidence, commit, push, merge, or open a PR. The runner owns those transitions. '
      'Do not read prior task transcripts. Report concise results with evidence paths.\n')
    if role=='review':
        common+=(HOME/'prompts/invariant-reviewer.md').read_text()+'\n'
        common+=('You are the independent invariant reviewer with a fresh context. Read the actual diff '
          'and affected code. Challenge authorization, isolation, recovery, edge cases, dependency contracts, '
          'verification, and task scope. Do not modify any file. Only a fully clean result may say clean. '
          'Return the required JSON with every finding; unknown or missing evidence is not approval.\n')
    else:common+='Implement and self-review this task. The runner executes required mechanical checks afterward.\n'
    return common+text


def attempt(root,journal,state,task,role,profile,feedback='',invoke=hosts.invoke):
    if reduce(journal.records())['status'] != 'running':
        raise Refused('The run was stopped or reached a checkpoint; no new attempt started')
    print(f"OH task {task['id']}: {role} · {profile['model']} / {profile['effort']}",flush=True)
    attempt_id=identifier();before=tree(root)
    git_tree=candidate_tree(root) if role=='review' else None
    directory=journal.path/'attempts'/attempt_id
    data={'id':attempt_id,'task':task['id'],'role':role,'profile':profile,'tree':before,
          'head':git(root,'rev-parse','HEAD'),'config_hash':state['config_hash'],
          'harness_version':state['harness_version'],'git_tree':git_tree,'config':state['config'],'root':str(root)}
    journal.append('attempt.started',data)
    best_effort('attempt.started',state['project'],state['id'],task['id'],attempt_id,
      role=role,phase='review' if role=='review' else ('repair' if feedback else 'implementation'),
      host=state['host'],model=profile['model'],effort=profile['effort'])
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    prompt=prompt_for(root,state,task,role,feedback)
    if role=='review':prompt+='\nOH NATIVE REVIEW ADMISSION: '+str(directory/'request.json')
    atomic_json(directory/'request.json',data|{'prompt':prompt},immutable=True)
    context={'project':state['project'],'run':state['id'],'task':task['id'],'attempt':attempt_id,
             'compact_tokens':state['config']['context']['compact_at_tokens']}
    started=time.monotonic()
    try:
        result=invoke(state['host'],root,profile,prompt,role,directory,context,
                      schema=hosts.REVIEW_SCHEMA if role=='review' else None)
    except Exception as exc:
        result={'failed':True,'returncode':-1,'text':str(exc),'structured':None,
                'duration_ms':round((time.monotonic()-started)*1000),'usage_observed':False}
    after=tree(root)
    if git(root,'rev-parse','HEAD')!=data['head']:
        atomic_json(directory/'result.json',result|{'outcome':'history_changed'},immutable=True)
        journal.append('attempt.finished',{'id':attempt_id,'outcome':'history_changed','summary':'Child changed HEAD; restore the recorded parent before resuming'})
        status(journal,state,'needs_attention')
        raise Refused('Child changed Git history; preserve its work and restore the recorded parent before resuming')
    if role=='review':
        outcome,findings=hosts.review_result(result)
        if after!=before:outcome='review_mutated_tree'
    else:
        outcome='failed' if result['failed'] else 'implemented';findings=[]
    # Preserve the full raw result outside the orchestrator context.
    atomic_json(directory/'result.json',result|{'outcome':outcome,'findings':findings,'tree':after},immutable=True)
    record={'id':attempt_id,'task':task['id'],'role':role,'outcome':outcome,'tree':after,
      'findings':findings,'summary':result['text'][:state['config']['context']['result_chars']],
      'duration_ms':result['duration_ms'],'evidence':str(directory),'git_tree':git_tree,'head':data['head']}
    journal.append('attempt.finished',record)
    from .observability import review_metadata
    metadata=review_metadata(result['text'],findings) if role=='review' else {}
    best_effort('attempt.finished',state['project'],state['id'],task['id'],attempt_id,**metadata,
      outcome=outcome,duration_ms=result['duration_ms'],substantive=role=='review' and outcome not in ('failed','review_mutated_tree'))
    return record


def status(journal,state,value):
    journal.append('run.status',{'status':value})
    best_effort('run.status',state['project'],state['id'],status=value)


@state_writer
def run(root,invoke=hosts.invoke):
    journal,state=load_run(root)
    lockpath=Path(git(root,'rev-parse','--absolute-git-dir'))/'oh-runner.lock'
    with lock(lockpath,wait=False):
        if git(root,'branch','--show-current') in ('main','master',''):
            raise Refused('Execute tasks on a short-lived branch, not main or detached HEAD')
        if git(root,'branch','--show-current')!=state['branch']:
            raise Refused('Run belongs to another branch; return to its checkout')
        from .initial import incarnation
        if incarnation(root,state['branch'])!=state['incarnation']:
            raise Refused('This branch was recreated; its old run cannot grant authority')
        from .config import version
        if version()!=state['harness_version']:
            raise Refused('Resume with the harness revision that owns this run; upgrades cannot change in-flight authority')
        # An interrupted attempt consumes its slot; a restart never silently erases it.
        for pending in [a for a in state['attempts'] if not a['finished']]:
            journal.append('attempt.finished',{'id':pending['id'],'outcome':'interrupted','summary':'Interrupted before durable completion'})
            best_effort('attempt.finished',state['project'],state['id'],pending['task'],pending['id'],outcome='interrupted',substantive=False)
        while True:
            apply_pending(root)
            state=reduce(journal.records());task=next_task(state)
            if not task:
                if state['status']=='running':
                    status(journal,state,'completed' if len(state['done'])==len(state['tasks']) else 'checkpoint')
                return checkpoint(root)
            task_id=task['id'];task_start=time.monotonic()
            previous=[a for a in state['attempts'] if a['task']==task_id]
            if task_id not in state['task_started']:
                journal.append('task.started',{'task':task_id})
                state=reduce(journal.records())
                best_effort('task.started',state['project'],state['id'],task_id,
                  title=task['title'],difficulty=task['difficulty'],rubric=state['rubric_version'])
            profiles=state['config']['models'][state['host']]
            profile=profiles[task['difficulty']]
            worker_attempts=[a for a in previous if a['role']=='implementation']
            reviews=[a for a in previous if a['role']=='review']
            if previous and (previous[-1].get('outcome')=='clean' or previous[-1]['id'] in state['resolutions']):
                complete_reviewed(root,journal,state,task,previous[-1]);continue
            if len(reviews)>=review_limit(state,task_id):
                status(journal,state,'review_checkpoint');return checkpoint(root)
            feedback=''
            if previous:feedback=previous[-1].get('summary','')
            # Bounded escalation persists through restarts and repairs.
            failures=sum(a.get('outcome') in ('failed','interrupted','verification_failed') for a in worker_attempts)
            failures-=max([g['spent_before'] for g in state.get('recovery_grants',[]) if g['task']==task_id]+[0])
            if failures>state['config']['max_escalations']:
                status(journal,state,'needs_attention');return checkpoint(root)
            if failures:profile=profiles['complex']
            last=previous[-1] if previous else None
            # A completed implementation can resume at verification without another model call.
            retained=worker_attempts[-1] if worker_attempts else None
            reusable=(retained and retained.get('outcome')=='implemented' and retained.get('tree')==tree(root)
                and (last is retained or last.get('outcome') in ('failed','interrupted')))
            work=retained
            if not reusable:
                parent=state['summaries'][-1]['commit'] if state['summaries'] else state['base']
                if git(root,'rev-parse','HEAD')!=parent:raise Refused('HEAD changed outside the runner; restore the recorded task parent')
                work=attempt(root,journal,state,task,'implementation',profile,feedback,invoke)
                if work['outcome']!='implemented':continue
            apply_pending(root)
            if reduce(journal.records())['status']!='running':return checkpoint(root)
            from .checks import resolve
            checks=resolve(root,state['project_checks']+state['checks'],state['base'])
            check_results=verify(root,checks,state['project'])
            journal.append('verification',{'task':task_id,'tree':tree(root),'checks':check_results})
            best_effort('phase.finished',state['project'],state['id'],task_id,phase='verification',
                        duration_ms=sum(r['duration_ms'] for r in check_results if not r['reused']),
                        reused=sum(r['reused'] for r in check_results),checks=len(check_results))
            if any(r['returncode'] for r in check_results):
                journal.append('verification.failed',{'attempt':work['id'],'task':task_id,
                    'summary':json.dumps(check_results)[-state['config']['context']['result_chars']:]})
                continue
            review=attempt(root,journal,state,task,'review',profiles['review'],json.dumps(check_results)[:4000],invoke)
            if review['outcome']=='clean':
                complete_reviewed(root,journal,state,task,review)
            elif review['outcome']=='needs_resolution':
                status(journal,state,'findings_checkpoint');return checkpoint(root)
            elif review['outcome']=='review_mutated_tree':
                status(journal,state,'needs_attention');return checkpoint(root)
            # Blocking or failed review starts a fresh repair/review only within the same grant.


def apply_pending(root):
    from .authority import materialize
    materialize(root)


def complete_reviewed(root,journal,state,task,review):
    # Recover both sides of commit publication without another implementation or review.
    apply_pending(root)
    with lock(Path(git(root,'rev-parse','--absolute-git-dir'))/'oh-control.lock'):
        state=reduce(journal.records())
        if state['status']!='running':return
        task_id=task['id'];expected=review.get('git_tree')
        if not expected:raise Refused('Review predates exact Git-tree binding; a fresh review is required')
        intent=state['commit_intents'].get(task_id)
        head=git(root,'rev-parse','HEAD')
        already=False
        if intent and head!=intent['parent']:
            message=git(root,'log','-1','--format=%B')
            already=(git(root,'rev-parse','HEAD^')==intent['parent'] and
                git(root,'rev-parse','HEAD^{tree}')==expected and
                f"OH-Run: {state['id']}" in message and f"OH-Review: {review['id']}" in message and
                intent.get('publication') is not None and f"OH-Evidence: {digest(intent['publication'])}" in message)
            if not already:raise Refused('HEAD changed after review; cannot recover this commit intent')
            if git(root,'status','--porcelain'):raise Refused('Preserve new edits before recovering the reviewed commit')
        if not already:
            if head!=review.get('head'):raise Refused('HEAD differs from the reviewed parent')
            if review['tree']!=tree(root) or candidate_tree(root)!=expected:raise Refused('The retained review does not cover the current tree')
            git(root,'add','--all')
            if git(root,'write-tree')!=expected:raise Refused('The staged tree differs from the reviewed Git tree')
            if not intent:
                from .publication import task_evidence
                publication=task_evidence(state,task,review,head)
                intent={'task':task_id,'review':review['id'],'git_tree':expected,'parent':head,'publication':publication}
                journal.append('commit.intent',intent)
            if not intent.get('publication'):raise Refused('This older commit intent needs fresh portable review evidence before publication')
            git(root,'commit','--allow-empty','-m',f"task {task_id}: {task['title']}\n\nOH-Run: {state['id']}\nOH-Review: {review['id']}\nOH-Reviewed-Tree: {expected}\nOH-Evidence: {digest(intent['publication'])}")
            if git(root,'rev-parse','HEAD^{tree}')!=expected or git(root,'rev-parse','HEAD^')!=head:raise Refused('Commit hooks changed the reviewed tree or parent')
        journal.append('task.completed',{'task':task_id,'commit':git(root,'rev-parse','HEAD'),'tree':expected,'review':review['id'],
            'summary':review['summary'],'evidence':review['evidence']})
        attempts=[a for a in state['attempts'] if a['task']==task_id]
        reviews=[a for a in attempts if a['role']=='review']
        best_effort('task.finished',state['project'],state['id'],task_id,status='completed',expected_attempts=len(attempts),expected_reviews=len(reviews),
            recovered=any(g['task']==task_id for g in state.get('recovery_grants',[])),confirmed_interventions=state['interventions'].get(task_id,0),first_review=reviews[0]['outcome'] if reviews else None,
            wall_ms=round((datetime.now(timezone.utc)-datetime.fromisoformat(state['task_started'][task_id])).total_seconds()*1000))
