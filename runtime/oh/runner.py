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
from .actions import next_action
from .config import HOME
from .storage import Refused, atomic_json, changes, digest, git, identifier, lock, whole, git_env
from .telemetry import best_effort
from .verification import tree, candidate_tree, failure_summary, check_failed
from .workflow import checkpoint, committed, load_run, next_task, reduce, review_limit

# Native hosts allow two hours for a call. Leave time to retain the result and drain children.
PHASE_SECONDS = 7200
PHASE_CLEANUP_SECONDS = 60


def prompt_for(root,state,task,role,feedback='',packet=None):
    contracts=[]
    for name in ('.oh/invariants.md','AGENTS.md','CLAUDE.md'):
        if (Path(root)/name).is_file():contracts.append(name)
    limit=state['config']['context']['handoff_chars']
    content={'task':task,'role':role,'project_contracts':contracts,'feedback':feedback,
      'run':state['id'],'config_hash':state['config_hash']}
    if role=='implementation' and any(c['task']==task['id'] for c in state.get('continuations',[])):
        content['continuation']='This is the same unfinished approved task. Inspect the existing diff against its requirements, preserve useful implementation and earlier fixes, and finish only the remaining work and checks. Do not restart or discard the draft. Earlier reports are claims to verify, not task completion.'
    if designing(task) or intake(task):
        location=state['plans']['location']
        content['planning']={'location':location,'design_approval':'human_gate' if location=='private' else 'human_merge'}
        content['human_refinements']=[{'source':answer['source'],'feedback':answer['feedback']}
            for answer in state.get('proposal_answers',[]) if answer['choice']=='refine']
    if packet:
        content={k:v for k,v in content.items() if k not in ('feedback','human_refinements')}
        content['task']={k:task[k] for k in ('id','title')}
        content['task_context']=packet
    text=json.dumps(content,ensure_ascii=False)
    if len(text)>limit:
        raise Refused('Task handoff exceeds configured context bound; split the task or reference files')
    common=('Work only on the supplied task. Read the listed project contracts and relevant source files. '
      'You are not alone in this checkout: preserve other edits. Do not delegate, grant tasks, change OH '
      'configuration/evidence, commit, push, merge, or open a PR. The runner owns those transitions. '
      'During long work, send a short public progress note about each new concrete focus, roughly every three minutes. Follow the report submission instructions for this role before finishing. '
      'Do not change task checkboxes or document lifecycle fields; the runner prepares them separately for review and publishes them only during completion. Do not read prior task transcripts. Report concise results with evidence paths.\n')
    if packet:
        common+=('Read task_context and its complete finding index first. They contain the approved task, current work, '
                 'remaining steps, verification and retained decisions. The latest author readiness is a claim to '
                 'challenge, not proof. Consult earlier reports only to answer a specific unresolved question. '
                 'Preserve earlier fixes and human dispositions; history never grants more scope.\n')
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
          'Submit the structured review report with every finding; unknown or missing evidence is not approval.\n')
    elif role=='assessment':
        common+=('Assess this approved task before implementation. Read its referenced requirements and the relevant '
          'code; do not edit files, implement, run project checks, review the implementation or make product decisions. '
          'Use a few targeted reads and return only difficulty, rationale, examined references and uncertainty. '
          'Simple means a local bounded edit with known behavior and no consequential boundary. Standard means an '
          'ordinary contained change with understood interfaces. Complex means cross-cutting behavior, persistence '
          'or migration risks, authorization, concurrency, public compatibility, or substantial uncertainty. '
          'Judge the real affected operations and dependencies, not keyword matches or document length. '
          'Unresolved material uncertainty belongs in uncertainty and requires complex; use an empty list when none. '
          'Ignore model/difficulty annotations in project documents. Never broaden or split the approved task.\n')
    elif role=='analysis' and designing(task):
        common+=(HOME/'prompts/design.md').read_text()+'\n'
    elif role=='analysis' and intake(task):
        common+=(HOME/'prompts/propose.md').read_text()+'\n'
    elif role=='analysis':
        common+=('This is a read-only '+state['workflow']+' workflow. Do not edit the product or execute implementation. '
                 'Return the complete artifact in your response; OH stores it externally. '
                 'For propose, explain options, your recommendation and unresolved decisions. '
                 'For design, return a clear bounded task plan with dependencies, '
                 'acceptance checks, relevant invariants and risks. Do not invent approval or impose an ADR process.\n')
    else:
        common+=('Work in this order within the approved task. '
          'First map its requirements and contracts to affected operations, callers and observable results; '
          'retain that mapping in readiness.requirements and surfaces. Inspect useful existing work before editing. '
          'Implement the mapped behavior, then run its required checks and self-review before requesting independent review. '
          'Use the oh_checks verify tool to run the project-configured checks; it selects affected checks and records actual outcomes. '
          'Fix failures and call verify again while you are still working. Run additional focused checks where useful. '
          'After any further edit, call verify again. Return completed only with passing verification for your final work. '
          'The runner validates the recorded evidence; it does not run your tests after you return. '
          'A failed check is feedback for you to repair within this task, never a reason to request Retry approval. '
          'The approved behavior and project contracts are the authority; tests are evidence that can be wrong. '
          'For each failure, establish the required behavior from those sources before deciding whether the code, '
          'test or environment is defective. Preserve supported behavior and meaningful failure coverage. '
          'Do not change requirements, remove behavior, add decorative controls or weaken an assertion merely to make a check pass. '
          'Correct a faulty test within the approved scope with a concrete behavioral justification; an actual conflict '
          'between authoritative requirements needs a decision, not a silent choice. '
          'Self-review complete operations from accepted input and relevant state through storage to the public result. '
          'Use the approved mapping to challenge alternate states, boundaries, permissions, replay and failure '
          'outcomes where applicable; do not enumerate irrelevant combinations or invent input policies. '
          'For each changed protection or reported defect, search sibling paths and close the whole family. '
          'Trace the trigger and assertion of its regression test; a changed fixture must still exercise the '
          'claimed failure. Open files your code or documentation makes claims about and confirm the claim '
          'or narrow it. Follow project documentation conventions. '
          'The approved scope never grows. Do not implement unrelated gaps or entries under Open review scope or Scope decisions. '
          'Return actionable unrelated gaps in found_along_way, never in the change. Routine verification notes, '
          'absence of sibling paths and unchanged documentation belong in summary, not found_along_way. '
          'Do not edit plan files; OH records those notes. '
          'Start summary with a short account of the delivered behavior, '
          'including existing implementation and earlier repairs you retained; put verification and limits in separate paragraphs. '
          'Return readiness with explicit requirements, rules, surfaces, proof, self_review, family_closure, '
          'prior_findings, verification, repairs and limits. Map every requirement to implementation and concrete proof. '
          'Name the rules checked and affected callers, alternate paths and documentation. Record self-review attacks '
          'and observed outcomes, sibling searches and whole-family repairs. For every receipt reference id (review-attempt#finding-number, never case_key) in the supplied '
          'index, return its disposition and concrete proof exactly once in prior_findings; preserve human choices. '
          'Verification names actual commands and outcomes. Repairs explain each failure, diagnosis against approved '
          'behavior, code/test/environment correction and proof. State why a section does not apply instead of omitting '
          'required coverage; repairs, family_closure, prior_findings and limits may be empty when none apply. '
          'These are claims the reviewer must challenge, never approval.\n')
        common+=('Persist until the entire supplied task and self-review are finished. Incomplete implementation, '
                 'self-review defects and failed checks are remaining work for you to fix, not blockers. '
                 'Preserve useful edits and repair incorrect parts in place; do not discard the draft because it is unfinished. '
                 'Read targeted sections and retain a concise working checklist rather than repeatedly reading whole contracts. '
                 'If continuing earlier work, inspect the current diff and complete the concrete remaining steps. '
                 'Return status completed with obstacle null only after all supplied work is finished, including '
                 'when the requested behavior already exists. Return blocked only for missing human authority or '
                 'an external dependency you cannot resolve within the existing authority; name that obstacle, its '
                 'concrete evidence and the next external action in obstacle. No elapsed time or context compaction '
                 'ends this task. If you nevertheless return before completion without such an obstacle, use '
                 'unfinished with obstacle null and summarize useful edits, remaining steps and checks still needed '
                 'so OH can continue them. Never describe unfinished work as blocked. A successful host call '
                 'is not task completion.\n')
    if role=='analysis':
        common+=('Self-review the proposed document against the project rules, its referenced claims and failure paths '
                 'before returning it. For review fixes, close the whole defect family across the document and its tasks, '
                 'preserve earlier fixes, and check whether the replacement introduces a new failure or makes a source '
                 'claim stale. Report the checks and limits concisely in your summary.\n')
    if state['host']=='claude' and hosts.WINDOWS:
        common+=('On Windows this worker has no shell. Use the file tools; implementation agents run configured '
                 'checks through the verify tool and repair failures before returning.\n')
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


