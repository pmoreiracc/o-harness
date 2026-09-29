from __future__ import annotations

from .storage import checkout_file

import argparse
import json
import os
from pathlib import Path
import shlex
import sys
from .config import HOME
from .storage import Refused, atomic_json, checkout_id, digest, identifier, project, read_json, state_home
from .workflow import active_file, checkpoint, choose, human_event, start


def host_hook(root,host,payload,*,verified):
    prompt=payload.get('prompt','').strip()
    import re
    prompt=re.sub(r'^[$/](?:o-harness:)?(oh-(?:pause|resume|stop))$',lambda m:m[1],prompt)
    prompt={'oh-pause':'pause','oh-stop':'stop','oh-resume':'resume'}.get(prompt,prompt)
    planning=re.fullmatch(r'[$/](?:o-harness:)?(?:oh-start\s+|oh-)(propose|design)\s+(.+)',prompt,re.S)
    if planning:
        kind,intent=planning.groups()
        from .workflow import unfinished
        if unfinished(root,verified):raise Refused('An unfinished run exists in this checkout; resume it, or stop it with /oh-stop, first')
        if kind=='design':
            from .plans import design_manifest
            manifest,plan=design_manifest(root,intent.strip())
            start(root,manifest,verified,plan=plan)
        else:
            from .plans import propose_manifest
            manifest,plan=propose_manifest(root,intent)
            start(root,manifest,verified,plan=plan)
        return checkpoint(root)
    from .entry import command
    parsed=command(prompt)
    from .delivery import parse
    delivery=parse(parsed[1]) if parsed and parsed[0]=='deliver' else None
    if delivery and delivery['kind']=='list':
        from .delivery import listing
        return listing(root)
    if delivery and delivery['kind']=='quick_fix':return delivery
    if delivery and delivery['kind']=='design':
        from .prepared import resolve
        if delivery['request']:
            prepared=resolve(root,delivery['request'],verified,'design')
            if prepared['doc']!=delivery['doc'] or prepared['track']!=delivery['track']:raise Refused('Prepared design and requested track differ')
            start(root,prepared['manifest'],verified,prepared=prepared)
        else:
            from .workflow import unfinished,load_run
            if unfinished(root,verified):raise Refused('An unfinished run exists; resume it or stop it first')
            source=digest({k:verified[k] for k in ('host','session','turn','prompt')})
            if active_file(root).exists() and load_run(root)[1]['source']==source:return checkpoint(root)
            from .delivery import selection
            from .plans import editing
            with editing(root):
                manifest,binding=selection(root,delivery['doc'],delivery['track'])
                start(root,manifest,verified,plan=binding)
        return checkpoint(root)
    if parsed and parsed[0] in ('oh-start','deliver') and parsed[1].startswith('request:'):
        from .prepared import resolve
        prepared=resolve(root,parsed[1],verified,'tasks')
        start(root,prepared['manifest'],verified,prepared=prepared)
        return checkpoint(root)
    from .entry import REFINE
    if (prompt in ('pause','continue','resume','retry','pr','stop','grant review','fix concerns','fix scope','fix findings','accept concerns','route scope','accept concerns and route scope','approve','reconsider')
            or re.fullmatch(REFINE,prompt,re.S)) and active_file(root).exists():
        choose(root,prompt,verified)
        return checkpoint(root)
    return None


def git_branch(root):
    from .storage import git
    return git(root,'branch','--show-current')


class Tolerant:
    """An output whose reader may go away, such as a host that ended a tool call: OH's notes, progress and result
    are then lost, but the run they describe goes on."""
    def __init__(self,stream):self.stream=stream
    def write(self,text):
        try:return self.stream.write(text)
        except (OSError,ValueError):return len(text)
    def flush(self):
        try:self.stream.flush()
        except (OSError,ValueError):pass
    def __getattr__(self,name):return getattr(self.stream,name)


