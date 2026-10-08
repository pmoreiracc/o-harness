from __future__ import annotations

from .storage import checkout_file

from .storage import state_writer

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime,timezone
import time
from pathlib import Path
from . import hosts
from .config import HOME
from .storage import Refused, atomic_json, changes, digest, git, identifier, lock, whole
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
    if designing(task) or intake(task):
        location=state['plans']['location']
        content['planning']={'location':location,'design_approval':'human_gate' if location=='private' else 'human_merge'}
        content['human_refinements']=[{'source':answer['source'],'feedback':answer['feedback']}
            for answer in state.get('proposal_answers',[]) if answer['choice']=='refine']
    text=json.dumps(content,ensure_ascii=False)
    if len(text)>limit:
        raise Refused('Task handoff exceeds configured context bound; split the task or reference files')
    common=('Work only on the supplied task. Read the listed project contracts and relevant source files. '
      'You are not alone in this checkout: preserve other edits. Do not delegate, grant tasks, change OH '
      'configuration/evidence, commit, push, merge, or open a PR. The runner owns those transitions. '
      'Do not change task checkboxes or document lifecycle fields; the runner renders them before review. Do not read prior task transcripts. Report concise results with evidence paths.\n')
    if designing(task) or intake(task):
        common+=('Use the supplied planning context for approval claims: human_gate means a human approves '
                 'the private design after review; human_merge means a human merges the repository design PR. '
                 'Neither an author nor a reviewer grants approval. The supplied human_refinements are recorded '
                 'human directions for this planning task: apply them with the original scope; newer directions '
                 'supersede conflicting older ones. A review finding or renewed review allowance does not reverse '
                 'them. Use them to interpret existing planning prose; do not claim the human direction lacks '
                 'evidence when it is supplied here. If a real project invariant conflicts, explain the specific '
                 'conflict instead of silently replacing the requested approach.\n')
    if intake(task):common+=(HOME/'prompts/proposal-routing.md').read_text()+'\n'
    if role=='review':
        common+=(HOME/'prompts/invariant-reviewer.md').read_text()+'\n'
        if intake(task):
            common+=('The subject is a proposal, not code: the roadmap row, new milestone, proposed decision record or '
              'design task OH wrote from the worker\'s routing of one idea, after the person approved exactly these lines. '
              'A finding that would move the idea or change what is written is blocking: OH then asks the person again. '
              'Review the routing against the shared proposal routing policy above, whether the '
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
    else:
        common+=('Implement exactly this task, then self-review. The runner executes required mechanical checks afterward. '
          'Open every other file your change makes a claim about; confirm the claim or narrow it to what you verified. '
          'For every protection you add or change, list the ways around it, search for sibling paths, and close them together. '
          'Every testable rule you write in a doc must name its test, and the test must name the doc. '
          'Fix review blockers and concerns as defect families: fix the root cause, search every sibling, and close the '
          'whole family together; never patch only the reported line. '
          'The approved scope never grows. Do not implement unrelated gaps or entries under Open review scope or Scope decisions. '
          'Return actionable unrelated gaps in found_along_way, never in the change. Routine verification notes, '
          'absence of sibling paths and unchanged documentation belong in summary, not found_along_way. '
          'Do not edit plan files; OH records those notes. '
          'Return summary with claims and evidence for requirements, rules, affected surfaces, self-review attacks, family closure, '
          'prior finding dispositions, verification and limits. The reviewer will challenge these claims.\n')
    if role=='analysis':
        common+=('Self-review the proposed document against the project rules, its referenced claims and failure paths '
                 'before returning it. For review fixes, close the whole defect family across the document and its tasks, '
                 'preserve earlier fixes, and check whether the replacement introduces a new failure or makes a source '
                 'claim stale. Report the checks and limits concisely in your summary.\n')
    if state['host']=='claude' and hosts.WINDOWS:
        common+=('On Windows this worker has no shell: read and edit files only. OH runs the project\'s checks '
                 'afterwards and sends failures back to you.\n')
    return common+text


def designing(task):
    """A task that writes a design (or its owed decision record) into the plans."""
    return (task.get('transition') or {}).get('profile')=='plans'


def intake(task):
    """A task that routes one idea: a roadmap row, a task in an approved design, or an improvement."""
    return (task.get('transition') or {}).get('profile')=='intake'


def gated(state,task):
    """Whether a reviewed design waits for the person's approve, refine or cancel: one whose plans are private
    (in the repository, merging its pull request approves it). A proposal asks before it writes; see `accepted`."""
    return designing(task) and not committed(state)


def accepted(state):
    """The person's answer to the proposal OH showed last: 'approve' when their latest answer approved exactly
    these lines at this place (so a repair that writes the same passes, and one that changes them asks again),
    'refine' when they asked for a change to it, None while they haven't answered."""
    shown=state['preview']['plan'];answers=state.get('proposal_answers',[])
    if not answers:return None
    last=answers[-1]
    if last['choice']=='refine':return 'refine' if last['attempt']==state['preview']['attempt'] else None
    return 'approve' if last.get('shown')==approved(shown) else None


def approved(plan):
    """What an approval of a proposal covers: where it goes and everything OH writes, into which files."""
    return {k:plan.get(k) for k in ('route','intent','lines','writes')}


def attempt(root,journal,state,task,role,profile,feedback='',invoke=hosts.invoke):
    current=reduce(journal.records())
    if current['status'] != 'running':
        raise Refused('The run was stopped or reached a checkpoint; no new attempt started')
    state=current  # the reviewer sees what OH wrote for this attempt
    from .delivery import guard
    guard(root,state)
    if state.get('plans',{}).get('location')=='private' and blocked_layout(root,current):raise Refused(blocked_layout(root,current))
    fallback=None;profile_error=None
    # Injected executors own their capabilities. Native selection precedes immutable admission.
    if invoke is hosts.invoke:
        from .capabilities import select_profile
        try:profile,fallback=select_profile(state['host'],profile,root)
        except Exception as exc:profile_error=exc
    if fallback and not any(a.get('model_fallback',{}).get('notice')==fallback['notice'] for a in state['attempts']):
        print(fallback['notice'],file=sys.stderr,flush=True)
    # Progress goes to stderr: stdout carries only the result, which tools and scripts read.
    action=('OH’s independent reviewer agent is checking' if role=='review' else
            'OH’s planning agent is drafting' if role=='analysis' else 'OH’s implementation agent is building')
    print(f"{action} task {task['id']}: {' '.join(task['title'].split())[:200]} ({profile['model']} / {profile['effort']}).",file=sys.stderr,flush=True)
    attempt_id=identifier();before=tree(root)
    git_tree=candidate_tree(root) if role=='review' else None
    directory=journal.path/'attempts'/attempt_id
    data={'id':attempt_id,'task':task['id'],'role':role,'profile':profile,'tree':before,
          'head':git(root,'rev-parse','HEAD'),'config_hash':state['config_hash'],
          'harness_version':state['harness_version'],'git_tree':git_tree,'config':state['config'],'root':str(root)}
    if fallback:data['model_fallback']=fallback
    journal.append('attempt.started',data)
    best_effort('attempt.started',state['project'],state['id'],task['id'],attempt_id,
      role=role,phase='review' if role=='review' else ('repair' if feedback else 'implementation'),
      host=state['host'],model=profile['model'],effort=profile['effort'])
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if state.get('plans',{}).get('location')=='private' or state.get('delivery',{}).get('layout',{}).get('location')=='private':
        from .plans import private_inputs,layout
        data['private_inputs']=private_inputs(layout(root))
    prompt=prompt_for(root,state,task,role,feedback)
    if role=='review':prompt+='\nOH NATIVE REVIEW ADMISSION: '+str(directory/'request.json')
    if role=='review' and git_tree:
        # The exact code change as a file, for reviewers without a shell (Claude on Windows) and everyone else.
        diff=subprocess.run(['git','-C',str(root),'diff','--no-color','--no-ext-diff','--text','--no-textconv','HEAD',git_tree],capture_output=True,check=True,
                            env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}).stdout
        (directory/'change.diff').write_bytes(diff)
        data['diff']={'path':str(directory/'change.diff'),'sha256':hashlib.sha256(diff).hexdigest()}
        prompt+='\nThe exact code change under review, from HEAD to the reviewed tree, is in '+str(directory/'change.diff')+'.'
    if role=='review' and (covers:=state.get('delivery',{}).get('covers')) and not state['summaries']:
        # Commits OH didn't make: the person's own, and merges of the base branch resolved by the agent or the person (for those,
        # what the resolution changed beyond Git's own merge).
        text=b''.join(subprocess.run(['git','-C',str(root),'show','--remerge-diff','--no-color','--no-ext-diff',commit],capture_output=True,check=True,
                                     env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}).stdout for commit in covers)
        (directory/'covered.diff').write_bytes(text)
        data['covers']={'commits':covers,'path':str(directory/'covered.diff'),'sha256':hashlib.sha256(text).hexdigest()}
        prompt+=('\nThis branch also holds commits OH did not make: '+', '.join(covers)+' (the person\'s own, or merges of the base branch '
                 'resolved by hand). What each changed, for a merge beyond Git\'s own merge, is in '+str(directory/'covered.diff')
                 +'. Review it as part of this subject: a '
                 'resolution that loses either side\'s intent, changes more than the conflict needs, or edits the plans beyond '
                 'the base branch\'s version and this branch\'s recorded progress is a blocker.')
    if role=='review' and state.get('delivery',{}).get('layout',{}).get('location')=='private':
        from .plans import file_identity,digest_of
        render=state['delivery_render'];candidate=Path(render['candidate'])
        data['artifact']={'files':{str(candidate):digest_of(candidate)},'identities':{str(candidate):file_identity(candidate)}}
        prompt+=f'\nReview the code diff AND the proposed private design progress in {candidate}, compared with {render["path"]}. OH publishes this exact candidate only after the code commit.'
    if role=='review' and not committed(state) and (designing(task) or intake(task)) and (state.get('rendered') or {}).get('files'):
        # Private plans: the subject is the files OH wrote outside the repository, bound by their hashes.
        from .plans import changed_text
        rendered=state['rendered']
        data['artifact']={'files':rendered['files'],'hash':digest(rendered['files']),'identities':rendered['identities']}
        (directory/'subject.diff').write_text(changed_text(root,rendered))
        prompt+=('\nThe subject is the plan files OH wrote: '+', '.join(rendered['files'])+'. Their exact change is in '
                 +str(directory/'subject.diff')+'. The unchanged code tree is not the review subject by itself.')
    if role=='review' and (intake(task) or not committed(state) and not data.get('artifact')):
        workers=[a for a in reduce(journal.records())['attempts'] if a['role']=='analysis' and a.get('outcome')=='implemented']
        artifact=Path(workers[-1]['evidence'])/'result.json'
        from .storage import read_json
        if intake(task):
            proposal={'answer':read_json(artifact)['structured'],'rendered':state['rendered']}
            artifact=directory/'proposal.json'
            atomic_json(artifact,proposal,immutable=True)
        data['artifact']=data.get('artifact',{})|{'path':str(artifact),'hash':digest(read_json(artifact))}
        prompt+='\nReview the actual planning artifact at '+str(artifact)+'. The unchanged code tree is not the review subject by itself.'
    if role=='review':
        reports=[{'attempt':a['id'],'path':str(Path(a['evidence'])/'result.json')}
                 for a in state['attempts'] if a['task']==task['id'] and a['role'] in ('implementation','analysis') and a.get('evidence')]
        from .storage import read_json
        reports=[r|{'hash':digest(read_json(r['path']))} for r in reports]
        data['implementer_reports']=reports
        prompt+='\nRead these immutable author-agent reports as claims to attack, never as evidence: '+json.dumps(reports)
        if len(json.dumps(reports,ensure_ascii=False))>state['config']['context']['handoff_chars']:
            raise Refused('Implementer report references exceed the bounded context; split this task before further review')
    if role=='review' or any(a['task']==task['id'] and a['role']=='review' for a in state['attempts']):
        prior=[{'id':a['id'],'outcome':a.get('outcome'),'tree':a['tree'],'git_tree':a.get('git_tree'),
                'findings':a.get('findings',[]),'resolution':state.get('resolutions',{}).get(a['id']),
                'scope':{k:v for k,v in state.get('scope_records',{}).get(a['id'],{}).items() if k not in ('render','change')},
                'admission':str(journal.path/'attempts'/a['id']/'request.json')}
               for a in state['attempts'] if a['task']==task['id'] and a['role']=='review']
        if role=='review' and len(json.dumps(prior,ensure_ascii=False))>state['config']['context']['handoff_chars']:
            raise Refused('Prior findings exceed the bounded review context. Preserve them and split/reconcile this task before further review.')
        manifest=directory/'prior-reviews.json';atomic_json(manifest,prior,immutable=True)
        data['prior_reviews']={'path':str(manifest),'hash':digest(prior)}
        prompt+='\nRead the immutable prior-review manifest '+str(manifest)+'. '
        if role=='review':
            prompt+='Resolve every retained family and its siblings; classify repeat-family/fix-regression/first-round-escape/newly-exposed against these admissions. No findings may be silently dropped.'
        else:
            prompt+=('Use it to preserve earlier fixes and human dispositions while carrying out the supplied feedback. '
                     'History is not additional task scope or permission to reopen accepted, dismissed or routed findings. '
                     'Do not read prior task transcripts.')
    atomic_json(directory/'request.json',data|{'prompt':prompt},immutable=True)
    context={'project':state['project'],'run':state['id'],'task':task['id'],'attempt':attempt_id,
             'compact_tokens':state['config']['context']['compact_at_tokens'],'controlled':True}
    started=time.monotonic()
    try:
        if profile_error:raise profile_error
        result=invoke(state['host'],root,profile,prompt,role,directory,context,
                      schema=hosts.REVIEW_SCHEMA if role=='review' else hosts.DESIGN_SCHEMA if designing(task) else hosts.PROPOSAL_SCHEMA if intake(task) else hosts.WORK_SCHEMA if role=='implementation' else None)
    except Exception as exc:
        result={'failed':True,'returncode':-1,'text':str(exc),'structured':None,
                'duration_ms':round((time.monotonic()-started)*1000),'usage_observed':False}
    after=tree(root)
    private_changed='private_inputs' in data and private_inputs(layout(root))!=data['private_inputs']
    delivery_changed=''
    try:guard(root,state)
    except Refused as exc:delivery_changed=str(exc)
    if private_changed and state.get('delivery'):delivery_changed='A worker changed private delivery documents; preserve edits and stop the run'
    if git(root,'rev-parse','HEAD')!=data['head']:
        atomic_json(directory/'result.json',result|{'outcome':'history_changed'},immutable=True)
        journal.append('attempt.finished',{'id':attempt_id,'outcome':'history_changed','summary':'Child changed HEAD; restore the recorded parent before resuming'})
        status(journal,state,'needs_attention')
        raise Refused('Child changed Git history; preserve its work and restore the recorded parent before resuming')
    if role=='review':
        outcome,findings=hosts.review_result(result)
        if after!=before or private_changed:outcome='review_mutated_tree'
        if 'files' in (data.get('artifact') or {}):
            from .plans import current_files,file_identity,resolved
            if current_files(root,data['artifact']['files'])!=data['artifact']['files']:outcome='review_mutated_tree'
            if {p:file_identity(resolved(root,p)) for p in data['artifact']['files']}!=data['artifact']['identities']:
                outcome='review_mutated_tree'
    else:
        outcome='failed' if result['failed'] else 'implemented';findings=[]
        if outcome=='implemented' and (designing(task) or intake(task)):
            from .plans import answer,proposal
            try:(answer if designing(task) else proposal)(result.get('structured'))
            except Refused as exc:
                # A shapeless answer is a failed attempt; its reason is the next attempt's feedback.
                outcome='failed';result=result|{'text':f'OH could not use the answer: {exc}\n'+result['text']}
        if role=='analysis' and (after!=before or private_changed):
            outcome='analysis_mutated_tree';status(journal,state,'needs_attention')
    if delivery_changed:
        outcome='delivery_context_changed';result=result|{'text':delivery_changed+'\n'+result['text']}
        status(journal,state,'needs_attention')
    answer=result.get('structured')
    notes=answer.get('found_along_way',[]) if role=='implementation' and isinstance(answer,dict) else []
    if not isinstance(notes,list) or any(not isinstance(n,str) for n in notes):
        notes=[];outcome='failed';result=result|{'text':'The implementing report needs found_along_way as a list of strings'}
    # Preserve the full raw result outside the orchestrator context.
    atomic_json(directory/'result.json',result|{'outcome':outcome,'findings':findings,'tree':after},immutable=True)
    record={'found_along_way':notes,'id':attempt_id,'task':task['id'],'role':role,'outcome':outcome,'tree':after,
      'findings':findings,'summary':result['text'][:state['config']['context']['result_chars']],
      'duration_ms':result['duration_ms'],'evidence':str(directory),'git_tree':git_tree,'head':data['head'],'artifact':data.get('artifact')}
    if isinstance(answer,dict) and isinstance(answer.get('summary'),str):
        record['human_summary']=answer['summary'][:state['config']['context']['result_chars']]
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
        import contextlib
        _,state=load_run(root)
        from .plans import editing
        with editing(root) if state.get('delivery') else contextlib.nullcontext():
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
                if not state['discard'].get('resume'):return
                state=reduce(journal.records())
            if state['status'] in ('paused','pausing','stopped','stopping','completed','pr'):return
            if state['status']=='prepared_checkpoint':return  # showing tasks has granted no branch or execution
            if state.get('branch_creation'):
                create_proposal_branch(root,journal,state)
                state=reduce(journal.records())
            if state.get('branch_move'):
                finish_move(root,journal,state)
                state=reduce(journal.records())
        # A proposal cuts its branch when it first writes; nothing runs on main before that.
        from .branches import trunk
        if committed(state) and state.get('workflow')!='propose' and git(root,'branch','--show-current') in (trunk(root,state['config']),''):
            raise Refused('Execute tasks on a short-lived branch, not the base branch or detached HEAD')
        if git(root,'branch','--show-current')!=state['branch']:
            raise Refused('Run belongs to another branch; return to its checkout')
        from .branches import incarnation
        if incarnation(root,state['branch'])!=state['incarnation']:
            raise Refused('This branch was recreated; its old run cannot grant authority')
        from .config import version
        if version()!=state['harness_version']:
            raise Refused('Resume with the harness revision that owns this run; upgrades cannot change in-flight authority')
        from .delivery import recover
        recover(root,state)
        # An interrupted attempt consumes its slot; a restart never silently erases it.
        for pending in [a for a in state['attempts'] if not a['finished']]:
            journal.append('attempt.finished',{'id':pending['id'],'outcome':'interrupted','summary':'Interrupted before durable completion'})
            best_effort('attempt.finished',state['project'],state['id'],pending['task'],pending['id'],outcome='interrupted',substantive=False)
        while True:
            apply_pending(root)
            state=reduce(journal.records())
            if state['status']=='running':recover(root,state)
            task=next_task(state)
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
            decided=state.get('proposals',{}).get(previous[-1]['id']) if gated(state,task) and previous else None
            if intake(task) and previous and previous[-1]['role']=='analysis' and previous[-1].get('outcome')=='implemented':
                # A proposal shows the person what it would write, and writes only what they approved.
                if (state.get('preview') or {}).get('attempt')!=previous[-1]['id']:
                    show(root,journal,state,task,previous[-1]);continue
                answer=accepted(state)
                if not answer:
                    unwrite(root,journal,state,previous[-1]['id'])
                    status(journal,reduce(journal.records()),'approval_checkpoint');return checkpoint(root)
                if answer=='refine':decided=state['proposal_answers'][-1]
                elif not state['preview']['plan']['lines']:
                    # An approved improvement or unclear idea: nothing to write, so nothing to review or commit.
                    plan=state['preview']['plan']
                    journal.append('task.completed',{'task':task_id,'route':plan['route'],'summary':plan['summary'],
                        'evidence':previous[-1]['evidence']})
                    observe_completion(state,task_id)
                    continue
            if gated(state,task) and previous and not decided and (previous[-1].get('outcome')=='clean' or previous[-1]['id'] in state['resolutions']):
                # Every route waits for independent review before human approval.
                status(journal,state,'approval_checkpoint');return checkpoint(root)
            if decided and decided['choice']=='approve':
                complete_reviewed(root,journal,state,task,previous[-1]);continue
            rerendered=bool(previous and state.get('scope_records',{}).get(previous[-1]['id'],{}).get('render'))
            if not gated(state,task) and previous and (previous[-1].get('outcome')=='clean' or previous[-1]['id'] in state['resolutions'] and not rerendered):
                complete_reviewed(root,journal,state,task,previous[-1]);continue
            if previous and previous[-1]['role']=='review' and previous[-1].get('outcome')=='blocking':
                from .scope import record
                record(root,journal,state,previous[-1],'route','required by blocker-plus-scope policy')
                state=reduce(journal.records())
            if len(reviews)>=review_limit(state,task_id):
                status(journal,state,'review_checkpoint');return checkpoint(root)
            feedback=''
            if previous:
                last=previous[-1]
                if last['role']=='review':
                    feedback=json.dumps([f for f in last.get('findings',[]) if f['severity'] in ('blocking','concern')],ensure_ascii=False)
                    if last.get('outcome') in ('failed','interrupted'):feedback='The reviewer could not finish. Recheck the authorized task only.'
                else:feedback=last.get('summary','')
            refined=bool(decided) and decided['choice']=='refine'
            if refined:feedback='The person asked you to refine the proposal: '+decided['feedback']+'\nYour previous answer: '+(
                state['preview']['plan'] if intake(task) else state['rendered']).get('summary','')
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
            if rerendered and previous[-1]['id'] in state['resolutions'] and retained and retained.get('outcome')=='implemented':reusable=True
            if retained and retained.get('outcome')=='verification_failed':feedback=retained['summary']
            work=retained
            existing=designing(task) and task['transition'].get('existing')
            if existing and not refined and (not previous or all(a['role']=='review' and a.get('outcome') in ('failed','interrupted') for a in previous)):
                # A private design someone edited: its first review is of the doc as it is, with no worker.
                if not state.get('rendered'):
                    from .plans import existing_plan
                    journal.append('subject.existing',{'plan':existing_plan(root,existing)})
                work=None
            elif not reusable:
                parent=state['summaries'][-1].get('commit',state['base']) if state['summaries'] else state['base']
                if git(root,'rev-parse','HEAD')!=parent:raise Refused('HEAD changed outside the runner; restore the recorded task parent')
                if designing(task) or intake(task):
                    # Refuse before paying for a worker whose plan OH could not write: a human edit to the last render,
                    # or changes in the checkout that OH didn't make.
                    from .plans import Blocked,layout,undo
                    rendered=reduce(journal.records()).get('rendered') or {}
                    if blocked_layout(root,state):raise Blocked(blocked_layout(root,state))
                    undo(root,rendered,check_only=True)
                    extra=[p for p in changes(root) if p not in rendered.get('intent',[])]
                    if extra:raise Blocked(f"The checkout has changes OH didn't write ({', '.join(extra[:5])}); a plan commit holds only its plan files")
                work=attempt(root,journal,state,task,'implementation' if state.get('workflow','deliver')=='deliver' else 'analysis',profile,feedback,invoke)
                if work['outcome']!='implemented' or intake(task):continue  # a proposal is shown before it is written
            apply_pending(root)
            if reduce(journal.records())['status']!='running':return checkpoint(root)
            if (designing(task) or intake(task)) and work is not None:
                with lock(checkout_file(root,'oh-control.lock')):
                    from .controls import check
                    check(root)
                    rendered=write_plan(root,journal,state,task,work)
                if rendered is None:continue
            elif task.get('transition') and not (designing(task) or intake(task)):
                with lock(checkout_file(root,'oh-control.lock')):
                    from .controls import check
                    check(root)
                    if state.get('delivery'):
                        from .delivery import render
                        render(root,journal,reduce(journal.records()),task)
                    else:
                        from .design_adapter import render
                        render(root,task)
                    journal.append('subject.prepared',{'attempt':work['id'],'tree':tree(root)})
            if work and work.get('found_along_way'):
                from .scope import record
                if record(root,journal,reduce(journal.records()),work,'noted','implementing agent observation'):
                    journal.append('subject.prepared',{'attempt':work['id'],'tree':tree(root)})
            from .checks import resolve
            # Plans run no project checks: OH validates every plan write itself and undoes one that breaks a rule.
            checks=(resolve(root,state['project_checks']+state['checks'],state['base'])
                    if committed(state) and not (designing(task) or intake(task)) and state['project_checks']+state['checks'] else [])
            print(f"OH is checking task {task_id} before handing it to the independent reviewer agent.",file=sys.stderr,flush=True)
            check_results=verify(root,checks,state['project'],controlled=True)
            journal.append('verification',{'task':task_id,'tree':tree(root),'checks':check_results})
            best_effort('phase.finished',state['project'],state['id'],task_id,phase='verification',
                        duration_ms=sum(r['duration_ms'] for r in check_results if not r['reused']),
                        reused=sum(r['reused'] for r in check_results),checks=len(check_results))
            if designing(task) or intake(task):
                from .plans import validate_outputs,layout
                validate_outputs(root,reduce(journal.records())['rendered'],layout(root)['base'])
            if any(r['returncode'] for r in check_results):
                journal.append('verification.failed',{'attempt':work['id'],'task':task_id,
                    'summary':json.dumps(check_results)[-state['config']['context']['result_chars']:]})
                continue
            apply_pending(root)
            from .controls import check
            check(root)
            review=attempt(root,journal,state,task,'review',profiles['review'],json.dumps(check_results)[:4000],invoke)
            if review['outcome']=='clean':
                if not gated(state,task):complete_reviewed(root,journal,state,task,review)
            elif review['outcome']=='needs_resolution':
                status(journal,state,'findings_checkpoint');return checkpoint(root)
            elif review['outcome']=='review_mutated_tree':
                status(journal,state,'needs_attention');return checkpoint(root)
            # Blocking or failed review starts a fresh repair/review only within the same grant.


