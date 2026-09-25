"""Generate host discovery only; workflows and implementation remain in the pinned core."""
import json
from pathlib import Path
import re
import tempfile
import hashlib
from .storage import Refused,read_json
from .config import HOME,load
from .storage import atomic_json,project


def _render(root,entry,kind,config,design_profile=False):
    root=Path(root)
    codex=json.loads((HOME/'adapters/codex/hooks.template.json').read_text())
    for event,groups in codex['hooks'].items():
        for group in groups:
            for hook in group['hooks']:
                old=hook['command'];args=old.split('run.sh"',1)[-1].strip()
                if event=='UserPromptSubmit':args='user-prompt-submit'
                hook['command']=f'"$(git rev-parse --show-toplevel)/{entry}" hook --host codex {args}'
    claude=json.loads((HOME/'adapters/claude/settings.template.json').read_text())
    claude['permissions']={'allow':[]}
    for event,groups in claude['hooks'].items():
        for group in groups:
            for hook in group['hooks']:
                name=hook['command'].rsplit('/',1)[-1]
                hook['command']=f'"$CLAUDE_PROJECT_DIR/{entry}" hook --host claude {name}'
    claude['hooks']['UserPromptSubmit']=[{'hooks':[{'type':'command','command':f'"$CLAUDE_PROJECT_DIR/{entry}" hook --host claude user-prompt-submit','timeout':15}]}]
    atomic_json(root/'.codex/hooks.json',codex)
    atomic_json(root/'.claude/settings.json',claude)
    profile=config['models']['codex']
    (root/'.codex/config.toml').write_text(f'''project_doc_fallback_filenames = ["CLAUDE.md"]
model = "{profile['orchestrator']['model']}"
model_reasoning_effort = "{profile['orchestrator']['effort']}"
model_auto_compact_token_limit = {config['context']['compact_at_tokens']}
[features]
hooks = true
multi_agent = true
''')
    reviewer=root/'.codex/agents/invariant-reviewer.toml';reviewer.parent.mkdir(parents=True,exist_ok=True)
    reviewer.write_text(f'''name = "invariant-reviewer"
description = "Read-only independent review against the OH and consumer invariants."
model = "{profile['review']['model']}"
model_reasoning_effort = "{profile['review']['effort']}"
sandbox_mode = "read-only"
developer_instructions = """Resolve the Git root, then run <root>/{entry} resource prompts/invariant-reviewer.md and follow the returned contract. Native runner reviews carry an immutable request; design reviews require the stated admission check. Return all findings and evidence. Never edit files."""
''')
    names=['oh']+(['deliver','design','propose'] if design_profile else [])
    for name in names:
        for host,base in [('codex','.agents/skills'),('claude','.claude/skills')]:
            directory=root/base/name;directory.mkdir(parents=True,exist_ok=True)
            description={'oh':'Execute an explicit batch of project tasks through OH with automatic model routing and independent review.',
             'deliver':'Deliver tasks from an approved product design through OH.',
             'design':'Review and decompose product work using the consumer design policy.',
             'propose':'Propose product policy changes using the consumer decision policy.'}[name]
            body=f'''---
name: {name}
description: {description}
disable-model-invocation: true
---
Resolve the project root with `git rev-parse --show-toplevel`.
{('Read `<root>/.oh/policy/'+name+'.md` and follow the consumer-owned workflow.' if name!='oh' else 'Run `<root>/'+entry+' resource workflows/oh/SKILL.md` and follow that shared workflow.')}
Keep coordinator responses short. Do not copy worker transcripts or run another task loop yourself.
'''
            if host=='codex':body=body.replace('disable-model-invocation: true\n','')
            (directory/'SKILL.md').write_text(body)
            if host=='codex':
                (directory/'agents').mkdir(exist_ok=True)
                (directory/'agents/openai.yaml').write_text('policy:\n  allow_implicit_invocation: false\n')
    agent=root/'.claude/agents/invariant-reviewer.md';agent.parent.mkdir(parents=True,exist_ok=True)
    agent.write_text(f'''---
name: invariant-reviewer
description: Independent read-only invariant review.
model: {config['models']['claude']['review']['model']}
---
Run the project entry point `{entry} resource prompts/invariant-reviewer.md` and follow its contract. Do not edit files.
''')
    hooks=root/'.oh/git-hooks';hooks.mkdir(parents=True,exist_ok=True)
    for name in ('pre-push','commit-msg','prepare-commit-msg'):
        path=hooks/name
        path.write_text(f'#!/bin/sh\nexec "$(git rev-parse --show-toplevel)/{entry}" git-hook {name} "$@"\n');path.chmod(0o755)
    return {'host_discovery':str(root),'skills':names}


def generate(root,*,consumer=True):
    root=Path(root).resolve();manifest=root/'.oh/discovery.json'
    def safe(name):
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:raise Refused('Unsafe discovery path: '+name)
        target=root/relative
        for component in (target,*target.parents):
            if component==root:break
            if component.is_symlink():raise Refused('Discovery refuses a symlink: '+name)
        if not target.resolve().is_relative_to(root):raise Refused('Discovery path escapes repository: '+name)
        return target
    safe('.oh/discovery.json')
    profile=project(root).get('design_profile')
    if profile not in (None,'consumer-v1'):raise Refused('Unknown consumer design profile')
    if profile:
        for name in ('design','propose','deliver'):
            if not safe('.oh/policy/'+name+'.md').is_file():raise Refused('Consumer design profile needs its own '+name+' policy')
    previous=read_json(manifest) if manifest.exists() else {}
    with tempfile.TemporaryDirectory(prefix='oh-discovery-') as temp:
        staged=Path(temp)
        result=_render(staged,'.oh/oh' if consumer else 'oh',project(root)['kind'],load(root),bool(profile))
        files=[p for p in staged.rglob('*') if p.is_file()]
        new_names={p.relative_to(staged).as_posix() for p in files}
        retired=[]
        for name,known in previous.items():
            target=safe(name)
            if name not in new_names and target.exists():
                if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=known:raise Refused('Modified retired discovery file: '+name+'; no files were changed')
                retired.append(target)
        for source in files:
            name=source.relative_to(staged).as_posix();target=safe(name)
            if target.exists() and not target.is_file():raise Refused('Discovery target is not a file: '+name)
            if target.exists() and target.read_bytes()!=source.read_bytes():
                known=previous.get(name)
                if not known or hashlib.sha256(target.read_bytes()).hexdigest()!=known:
                    raise Refused('Existing consumer configuration conflicts with OH: '+name+'. Preserve it and integrate the OH entry explicitly; no files were changed.')
        for target in retired:target.unlink()
        inventory={}
        for source in files:
            name=source.relative_to(staged).as_posix();target=root/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(source.read_bytes());target.chmod(source.stat().st_mode & 0o777)
            inventory[name]=hashlib.sha256(source.read_bytes()).hexdigest()
        atomic_json(manifest,inventory)
        return result|{'host_discovery':str(root)}
