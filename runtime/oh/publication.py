"""Portable PR evidence for native runs; local journals remain the authority."""
import json
import re
from .storage import Refused,Journal,changes,digest,git,project
from .workflow import reduce

START='<!-- oh-review:start -->'
END='<!-- oh-review:end -->'


def task_evidence(state,task,review,parent):
    attempts=[a for a in state['attempts'] if a['task']==task['id'] and a['role']=='review']
    history=[{k:a.get(k) for k in ('id','outcome','duration_ms','profile','findings','git_tree','head')} for a in attempts]
    resolutions={a['id']:state['resolutions'][a['id']] for a in attempts if a['id'] in state['resolutions']}
    value={'schema':1,'project':state['project'],'run':state['id'],'task':task['id'],'title':task['title'],
        'host':state['host'],'version':state['harness_version'],'config_hash':state['config_hash'],'branch':state['branch'],
        'parent':parent,'git_tree':review['git_tree'],'review':review['id'],'attempts':history,'resolutions':resolutions}
    # The first task a run commits was also reviewed with the merges of main resolved by hand before it.
    if (merges:=(state.get('delivery') or {}).get('merges')) and not state['summaries']:value['merges']=merges
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
    expected={'accept concerns':{'concern'},'route scope':{'scope'},'accept concerns and route scope':{'concern','scope'}}
    if expected.get(resolution.get('choice'))!=severities or resolution.get('tree')!=value['git_tree'] or not resolution.get('source'):raise Refused('Missing exact-tree human finding disposition')
    if 'scope' in severities and not resolution.get('issue'):raise Refused('Scope routing is incomplete')


def trailer(root,commit,name):
    values=re.findall('^'+re.escape(name)+r': (.+)$',git(root,'show','-s','--format=%B',commit),re.M)
    if len(values)!=1:raise Refused('Expected exactly one '+name+' trailer on '+commit)
    return values[0]


def commits(root,base,reviewed=()):
    """The branch's commits since `base`, oldest first, without the merges that brought `base` into it. Every merge
    must be Git's clean merge of `base` or one of `reviewed`, whose resolution a review covered; None only lists."""
    anchor=git(root,'merge-base',base,'HEAD');values=[]
    for line in git(root,'rev-list','--reverse','--parents',anchor+'..HEAD').splitlines():
        commit,*parents=line.split()
        if len(parents)>1:
            if reviewed is not None and commit not in reviewed:merged(root,commit,parents,base)
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
    for merge in evidence.get('merges',[]):
        try:
            if len(git(root,'show','-s','--format=%P',merge).split())!=2:raise Refused('Reviewed merge is not a merge')
            git(root,'merge-base','--is-ancestor',merge,evidence['parent'])
        except CalledProcessError:raise Refused('A reviewed merge is not part of this commit\'s history') from None
    for name,value in [('OH-Run',evidence['run']),('OH-Review',evidence['review']),('OH-Reviewed-Tree',evidence['git_tree']),('OH-Evidence',digest(evidence))]:
        if trailer(root,commit,name)!=value:raise Refused('Native review evidence differs from committed '+name)


def has_native_history(root,base):
    # Never downgrade a mixed native branch because its newest commit lacks trailers.
    return any(re.search(r'^OH-(?:Evidence|Run|Review|Reviewed-Tree):',
        git(root,'show','-s','--format=%B',commit),re.M) for commit in commits(root,base,reviewed=None))


def render(root,base='origin/main'):
    if changes(root):raise Refused('Publish only from a clean reviewed checkout')
    records=[];grants={};p=project(root);branch=git(root,'branch','--show-current')
    for commit in commits(root,base,reviewed=None):
        run=trailer(root,commit,'OH-Run');state=reduce(Journal(p['id'],run).records())
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
    commits(root,base,reviewed=covered(records))  # every merge is main's clean one or one a review covered
    value={'schema':1,'branch':branch,'head':git(root,'rev-parse','HEAD'),'records':records,'grants':grants}
    validate_grants(value)
    body=START+'\n```json\n'+json.dumps(value,indent=2)+'\n```\n'+END
    if len(body.encode())>60000:raise Refused('Review evidence exceeds the PR body budget; publish a smaller reviewed batch')
    return body


def covered(records):
    """The merges of main the records' reviews covered, each bound to its commit by the evidence trailer."""
    return {merge for record in records for merge in record['evidence'].get('merges',[])}


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