def main(argv=None):
    for name in ('stdout','stderr'):
        if not isinstance(getattr(sys,name),Tolerant):setattr(sys,name,Tolerant(getattr(sys,name)))
    parser=argparse.ArgumentParser(prog='oh')
    parser.add_argument('--root',type=Path)
    sub=parser.add_subparsers(dest='command',required=True)
    build=sub.add_parser('build-plugin');build.add_argument('destination',type=Path);build.add_argument('--host',choices=['codex','claude'],required=True)
    install=sub.add_parser('setup');install.add_argument('--development',action='store_true');install.add_argument('--if-newer',action='store_true')
    plugin_hook=sub.add_parser('plugin-hook');plugin_hook.add_argument('--host',choices=['codex','claude'],required=True)
    launch=sub.add_parser('start');launch.add_argument('request',nargs='?')
    export=sub.add_parser('profile-export');export.add_argument('destination',type=Path)
    imported=sub.add_parser('profile-import');imported.add_argument('source',type=Path);imported.add_argument('--name',help='register the project under another name')
    renamed=sub.add_parser('rename');renamed.add_argument('name')
    prep=sub.add_parser('prepare');prep.add_argument('manifest')
    prep_design=sub.add_parser('prepare-design');prep_design.add_argument('doc');prep_design.add_argument('track',nargs='?',default='')
    verification=sub.add_parser('verify');verification.add_argument('base',nargs='?',default='origin/main');verification.add_argument('mode',nargs='?',default='review',choices=['review','pre-push','ci'])
    publication=sub.add_parser('pr-summary');publication.add_argument('base',nargs='?',default='origin/main');publication.add_argument('--validate-event',type=Path)
    trusted=sub.add_parser('trust-host');trusted.add_argument('host',choices=['codex','claude']);trusted.add_argument('path',type=Path,nargs='?')
    init=sub.add_parser('init');init.add_argument('--name',help='defaults to the repository\'s project, or the repository\'s folder name');init.add_argument('--replace',action='store_true');init.add_argument('--attach');init.add_argument('--reattach');init.add_argument('--kind',choices=['harness','product'],default='product')
    backup=sub.add_parser('backup');backup.add_argument('destination',type=Path)
    restore=sub.add_parser('restore');restore.add_argument('source',type=Path)
    sub.add_parser('pause');sub.add_parser('stop');sub.add_parser('resume');sub.add_parser('status');sub.add_parser('run');sub.add_parser('collect');sub.add_parser('rebuild');sub.add_parser('observe-ci')
    settings=sub.add_parser('config');settings.add_argument('action',nargs='?',choices=['set','unset','open']);settings.add_argument('key',nargs='?');settings.add_argument('value',nargs='?')
    settings.add_argument('--global',dest='everywhere',action='store_true',help='change your settings for every project')
    planning=sub.add_parser('plans');planning.add_argument('action',choices=['path','check','list'])
    hook=sub.add_parser('host-hook');hook.add_argument('--host',choices=['codex','claude'],required=True)
    serve=sub.add_parser('serve');serve.add_argument('--port',type=int,default=4318)
    sub.add_parser('service-install');sub.add_parser('service-uninstall')
    suggest=sub.add_parser('suggest');suggest.add_argument('--host',choices=['codex','claude'],default='codex')
    deliver=sub.add_parser('deliver');deliver.add_argument('arguments',nargs='*')
    resource=sub.add_parser('resource');resource.add_argument('path')
    args=parser.parse_args(argv);invocation=Path.cwd();root=(args.root or invocation).resolve()
    from .system import WINDOWS
    if WINDOWS:
        # CreateProcess searches OH's own current folder for bare commands whatever that variable says, so OH
        # leaves the checkout for its own installed folder once every path argument is absolute.
        for name,value in vars(args).items():
            if isinstance(value,Path):setattr(args,name,value.resolve())
        os.chdir(HOME)
    try:
        if args.command=='build-plugin':
            from .installation import build
            result=build(args.destination,args.host)
        elif args.command=='setup':
            from .installation import setup
            result=setup(development=args.development,if_newer=args.if_newer)
        elif args.command in ('profile-export','profile-import'):
            from .profiles import export_profile,import_profile
            result=export_profile(root,args.destination) if args.command=='profile-export' else import_profile(root,args.source,args.name)
        elif args.command=='plugin-hook':
            from .entry import receive
            result=receive(root,args.host,json.load(sys.stdin))
        elif args.command in ('prepare','prepare-design'):
            from .prepared import prepare
            result=prepare(root,manifest=args.manifest) if args.command=='prepare' else prepare(root,doc=args.doc,track=args.track)
        elif args.command=='verify':
            from .checks import run
            result=run(root,args.base,args.mode)
            print(json.dumps(result,indent=2))
            raise SystemExit(1 if any(x['returncode'] for x in result) else 0)
        elif args.command=='pr-summary':
            from .publication import has_native_history,render,validate_event
            if not has_native_history(root,args.base):raise Refused('This branch has no OH-reviewed commits to summarize')
            if args.validate_event:result=validate_event(root,read_json(args.validate_event),args.base)
            else:print(render(root,args.base));return
        elif args.command=='trust-host':
            from .hosts import trust
            # Host trust is machine-wide: the current folder is a project only when --root names it.
            result=trust(args.host,args.path,args.root.resolve() if args.root else None)
        elif args.command=='rename':
            from .registry import rename
            result=rename(root,args.name)
        elif args.command=='init':
            from .registry import register
            from .config import ensure_project,layers,read_file
            layers(read_file())  # a settings problem stops init before anything is registered
            registered=register(root,args.name,args.kind,attach=args.attach,reattach=args.reattach,replace=args.replace);settings=ensure_project(root)
            notes=[n for n in (registered.get('note'),settings.get('note')) if n]
            result=registered|settings|({'note':' '.join(notes)} if notes else {})
        elif args.command=='backup':
            from .backup import backup
            result=backup(args.destination)
        elif args.command=='restore':
            from .backup import restore
            result=restore(args.source)
        elif args.command=='config':
            from .config import change,describe,open_settings
            if not args.action:result=describe(root)
            elif args.action=='open':result=open_settings(root)
            elif not args.key or (args.action=='set')!=(args.value is not None):raise Refused('Use: oh config set <key> <value>, or oh config unset <key>')
            else:
                value=args.value
                # @file reads the value from a file: JSON passes through PowerShell and cmd without losing its quotes.
                if value and value.startswith('@') and len(value)>1:value=(invocation/Path(value[1:]).expanduser()).read_text(encoding='utf-8-sig')
                result=change(root,args.key,value if args.action=='set' else None,scope='global' if args.everywhere else None)
        elif args.command=='plans':
            from .plans import check,layout,listing
            where=layout(root)
            result=check(root,where) if args.action=='check' else listing(root) if args.action=='list' else {k:str(v) for k,v in where.items()}
        elif args.command=='status':
            result=checkpoint(root) if active_file(root).exists() else {
                'status':'none','next':'No OH run in this checkout yet: start one with oh-propose, oh-design or oh-deliver.'}
        elif args.command in ('pause','stop'):
            from .controls import request
            result=request(root,args.command)
        elif args.command=='resume':
            from .authority import materialize
            materialize(root)
            from .workflow import load_run
            _,state=load_run(root)
            if state['status']=='paused':raise Refused('Submit /oh-resume (Codex: $oh-resume) in the owning host conversation, then run oh resume')
            from .runner import run
            result=run(root)
        elif args.command=='host-hook':
            from .authority import stage
            result=stage(root,args.host,json.load(sys.stdin))
        elif args.command in ('run','start'):
            from .authority import materialize
            materialize(root)
            if args.command=='start' and args.request:
                from .workflow import load_run
                _,state=load_run(root)
                if args.request not in state['human']['prompt']:
                    raise Refused('This request has no matching native human authorization')
            from .runner import run
            result=run(root)
        elif args.command=='observe-ci':
            from .observability import observe_ci
            result=observe_ci(root)
        elif args.command=='rebuild':
            from .telemetry import rebuild
            result=rebuild()
        elif args.command=='collect':
            from .telemetry import collect
            result={'ingested':collect()}
        elif args.command=='serve':
            from .server import serve
            serve(args.port);return
        elif args.command.startswith('service-'):
            from .service import install,uninstall
            result=install() if args.command=='service-install' else uninstall()
        elif args.command=='suggest':
            from .suggestions import generate
            result=generate(root,args.host)
        elif args.command=='deliver':
            from .delivery import parse,listing
            selected=parse(' '.join(args.arguments))
            if selected['kind']=='list':result=listing(root)
            elif selected['kind']=='quick_fix':result=selected
            else:
                from .authority import materialize
                admitted=materialize(root)
                if admitted and admitted.get('limits'):print(admitted['limits'],flush=True)
                if selected['kind']=='design':
                    from .design_runner import run
                    result=run(root,selected['doc'],selected['track'])
                else:
                    from .runner import run
                    result=run(root)
        elif args.command=='resource':
            path=(HOME/args.path).resolve()
            if not path.is_relative_to(HOME):raise Refused('Resource outside OH')
            print(path.read_text());return
        if result is not None:print(json.dumps(result,indent=2))
    except (Refused,OSError,ValueError,KeyError) as exc:
        print(f'OH: {exc}',file=sys.stderr);raise SystemExit(2)