def repeated_family(reviews):
    """Escalation needs two independent receipts of the same unresolved defect family."""
    seen=set();receipts=set()
    for review in reviews:
        if review['id'] in receipts:continue
        receipts.add(review['id'])
        if review.get('outcome') not in ('blocking','needs_resolution'):continue
        families={f['family'].strip() for f in review.get('findings',[])
                  if f['severity']=='blocking' and f.get('family','').strip()}
        if seen & families:return sorted(seen & families)
        seen.update(families)
    return []


def progress(message):
    """Native host progress is emitted only when the runner actually changes phase."""
    print(message,file=sys.stderr,flush=True)


def attempt(root,journal,state,task,role,profile,feedback='',invoke=hosts.invoke,*,deadline=None):
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
    attempt_id=identifier();before=tree(root)
    from .delivery import replacements
    git_tree=candidate_tree(root,replacements(root,state)) if role=='review' else None
    directory=journal.path/'attempts'/attempt_id
    data={'id':attempt_id,'task':task['id'],'role':role,'host':state['host'],'profile':profile,'tree':before,
          'head':git(root,'rev-parse','HEAD'),'config_hash':state['config_hash'],
          'harness_version':state['harness_version'],'runtime':str(HOME),'git_tree':git_tree,'config':state['config'],'root':str(root)}
    if role=='implementation' and state.get('delivery'):
        data['read_only_paths']=sorted(state['delivery']['inputs'])
    if role=='implementation':
        data['verification_timeout']=60+sum(c.get('timeout_seconds',900)+10*len(c.get('toolchain',[]))
                                           for c in state['project_checks']+state['checks'])
    if role in ('implementation','analysis') and (families:=repeated_family([a for a in state['attempts'] if a['task']==task['id'] and a['role']=='review'])):
        data['escalated_families']=families
    if fallback:data['model_fallback']=fallback
    journal.append('attempt.started',data)
    best_effort('attempt.started',state['project'],state['id'],task['id'],attempt_id,
      role=role,phase=role if role in ('review','assessment') else ('repair' if feedback else 'implementation'),
      host=state['host'],model=profile['model'],effort=profile['effort'])
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if state.get('plans',{}).get('location')=='private' or state.get('delivery',{}).get('layout',{}).get('location')=='private':
        from .plans import private_inputs,layout
        data['private_inputs']=private_inputs(layout(root))
    from .handoff import prepare
    data['context_version']=3
    if role in ('implementation','review'):data['report_protocol']=1
    data['task_context'],finding_context=prepare(state,task,role,directory,data,feedback)
    prompt=prompt_for(root,state,task,role,feedback,packet=data['task_context'])
    if role in ('implementation','review'):
        prompt+='\nBefore exiting, call oh_checks submit_report with your complete structured report. Correct any returned issues in this same attempt. Once accepted, finish with a short plain summary; final prose is not another report. Do not repeat unchanged passing checks for report corrections.\n'
    if role=='review':prompt+='\nOH NATIVE REVIEW ADMISSION: '+str(directory/'request.json')
    if role=='review' and git_tree:
        # The exact code change as a file, for reviewers without a shell (Claude on Windows) and everyone else.
        diff=subprocess.run(['git','-C',str(root),'diff','--no-color','--no-ext-diff','--text','--no-textconv','HEAD',git_tree],capture_output=True,check=True,
                            env=git_env()).stdout
        (directory/'change.diff').write_bytes(diff)
        data['diff']={'path':str(directory/'change.diff'),'sha256':hashlib.sha256(diff).hexdigest()}
        prompt+='\nThe exact code change under review, from HEAD to the reviewed tree, is in '+str(directory/'change.diff')+'.'
        sizes=git(root,'diff','--numstat','--no-renames','-z','HEAD',git_tree,raw=True)
        index=[dict(zip(('added','removed','path'),entry.decode().split('\t',2))) for entry in sizes.split(b'\0') if entry]
        atomic_json(directory/'change-index.json',index,immutable=True)
        data['change_index']={'path':str(directory/'change-index.json'),'hash':digest(index)}
        prompt+='\nStart with the complete changed-file index '+str(directory/'change-index.json')+' to plan coverage. Large generated artifacts must not crowd out source, tests or affected documentation; validate their generation and inspect relevant contracts.'
    if role=='review' and (covers:=state.get('delivery',{}).get('covers')) and not state['summaries']:
        # Commits OH didn't make: the person's own, and merges of the base branch resolved by the agent or the person (for those,
        # what the resolution changed beyond Git's own merge).
        text=b''.join(subprocess.run(['git','-C',str(root),'show','--remerge-diff','--no-color','--no-ext-diff',commit],capture_output=True,check=True,
                                     env=git_env()).stdout for commit in covers)
        (directory/'covered.diff').write_bytes(text)
        data['covers']={'commits':covers,'path':str(directory/'covered.diff'),'sha256':hashlib.sha256(text).hexdigest()}
        prompt+=('\nThis branch also holds commits OH did not make: '+', '.join(covers)+' (the person\'s own, or merges of the base branch '
                 'resolved by hand). What each changed, for a merge beyond Git\'s own merge, is in '+str(directory/'covered.diff')
                 +'. Review it as part of this subject: a '
                 'resolution that loses either side\'s intent, changes more than the conflict needs, or edits the plans beyond '
                 'the base branch\'s version and this branch\'s recorded progress is a blocker.')
    if role=='review' and 'candidate' in state.get('delivery_render',{}):
        from .plans import file_identity,digest_of
        render=state['delivery_render'];candidate=Path(render['candidate'])
        data['artifact']={'files':{str(candidate):digest_of(candidate)},'identities':{str(candidate):file_identity(candidate)}}
        prompt+=f'\nReview the code diff AND the proposed design progress in {candidate}, compared with {render["path"]}. The live task stays pending until native completion publishes the reviewed result.'
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
    admission=data|{'prompt':prompt}
    atomic_json(directory/'request.json',admission,immutable=True)
    journal.append('attempt.admitted',{'id':attempt_id,'hash':digest(admission)})
    from . import receipts
    try:receipts.request(directory,data)
    except (OSError,Refused) as exc:progress('Readable request unavailable; the native admission is retained: '+str(exc))
    context={'project':state['project'],'run':state['id'],'task':task['id'],'attempt':attempt_id,'controlled':True,
             'read_only_paths':data.get('read_only_paths',[])}
    started=time.monotonic()
    try:
        if profile_error:raise profile_error
        # Announce the handoff only after admission succeeds, at the actual worker launch.
        if role!='assessment':
            action=('The independent reviewer agent is now challenging' if role=='review' else
                    'The planning agent is drafting' if role=='analysis' else 'The implementation agent is working on')
            progress(f"{action} task {task['id']}: {' '.join(task['title'].split())[:200]} ({profile['model']} / {profile['effort']}).")
        options={'schema':hosts.REVIEW_SCHEMA if role=='review' else hosts.ASSESSMENT_SCHEMA if role=='assessment' else hosts.DESIGN_SCHEMA if designing(task) else hosts.PROPOSAL_SCHEMA if intake(task) else hosts.WORK_SCHEMA if role=='implementation' else None}
        if deadline is not None:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise Refused('This phase exhausted its call budget before the agent could start. Saved work and authority are retained.')
            options['timeout']=remaining
        result=invoke(state['host'],root,profile,prompt,role,directory,context,**options)
    except Exception as exc:
        result={'failed':True,'returncode':-1,'text':str(exc),'structured':None,
                'duration_ms':round((time.monotonic()-started)*1000),'usage_observed':False}
    try:
        if role in ('implementation','review'):
            from .worker_checks import returned
            result=returned(directory,result)
        if role in ('analysis','review') and result['failed']:result=result|{'text':hosts.failure_text(result)}
        after=tree(root)
    except Exception as exc:
        _,findings=hosts.review_result(result) if role=='review' else ('failed',[])
        detail=f'OH could not fingerprint the returned worker result: {exc}. Preserve the work, repair the checkout and resume this run.'
        atomic_json(directory/'result.json',result|{'outcome':'failed','tree':None,'findings':findings,'fingerprint_error':str(exc)},immutable=True)
        journal.append('attempt.finished',{'id':attempt_id,'task':task['id'],'role':role,'outcome':'failed','tree':None,
            'findings':findings,'summary':detail,'fingerprint_error':str(exc),'duration_ms':result['duration_ms'],
            'evidence':str(directory),'git_tree':git_tree,'head':data['head']})
        status(journal,state,'needs_attention')
        raise Refused(detail) from exc
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
        parsed=hosts.review_details(result)
        outcome,findings=parsed['outcome'],parsed['findings']
        if parsed['issues']:
            result=result|{'text':result['text']+'\nReview report limitations: '+'; '.join(parsed['issues'])}
        if after!=before or private_changed:outcome='review_mutated_tree'
        if 'files' in (data.get('artifact') or {}):
            from .plans import current_files,file_identity,resolved
            if current_files(root,data['artifact']['files'])!=data['artifact']['files']:outcome='review_mutated_tree'
            if {p:file_identity(resolved(root,p)) for p in data['artifact']['files']}!=data['artifact']['identities']:
                outcome='review_mutated_tree'
    else:
        outcome='failed' if result['failed'] else 'implemented';findings=[]
        if role=='assessment':
            outcome,summary=hosts.assessment_result(result)
            result=result|{'text':summary}
        if role=='implementation':
            outcome,summary=hosts.work_result(result)
            if outcome=='implemented':
                from .handoff import validate_readiness,finding_ids
                if problem:=validate_readiness(result['structured']['readiness'],finding_ids(finding_context)):
                    outcome='report_invalid';summary+='\n'+problem
            failed_check=(any(a['task']==task['id'] and a.get('outcome')=='verification_failed' for a in state['attempts'])
                          or any(r['kind']=='verification' and r['data'].get('attempt')==attempt_id
                                 and any(check_failed(c) for c in r['data']['checks']) for r in journal.records()))
            if (outcome=='implemented' and failed_check
                    and not result['structured']['readiness']['repairs']):
                outcome='report_invalid';summary+='\nExplain the failed-check diagnosis and repair against the approved behavior in readiness.repairs before review.'
            if outcome!='implemented':result=result|{'text':summary}
        if outcome=='implemented' and (designing(task) or intake(task)):
            from .plans import answer,proposal
            try:(answer if designing(task) else proposal)(result.get('structured'))
            except Refused as exc:
                # A shapeless answer is a failed attempt; its reason is the next attempt's feedback.
                outcome='failed';result=result|{'text':f'OH could not use the answer: {exc}\n'+result['text']}
        if role in ('analysis','assessment') and (after!=before or private_changed):
            outcome=role+'_mutated_tree';status(journal,state,'needs_attention')
    if delivery_changed:
        outcome='delivery_context_changed';result=result|{'text':delivery_changed+'\n'+result['text']}
        status(journal,state,'needs_attention')
    answer=result.get('structured')
    notes=answer.get('found_along_way',[]) if role=='implementation' and isinstance(answer,dict) else []
    if not isinstance(notes,list) or any(not isinstance(n,str) for n in notes):
        notes=[];outcome='failed' if result['failed'] else 'report_invalid';result=result|{'text':'The implementing report needs found_along_way as a list of strings'}
    # Preserve the full raw result outside the orchestrator context.
    atomic_json(directory/'result.json',result|{'outcome':outcome,'findings':findings,'tree':after},immutable=True)
    record={'found_along_way':notes,'id':attempt_id,'task':task['id'],'role':role,'outcome':outcome,'tree':after,
      'findings':findings,'summary':result['text'][:state['config']['context']['result_chars']],
      'returncode':result.get('returncode'),'cancellation':result.get('cancellation',[]),
      'duration_ms':result['duration_ms'],'evidence':str(directory),'git_tree':git_tree,'head':data['head'],'artifact':data.get('artifact')}
    if role=='review':record.update(report_issues=parsed['issues'],review_fragments=parsed['fragments'],finding_positions=parsed['positions'])
    elif result.get('report_issues'):record['report_issues']=result['report_issues']
    if data.get('escalated_families'):record['escalated_families']=data['escalated_families']
    if role=='assessment' and outcome=='assessed':record['assessment']=answer
    if isinstance(answer,dict) and isinstance(answer.get('summary'),str):
        record['human_summary']=(result['text'] if outcome=='blocked' else answer['summary'])[:state['config']['context']['result_chars']]
    journal.append('attempt.finished',record)
    try:receipts.completed(directory,data,result,record,reduce(journal.records()))
    except (OSError,Refused) as exc:progress('Readable receipt unavailable; the original result is retained: '+str(exc))
    if role=='review' and parsed['issues']:
        progress('The review receipt is incomplete: '+'; '.join(parsed['issues'])[:900]+'. Findings are retained; this is not a clean review.')
    if role=='review':
        rounds=sum(a['role']=='review' and a['task']==task['id'] for a in reduce(journal.records())['attempts'])
        result_label={'clean':'clean','blocking':'blocking findings','needs_resolution':'findings need a decision'}.get(outcome,'could not complete the review')
        progress(f"The independent reviewer agent finished round {rounds}: {result_label}; "
                 +(f"{len(findings)} finding"+('s.' if len(findings)!=1 else '.') if findings else 'no findings.' if outcome=='clean' else 'no completed verdict.'))
        for finding in findings:
            progress(f"{finding['severity']}: {' '.join(finding['description'].split())[:350]}")
    elif outcome=='implemented':
        summary=record.get('human_summary') or record['summary']
        progress('The '+('implementation' if role=='implementation' else 'planning')+f" agent finished its round for task {task['id']}: "
                 +' '.join(summary.split('\n\n',1)[0].split())[:350])
    elif outcome=='unfinished':
        progress('The '+('assessment' if role=='assessment' else 'implementation')+' agent has remaining work; OH will continue on the same profile with useful work retained.')
    elif outcome in ('failed','blocked','report_invalid','history_changed','delivery_context_changed'):
        progress('The '+('implementation' if role=='implementation' else 'planning')+' agent could not finish: '
                 +' '.join(record['summary'].split())[:450])
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
def run(root,invoke=hosts.invoke,*,one_phase=False,deadline=None):
    if one_phase and deadline is None:deadline=time.monotonic()+PHASE_SECONDS-PHASE_CLEANUP_SECONDS
    from .controls import settle, Interrupted
    try:
        import contextlib
        _,state=load_run(root)
        from .plans import editing
        with editing(root) if state.get('delivery') else contextlib.nullcontext():
            _run(root,invoke,one_phase=one_phase,deadline=deadline)
    except Interrupted:
        pass
    # An exceptional process cleanup must retain STOPPING, never report false success.
    from .controls import busy
    if not busy(root):settle(root)
    result=checkpoint(root)
    if one_phase:
        automatic=result['status']=='running' or bool(result['next_action'].get('resume'))
        if automatic:
            # A transport handoff carries current work, not another copy of completed history.
            result={k:v for k,v in result.items() if k in ('run','status','next_action','report','progress','last_failure','model_notices')}
            if 'progress' in result:
                result['progress']={k:v for k,v in result['progress'].items() if k in ('task','title','phase','attempt','profile','focus')}
            _,state=load_run(root)
            if state['attempts']:
                last=state['attempts'][-1]
                result['phase_result']={k:last.get(k) for k in ('id','task','role','outcome')}
                result['phase_result']['summary']=(last.get('human_summary') or last.get('summary',''))[:400]
        result['continue_execution']=automatic
    return result