def write_plan(root,journal,state,task,work):
    from .plans import editing
    with editing(root):return _write_plan(root,journal,state,task,work)


def _write_plan(root,journal,state,task,work):
    """OH writes the worker's prose into the plans. A problem with the prose goes back to the worker as feedback;
    a changed checkout or setting stops the run with its reason."""
    from .plans import Blocked,render,render_proposal,undo
    from .storage import read_json
    value=read_json(Path(work['evidence'])/'result.json').get('structured')
    previous=reduce(journal.records()).get('rendered')
    if blocked_layout(root,state):raise Blocked(blocked_layout(root,state))  # before undo throws the paid answer's render away
    undo(root,previous)  # refuses to discard a human edit: that stops the run, it isn't the worker's to fix
    def record(intent,before=None):
        journal.append('subject.preparing',{'attempt':work['id'],'intent':intent}|({'before':before} if before is not None else {}))
    try:
        if intake(task):plan=render_proposal(root,value,record,lambda topic:move(root,journal,topic))
        else:plan=render(root,state['slug'],value,record,existing=task['transition'].get('existing'))
    except Blocked:raise
    except Refused as exc:
        journal.append('verification.failed',{'attempt':work['id'],'task':task['id'],
            'summary':f'OH could not write the plan from this answer: {exc}'[-state['config']['context']['result_chars']:]})
        return None
    plan['attempt']=work['id']
    journal.append('subject.prepared',{'attempt':work['id'],'tree':tree(root),'plan':plan})
    return plan


