from __future__ import annotations

from .storage import checkout_file

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
from .workflow import checkpoint, committed, load_run, next_task, reduce, review_limit


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
      'Do not change task checkboxes or document lifecycle fields; the runner renders them before review. Do not read prior task transcripts. Report concise results with evidence paths.\n')
    if role=='review':
        common+=(HOME/'prompts/invariant-reviewer.md').read_text()+'\n'
        if intake(task):
            common+=('The subject is a proposal, not code: the roadmap row, new milestone, proposed decision record or '
              'design task OH wrote from the worker\'s routing of one idea, or no change at all for an improvement. Review '
              'the routing: whether it is the right route (a roadmap row for new work that needs many PRs or has more than '
              'one defensible approach; a task in an approved design; an improvement to existing behaviour), whether the '
              'dependencies are hard edges, whether it duplicates an existing initiative, task or capability, and whether it '
              'silently decides an open question. OH owns numbers and links. The worker\'s reading of the idea: '
              +json.dumps({k:(state.get('rendered') or {}).get(k,'') for k in ('understanding','reason','evidence')},ensure_ascii=False)[:3000]+'\n')
        if designing(task):
            common+=('The subject is a plan, not code: the design doc or proposed decision record OH wrote from the '
              'worker\'s prose, plus its roadmap link or decision log row. Review the decomposition: whether the tasks '
              'cover the initiative, whether a task is really several, whether an alternative is a strawman, whether an '
              'open question would change the approach (then it belongs in a decision record), and whether the plan '
              'relies on decisions that are not accepted. OH owns the number, frontmatter and links.\n')
        common+=('You are the independent invariant reviewer with a fresh context. Read the actual diff '
          'and affected code. Challenge authorization, isolation, recovery, edge cases, dependency contracts, '
          'verification, and task scope. Do not modify any file. Only a fully clean result may say clean. '
          'Return the required JSON with every finding; unknown or missing evidence is not approval.\n')
    elif role=='analysis' and designing(task):
        common+=(HOME/'prompts/design.md').read_text()+'\n'
    elif role=='analysis' and intake(task):
        common+=(HOME/'prompts/propose.md').read_text()+'\n'
    elif role=='analysis':
        common+=('This is a read-only '+state['workflow']+' workflow. Do not edit the product or execute implementation. '
                 'Return the complete artifact in your response; OH stores it externally. '
                 'For propose, explain options, your recommendation and unresolved decisions. '
                 'For design, return a clear bounded task plan with dependencies, three-level difficulty rationale, '
                 'acceptance checks, relevant invariants and risks. Do not invent approval or impose an ADR process.\n')
    else:common+='Implement and self-review this task. The runner executes required mechanical checks afterward.\n'
    return common+text


def designing(task):
    """A task that writes a design (or its owed decision record) into the plans."""
    return (task.get('transition') or {}).get('profile')=='plans'


def intake(task):
    """A task that routes one idea: a roadmap row, a task in an approved design, or an improvement."""
    return (task.get('transition') or {}).get('profile')=='intake'


