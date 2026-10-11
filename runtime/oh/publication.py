"""Portable PR evidence for native runs; local journals remain the authority."""
import json
import re
from pathlib import Path
from .storage import Refused,Journal,changes,digest,git,project
from .workflow import reduce

START='<!-- oh-review:start -->'
END='<!-- oh-review:end -->'


def public_value(root,state,value):
    """Prepare public text before sealing evidence; local journals keep original paths and reports."""
    from .storage import state_home
    from tempfile import gettempdir
    prefixes=[(str(Path.home()),'local'),(str(state_home()),'OH evidence'),(gettempdir(),'local temp')]
    if root:prefixes.append((str(root),'repository'))
    for layout in (state.get('plans',{}),state.get('delivery',{}).get('layout',{})):
        if layout.get('location')=='private' and layout.get('base'):prefixes.append((str(layout['base']),'private plans'))
    prefixes += [(str(Path(prefix).resolve()),label) for prefix,label in prefixes]
    prefixes=sorted(prefixes,key=lambda pair:len(pair[0]),reverse=True)
    def clean(item):
        if isinstance(item,dict):return {k:clean(v) for k,v in item.items()}
        if isinstance(item,list):return [clean(v) for v in item]
        if not isinstance(item,str):return item
        for prefix,label in prefixes:
            for spelling in {prefix.replace('\\','/'),prefix.replace('/','\\')}:
                # Both path spellings occur in host reports; Windows paths are case-insensitive.
                flags=re.I if re.match(r'^[A-Za-z]:',spelling) else 0
                item=re.sub(re.escape(spelling.rstrip('/\\'))+r'[/\\]',lambda _:'' if label=='repository' else label+'/',item,flags=flags)
                item=re.sub(re.escape(spelling.rstrip('/\\'))+r'(?![\w.-])',lambda _:label,item,flags=flags)
        return item
    return clean(value)


def task_evidence(root,state,task,review,parent):
    attempts=[a for a in state['attempts'] if a['task']==task['id'] and a['role']=='review']
    history=[{k:a.get(k) for k in ('id','outcome','duration_ms','profile','findings','git_tree','head')} for a in attempts]
    resolutions={a['id']:state['resolutions'][a['id']]|{'scope':{k:v for k,v in state['resolutions'][a['id']].get('scope',{}).items() if k not in ('render','change')}}
                 for a in attempts if a['id'] in state['resolutions']}
    value={'schema':1,'project':state['project'],'run':state['id'],'task':task['id'],'title':task['title'],
        'host':state['host'],'version':state['harness_version'],'config_hash':state['config_hash'],'branch':state['branch'],
        'parent':parent,'git_tree':review['git_tree'],'review':review['id'],'attempts':history,'resolutions':resolutions}
    # The first task a run commits was also reviewed with the commits OH didn't make before it: the person's own,
    # and merges of main resolved by hand.
    if (covers:=(state.get('delivery') or {}).get('covers')) and not state['summaries']:value['covers']=covers
    scope={k:{name:v for name,v in record.items() if name not in ('render','change')} for k,record in state.get('scope_records',{}).items() if record['task']==task['id']}
    if scope:value['scope']=scope
    value=public_value(root,state,value)
    validate_evidence(value)
    return value