def show(root,journal,state,task,work):
    """What OH would write for the worker's proposal, worked out without writing anything, for the person to
    approve first. It is exactly what OH writes after approval: the checkout stays clean on the same commit, and
    private plans can't change during the run. An answer OH couldn't write goes back to the worker."""
    from .plans import Blocked,preview_proposal
    from .storage import read_json
    if blocked_layout(root,state):raise Blocked(blocked_layout(root,state))
    unwrite(root,journal,state,work['id'])  # a repair's lines are worked out from the plans as they were
    try:plan=preview_proposal(root,read_json(Path(work['evidence'])/'result.json').get('structured'))
    except Blocked:raise
    except Refused as exc:
        journal.append('verification.failed',{'attempt':work['id'],'task':task['id'],
            'summary':f'OH could not write the plan from this answer: {exc}'[-state['config']['context']['result_chars']:]})
        return
    journal.append('proposal.preview',{'attempt':work['id'],'plan':plan})


def unwrite(root,journal,state,attempt):
    """Put back what OH wrote for a proposal and leave the branch it cut: before a repair's lines are worked out,
    and before the person decides on lines, so nothing is written while they do. `attempt` is the worker attempt
    whose checkout this becomes."""
    rendered=state.get('rendered') or {}
    if not rendered.get('files'):return
    from .plans import undo
    if state.get('moved_from'):
        from .workflow import discard_proposal
        from .branches import incarnation
        target=state['moved_from']
        journal.append('proposal.discard',{'branch':state['branch'],'incarnation':state['incarnation'],
            'base':state['base'],'return_to':target,'return_incarnation':incarnation(root,target),'resume':True})
        discard_proposal(root,journal,reduce(journal.records()))
    else:undo(root,rendered)
    journal.append('subject.cleared',{'attempt':attempt,'tree':tree(root)})