def attempt(root,journal,state,task,role,profile,feedback='',invoke=hosts.invoke):
    current=reduce(journal.records())
    if current['status'] != 'running':
        raise Refused('The run was stopped or reached a checkpoint; no new attempt started')
    state=state|{'rendered':current.get('rendered')}  # the reviewer sees what OH wrote for this attempt
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
    if role=='review' and not committed(state):
        workers=[a for a in reduce(journal.records())['attempts'] if a['role']=='analysis' and a.get('outcome')=='implemented']
        artifact=Path(workers[-1]['evidence'])/'result.json'
        from .storage import read_json
        data['artifact']={'path':str(artifact),'hash':digest(read_json(artifact))}
        prompt+='\nReview the actual planning artifact at '+str(artifact)+'. The unchanged code tree is not the review subject by itself.'
    if role=='review':
        prior=[{'id':a['id'],'outcome':a.get('outcome'),'tree':a['tree'],'git_tree':a.get('git_tree'),
                'findings':a.get('findings',[]),'resolution':state.get('resolutions',{}).get(a['id']),
                'admission':str(journal.path/'attempts'/a['id']/'request.json')}
               for a in state['attempts'] if a['task']==task['id'] and a['role']=='review']
        if len(json.dumps(prior,ensure_ascii=False))>state['config']['context']['handoff_chars']:
            raise Refused('Prior findings exceed the bounded review context. Preserve them and split/reconcile this task before further review.')
        manifest=directory/'prior-reviews.json';atomic_json(manifest,prior,immutable=True)
        data['prior_reviews']={'path':str(manifest),'hash':digest(prior)}
        prompt+='\nRead the immutable prior-review manifest '+str(manifest)+'. Resolve every retained family and its siblings; classify repeat-family/fix-regression/first-round-escape/newly-exposed against these admissions. No findings may be silently dropped.'
    atomic_json(directory/'request.json',data|{'prompt':prompt},immutable=True)
    context={'project':state['project'],'run':state['id'],'task':task['id'],'attempt':attempt_id,
             'compact_tokens':state['config']['context']['compact_at_tokens'],'controlled':True}
    started=time.monotonic()
    try:
        result=invoke(state['host'],root,profile,prompt,role,directory,context,
                      schema=hosts.REVIEW_SCHEMA if role=='review' else hosts.DESIGN_SCHEMA if designing(task) else hosts.PROPOSAL_SCHEMA if intake(task) else None)
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
        if outcome=='implemented' and (designing(task) or intake(task)):
            from .plans import answer,proposal
            try:(answer if designing(task) else proposal)(result.get('structured'))
            except Refused as exc:
                # A shapeless answer is a failed attempt; its reason is the next attempt's feedback.
                outcome='failed';result=result|{'text':f'OH could not use the answer: {exc}\n'+result['text']}
        if role=='analysis' and after!=before:
            outcome='analysis_mutated_tree';status(journal,state,'needs_attention')
    # Preserve the full raw result outside the orchestrator context.
    atomic_json(directory/'result.json',result|{'outcome':outcome,'findings':findings,'tree':after},immutable=True)
    record={'id':attempt_id,'task':task['id'],'role':role,'outcome':outcome,'tree':after,
      'findings':findings,'summary':result['text'][:state['config']['context']['result_chars']],
      'duration_ms':result['duration_ms'],'evidence':str(directory),'git_tree':git_tree,'head':data['head'],'artifact':data.get('artifact')}
    journal.append('attempt.finished',record)
    from .observability import review_metadata
    metadata=review_metadata(result['text'],findings) if role=='review' else {}
    best_effort('attempt.finished',state['project'],state['id'],task['id'],attempt_id,**metadata,
      outcome=outcome,duration_ms=result['duration_ms'],substantive=role=='review' and outcome not in ('failed','review_mutated_tree'))
    return record


def status(journal,state,value):
    from .storage import state_home
    with lock(state_home()/'checkout-state'/state['checkout']/'oh-control.lock'):
        if reduce(journal.records())['status']!='running':return
        journal.append('run.status',{'status':value})
        best_effort('run.status',state['project'],state['id'],status=value)


@state_writer
def run(root,invoke=hosts.invoke):
    from .controls import settle, Interrupted
    try:
        _run(root,invoke)
    except Interrupted:
        pass
    # An exceptional process cleanup must retain STOPPING, never report false success.
    from .controls import busy
    if not busy(root):settle(root)
    return checkpoint(root)