def validate_evidence(value):
    if value.get('schema')!=1 or not isinstance(value.get('attempts'),list) or not value['attempts']:raise Refused('Missing native review history')
    history=value['attempts'];ids=[a['id'] for a in history]
    if len(set(ids))!=len(ids) or ids[-1]!=value['review']:raise Refused('Final review does not match retained history')
    final=history[-1]
    if final['git_tree']!=value['git_tree'] or final['head']!=value['parent']:raise Refused('Review is not bound to this commit tree and parent')
    findings=final.get('findings') or []
    severities={f['severity'] for f in findings}
    if final['outcome']=='clean' and not findings:return
    if final['outcome']!='needs_resolution' or not severities or not severities<={'concern','scope'}:raise Refused('Native final review is unresolved')
    resolution=value.get('resolutions',{}).get(final['id'],{})
    expected={'accept concerns':{'concern'},'route scope':{'scope'},'accept concerns and route scope':{'concern','scope'},
              'dismiss scope':{'scope'},'accept concerns and dismiss scope':{'concern','scope'}}
    if expected.get(resolution.get('choice'))!=severities or resolution.get('tree')!=value['git_tree'] or not resolution.get('source'):raise Refused('Missing exact-tree human finding disposition')
    if 'scope' in severities and not resolution.get('issue'):
        scope=resolution.get('scope',{})
        if scope.get('attempt')!=final['id'] or scope.get('findings')!=[f for f in findings if f['severity']=='scope'] or scope.get('action')!='dismiss' or scope.get('destination')!={'pr':True}:raise Refused('Scope routing is incomplete')


def trailer(root,commit,name):
    values=re.findall('^'+re.escape(name)+r': (.+)$',git(root,'show','-s','--format=%B',commit),re.M)
    if len(values)!=1:raise Refused('Expected exactly one '+name+' trailer on '+commit)
    return values[0]


def made(root,project_id,commit):
    """The state of the OH run that made `commit`, or None: its trailer names the run, and that run recorded this
    exact commit. A message that merely claims to be OH's, or an OH commit the person amended or rebased, is not."""
    try:state=reduce(Journal(project_id,trailer(root,commit,'OH-Run')).records())
    except Refused:return None
    return state if any(done.get('commit')==commit for done in state['summaries']) else None


def commits(root,base,reviewed=()):
    """The branch's commits since `base`, oldest first, without the merges that brought `base` into it and without
    `reviewed`, the commits OH didn't make that a review covered. Every other merge must be Git's clean merge of
    `base`. None only lists every commit that isn't a merge."""
    anchor=git(root,'merge-base',base,'HEAD');values=[]
    for line in git(root,'rev-list','--reverse','--parents',anchor+'..HEAD').splitlines():
        commit,*parents=line.split()
        if reviewed is not None and commit in reviewed:continue
        if len(parents)>1:
            if reviewed is not None:merged(root,commit,parents,base)
        else:values.append(commit)
    if not values:raise Refused('No reviewed commits to publish')
    return values


def merged(root,commit,parents,base):
    """Refuse a merge unless it brought `base` into the branch exactly as Git merges it without conflicts, so it
    carries no change of its own for review to miss."""
    from subprocess import CalledProcessError
    from .branches import merged_tree
    try:
        git(root,'merge-base','--is-ancestor',parents[-1],base)
        clean=len(parents)==2 and merged_tree(root,*parents)==git(root,'rev-parse',commit+'^{tree}')
    except CalledProcessError:clean=False
    if not clean:raise Refused(f'Merge {commit[:12]} is not a clean merge of {base} into the branch, so OH cannot publish it as reviewed')


def verify_record(root,commit,evidence):
    validate_evidence(evidence)
    if git(root,'show','-s','--format=%P',commit)!=evidence['parent'] or git(root,'rev-parse',commit+'^{tree}')!=evidence['git_tree']:raise Refused('Native evidence does not describe the actual commit')
    from subprocess import CalledProcessError
    for covered in evidence.get('covers',[]):
        try:git(root,'merge-base','--is-ancestor',covered,evidence['parent'])
        except CalledProcessError:raise Refused('A commit this review covered is not part of its history') from None
    for name,value in [('OH-Run',evidence['run']),('OH-Review',evidence['review']),('OH-Reviewed-Tree',evidence['git_tree']),('OH-Evidence',digest(evidence))]:
        if trailer(root,commit,name)!=value:raise Refused('Native review evidence differs from committed '+name)


def has_native_history(root,base):
    # Never downgrade a mixed native branch because its newest commit lacks trailers.
    return any(re.search(r'^OH-(?:Evidence|Run|Review|Reviewed-Tree):',
        git(root,'show','-s','--format=%B',commit),re.M) for commit in commits(root,base,reviewed=None))