def blocked_layout(root,state):
    """Why the plans can't be written where this run started writing them, or None."""
    from .plans import layout,layout_snapshot,private_drift
    try:where=layout(root)
    except Refused as exc:return str(exc)
    if where['location']!=state['plans']['location']:return f"plans.location changed to {where['location']} during this run; set it back or stop the run"
    if layout_snapshot(where)!=state['plans']:return 'Plan paths changed during this run; restore the original plans settings and paths or stop the run'
    if private_drift(root,state):return 'Private plan files changed after the run started or after review; preserve the edits and stop this run'
    return None


def move(root,journal,topic):
    """Record an exact branch transition before switching or writing any plan files."""
    state=reduce(journal.records());current=git(root,'branch','--show-current')
    if state.get('branch_move'):
        finish_move(root,journal,state)
        return
    from .branches import trunk
    if current!=trunk(root,state['config']):return
    from .plans import branch_for,Blocked
    name=branch_for(root,topic,state['id'],'propose')
    journal.append('branch.creating',{'from':current,'from_incarnation':state['incarnation'],
        'branch':name,'base':state['base'],'reflog':'branch: Created for proposal '+state['id']})
    create_proposal_branch(root,journal,reduce(journal.records()))
    try:finish_move(root,journal,reduce(journal.records()))
    except Refused as exc:raise Blocked(f'Proposal branch transition is pending; run OH again after fixing: {exc}') from None