def _run(root,invoke):
    journal,state=load_run(root)
    lockpath=checkout_file(root, 'oh-runner.lock')
    with lock(lockpath,wait=False):
        with lock(checkout_file(root, 'oh-control.lock')):
            state=reduce(journal.records())
            if state.get('discard'):
                from .workflow import discard_proposal
                discard_proposal(root,journal,state)
                return
            if state.get('branch_move'):
                finish_move(root,journal,state)
                state=reduce(journal.records())
        # A proposal cuts its branch when it first writes; nothing runs on main before that.
        if committed(state) and state.get('workflow')!='propose' and git(root,'branch','--show-current') in ('main','master',''):
            raise Refused('Execute tasks on a short-lived branch, not main or detached HEAD')
        if git(root,'branch','--show-current')!=state['branch']:
            raise Refused('Run belongs to another branch; return to its checkout')
        from .branches import incarnation
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
            worker_attempts=[a for a in previous if a['role'] in ('implementation','analysis')]
            reviews=[a for a in previous if a['role']=='review']
            decided=state.get('proposals',{}).get(previous[-1]['id']) if intake(task) and previous else None
            if intake(task) and previous and not decided and (previous[-1].get('outcome')=='clean' or previous[-1]['id'] in state['resolutions']
                    or (previous[-1]['role']=='analysis' and (state.get('rendered') or {}).get('attempt')==previous[-1]['id']
                        and not state['rendered'].get('files'))):
                # A reviewed proposal, or an improvement with nothing to write, waits for approve, refine or reconsider.
                status(journal,state,'approval_checkpoint');return checkpoint(root)
            if decided and decided['choice']=='approve':
                complete_reviewed(root,journal,state,task,previous[-1]);continue
            if not intake(task) and previous and (previous[-1].get('outcome')=='clean' or previous[-1]['id'] in state['resolutions']):
                complete_reviewed(root,journal,state,task,previous[-1]);continue
            if len(reviews)>=review_limit(state,task_id):
                status(journal,state,'review_checkpoint');return checkpoint(root)
            feedback=''
            if previous:feedback=previous[-1].get('summary','')
            refined=bool(decided) and decided['choice']=='refine'
            if refined:feedback='The person asked you to refine the proposal: '+decided['feedback']+'\nYour previous answer: '+state['rendered'].get('summary','')
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
                and (last is retained or last.get('outcome') in ('failed','interrupted')) and not refined)
            work=retained
            if not reusable:
                parent=state['summaries'][-1].get('commit',state['base']) if state['summaries'] else state['base']
                if git(root,'rev-parse','HEAD')!=parent:raise Refused('HEAD changed outside the runner; restore the recorded task parent')
                if designing(task) or intake(task):
                    # Refuse before paying for a worker whose plan OH could not write: a human edit to the last render,
                    # or changes in the checkout that OH didn't make.
                    from .plans import Blocked,changes,layout,undo
                    rendered=reduce(journal.records()).get('rendered') or {}
                    if blocked_layout(root,state):raise Blocked(blocked_layout(root,state))
                    undo(root,rendered,check_only=True)
                    extra=[p for p in changes(root) if p not in rendered.get('intent',[])]
                    if extra:raise Blocked(f"The checkout has changes OH didn't write ({', '.join(extra[:5])}); a plan commit holds only its plan files")
                work=attempt(root,journal,state,task,'implementation' if state.get('workflow','deliver')=='deliver' else 'analysis',profile,feedback,invoke)
                if work['outcome']!='implemented':continue
            apply_pending(root)
            if reduce(journal.records())['status']!='running':return checkpoint(root)
            if designing(task) or intake(task):
                with lock(checkout_file(root,'oh-control.lock')):
                    from .controls import check
                    check(root)
                    rendered=write_plan(root,journal,state,task,work)
                if rendered is None:continue
                if intake(task) and not rendered['files']:continue  # nothing to check or review: the gate is next
            elif task.get('transition'):
                with lock(checkout_file(root,'oh-control.lock')):
                    from .controls import check
                    check(root)
                    from .design_adapter import render
                    render(root,task)
                    journal.append('subject.prepared',{'attempt':work['id'],'tree':tree(root)})
            from .checks import resolve
            # A design in a project without checks has nothing to run: delivery alone requires checks.
            checks=resolve(root,state['project_checks']+state['checks'],state['base']) if committed(state) and state['project_checks']+state['checks'] else []
            check_results=verify(root,checks,state['project'],controlled=True)
            journal.append('verification',{'task':task_id,'tree':tree(root),'checks':check_results})
            best_effort('phase.finished',state['project'],state['id'],task_id,phase='verification',
                        duration_ms=sum(r['duration_ms'] for r in check_results if not r['reused']),
                        reused=sum(r['reused'] for r in check_results),checks=len(check_results))
            if designing(task) or intake(task):
                from .plans import Blocked,changes,digest_of
                rendered=reduce(journal.records())['rendered']
                extra=[p for p in changes(root) if p not in rendered['intent']]
                if extra:raise Blocked(f"The checks left files OH didn't write ({', '.join(extra[:5])}); a plan commit holds only "
                                       'its plan files. Make the checks clean up, or list those files in .git/info/exclude, then run OH again')
                touched=[p for p in rendered['intent'] if digest_of(Path(root)/p)!=rendered['files'].get(p)]
                if touched:raise Blocked(f"A check changed {', '.join(touched)} after OH wrote it; plan files stay as OH wrote them. "
                                         'Stop the check from rewriting them, then run OH again')
                # A check that runs on every change fails for reasons a design can't fix; one scoped with `when` ran
                # because of the plan files, so its failure goes back to the worker.
                named={c['name']:c for c in checks}
                unscoped=[r['name'] for r in check_results if r['returncode'] and not named.get(r['name'],{}).get('when')]
                if unscoped:raise Blocked(f"The project's checks fail with the design in place ({', '.join(unscoped)}). A design only adds plan "
                                          'files, so fix those checks (or scope them to paths with when) and run OH again')
            if any(r['returncode'] for r in check_results):
                journal.append('verification.failed',{'attempt':work['id'],'task':task_id,
                    'summary':json.dumps(check_results)[-state['config']['context']['result_chars']:]})
                continue
            apply_pending(root)
            from .controls import check
            check(root)
            review=attempt(root,journal,state,task,'review',profiles['review'],json.dumps(check_results)[:4000],invoke)
            if review['outcome']=='clean':
                if not intake(task):complete_reviewed(root,journal,state,task,review)
            elif review['outcome']=='needs_resolution':
                status(journal,state,'findings_checkpoint');return checkpoint(root)
            elif review['outcome']=='review_mutated_tree':
                status(journal,state,'needs_attention');return checkpoint(root)
            # Blocking or failed review starts a fresh repair/review only within the same grant.