def reference(root):
    """Publication keeps the base selected when the person approved the run."""
    from .branches import main_ref
    from .workflow import active_file,load_run
    config=None
    if active_file(root).exists():
        _,state=load_run(root)
        if state['status']=='pr':config=state['config']
    return main_ref(root,config)


def render(root,base=None):
    base=base or reference(root)
    if not base:raise Refused('No base branch found; set base_branch with oh config')
    if changes(root):raise Refused('Publish only from a clean reviewed checkout')
    records=[];grants={};states={};p=project(root);branch=git(root,'branch','--show-current')
    for commit in commits(root,base,reviewed=None):
        state=made(root,p['id'],commit)
        if not state:continue  # not OH's: it must be one a review covered, checked below
        run=state['id']
        if run not in states:
            from .delivery_verify import verify_run
            verify_run(root,state,current=any(d.get('commit')==git(root,'rev-parse','HEAD') for d in state['summaries']))
        states[run]=state
        # A stopped run's commits, or those of a completed run nobody chose to publish, are published by the PR
        # choice of the run that resumed its branch.
        if state['status'] not in ('pr','stopped','completed'):raise Refused('A recorded human PR choice is required before exporting native evidence')
        if state['status']=='pr':grants[run]=state.get('publication')
        done=[t for t in state['summaries'] if t['commit']==commit]
        if len(done)!=1:raise Refused('Commit has no unique authoritative task completion')
        evidence=state['commit_intents'][done[0]['task']].get('publication')
        if not evidence:raise Refused('This older run lacks portable review evidence; obtain a fresh final review before publication')
        if evidence['branch']!=branch:raise Refused('Review evidence belongs to another branch')
        verify_record(root,commit,evidence)
        records.append({'commit':commit,'evidence':evidence})
    if commits(root,base,reviewed=covered(records))!=[record['commit'] for record in records]:
        raise Refused('This branch holds commits that OH neither made nor reviewed, so OH cannot publish it as reviewed')
    value={'schema':1,'branch':branch,'head':git(root,'rev-parse','HEAD'),'records':records,'grants':grants}
    validate_grants(value)
    notes=''.join('\n\nFound along the way (task '+r['evidence']['task']+'):\n'+''.join('\n> '+line for f in record['findings'] for line in f['description'].splitlines()) for r in records for record in r['evidence'].get('scope',{}).values() if record['action']=='noted' and record['destination'].get('pr'))
    notes=public_value(root,{},notes)
    # Keep portable evidence in the PR source, not its rendered description. Escape HTML so
    # finding text containing a comment terminator cannot expose the machine packet.
    packet=json.dumps(value,separators=(',',':')).replace('&',r'\u0026').replace('<',r'\u003c').replace('>',r'\u003e')
    body='Base branch: `'+base+'`.\n\n'+readable(records,states,root)+notes+'\n\n'+START+'\n<!--\n```json\n'+packet+'\n```\n-->\n'+END
    if len(body.encode())>60000:raise Refused('Review evidence exceeds the PR body budget; publish a smaller reviewed batch')
    return body