def create_proposal_branch(root,journal,state):
    """Recover ref creation from durable intent before binding its incarnation and switching."""
    from .branches import incarnation
    pending=state['branch_creation'];name=pending['branch'];ref='refs/heads/'+name
    if (git(root,'branch','--show-current')!=pending['from'] or changes(root)
            or git(root,'rev-parse','HEAD')!=pending['base'] or incarnation(root,pending['from'])!=pending['from_incarnation']):
        raise Refused('Restore the unchanged original proposal branch before retrying its creation')
    if not git(root,'branch','--list',name):
        # Compare-and-create also refuses a concurrently created ref. The ordinary Git reflog
        # reason identifies this creation if the process dies before its incarnation is saved.
        git(root,'update-ref','--create-reflog','-m',pending['reflog'],ref,pending['base'],'0'*len(pending['base']))
    if (git(root,'rev-parse',ref)!=pending['base'] or git(root,'reflog','show','-1','--format=%gs',ref)!=pending['reflog']):
        raise Refused('The pending proposal branch was changed or created elsewhere; preserve it and resolve the branch name before retrying')
    try:
        journal.append('branch.moving',pending|{'incarnation':incarnation(root,name,create=True)})
    except Exception:
        if not reduce(journal.records()).get('branch_move'):
            from subprocess import CalledProcessError
            try:git(root,'update-ref','-d',ref,pending['base'])
            except CalledProcessError:
                raise Refused('The proposal branch changed during cleanup; preserve it and inspect it before retrying') from None
        raise