def write_plan(root,journal,state,task,work):
    """OH writes the worker's prose into the plans. A problem with the prose goes back to the worker as feedback;
    a changed checkout or setting stops the run with its reason."""
    from .plans import Blocked,render,render_proposal,undo
    from .storage import read_json
    value=read_json(Path(work['evidence'])/'result.json').get('structured')
    previous=reduce(journal.records()).get('rendered')
    if blocked_layout(root,state):raise Blocked(blocked_layout(root,state))  # before undo throws the paid answer's render away
    undo(root,previous)  # refuses to discard a human edit: that stops the run, it isn't the worker's to fix
    record=lambda intent:journal.append('subject.preparing',{'attempt':work['id'],'intent':intent})
    try:
        if intake(task):plan=render_proposal(root,value,record,lambda topic:move(root,journal,topic))
        else:plan=render(root,state['slug'],value,record)
    except Blocked:raise
    except Refused as exc:
        journal.append('verification.failed',{'attempt':work['id'],'task':task['id'],
            'summary':f'OH could not write the plan from this answer: {exc}'[-state['config']['context']['result_chars']:]})
        return None
    plan['attempt']=work['id']
    journal.append('subject.prepared',{'attempt':work['id'],'tree':tree(root),'plan':plan})
    return plan


def blocked_layout(root,state):
    """Why the plans can't be written where this run started writing them, or None."""
    from .plans import layout,layout_snapshot
    try:where=layout(root)
    except Refused as exc:return str(exc)
    if where['location']!=state['plans']['location']:return f"plans.location changed to {where['location']} during this run; set it back or stop the run"
    if layout_snapshot(where)!=state['plans']:return 'Plan paths changed during this run; restore the original plans settings and paths or stop the run'
    return None


def move(root,journal,topic):
    """Record an exact branch transition before switching or writing any plan files."""
    state=reduce(journal.records());current=git(root,'branch','--show-current')
    if state.get('branch_move'):
        finish_move(root,journal,state)
        return
    if current not in ('main','master'):return
    from .branches import incarnation
    from .plans import branch_for,Blocked
    name=branch_for(root,topic,state['id'],'propose')
    git(root,'branch',name)
    try:
        journal.append('branch.moving',{'from':current,'from_incarnation':state['incarnation'],
            'branch':name,'incarnation':incarnation(root,name,create=True),'base':state['base']})
    except Exception:
        if not reduce(journal.records()).get('branch_move'):
            git(root,'branch','-D',name)
        raise
    try:finish_move(root,journal,reduce(journal.records()))
    except Refused as exc:raise Blocked(f'Proposal branch transition is pending; run OH again after fixing: {exc}') from None


