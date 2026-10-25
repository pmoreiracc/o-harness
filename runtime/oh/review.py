"""Immutable standalone review subjects and historical repair evidence."""
from .system import Path
import hashlib
import shlex
import subprocess
from .storage import Refused, Journal, atomic_json, checkout_file, digest, git, git_env, project, read_json


def workflow_reviews(state, task):
    return [a for a in state['attempts'] if a['task'] == task and a['role'] == 'review'
            and a.get('purpose', 'workflow') == 'workflow']

def subject(root, arguments):
    """Explicit selectors avoid guessing whether a number is a revision or a task."""
    words=shlex.split(arguments)
    feedback_only='--feedback-only' in words
    words=[w for w in words if w!='--feedback-only']
    if not words:raise Refused('Name the review subject: changes, tree, commit <ref>, range <base> <head>, paths <paths>, or task <id>.')
    kind=words.pop(0)
    from .verification import tree,candidate_tree
    current={'head':git(root,'rev-parse','HEAD'),'branch':git(root,'branch','--show-current'),'tree':tree(root)}
    if kind in ('changes','tree') and not words:
        target=candidate_tree(root);base=current['head']
    elif kind=='paths' and words:
        for name in words:
            path=Path(name)
            if path.is_absolute() or '..' in path.parts or not (Path(root)/path).exists():
                raise Refused('Review paths must exist inside the checkout: '+name)
        target=candidate_tree(root);base=current['head']
    elif kind=='commit' and len(words)==1:
        target=git(root,'rev-parse','--verify',words[0]+'^{commit}')
        parents=git(root,'rev-list','--parents','-n','1',target).split()[1:]
        base=parents[0] if parents else subprocess.check_output(['git','-C',str(root),'hash-object','-w','-t','tree','--stdin'],input=b'',env=git_env()).decode().strip()
    elif kind=='range' and len(words)==2:
        base,target=[git(root,'rev-parse','--verify',ref+'^{commit}') for ref in words]
    else:raise Refused('Use changes, tree, paths <paths>, commit <ref>, range <base> <head>, or task <id>.')
    return current|{'kind':kind,'base':base,'revision':target,'git_tree':git(root,'rev-parse',target+'^{tree}'),
                    'paths':words if kind=='paths' else [],'feedback_only':feedback_only,'description':arguments}

def capture(root, directory, selected):
    """Export exact Git blobs for both hosts; never check out a historical revision."""
    folder=Path(directory)/'subject';folder.mkdir(parents=True,exist_ok=True)
    files={};links=[]
    for entry in git(root,'ls-tree','-rz',selected['git_tree'],raw=True).split(b'\0'):
        if not entry:continue
        metadata,name=entry.split(b'\t',1);mode,kind,oid=metadata.split()
        name=name.decode('utf-8');path=Path(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name:
            raise Refused('Cannot safely export the review subject path: '+name)
        if kind!=b'blob':
            links.append(name+' (Git submodule; inspect its bound commit separately)');continue
        if mode==b'120000':
            links.append(name+' (symbolic link; not followed in the exported subject)');continue
        data=git(root,'cat-file','blob',oid.decode(),raw=True)
        destination=folder/path;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
        files[str(destination)]=hashlib.sha256(data).hexdigest()
    from .plans import file_identity
    manifest={'files':files,'identities':{p:file_identity(Path(p)) for p in files}}
    path=Path(directory)/'subject-files.json';atomic_json(path,manifest,immutable=True)
    return {'manifest':{'path':str(path),'hash':digest(manifest)},'limits':links,'root':str(folder)}

def artifact_content(artifact):
    if not artifact.get('manifest'):return artifact
    reference=artifact['manifest'];value=read_json(reference['path'])
    if digest(value)!=reference['hash']:raise Refused('The retained subject manifest changed; preserve it and request a fresh review.')
    return value

def repair_source(root, run):
    """Read-only eligibility; a completed review is input, not delivery authority."""
    from .workflow import reduce
    journal=Journal(project(root)['id'],run);state=reduce(journal.records())
    if state.get('workflow')!='review' or state['status']!='completed':raise Refused('Fix preparation requires a completed standalone review.')
    latest=state['attempts'][-1]
    if latest.get('outcome') not in ('blocking','needs_resolution') or not latest.get('findings') or latest.get('report_issues'):
        raise Refused('This receipt has no complete findings to prepare as repairs.')
    from .verification import tree
    current={'branch':git(root,'branch','--show-current'),'head':git(root,'rev-parse','HEAD'),'tree':tree(root)}
    # Historical findings are reconciled by the coordinator against the current source before preparing.
    if state['subject']['kind'] in ('changes','tree','paths') and any(current[k]!=state['subject'][k] for k in current):
        raise Refused('The reviewed work changed. Review the current work before preparing its fixes; your edits are retained.')
    from .storage import changes
    paths=state['subject']['paths']
    if paths and any(not any(name==p or name.startswith(p.rstrip('/')+'/') for p in paths) for name in changes(root)):
        raise Refused('Other uncommitted files are outside this review. Preserve them separately or review the complete change before approving a commit.')
    canonical=checkout_file(root,'oh-active-run.json')
    published_branch=False
    if canonical.exists():
        other=reduce(Journal(state['project'],read_json(canonical)['run']).records())
        published_branch=bool(other.get('published') and other['branch']==current['branch'])
        if other['status'] not in ('completed','stopped') and not other.get('published'):
            raise Refused('A delivery is still pending in this checkout. Keep this review as feedback and finish or stop that delivery before starting unrelated repairs.')
    from .branches import main_ref
    from .delivery import unreviewed
    base=main_ref(root)
    fork=git(root,'merge-base','HEAD',base) if base else current['head']
    covers=unreviewed(root,fork,base) if base else []
    return {'run':run,'attempt':latest['id'],'receipt':str(Path(latest['evidence'])/'result.json'),
            'hash':digest(read_json(Path(latest['evidence'])/'result.json')),'findings':latest['findings'],
            'subject':state['subject'],'starting_work':current,'files':changes(root),'covers':covers,
            'review_base':fork if covers else current['head'],'new_branch':published_branch}
