"""Verify saved delivery evidence and prepare a human-readable PR summary."""
import json
import re
from pathlib import Path
from .storage import Refused,Journal,changes,digest,git,project,state_writer
from .workflow import reduce
from .verification import check_failed

def summary_identity(body):
    """An update locator, never approval or a replacement for saved review evidence."""
    matches=re.findall(r'<!-- oh-publication:([0-9a-f]{64}) -->',body or '')
    return matches[0] if len(matches)==1 else None


def destination(root, *, required=False):
    """Bind Git's actual push destination without copying credentials into questions or receipts."""
    from .branches import run_git
    from urllib.parse import urlsplit, urlunsplit
    result=run_git(root,'remote','get-url','--push','--all','origin')
    urls=result.stdout.strip().splitlines() if result.returncode==0 else []
    if len(urls)!=1:
        if required:raise Refused('Publication needs one origin push destination. Configure the intended repository as origin, then use the current publication choice; completed work and review are retained.')
        return None
    raw=urls[0]
    if '://' in raw:
        parsed=urlsplit(raw)
        display=urlunsplit((parsed.scheme,parsed.netloc.rsplit('@',1)[-1],parsed.path,'',''))
    else:
        display=re.sub(r'^[^/@:]+@([^:]+):',r'ssh://\1/',raw).split('?',1)[0].split('#',1)[0]
    return {'remote':'origin','destination':display,'remote_fingerprint':digest(urls)}


def destination_state(root, state):
    if state['status']!='pr' or state.get('published'):return state
    grant=state.get('publication') or {}
    expected={k:grant.get(k) for k in ('remote','destination','remote_fingerprint')}
    return state|{'publication_changed':destination(root)!=expected}


def settled(state):
    """Original completion evidence cannot settle a newer task review or correction."""
    if state.get('extra_review') or state.get('correction'):
        raise Refused('Finish the requested task review and any reviewed correction before publication; original commits and evidence are retained.')