def finish_move(root,journal,state):
    from .branches import incarnation
    pending=state['branch_move'];current=git(root,'branch','--show-current')
    if (current not in (pending['from'],pending['branch']) or git(root,'status','--porcelain')
            or git(root,'rev-parse','HEAD')!=pending['base']
            or git(root,'rev-parse',pending['branch'])!=pending['base']
            or incarnation(root,pending['branch'])!=pending['incarnation']
            or incarnation(root,pending['from'])!=pending['from_incarnation']):
        raise Refused('Restore the unchanged proposal branches and recorded base before retrying the pending transition')
    if current!=pending['branch']:git(root,'switch',pending['branch'])
    journal.append('branch.moved',pending)


def apply_pending(root):
    from .authority import materialize
    materialize(root)


def complete_reviewed(root,journal,state,task,review):
    # Recover both sides of commit publication without another implementation or review.
    apply_pending(root)
    with lock(checkout_file(root, 'oh-control.lock')):
        state=reduce(journal.records())
        if state['status']!='running':return
        task_id=task['id'];expected=review.get('git_tree')
        if intake(task) and not (state.get('rendered') or {}).get('files'):
            # An approved improvement or unclear idea: nothing was written, so nothing is committed.
            journal.append('task.completed',{'task':task_id,'route':state['rendered']['route'],'summary':state['rendered']['summary'],
                'evidence':review['evidence']})
            return
        if not committed(state):
            from .storage import read_json
            artifact=review.get('artifact')
            if not artifact or digest(read_json(artifact['path']))!=artifact['hash']:
                raise Refused('The planning artifact differs from its independent review')
            if git(root,'rev-parse','HEAD')!=review['head'] or tree(root)!=review['tree']:
                raise Refused('The project changed while the planning artifact was reviewed')
            journal.append('task.completed',{'task':task_id,'artifact':artifact,'review':review['id'],
                'summary':review['summary'],'evidence':review['evidence']})
            attempts=[a for a in state['attempts'] if a['task']==task_id]
            reviews=[a for a in attempts if a['role']=='review']
            best_effort('task.finished',state['project'],state['id'],task_id,status='completed',
                expected_attempts=len(attempts),expected_reviews=len(reviews),first_review=reviews[0]['outcome'],
                wall_ms=round((datetime.now(timezone.utc)-datetime.fromisoformat(state['task_started'][task_id])).total_seconds()*1000))
            return
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
            title=(f"{state['rendered']['kind']} {state['rendered']['number']}: {state['rendered']['title']}" if designing(task) else
                   'propose: '+state['rendered']['lines'][-1][:120] if intake(task) else f"task {task_id}: {task['title']}")
            git(root,'commit','--allow-empty','-m',f"{title}\n\nOH-Run: {state['id']}\nOH-Review: {review['id']}\nOH-Reviewed-Tree: {expected}\nOH-Evidence: {digest(intent['publication'])}")
            if git(root,'rev-parse','HEAD^{tree}')!=expected or git(root,'rev-parse','HEAD^')!=head:raise Refused('Commit hooks changed the reviewed tree or parent')
        journal.append('task.completed',{'task':task_id,'commit':git(root,'rev-parse','HEAD'),'tree':expected,'review':review['id'],
            'summary':review['summary'],'evidence':review['evidence']})
        attempts=[a for a in state['attempts'] if a['task']==task_id]
        reviews=[a for a in attempts if a['role']=='review']
        best_effort('task.finished',state['project'],state['id'],task_id,status='completed',expected_attempts=len(attempts),expected_reviews=len(reviews),
            recovered=any(g['task']==task_id for g in state.get('recovery_grants',[])),confirmed_interventions=state['interventions'].get(task_id,0),first_review=reviews[0]['outcome'] if reviews else None,
            wall_ms=round((datetime.now(timezone.utc)-datetime.fromisoformat(state['task_started'][task_id])).total_seconds()*1000))