def readable(records,states,root=None):
    """Work, verification and review decisions; full execution history remains in the journal."""
    from .gates import finding_text,report_text
    lines=[]
    for record in records:
        evidence=record['evidence'];state=states[evidence['run']];task=evidence['task']
        lines.append(f"### Task {task}: {evidence['title']}")
        worker=next((a for a in reversed(state['attempts']) if a['task']==task and a['role'] in ('implementation','analysis') and a.get('outcome')=='implemented'),None)
        lines.extend(['',report_text(worker) or 'No implementing report recorded.' if worker else 'No implementing report recorded.',''])
        verification=state.get('verification',{}).get(task)
        checks=verification.get('checks',[]) if verification else []
        lines.append('Verification: '+('; '.join(c['name']+' ('+('passed' if c['returncode']==0 else 'failed')+')' for c in checks) if checks else
                     'document validation passed' if state.get('workflow') in ('design','propose') else
                     'no project checks applied' if verification else 'no check results recorded')+'.')
        reviews=evidence['attempts'];final=reviews[-1]
        outcome='clean' if final['outcome']=='clean' else 'completed with recorded finding decisions'
        lines.append(f"Independent invariant review: {outcome}; {len(reviews)} round"+('s' if len(reviews)!=1 else '')+'.')
        for number,attempt in enumerate(reviews,1):
            if not attempt.get('findings'):continue
            lines.extend(['',f'Review {number} findings:'])
            lines.extend('- '+finding_text(f) for f in attempt['findings'])
            resolution=evidence['resolutions'].get(attempt['id'])
            if resolution:
                lines.append('Decision: '+resolution['choice']+'.')
            scope=evidence.get('scope',{}).get(attempt['id'])
            if scope:
                from pathlib import Path
                destination=scope['destination']
                where=(destination['issue']['url'] if destination.get('issue') else
                       Path(destination['design']).name+' '+destination['section'] if destination.get('design') else 'this PR')
                lines.append('Scope: '+scope['action']+'; recorded in '+where+'.')
            elif resolution and resolution.get('issue'):lines.append('Destination: '+resolution['issue']['url']+'.')
        lines.append('')
    return public_value(root,{},'\n'.join(lines))


def covered(records):
    """The commits OH didn't make that the records' reviews covered, each bound to its commit by the evidence trailer."""
    return {commit for record in records for commit in record['evidence'].get('covers',[])}


def validate_grants(value):
    """Each run's PR choice covers the next stretch of the branch's commits: its own, after any that a stopped run
    left on the branch before this run resumed it. Together they cover every commit once, in order."""
    records=value['records'];grants=value.get('grants',{});at=0
    if not isinstance(grants,dict) or not grants:raise Refused('Every run needs its retained publication grant')
    for run,grant in grants.items():
        if not isinstance(grant,dict) or grant.get('choice')!='pr' or not re.fullmatch('[0-9a-f]{64}',grant.get('source','')) or grant.get('branch')!=value['branch'] or not isinstance(grant.get('commits'),list) or not grant['commits'] or grant.get('head')!=grant['commits'][-1]:
            raise Refused('Publication grant does not cover the exact reviewed run commits')
        stretch=records[at:at+len(grant['commits'])];at+=len(stretch)
        own=[r['evidence']['run']==run for r in stretch]
        if [r['commit'] for r in stretch]!=grant['commits'] or not own[-1] or own!=sorted(own) or any(r['evidence']['run'] in grants for r,mine in zip(stretch,own) if not mine):
            raise Refused('Publication grant does not cover the exact reviewed run commits')
    if at!=len(records):raise Refused('Every run needs its retained publication grant')
    if records[-1]['commit']!=value['head']:raise Refused('Publication grant does not cover this branch head')


def validate_event(root,event,base):
    pr=event['pull_request'];body=pr.get('body') or ''
    if body.count(START)!=1 or body.count(END)!=1:raise Refused('PR must retain one complete native OH review summary')
    block=body.split(START,1)[1].split(END,1)[0].strip()
    if block.startswith('<!--\n') and block.endswith('\n-->'):block=block[5:-4].strip()
    if not block.startswith('```json\n') or not block.endswith('\n```'):raise Refused('Malformed native review summary')
    value=json.loads(block[8:-4])
    if value.get('schema')!=1 or value['head']!=git(root,'rev-parse','HEAD') or value['head']!=pr['head']['sha'] or value['branch']!=pr['head']['ref']:raise Refused('Native PR summary is stale or belongs to another branch')
    validate_grants(value)
    expected=commits(root,base,reviewed=covered(value['records']))
    if [r['commit'] for r in value['records']]!=expected:raise Refused('Native PR summary must cover every commit exactly once in order')
    for record in value['records']:
        if record['evidence']['branch']!=value['branch'] or record['evidence']['project']!=project(root)['id']:raise Refused('Native review project/branch mismatch')
        verify_record(root,record['commit'],record['evidence'])
    return {'status':'verified','commits':len(expected)}
