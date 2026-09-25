from __future__ import annotations

from .storage import state_writer

import json
from pathlib import Path
import re
import subprocess
import time
from .config import HOME,classify
from .hosts import invoke
from .initial import load,bind
from .legacy import execute,environment
from .storage import Refused,atomic_json,git,identifier,lock,now,read_json
from .telemetry import best_effort
from .verification import tree,candidate_tree,verify

IMPLEMENTATION_SCHEMA={'type':'object','additionalProperties':False,'required':['summary','readiness'],
 'properties':{'summary':{'type':'string'},'readiness':{'type':'string'}}}


@state_writer
def run(root,doc,track='',host=None,call=invoke):
    if read_json(Path(root)/'.oh/project.json').get('design_profile')!='consumer-v1':raise Refused('Design delivery requires an explicit consumer-owned profile')
    directory,grant=load(root)
    if grant['doc']!=doc or grant['track']!=track:raise Refused('The host grant is for another design')
    host=host or grant['human']['host'];config=grant['config'];run_id=grant['run'];p=grant['project']
    with lock(Path(git(root,'rev-parse','--absolute-git-dir'))/'oh-runner.lock',wait=False):
        from .config import version
        if version()!=grant['harness_version']:raise Refused('Resume this design run with its original pinned harness revision')
        if git(root,'branch','--show-current')=='main':
            result=execute(root,'scripts/start.sh',[doc]+([track] if track else []))
            if result.returncode:raise Refused(result.stderr)
        bind(root)
        if not (directory/'telemetry.json').exists():
            best_effort('run.started',p,run_id,name=read_json(Path(root)/'.oh/project.json')['name'],
              work_kind='product',host=host,version=grant['harness_version'],config_hash=grant['config_hash'])
            atomic_json(directory/'telemetry.json',{'started':now()},immutable=True)
        from .authority import materialize
        materialize(root)
        completed=[]
        for pending in sorted((directory/'tasks').glob('*/pending-review.json')):
            task_dir=pending.parent
            if (task_dir/'done.json').exists() or (task_dir/'ready-to-complete.json').exists():continue
            admission=read_json(pending);attempt=Path(admission['attempt']);raw=Path(admission['output'])/'review.md'
            if not (attempt/'completion.json').exists():
                recovered=execute(root,'scripts/driver-review.sh',['finish',attempt,raw] if raw.exists() else ['interrupt',attempt])
                if recovered.returncode:raise Refused('Interrupted review needs evidence recovery: '+recovered.stderr[-2000:])
            completion=read_json(attempt/'completion.json')
            authorized=completion['outcome']=='clean'
            if not authorized:
                checked=subprocess.run(['/bin/bash','-c','source "$1/core/review-receipt.sh"; tree=$("$1/core/scripts/tree-digest.sh"); review_completion_authorized "$2" "$tree"','oh-resolution',str(HOME),str(root)],cwd=root,env=environment(root),capture_output=True,text=True)
                authorized=checked.returncode==0
            if authorized:
                if candidate_tree(root)!=admission['git_tree']:raise Refused('Interrupted clean review no longer matches this tree')
                atomic_json(task_dir/'ready-to-complete.json',admission,immutable=True)
        # Finish an interrupted reviewed transition before asking the planner for another task.
        for ready in sorted((directory/'tasks').glob('*/ready-to-complete.json')):
            if not (ready.parent/'done.json').exists():
                completed.append(finish_task(root,doc,ready.parent,read_json(ready),p,run_id))
        while True:
            from .authority import materialize
            materialize(root)
            if (directory/'stopped.json').exists():return {'status':'stopped','run':run_id}
            result=execute(root,'scripts/next.sh',[doc]+([track] if track else []))
            if result.returncode and result.returncode!=6:
                states={3:'blocked',6:'finalize',7:'completed',8:'checkpoint',9:'pr'}
                status=states.get(result.returncode,'needs_attention')
                best_effort('run.status',p,run_id,status=status)
                return {'run':run_id,'status':status,'completed_now':completed,'detail':result.stderr[-3000:]}
            task_id,title=('finalize','Finalize the completed design and its documentation') if result.returncode==6 else re.split(r'\s+',result.stdout.strip(),maxsplit=1)
            task_dir=directory/'tasks'/task_id;task_dir.mkdir(parents=True,exist_ok=True)
            design=next((Path(root)/'docs/design').glob(doc+'-*.md'))
            match=re.search(r'^- \[ \] \*\*'+re.escape(task_id)+r'\.\*\*.*?(?=^- \[[ x]\] \*\*\d+\.\*\*|\Z)',design.read_text(),re.M|re.S)
            if not match and task_id!='finalize':raise Refused('Cannot resolve the admitted task text')
            task={'id':task_id,'title':title,'instructions':match.group(0)[:config['context']['handoff_chars']] if match else 'Verify the complete design and update affected documentation for consistency. Do not change task boxes or lifecycle status; the runner applies the reviewed freeze.',
                  'design':str(design.relative_to(root))}
            difficulty,reason=classify(task)
            if not (task_dir/'started.json').exists():
                atomic_json(task_dir/'started.json',{'at':now(),'difficulty':difficulty,'reason':reason,'parent':git(root,'rev-parse','HEAD')},immutable=True)
                best_effort('task.started',p,run_id,task_id,title=title,difficulty=difficulty,rubric=1)
            started_record=read_json(task_dir/'started.json')
            parent=started_record['parent']
            if git(root,'rev-parse','HEAD')!=parent:raise Refused('HEAD changed outside the runner; restore the recorded task parent')
            difficulty=started_record['difficulty']
            profiles=config['models'][host];feedback='';repairs=0
            pending=task_dir/'pending-review.json'
            if pending.exists():
                saved=read_json(pending);raw=Path(saved['output'])/'review.md'
                if raw.exists():feedback=f"Prior attempt: {Path(saved['attempt']).name}\n"+raw.read_text()
            while True:
                budget=execute(root,'scripts/driver-review.sh',['status'])
                if budget.returncode:return {'status':'review_checkpoint','task':task_id,'reason':budget.stderr[-2000:]}
                # Each failed startup or implementation is durable; restarting cannot erase it.
                workers=list(task_dir.glob('worker-*.json'))
                if len(workers)>=int(budget.stdout.split()[1])*(config['max_escalations']+2):
                    return {'status':'needs_attention','task':task_id,'reason':'Implementation attempt allowance exhausted','evidence':str(task_dir)}
                worker=identifier();profile=profiles['complex'] if repairs else profiles[difficulty]
                atomic_json(task_dir/f'worker-{worker}.json',{'at':now(),'profile':profile},immutable=True)
                best_effort('attempt.started',p,run_id,task_id,worker,role='implementation',phase='repair' if feedback else 'implementation',host=host,**profile)
                context={'project':p,'run':run_id,'task':task_id,'attempt':worker,'compact_tokens':config['context']['compact_at_tokens']}
                heads='Requirements covered|Rules checked|Affected surfaces|Claims and proof|Adversarial self-review|Defect-family closure|Prior finding dispositions|Verification|Limits'
                prompt=('Implement exactly this admitted task. Read the project instructions and cited design contracts. '
                  'Preserve unrelated work. Do not delegate, commit, push, tick design tasks, change OH configuration/evidence, or grant authority. '
                  'Return a concise summary and a readiness Markdown string with these exact ## headings, in order: '+heads+'. '
                  'Each section needs at least one concrete list entry. On the first review, Prior finding dispositions must be '
                  '"- none — first review". Later list each prior attempt-id#finding | fixed/routed/accepted/dismissed/still-open/disputed | explanation. '
                  'Read prior retained evidence only for this task when needed. The runner verifies the change and admits a fresh reviewer.\n'+
                  json.dumps(task)+'\nFeedback: '+feedback[-config['context']['result_chars']:])
                try:response=call(host,root,profile,prompt,'implementation',task_dir/worker,context,schema=IMPLEMENTATION_SCHEMA)
                except Exception as exc:response={'failed':True,'text':str(exc),'structured':None,'duration_ms':0}
                if git(root,'rev-parse','HEAD')!=parent:raise Refused('Child changed Git history; restore the recorded task parent')
                materialize(root)
                if (directory/'stopped.json').exists():return {'status':'stopped','run':run_id}
                best_effort('attempt.finished',p,run_id,task_id,worker,outcome='failed' if response['failed'] else 'implemented',duration_ms=response['duration_ms'],substantive=True)
                atomic_json(task_dir/worker/'result.json',response,immutable=True)
                if response['failed'] or not isinstance(response['structured'],dict):
                    repairs+=1;feedback=response['text']
                    if repairs>config['max_escalations']:return {'status':'needs_attention','task':task_id,'reason':'Worker failed','evidence':str(task_dir/worker)}
                    continue
                if not grant['checks']:raise Refused('This run has no required product check contract; configure .oh/checks.json before granting a new run')
                from .checks import resolve
                checks=resolve(root,grant['checks'])
                results=verify(root,checks,p)
                atomic_json(task_dir/worker/'verification.json',{'checks':results},immutable=True)
                best_effort('phase.finished',p,run_id,task_id,phase='verification',duration_ms=sum(r['duration_ms'] for r in results if not r['reused']),reused=sum(r['reused'] for r in results),checks=len(results))
                if any(r['returncode'] for r in results):
                    repairs+=1;feedback=json.dumps(results)[-config['context']['result_chars']:]
                    if repairs>config['max_escalations']:return {'status':'needs_attention','task':task_id,'reason':'Verification failed','evidence':str(task_dir/worker)}
                    continue
                readiness=task_dir/worker/'readiness.md';readiness.write_text(response['structured']['readiness'])
                stage=execute(root,'scripts/review-ready.sh',['stage',doc,task_id,readiness])
                if stage.returncode:
                    repairs+=1;feedback=stage.stderr
                    if repairs>config['max_escalations']:return {'status':'needs_attention','task':task_id,'reason':feedback}
                    continue
                reviewed_git_tree=candidate_tree(root)
                final_tree=preview_completion(root,doc,task_id,design,task_dir/worker)
                reviewer=identifier()
                admission=execute(root,'scripts/driver-review.sh',['start',host,reviewer,run_id])
                if admission.returncode:return {'status':'review_checkpoint','task':task_id,'reason':admission.stderr[-3000:]}
                attempt=Path(admission.stdout.strip());profile=profiles['review']
                best_effort('attempt.started',p,run_id,task_id,reviewer,role='review',phase='review',host=host,**profile)
                context['attempt']=reviewer
                entry=str(Path(root)/('.oh/oh' if (Path(root)/'.oh/oh').exists() else 'oh'))
                prompt=(HOME/'prompts/invariant-reviewer.md').read_text()+f'\nProject: {root}\nTask: {doc}/{task_id}\nHARNESS REVIEW ADMISSION: {attempt}/start.json\nUse {entry} legacy scripts/review-admission-check.sh {attempt}/start.json. Return the complete text report. Do not edit or spawn agents.'
                prompt+=f'\nThe deterministic completion is already materialized as Git tree {final_tree}. Review git diff {parent} {final_tree}, including the design lifecycle change, and git show {final_tree}:{design.relative_to(root)}. The working document remains pending solely for the legacy admission gate. Only this exact final tree can be committed.'
                atomic_json(task_dir/reviewer/'final-candidate.json',{'attempt':str(attempt),'parent':parent,'final_tree':final_tree,'working_tree':reviewed_git_tree,'design':str(design.relative_to(root))},immutable=True)
                atomic_json(task_dir/'pending-review.json',{'attempt':str(attempt),'output':str(task_dir/reviewer),'git_tree':reviewed_git_tree,'final_tree':final_tree,'parent':parent,'task':task_id,'title':title})
                try:review=call(host,root,profile,prompt,'review',task_dir/reviewer,context)
                except Exception as exc:review={'failed':True,'text':'','duration_ms':0,'error':str(exc)}
                if git(root,'rev-parse','HEAD')!=parent:raise Refused('Child changed Git history; restore the recorded task parent')
                materialize(root)
                if (directory/'stopped.json').exists():return {'status':'stopped','run':run_id}
                (task_dir/reviewer).mkdir(parents=True,exist_ok=True)
                raw=task_dir/reviewer/'review.md';raw.write_text(review['text'])
                retained=execute(root,'scripts/driver-review.sh',['finish',attempt,raw])
                outcome=retained.stdout.strip() if retained.returncode==0 else 'retention_failed'
                from .observability import review_metadata
                best_effort('attempt.finished',p,run_id,task_id,reviewer,**review_metadata(review['text']),outcome=outcome,duration_ms=review['duration_ms'],substantive=bool(review['text']))
                if outcome=='clean':
                    if candidate_tree(root)!=reviewed_git_tree:raise Refused('Reviewer changed the commit tree')
                    atomic_json(task_dir/'ready-to-complete.json',{'task':task_id,'title':title,'attempt':str(attempt),'git_tree':reviewed_git_tree,'final_tree':final_tree,'parent':parent},immutable=True)
                    break
                if outcome=='blocking':feedback=f'Prior attempt: {attempt.name}\n'+review['text'];repairs=0;continue
                return {'status':'findings_checkpoint','task':task_id,'outcome':outcome,'evidence':str(attempt),'detail':retained.stderr[-2000:]}
            completed.append(finish_task(root,doc,task_dir,read_json(task_dir/'ready-to-complete.json'),p,run_id))