def _run(root,invoke,*,one_phase=False,deadline=None):
    phases=0
    def execute(*args):
        nonlocal phases
        phases+=1
        return attempt(*args,**({'deadline':deadline} if one_phase else {}))
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
            if state['status']=='review_checkpoint' and next_action(state,current_tree=tree(root)).get('resume'):
                with lock(checkout_file(root,'oh-control.lock')):
                    current=reduce(journal.records())
                    if next_action(current,current_tree=tree(root)).get('resume'):
                        journal.append('run.status',{'status':'running',
                            'reason':'Repairing the already-approved task before another review allowance is needed.'})
                continue
            if state['status']=='running':recover(root,state)
            task=next_task(state)
            if not task:
                if state['status']=='running':
                    status(journal,state,'completed' if len(state['done'])==len(state['tasks']) else 'checkpoint')
                return checkpoint(root)
            task_id=task['id'];task_start=time.monotonic()
            decision=next_action(state,current_tree=tree(root))
            if decision['kind']=='restore_report':
                from .handoff import recover_legacy
                with lock(checkout_file(root,'oh-control.lock')):
                    from .controls import check
                    check(root)
                    recover_legacy(root,journal,state,next(a for a in state['attempts'] if a['id']==decision['work']))
                progress('The retained implementation report now uses its original review references. Saved work and checks are unchanged.')
                continue
            if decision['kind']=='blocked':
                status(journal,state,'needs_attention');return checkpoint(root)
            history=[a for a in state['attempts'] if a['task']==task_id]
            profiles=state['config']['models'][state['host']]
            if decision['kind']=='assess':
                assessments=[a for a in history if a['role']=='assessment']
                latest=assessments[-1] if assessments else None
                if latest and latest.get('outcome')=='assessed' and latest.get('tree')==tree(root):
                    value=latest['assessment']
                    journal.append('task.assessed',{'task':task_id,'attempt':latest['id'],
                        'difficulty':'complex' if value['uncertainty'] else value['difficulty'],
                        'rationale':value['rationale'],'references':value['references'],'uncertainty':value['uncertainty']})
                    continue
                if one_phase and phases:return
                result=execute(root,journal,state,task,'assessment',profiles['standard'],
                    latest.get('summary','') if latest else '',invoke)
                if result['outcome']=='assessment_mutated_tree':return checkpoint(root)
                continue
            previous=[a for a in history if a['role']!='assessment']
            if task_id not in state['task_started']:
                first=next((a['started_at'] for a in history if a['role']=='assessment'),None)
                journal.append('task.started',{'task':task_id}|({'started_at':first} if first else {}))
                state=reduce(journal.records())
                best_effort('task.started',state['project'],state['id'],task_id,
                  title=task['title'],difficulty=task['difficulty'],rubric=state['rubric_version'])
            profile=profiles[task['difficulty']]
            worker_attempts=[a for a in previous if a['role'] in ('implementation','analysis')]
            reviews=[a for a in previous if a['role']=='review']
            decided=state.get('proposals',{}).get(previous[-1]['id']) if gated(state,task) and previous else None
            if decision['kind']=='preview':
                show(root,journal,state,task,previous[-1]);continue
            if decision['kind']=='approve_plan':
                if intake(task):unwrite(root,journal,state,previous[-1]['id'])
                status(journal,reduce(journal.records()),'approval_checkpoint');return checkpoint(root)
            if decision['kind']=='complete_proposal':
                plan=state['preview']['plan']
                journal.append('task.completed',{'task':task_id,'route':plan['route'],'summary':plan['summary'],
                    'evidence':previous[-1]['evidence']})
                observe_completion(state,task_id);continue
            if decision['kind']=='complete':
                complete_reviewed(root,journal,state,task,previous[-1]);continue
            if decision['kind']=='route_scope':
                from .scope import record
                record(root,journal,state,previous[-1],'route','required by blocker-plus-scope policy')
                continue
            if decision.get('refined') and intake(task):decided=state['proposal_answers'][-1]
            feedback=''
            if previous:
                last=previous[-1]
                if last['role']=='review':
                    feedback=json.dumps([f for f in last.get('findings',[]) if f['severity'] in ('blocking','concern')],ensure_ascii=False)
                    if last.get('outcome') in ('failed','interrupted'):feedback='The reviewer could not finish. Recheck the authorized task only.'
                else:feedback=last.get('summary','')
                if last.get('outcome')=='unfinished':
                    feedback='Continue the unfinished approved task. Inspect the current diff, preserve useful edits and finish these remaining steps and checks:\n'+feedback
            refined=decision.get('refined',False)
            if refined:feedback='The person asked you to refine the proposal: '+decided['feedback']+'\nYour previous answer: '+(
                state['preview']['plan'] if intake(task) else state['rendered']).get('summary','')
            # Checks never escalate models or spend a repair allowance. Only a repeated
            # independent finding proves that the author failed to repair a defect family.
            families=repeated_family(reviews)
            if families:
                profile=profiles['complex']
                if not any(a.get('escalated_families') for a in worker_attempts):
                    progress('The same defect family remains after independent review: '+', '.join(families)
                             +'. The implementation agent will use '+profile['model']+' to repair it.')
            # A broken host launch/report gets one automatic retry on the same profile.
            # Persistent external failures retain work and explain the action needed;
            # they never create review authority or a Deliver retry menu.
            last=previous[-1] if previous else None
            # A completed implementation can resume at verification without another model call.
            retained=worker_attempts[-1] if worker_attempts else None
            reusable=decision.get('reuse',False)
            if retained and retained.get('outcome')=='verification_failed':feedback=retained['summary']
            work=retained
            existing=task['transition'].get('existing') if decision.get('existing') else None
            if existing:
                # A private design someone edited: its first review is of the doc as it is, with no worker.
                if not state.get('rendered'):
                    from .plans import existing_plan
                    journal.append('subject.existing',{'plan':existing_plan(root,existing)})
                work=None
            elif not reusable:
                if one_phase and phases:return
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
                work=execute(root,journal,state,task,'implementation' if state.get('workflow','deliver')=='deliver' else 'analysis',profile,feedback,invoke)
                if work['outcome'] in ('blocked','report_invalid'):
                    status(journal,state,'needs_attention');return checkpoint(root)
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
            # The implementer runs checks before returning. Native receipts, not its report,
            # establish that the exact final work passed the configured checks.
            if work and work['role']=='implementation':
                from .worker_checks import evidence
                try:check_results=evidence(root,reduce(journal.records()),work)
                except Refused as exc:
                    journal.append('verification.failed',{'attempt':work['id'],'task':task_id,'summary':str(exc)})
                    progress('The implementation agent must finish verification before independent review: '+str(exc)[:700])
                    continue
            else:
                # Planning validates its documents without executing product checks.
                check_results=[]
                journal.append('verification',{'task':task_id,'tree':tree(root),'checks':check_results})
            if designing(task) or intake(task):
                from .plans import validate_outputs,layout
                validate_outputs(root,reduce(journal.records())['rendered'],layout(root)['base'])
            apply_pending(root)
            from .controls import check
            check(root)
            decision=next_action(reduce(journal.records()),current_tree=tree(root),verified=True)
            if decision['kind']=='review_allowance':
                progress(f"Task {task_id} is ready for review; the reviewer has not started because the review allowance is spent.")
                status(journal,state,'review_checkpoint');return checkpoint(root)
            if decision['kind']!='review':continue
            if one_phase and phases:return
            review=execute(root,journal,state,task,'review',profiles['review'],'',invoke)
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
    # Pause/stop already reduced authority. Draining that step needs no fresh human record,
    # which the host may not have saved yet when it interrupts the calling conversation.
    controls=('pausing','paused','stopping','stopped')
    _,current=load_run(root)
    if current['status'] not in ('stopping','stopped'):
        from .authority import owner_stop_reader
        if source:=owner_stop_reader(current)():
            from .controls import request
            request(root,'stop',expected_run=current['id'],source=source)
            return
    if current['status'] in controls:return
    from .authority import materialize,waiting_work
    try:
        if not waiting_work(root):materialize(root)
    except Refused:
        # A control can arrive during the native-record read as well as before it.
        if load_run(root)[1]['status'] not in controls:raise


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
        from .delivery import reviewed,replacements,publish_progress
        reviewed(root,state,review)
        if (designing(task) or intake(task)) and committed(state):
            from .plans import validate_outputs
            validate_outputs(root,state['rendered'])
        task_id=task['id'];expected=review.get('git_tree')
        if task_id not in state['granted'] or task_id in state['done']:
            raise Refused('This task has no remaining completion authority')
        checked=state.get('verification',{}).get(task_id)
        if not checked or checked['tree']!=review['tree'] or any(check_failed(c) for c in checked['checks']):
            raise Refused('Completion requires passing checks for the reviewed work')
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
            proposed=candidate_tree(root,replacements(root,state))
            applied=intent and candidate_tree(root)==expected
            if proposed!=expected or review['tree']!=tree(root) and not applied:
                raise Refused('The retained review does not cover the current tree')
            # Validate the native verdict before any completion edit. The intent survives
            # interruption between publishing the reviewed document and its commit.
            from .publication import task_evidence
            publication=task_evidence(root,state,task,review,head)
            if not intent:
                intent={'task':task_id,'review':review['id'],'git_tree':expected,'parent':head,'publication':publication}
                journal.append('commit.intent',intent)
            if not intent.get('publication'):raise Refused('This older commit intent needs fresh portable review evidence before publication')
            publish_progress(root,reduce(journal.records()))
            git(root,'add','--all',*whole(root))
            if git(root,'write-tree')!=expected:raise Refused('The staged tree differs from the reviewed Git tree')
            title=(f"{state['rendered']['kind']} {state['rendered']['number']}: {state['rendered']['title']}" if designing(task) else
                   'propose: '+state['rendered']['lines'][-1][:120] if intake(task) else f"task {task_id}: {task['title']}")
            git(root,'commit','--allow-empty','-m',f"{title}\n\nOH-Run: {state['id']}\nOH-Review: {review['id']}\nOH-Reviewed-Tree: {expected}\nOH-Evidence: {digest(intent['publication'])}")
            if git(root,'rev-parse','HEAD^{tree}')!=expected or git(root,'rev-parse','HEAD^')!=head:raise Refused('Commit hooks changed the reviewed tree or parent')
        from .delivery import finish
        finish(root,journal,reduce(journal.records()),review)
        journal.append('task.completed',{'task':task_id,'commit':git(root,'rev-parse','HEAD'),'tree':expected,'review':review['id'],
            'summary':review['summary'],'evidence':review['evidence']})
        observe_completion(state,task_id)