def finish_move(root,journal,state):
    from .branches import incarnation
    pending=state['branch_move'];current=git(root,'branch','--show-current')
    if (current not in (pending['from'],pending['branch']) or changes(root)
            or git(root,'rev-parse','HEAD')!=pending['base']
            or git(root,'rev-parse',pending['branch'])!=pending['base']
            or incarnation(root,pending['branch'])!=pending['incarnation']
            or incarnation(root,pending['from'])!=pending['from_incarnation']):
        raise Refused('Restore the unchanged proposal branches and recorded base before retrying the pending transition')
    if current!=pending['branch']:git(root,'switch',pending['branch'])
    journal.append('branch.moved',pending)


def apply_pending(root):
    """Apply the person's menu answers and typed choices while the run works. A typed command that starts other
    work waits for the agent's next `run`, and never stops this one."""
    from .authority import materialize,waiting_work
    if not waiting_work(root):materialize(root)


def observe_completion(state,task_id):
    """Completion has the same dashboard record for code, private plans and no-write assessments."""
    attempts=[a for a in state['attempts'] if a['task']==task_id]
    reviews=[a for a in attempts if a['role']=='review']
    best_effort('task.finished',state['project'],state['id'],task_id,status='completed',
        expected_attempts=len(attempts),expected_reviews=len(reviews),
        recovered=any(g['task']==task_id for g in state.get('recovery_grants',[])),
        confirmed_interventions=state['interventions'].get(task_id,0),first_review=reviews[0]['outcome'] if reviews else None,
        wall_ms=round((datetime.now(timezone.utc)-datetime.fromisoformat(state['task_started'][task_id])).total_seconds()*1000))