def repository(grant):
    """Use the approved push destination, never the checkout's possibly changed remote."""
    from urllib.parse import urlsplit
    url=urlsplit(grant.get('destination',''))
    path=url.path.strip('/').removesuffix('.git')
    if (url.scheme not in ('https','http','ssh','git') or not url.hostname or
            not re.fullmatch(r'[A-Za-z0-9.-]+',url.hostname) or
            not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',path)):
        raise Refused('OH cannot verify a PR at the saved publication destination. Check the approved GitHub repository before publishing; saved work and approval are retained.')
    return url.hostname,path


def github(root,host,endpoint,*,pages=False):
    """Read GitHub facts through the person's existing gh login; never create or update a PR."""
    import subprocess
    args=['gh','api','--hostname',host,endpoint]+(['--paginate','--slurp'] if pages else [])
    try:
        result=subprocess.run(args,cwd=Path(__file__).resolve().parent,capture_output=True,text=True,encoding='utf-8',timeout=30)
    except FileNotFoundError:
        raise Refused('GitHub verification needs gh. Install GitHub CLI, then repeat publication; do not create another PR before checking for the existing one.') from None
    except (OSError,subprocess.TimeoutExpired):
        raise Refused('GitHub verification could not finish. Check the connection and gh authentication, then repeat publication; do not create another PR while its result is unknown.') from None
    if result.returncode:
        raise Refused('GitHub could not verify publication. Check gh auth status and access to the approved repository, then repeat publication; no duplicate PR should be created.')
    try:
        value=json.loads(result.stdout)
        if pages:
            if not isinstance(value,list) or any(not isinstance(page,list) for page in value):raise ValueError()
            return [item for page in value for item in page]
        if not isinstance(value,dict):raise ValueError()
        return value
    except ValueError:
        raise Refused('GitHub returned an incomplete publication result. Repeat publication once the API is available; keep the existing approval.') from None


def correction_pr(root,target,*,heads=None):
    """Recheck an explicitly selected PR without granting edits or publication."""
    from urllib.parse import urlsplit
    if destination(root)!={k:target[k] for k in ('remote','destination','remote_fingerprint')}:
        raise Refused('The selected PR destination changed. Restore its origin remote, or cancel and prepare the intended PR again.')
    host,repo=repository(target)
    pr=github(root,host,f'repos/{repo}/pulls/{target["number"]}')
    try:
        url=urlsplit(pr['html_url'])
        valid=(type(pr['id']) is int and type(pr['number']) is int and pr['number']==target['number'] and
               url.scheme=='https' and url.hostname==host and url.path.casefold()==f'/{repo}/pull/{target["number"]}'.casefold() and
               pr['state']=='open' and not pr.get('merged_at') and
               pr['base']['repo']['full_name'].casefold()==repo.casefold() and
               (pr['head'].get('repo') or {}).get('full_name','').casefold()==repo.casefold() and
               pr['base']['ref']==target['base_branch'] and
               isinstance(pr['head']['ref'],str) and
               re.fullmatch('[0-9a-f]{40,64}',pr['head']['sha']) and
               ('id' not in target or pr['id']==target['id']) and
               ('branch' not in target or pr['head']['ref']==target['branch']) and
               ('head' not in target or pr['head']['sha'] in (heads or (target['head'],))))
        if not valid:raise ValueError()
    except (KeyError,TypeError,ValueError,AttributeError):
        raise Refused('The selected PR is no longer the same open PR, branch, base or head in origin. Preserve the work and inspect the PR; prepare a new scope if its target changed. No other PR is authorized.') from None
    return pr


def prepare_correction(root,number,*,previous=None):
    """Select existing PR work before preparing scope; never reset or overwrite it."""
    from .branches import untouched,trunk,run_git,holder
    if type(number) is not int or number<=0:raise Refused('The PR number must be positive')
    untouched(root)
    # Refinement can approve a fresh head, but cannot silently retarget the PR or remote.
    target=({k:v for k,v in previous.items() if k!='head'} if previous else
            destination(root,required=True)|{'number':number,'base_branch':trunk(root)})
    pr=correction_pr(root,target)
    branch=pr['head']['ref'];head=pr['head']['sha']
    if not isinstance(branch,str) or branch==target['base_branch'] or run_git(root,'check-ref-format','--branch',branch).returncode:
        raise Refused('The selected PR needs a valid execution branch distinct from the base branch.')
    if holder(root,branch):raise Refused(f'{branch} is checked out in another worktree. Prepare this PR from that checkout; its work is preserved.')
    target.update(id=pr['id'],url=pr['html_url'],branch=branch,head=head)
    fetched=run_git(root,'fetch','--quiet','origin','refs/heads/'+branch,timeout=60)
    if fetched.returncode or git(root,'rev-parse','FETCH_HEAD')!=head:
        raise Refused('The selected PR head could not be fetched unchanged. Check the connection and current PR head, then prepare again; no branch was switched.')
    local=run_git(root,'show-ref','--verify','--quiet','refs/heads/'+branch).returncode==0
    if local and run_git(root,'merge-base','--is-ancestor','refs/heads/'+branch,head).returncode:
        raise Refused(f'{branch} has local work outside the selected PR head. Preserve and reconcile those commits before preparing this correction; OH will not reset them.')
    if local:
        git(root,'switch','--quiet',branch)
        git(root,'merge','--ff-only','--quiet',head)
    else:git(root,'switch','--quiet','--no-track','-c',branch,head)
    from .branches import main_ref
    from .delivery import unreviewed
    base=main_ref(root,{'base_branch':target['base_branch']})
    fork=git(root,'merge-base',base,head)
    target.update(review_base=fork,covers=unreviewed(root,fork,base))
    return target


def discover(root,state,number=None):
    """Find this run's PR, including creation that succeeded before OH saved its receipt."""
    from urllib.parse import urlencode,urlsplit
    grant=state.get('publication') or {}
    host,repo=repository(grant)
    saved=state.get('published')
    if (target:=state.get('pr_target')) and not saved:
        if number is not None and number!=target['number']:raise Refused('This correction targets its approved existing PR; no other PR is authorized.')
        pr=correction_pr(root,target,heads=(target['head'],grant['head']))
        # The old PR is expected before push. After push, an interrupted body update
        # still needs finishing; neither state is a completed publication receipt.
        current=(pr['head']['sha']==grant['head'] and
                 summary_identity(pr.get('body'))==summary_identity(render(root)))
        return {'id':pr['id'],'number':pr['number'],'url':pr['html_url'],'repository':repo,'host':host,
                'state':'open','observed_head':pr['head']['sha'],'pending_update':not current}
    if saved:
        if number is not None and number!=saved['number']:raise Refused('This delivery already has a recorded PR; use its saved link.')
        number=saved['number']
    prefix=f'repos/{repo}/pulls'
    candidates=([github(root,host,f'{prefix}/{number}')] if number else
                github(root,host,prefix+'?'+urlencode({'state':'all','head':repo.split('/')[0]+':'+grant['branch'],
                                                       'base':grant['base_branch'],'per_page':100}),pages=True))
    matches=[];open_other=False
    for pr in candidates:
        try:
            if (type(pr['id']) is not int or type(pr['number']) is not int or pr['number']<=0 or
                    pr['state'] not in ('open','closed') or not re.fullmatch('[0-9a-f]{40,64}',pr['head']['sha'])):raise ValueError()
            if number is not None and pr['number']!=number:raise ValueError()
            url=urlsplit(pr['html_url'])
            identity=(url.scheme=='https' and url.hostname==host and
                      url.path.casefold()==f'/{repo}/pull/{pr["number"]}'.casefold() and
                      pr['base']['repo']['full_name'].casefold()==repo.casefold())
            if saved:
                if not identity or pr['number']!=number or pr['id']!=saved['id']:raise ValueError()
                matches.append(pr);continue  # the receipt remains valid after later head/base edits
            bound=(identity and pr['base']['ref']==grant['base_branch'] and pr['head']['ref']==grant['branch'] and
                   (pr['head'].get('repo') or {}).get('full_name','').casefold()==repo.casefold())
            if not bound:
                if number:raise ValueError()
                if pr['state']=='open':open_other=True
                continue
            holds=pr['head']['sha']==grant['head']
            if not holds:
                history=github(root,host,f'{prefix}/{pr["number"]}/commits?per_page=100',pages=True)
                holds=any(c['sha']==grant['head'] for c in history)
                # GitHub caps this endpoint at 250 commits. Absence in a truncated list is not proof.
                if not holds and len(history)>=250:
                    raise Refused('This PR has too many commits to confirm the saved delivery through GitHub. Inspect the PR against the approved commit before proceeding; OH will not create a duplicate.')
            if holds:matches.append(pr)
            elif pr['state']=='open':open_other=True
        except (KeyError,TypeError,ValueError):
            raise Refused('GitHub PR details do not match the saved delivery. Check the repository and PR identity before proceeding; no publication result was recorded.') from None
    if len(matches)>1:
        raise Refused('Several PRs contain this delivery: '+', '.join(str(p['number']) for p in matches)+
                      '. Identify the intended PR, then run publication --pr NUMBER to verify it; do not create another.')
    if not matches:
        if number or open_other:raise Refused('The existing PR does not contain the approved delivery commit. Reconcile that PR with the saved work before publishing; OH will not create a competing PR.')
        return None
    pr=matches[0]
    return {'id':pr['id'],'number':pr['number'],'url':pr['html_url'],'repository':repo,'host':host,
            'state':'merged' if pr.get('merged_at') else pr['state'],'observed_head':pr['head']['sha']}


@state_writer
def reconcile(root,number=None):
    """Append only verified publication evidence, independent of the publishing session's lifetime."""
    import os
    from .storage import now
    from .workflow import load_run,checkpoint,settled_owner
    if os.environ.get('OH_CHILD_ATTEMPT'):raise Refused('Workers cannot record their parent run\'s publication')
    with settled_owner(root):
        journal,state=load_run(root)
        if state['status']!='pr' or not state.get('publication'):
            raise Refused('This run has no publication approval. Use the current delivery decision first.')
        try:found=discover(root,state,number)
        except Refused as exc:
            if not state.get('published'):raise
            return checkpoint(root)|{'publication_notice':str(exc),'publication_status':'last verified'}
        if found and found.get('pending_update'):
            if git(root,'rev-parse','HEAD')!=state['publication']['head'] or git(root,'branch','--show-current')!=state['publication']['branch'] or changes(root):
                raise Refused('The checkout changed after publication approval. Preserve the changes and return to the approved clean branch head before updating this PR.')
            return checkpoint(root)|{'publication_status':'update pending','existing_pr':found,
                'push_required':found['observed_head']!=state['publication']['head']}
        if found:found.pop('pending_update',None)  # a transient next action is not part of the completed receipt
        if found and not state.get('published'):
            grant=state['publication']
            journal.append('publication.completed',found|{'run':state['id'],'grant':grant['source'],
                'approved_head':grant['head'],'branch':grant['branch'],'base_branch':grant['base_branch'],
                'destination':grant['destination'],'verified_at':now()})
        result=checkpoint(root)
        if found:return result|{'published':result['published']|found,'publication_status':'current'}
        # No PR exists. A later local head is not permission to push those edits (or rewind them).
        if git(root,'rev-parse','HEAD')!=state['publication']['head']:
            raise Refused('No matching PR exists, and this checkout has later or different work. Reconcile it with the approved commit before publication; no later work is approved by this run.')
        return result|{'publication_status':'not published'}


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
    from .review import workflow_reviews
    if review.get('purpose','workflow')!='workflow':raise Refused('Standalone review cannot authorize completion')
    attempts=workflow_reviews(state,task['id'])
    history=[{k:a.get(k) for k in ('id','host','outcome','duration_ms','profile','findings','git_tree','head','started_at','finished_at','report_issues','review_fragments','finding_positions')} for a in attempts]
    resolutions={a['id']:state['resolutions'][a['id']]|{'scope':{k:v for k,v in state['resolutions'][a['id']].get('scope',{}).items() if k not in ('render','change')}}
                 for a in attempts if a['id'] in state['resolutions']}
    value={'schema':1,'project':state['project'],'run':state['id'],'task':task['id'],'title':task['title'],
        'host':state['host'],'version':state['harness_version'],'config_hash':state['config_hash'],'branch':state['branch'],
        'parent':parent,'git_tree':review['git_tree'],'review':review['id'],'attempts':history,'resolutions':resolutions,'scope_policy':'retained-followups'}
    if state.get('correction'):
        value['correction_of']=state['correction']['prior_commit']
        correction_ancestor(root,value)
    # The first task a run commits was also reviewed with the commits OH didn't make before it: the person's own,
    # and merges of main resolved by hand.
    if (covers:=state.get('covers') or (state.get('delivery') or {}).get('covers') or state.get('repair_source',{}).get('covers') or state.get('pr_target',{}).get('covers')) and not state['summaries']:value['covers']=covers
    scope={k:{name:v for name,v in record.items() if name not in ('render','change')} for k,record in state.get('scope_records',{}).items() if record['task']==task['id']}
    if scope:value['scope']=scope
    value=public_value(root,state,value)
    validate_evidence(value)
    return value


def issue_url(value):
    """Current native strings and historical issue objects describe the same destination."""
    return value.get('url','') if isinstance(value,dict) else value if isinstance(value,str) else ''


def validate_scope(value):
    for attempt in value['attempts']:
        findings=[f for f in attempt.get('findings',[]) if f['severity']=='scope']
        if not findings:continue
        record=value.get('scope',{}).get(attempt['id']) or value.get('resolutions',{}).get(attempt['id'],{}).get('scope',{})
        resolution=value.get('resolutions',{}).get(attempt['id'],{})
        if not record and value.get('scope_policy')=='retained-followups':continue
        if record.get('action')=='retained' and record.get('destination')=={'saved':True} and record.get('findings')==findings and record.get('attempt')==attempt['id'] and value.get('scope_policy')=='retained-followups':continue
        if not record and resolution.get('issue') and 'route scope' in resolution.get('choice',''):
            continue  # historical exact-review disposition predates separate scope records
        if record.get('attempt')!=attempt['id'] or record.get('findings')!=findings or not record.get('source'):
            raise Refused('Outstanding scope findings require their explicit retained disposition')
        destination=record.get('destination',{})
        if record.get('action')=='dismiss' and (destination=={'pr':True} or
                destination.get('design') and destination.get('section')=='## Scope decisions'):continue
        if record.get('action') in ('route','noted') and (issue_url(destination.get('issue')) or
                destination.get('design') and destination.get('section') or destination.get('pr') and record['action']=='noted'):continue
        raise Refused('Scope routing is incomplete')


def correction_ancestor(root,value):
    if not value.get('correction_of'):return
    from subprocess import CalledProcessError
    try:git(root,'merge-base','--is-ancestor',value['correction_of'],value['parent'])
    except CalledProcessError:raise Refused('The original corrected task is not part of the reviewed parent history') from None
    if trailer(root,value['correction_of'],'OH-Run')!=value['run'] or trailer(root,value['correction_of'],'OH-Review') not in {a['id'] for a in value['attempts']}:
        raise Refused('Correction does not identify an earlier reviewed task in this run')


def validate_evidence(value):
    if value.get('schema')!=1 or not isinstance(value.get('attempts'),list) or not value['attempts']:raise Refused('Missing native review history')
    history=value['attempts'];ids=[a['id'] for a in history]
    if len(set(ids))!=len(ids) or ids[-1]!=value['review']:raise Refused('Final review does not match retained history')
    final=history[-1]
    if final.get('report_issues') or final.get('review_fragments'):raise Refused('The final review has unclassified evidence; obtain a complete review of the retained fragments before completion')
    if final['git_tree']!=value['git_tree'] or final['head']!=value['parent']:raise Refused('Review is not bound to this commit tree and parent')
    validate_scope(value)
    findings=final.get('findings') or []
    severities={f['severity'] for f in findings}
    if final['outcome']=='clean' and not findings:return
    if final['outcome']!='needs_resolution' or not severities or not severities<={'concern','scope'}:raise Refused('Native final review is unresolved')
    resolution=value.get('resolutions',{}).get(final['id'],{})
    if value.get('scope_policy')=='retained-followups':
        severities=severities-{'scope'}
        if not severities:return
    expected={'accept concerns':{'concern'},'route scope':{'scope'},'accept concerns and route scope':{'concern','scope'},
              'dismiss scope':{'scope'},'accept concerns and dismiss scope':{'concern','scope'}}
    if value.get('scope_policy')=='retained-followups':expected={k:v-{'scope'} for k,v in expected.items()}
    if expected.get(resolution.get('choice'))!=severities or resolution.get('tree')!=value['git_tree'] or not resolution.get('source'):raise Refused('Missing exact-tree human finding disposition')


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
    correction_ancestor(root,evidence)
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
        if state['status']=='pr':
            config=state['config']
            if state.get('pr_target'):config=config|{'base_branch':state['pr_target']['base_branch']}
    return main_ref(root,config)


def render(root,base=None):
    from .workflow import active_file,load_run
    if active_file(root).exists() and (state:=load_run(root)[1]).get('published'):
        raise Refused('This delivery is already published: '+state['published']['url']+'. Use its PR; a new Deliver request starts further approved work.')
    base=base or reference(root)
    if not base:raise Refused('No base branch found; set base_branch with oh config')
    if changes(root):raise Refused('Publish only from a clean reviewed checkout')
    records=[];grants={};states={};p=project(root);branch=git(root,'branch','--show-current')
    for commit in commits(root,base,reviewed=None):
        state=made(root,p['id'],commit)
        if not state:continue  # not OH's: it must be one a review covered, checked below
        settled(state)
        run=state['id']
        if run not in states:
            from .delivery_verify import verify_run
            verify_run(root,state,current=any(d.get('commit')==git(root,'rev-parse','HEAD') for d in state['summaries']))
        states[run]=state
        # A stopped run's commits, or those of a completed run nobody chose to publish, are published by the PR
        # choice of the run that resumed its branch.
        if state['status'] not in ('pr','stopped','completed'):raise Refused('A recorded human PR choice is required before exporting native evidence')
        if state['status']=='pr':
            grant=state.get('publication')
            if grant and grant.get('remote_fingerprint') and destination(root)!= {k:grant[k] for k in ('remote','destination','remote_fingerprint')}:
                raise Refused('The publication destination changed after approval. Restore the approved remote or request publication for the new destination; do not rerun completed tasks.')
            grants[run]=grant
        done=[t for t in state['summaries'] if t['commit']==commit]
        if len(done)!=1:raise Refused('Commit has no unique authoritative task completion')
        evidence=state['commit_intents'][done[0].get('commit_key',done[0]['task'])].get('publication')
        if not evidence:raise Refused('This older run lacks portable review evidence; obtain a fresh final review before publication')
        if evidence['branch']!=branch:raise Refused('Review evidence belongs to another branch')
        verify_record(root,commit,evidence)
        records.append({'commit':commit,'evidence':evidence})
    if commits(root,base,reviewed=covered(records))!=[record['commit'] for record in records]:
        raise Refused('This branch holds commits that OH neither made nor reviewed, so OH cannot publish it as reviewed')
    value=public_value(root,{}, {'schema':1,'branch':branch,'head':git(root,'rev-parse','HEAD'),'records':records,'grants':grants})
    validate_grants(value)
    target=next((g.get('base_branch',base) for g in grants.values() if g.get('head')==value['head']),base)
    # Full evidence is already retained and verified above. PR prose is a presentation,
    # not another journal or a machine evidence transport. The host may summarize it.
    summary=readable(records,states,root)
    identity=digest({'evidence':value,'summary':summary})
    return 'Base branch: `'+target+'`.\n\n'+summary+'\n<!-- oh-publication:'+identity+' -->\n'


def readable(records,states,root=None):
    """Factual starting point for the host's PR narrative; complete receipts stay saved."""
    from html import escape
    from .handoff import report,finding_index
    from .receipts import seconds
    from .review import workflow_reviews
    grouped={}
    for record in records:
        evidence=record['evidence'];key=(evidence['run'],evidence['task'])
        first=grouped.get(key,record)
        grouped[key]=record|{'original_evidence':first.get('original_evidence',first['evidence'])}
    lines=[]
    for record in grouped.values():
        evidence=record['evidence'];state=states[evidence['run']];task=evidence['task']
        original=record['original_evidence']
        at=next((i for i,a in enumerate(state['attempts']) if a.get('id')==original['review']),len(state['attempts']))
        author=next((a for a in reversed(state['attempts'][:at]) if a['task']==task and
                     a['role'] in ('implementation','analysis') and a.get('outcome')=='implemented'),None)
        value=report(author)
        summary=value.get('summary') or (author or {}).get('human_summary') or (author or {}).get('summary')
        summary=(summary or 'No author summary was recorded.').split('\n\n',1)[0].strip()
        lines.extend([f"## Task {task} — {escape(evidence['title'])}",'',escape(public_value(root,state,summary)),''])
        if original!=evidence:
            repair=next((a for a in reversed(state['attempts']) if a['task']==task and a['role']=='implementation' and a.get('outcome')=='implemented'),None)
            lines.extend(['Correction: '+escape(public_value(root,state,report(repair).get('summary','Reviewed corrections committed.').split('\n\n',1)[0].strip())), ''])
        if evidence.get('covers') or original.get('covers'):
            lines.extend(['Includes reviewed original commits: '+', '.join('`'+c+'`' for c in dict.fromkeys(original.get('covers',[])+evidence.get('covers',[])))+'.',''])
        reviews=workflow_reviews(state,task) or evidence['attempts'];final=reviews[-1]
        lines.extend([f"Review rounds: **{len(reviews)}**",'',f"Final receipt: `{final['id']}`",'',
                      'Final receipt elapsed: **'+seconds(final.get('duration_ms'))+'**','', '### Verification',''])
        verification=state.get('verification',{}).get(task)
        checks=verification.get('checks',[]) if verification else []
        for check in checks:lines.append('- '+escape(check['name'])+': '+('failed' if check_failed(check) else 'passed')+'.')
        if not checks:lines.append('Document validation passed.' if state.get('workflow') in ('design','propose') else
                                    'No project checks applied.' if verification else 'Not recorded.')
        # Legacy structured manifests can be presented directly. Current receipts have
        # flexible prose: the native host reads and summarizes them without a parser.
        manifest=report(final).get('evidence')
        if isinstance(manifest,dict):
            lines.extend(['','### Final evidence manifest',''])
            for key,title in (('anchors','Anchors read'),('lenses','Scope examined'),('attacks','Adversarial attacks'),('limits','Limits')):
                items=manifest.get(key)
                if not items:continue
                lines.extend(['#### '+title,''])
                if isinstance(items,dict):lines.extend('- '+escape(str(k))+': '+escape(str(v)) for k,v in items.items())
                elif isinstance(items,list):lines.extend('- '+escape(str(item)) for item in items)
                lines.append('')
        severities={f['severity'] for f in final.get('findings',[])}
        outcome=('clean' if final['outcome']=='clean' else 'ready with outside-scope follow-ups' if severities=={'scope'} else 'completed with recorded concern acceptance')
        lines.extend(['','### Final verdict','',outcome+'.','','### Findings and dispositions',''])
        dispositions={item['id']:item['disposition'] for family in finding_index(state,task)['families'] for item in family['occurrences']}
        for number,attempt in enumerate(reviews,1):
            if not attempt.get('findings'):
                lines.append(f"- Round {number}: "+('no findings; clean verdict.' if attempt['outcome']=='clean' else 'no completed verdict; retained in workflow history.'))
            for position,item in enumerate(attempt.get('findings',[]),1):
                positions=attempt.get('finding_positions') or list(range(1,len(attempt['findings'])+1))
                finding_id=attempt['id']+'#'+str(positions[position-1])
                disposition=dispositions.get(finding_id,'still-open')
                description=' '.join(item['description'].split())
                lines.append(f"- Round {number} — **{item['severity'].upper()}**: "+escape(description)+' **'+disposition+'**.')
            resolution=(evidence.get('resolutions',{})|state.get('resolutions',{})).get(attempt['id'])
            scope=(evidence.get('scope',{})|state.get('scope_records',{})).get(attempt['id'])
            if resolution:lines.append('  Decision: '+escape(resolution['choice'])+'.')
            if scope:
                destination=scope['destination']
                where=(issue_url(destination['issue']) if destination.get('issue') else
                       Path(destination['design']).name+' '+destination['section'] if destination.get('design') else 'saved workflow follow-ups' if destination.get('saved') else 'this PR')
                lines.append('  Scope: '+scope['action']+'; recorded in '+escape(where)+'.')
            elif resolution and resolution.get('issue'):lines.append('  Destination: '+issue_url(resolution['issue'])+'.')
            elif any(f['severity']=='scope' for f in attempt.get('findings',[])):
                lines.append('  Outside-scope work remains open in saved workflow follow-ups; it was not implemented or dismissed.')
            for issue in attempt.get('report_issues') or []:lines.append('  Historical report limitation: '+escape(issue))
            if attempt.get('review_fragments'):lines.append('  Unclassified finding fragments are retained in the complete workflow history.')
        lines.append('')
    lines.extend(['## Stop reason',''])
    latest=states[records[-1]['evidence']['run']]
    pending=[t for t in latest.get('tasks',[]) if t['id'] not in latest.get('done',[])]
    lines.append('The human chose publication of the completed reviewed work. '+
                 (f"Next planned task: {pending[0]['id']} — {escape(public_value(root,latest,pending[0]['title']))}. It has not been delivered in this PR." if pending else 'No planned tasks remain in this run.'))
    lines.extend(['','## Task checkpoint history',''])
    checkpoints=[]
    for run_id in dict.fromkeys(r['evidence']['run'] for r in records):
        state=states[run_id]
        retained=Journal(state['project'],run_id).records() if root is not None and state.get('project') else []
        completed=[];allowed=[]
        for entry in retained:
            events=entry['data']['events'] if entry['kind']=='transition' else [entry]
            for event in events:
                data=event['data']
                if event['kind']=='grant':allowed=data['tasks']
                if event['kind']=='task.completed' and data['task'] not in completed:completed.append(data['task'])
                if event['kind']=='decision' and data['choice'] in ('continue','pr','stop'):
                    boundary='After task '+completed[-1] if completed else 'Before the first task'
                    permitted=[t for t in allowed if t not in completed] if data['choice']=='continue' else []
                    checkpoints.append('- '+boundary+': '+data['choice']+'; permitted tasks: '+
                                       (', '.join(permitted) or 'none')+'; '+entry['at']+'.')
    lines.extend(checkpoints or ['No task checkpoint decisions were recorded.'])
    return public_value(root,{},'\n'.join(lines)+'\n')


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
