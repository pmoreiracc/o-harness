
from .storage import state_writer
"""Durable issue routing. Offline or uncertain publication never loses finding provenance."""
import json
from pathlib import Path
import re
import subprocess
from .storage import Refused,atomic_json,digest,git,read_json,state_home


@state_writer
def route(root,project_id,run,attempt,findings):
    remote=git(root,'remote','get-url','origin')
    match=re.fullmatch(r'(?:https://github.com/|git@github.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?',remote)
    if not match:raise Refused('Configure a GitHub origin before routing scope findings')
    repository=match[1];key=digest({'project':project_id,'run':run,'attempt':attempt})
    directory=state_home()/'issue-outbox'/key;record=directory/'request.json'
    if not record.exists():atomic_json(record,{'repository':repository,'project':project_id,'run':run,'attempt':attempt,'findings':findings},immutable=True)
    if (directory/'published.json').exists():return read_json(directory/'published.json')
    marker='OH-finding-route: '+key
    body='Scope identified by independent review.\n\n'+'\n\n'.join(f"- {f['description']}\n  Evidence: {f['path']}" for f in findings)+'\n\n'+marker+'\n'
    bodyfile=directory/'body.md';bodyfile.write_text(body)
    title='Review follow-up: '+findings[0]['description'][:85]
    try:
        listed=subprocess.run(['gh','issue','list','--repo',repository,'--state','all','--search',key,'--json','url,body'],capture_output=True,text=True,timeout=30,check=True)
        existing=[x['url'] for x in json.loads(listed.stdout) if marker in x['body']]
        if len(existing)>1:raise Refused('Multiple issue routes match this finding; reconcile before completing it')
        url=existing[0] if existing else subprocess.run(['gh','issue','create','--repo',repository,'--title',title,'--body-file',str(bodyfile)],capture_output=True,text=True,timeout=30,check=True).stdout.strip()
        if not re.fullmatch(r'https://github.com/'+re.escape(repository)+r'/issues/[0-9]+',url):raise Refused('Issue publication returned no verifiable URL')
        value={'status':'published','url':url,'request':key};atomic_json(directory/'published.json',value,immutable=True)
        return value
    except (subprocess.CalledProcessError,subprocess.TimeoutExpired,OSError) as exc:
        atomic_json(directory/'pending.json',{'status':'pending','reason':type(exc).__name__})
        raise Refused('Issue routing is saved locally but not confirmed online. Restore GitHub access and repeat route scope; no finding was discarded.')