def complete_reviewed(root,journal,state,task,review):
    # Recover both sides of commit publication without another implementation or review.
    apply_pending(root)
    with lock(checkout_file(root, 'oh-control.lock')):
        state=reduce(journal.records())
        if state['status']!='running':return
        from .delivery import reviewed
        reviewed(root,state,review)
        if (designing(task) or intake(task)) and committed(state):
            from .plans import validate_outputs
            validate_outputs(root,state['rendered'])
        task_id=task['id'];expected=review.get('git_tree')
        if state.get('plans',{}).get('location')=='private' and blocked_layout(root,state):raise Refused(blocked_layout(root,state))
        if intake(task):
            from .storage import read_json
            artifact=review.get('artifact')
            if not artifact or digest(read_json(artifact['path']))!=artifact['hash']:
                raise Refused('The proposal artifact differs from its independent review')
            if read_json(artifact['path'])['rendered']!=state['rendered']:
                raise Refused('The proposal changed after independent review')
            answer=(state.get('proposal_answers') or [{}])[-1]
            if answer.get('choice')!='approve' or answer.get('shown')!=approved(state['rendered']):
                raise Refused('OH wrote something other than what the person approved; stop this run and propose again')
        artifact=review.get('artifact') or {}
        if not committed(state) and 'files' in artifact:
            # Private plans, approved by the person just now: bound to exactly the reviewed files.
            from .plans import finish_private,editing
            if blocked_layout(root,state):raise Refused(blocked_layout(root,state))
            if git(root,'rev-parse','HEAD')!=review['head'] or tree(root)!=review['tree']:
                raise Refused('The project changed while the plan was reviewed')
            with editing(root):
                approval=finish_private(root,state,task['transition']['profile'],journal,artifact['files'])
                journal.append('task.completed',{'task':task_id,'artifact':artifact,'review':review['id'],'approved':approval,
                    'summary':review['summary'],'evidence':review['evidence']})
            observe_completion(state,task_id)
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
            observe_completion(state,task_id)
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
            if changes(root):raise Refused('Preserve new edits before recovering the reviewed commit')
        if not already:
            if head!=review.get('head'):raise Refused('HEAD differs from the reviewed parent')
            if review['tree']!=tree(root) or candidate_tree(root)!=expected:raise Refused('The retained review does not cover the current tree')
            git(root,'add','--all',*whole(root))
            if git(root,'write-tree')!=expected:raise Refused('The staged tree differs from the reviewed Git tree')
            if not intent:
                from .publication import task_evidence
                publication=task_evidence(root,state,task,review,head)
                intent={'task':task_id,'review':review['id'],'git_tree':expected,'parent':head,'publication':publication}
                journal.append('commit.intent',intent)
            if not intent.get('publication'):raise Refused('This older commit intent needs fresh portable review evidence before publication')
            title=(f"{state['rendered']['kind']} {state['rendered']['number']}: {state['rendered']['title']}" if designing(task) else
                   'propose: '+state['rendered']['lines'][-1][:120] if intake(task) else f"task {task_id}: {task['title']}")
            git(root,'commit','--allow-empty','-m',f"{title}\n\nOH-Run: {state['id']}\nOH-Review: {review['id']}\nOH-Reviewed-Tree: {expected}\nOH-Evidence: {digest(intent['publication'])}")
            if git(root,'rev-parse','HEAD^{tree}')!=expected or git(root,'rev-parse','HEAD^')!=head:raise Refused('Commit hooks changed the reviewed tree or parent')
        from .delivery import finish
        finish(root,journal,state,review)
        journal.append('task.completed',{'task':task_id,'commit':git(root,'rev-parse','HEAD'),'tree':expected,'review':review['id'],
            'summary':review['summary'],'evidence':review['evidence']})
        observe_completion(state,task_id)