def finish_task(root,doc,task_dir,ready,project_id,run_id):
    from .authority import materialize
    materialize(root)
    with lock(Path(git(root,'rev-parse','--absolute-git-dir'))/'oh-control.lock'):
        return _finish_task(root,doc,task_dir,ready,project_id,run_id)


def _finish_task(root,doc,task_dir,ready,project_id,run_id):
    from datetime import datetime,timezone
    if (task_dir.parent.parent/'stopped.json').exists():raise Refused('Run stopped before commit')
    intent_file=task_dir/'commit-intent.json';task_id=ready['task']
    if intent_file.exists():intent=read_json(intent_file)
    else:
        finished=execute(root,'scripts/freeze.sh' if task_id=='finalize' else 'scripts/complete.sh',[doc] if task_id=='finalize' else [doc,task_id])
        if finished.returncode:raise Refused(finished.stderr[-3000:])
        expected=candidate_tree(root)
        if expected!=ready['final_tree']:raise Refused('Completion differs from the final Git tree inspected by the reviewer')
        if git(root,'rev-parse','HEAD')!=ready['parent']:raise Refused('HEAD differs from the reviewed task parent')
        intent={'parent':git(root,'rev-parse','HEAD'),'git_tree':expected,
            'message':(f"review: freeze design after track convergence\n\nOH-Run: {run_id}" if task_id=='finalize' else f"task {task_id}: {ready['title']}\n\n{finished.stdout.strip()}\nOH-Run: {run_id}")}
        atomic_json(intent_file,intent,immutable=True)
    head=git(root,'rev-parse','HEAD')
    if head==intent['parent']:
        if candidate_tree(root)!=intent['git_tree']:raise Refused('Edits after task completion do not match the retained commit intent')
        git(root,'add','--all')
        if git(root,'write-tree')!=intent['git_tree']:raise Refused('Staging changed the reviewed result')
        git(root,'commit','-m',intent['message'])
    elif git(root,'rev-parse','HEAD^')!=intent['parent'] or f'OH-Run: {run_id}' not in git(root,'log','-1','--format=%B'):
        raise Refused('HEAD changed after the retained task commit intent')
    if git(root,'rev-parse','HEAD^{tree}')!=ready['final_tree'] or git(root,'rev-parse','HEAD^')!=ready['parent'] or git(root,'status','--porcelain'):
        raise Refused('The committed tree differs from the reviewed transition')
    value={'task':task_id,'commit':git(root,'rev-parse','HEAD')}
    atomic_json(task_dir/'done.json',value,immutable=True)
    started=read_json(task_dir/'started.json')['at']
    review_paths=[p for p in Path(ready['attempt']).parent.glob('*/start.json') if read_json(p).get('session')==run_id]
    review_paths.sort(key=lambda p:read_json(p)['ordinal'])
    reviews=[read_json(p.parent/'completion.json') if (p.parent/'completion.json').exists() else {'outcome':'interrupted'} for p in review_paths]
    rounds=load(root)[1]['config']['review_rounds']
    interventions=sum((p.parent/'resolution.json').exists() for p in review_paths)+max(0,(len(reviews)-1)//rounds)
    best_effort('task.finished',project_id,run_id,task_id,status='completed',
        expected_attempts=len(list(task_dir.glob('worker-*.json')))+len(reviews),expected_reviews=len(reviews),
        confirmed_interventions=interventions,first_review=reviews[0]['outcome'] if reviews else None,
        wall_ms=(datetime.now(timezone.utc)-datetime.fromisoformat(started)).total_seconds()*1000)
    return value


def preview_completion(root,doc,task,design,directory):
    """Render the final document into a Git object before review without consuming authority."""
    result=subprocess.run(['/bin/bash','-c','source "$1"; freeze_render "$2" "$3"','oh-render',
      str(HOME/'core/scripts/freeze.sh'),doc,'' if task=='finalize' else task],cwd=root,env=environment(root),capture_output=True,text=True)
    if result.returncode:raise Refused('Cannot render final lifecycle candidate: '+result.stderr[-2000:])
    path=directory/'completion-preview.md';path.write_text(result.stdout)
    return candidate_tree(root,{str(design.relative_to(root)):path})
