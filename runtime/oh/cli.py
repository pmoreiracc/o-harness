from __future__ import annotations
import argparse
import json
import os
from .system import Path
import shlex
import sys
from .config import HOME
from .storage import Refused, read_json

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


def _locator(value):
    """A native locator is inline JSON or a JSON file; neither needs platform text editing."""
    if value is None:return None
    located=json.loads(value) if value.lstrip().startswith('{') else read_json(Path(value))
    if not isinstance(located,dict):raise ValueError('A native locator must be a JSON object')
    return located


def main(argv=None):
    for name in ('stdout','stderr'):
        if not isinstance(getattr(sys,name),Tolerant):setattr(sys,name,Tolerant(getattr(sys,name)))
    parser=argparse.ArgumentParser(prog='oh')
    parser.add_argument('--root',type=Path)
    parser.add_argument('--data-home',type=Path,help=argparse.SUPPRESS)
    sub=parser.add_subparsers(dest='command',required=True)
    formatting=sub.add_parser('command-format');formatting.add_argument('attempt');formatting.add_argument('--argv',required=True)
    scope=sub.add_parser('scope');actions=scope.add_subparsers(dest='action',required=True)
    prep=actions.add_parser('prepare');prep.add_argument('manifest',type=Path,nargs='?');prep.add_argument('--doc');prep.add_argument('--track',default='');prep.add_argument('--workflow',default='deliver',choices=['deliver','design','propose']);prep.add_argument('--human')
    approve=actions.add_parser('approve');approve.add_argument('scope_id');approve.add_argument('locator')
    attempt=sub.add_parser('attempt');attempts=attempt.add_subparsers(dest='action',required=True)
    admit=attempts.add_parser('admit');admit.add_argument('role',choices=['assessment','implementation','analysis','review'])
    for action in ('bind','retain'):
        step=attempts.add_parser(action);step.add_argument('attempt');step.add_argument('locator')
    review_check=sub.add_parser('review-check');review_check.add_argument('report',type=Path,nargs='?')
    review_check.add_argument('--text',help='Validate a literal draft without a shell pipe or scratch file')
    native_event=sub.add_parser('native-event');native_event.add_argument('host',choices=['claude','codex'])
    native_control=sub.add_parser('native-control');native_control.add_argument('host',choices=['claude','codex'])
    owned=sub.add_parser('owned-command');owned.add_argument('attempt');owned.add_argument('--argv',required=True)
    sub.add_parser('candidate')
    evidence=sub.add_parser('evidence');evidence.add_argument('attachment',type=Path)
    complete=sub.add_parser('complete');complete.add_argument('attempt')
    decision=sub.add_parser('decision');decision.add_argument('kind');decision.add_argument('locator');decision.add_argument('--attempt');decision.add_argument('--destination',type=Path)
    request=sub.add_parser('decision-request');request.add_argument('kind');request.add_argument('--attempt');request.add_argument('--rounds',type=int,help='Override the configured review window only when the person explicitly requests a different count; otherwise omit');request.add_argument('--run');request.add_argument('--also');request.add_argument('--repair')
    track=sub.add_parser('finding-track');track.add_argument('attempt');track.add_argument('--destination',type=Path)
    resume=sub.add_parser('resume');resume.add_argument('--human');resume.add_argument('--run')
    status=sub.add_parser('status');status.add_argument('--saved',action='store_true')
    review=sub.add_parser('review');review.add_argument('arguments',nargs='*');review.add_argument('--human')
    deliver=sub.add_parser('deliver');deliver.add_argument('arguments',nargs='*');deliver.add_argument('--human')
    prep=sub.add_parser('prepare');prep.add_argument('manifest',type=Path);prep.add_argument('--review');prep.add_argument('--pr',type=int)
    pd=sub.add_parser('prepare-design');pd.add_argument('doc');pd.add_argument('track',nargs='?',default='')
    verify=sub.add_parser('verify');verify.add_argument('base',nargs='?');verify.add_argument('mode',nargs='?',default='review',choices=['review','pre-push','ci'])
    verify.add_argument('--attempt',help=argparse.SUPPRESS)
    admission=sub.add_parser('admission');admission.add_argument('directory',type=Path)
    pub=sub.add_parser('publication');pub.add_argument('--pr',type=int)
    ci=sub.add_parser('ci-wait');ci.add_argument('--pr',type=int);ci.add_argument('--timeout',type=int,default=1500)
    summary=sub.add_parser('pr-summary');summary.add_argument('base',nargs='?')
    plans=sub.add_parser('plans');plans.add_argument('action',choices=['path','check','list'])
    resource=sub.add_parser('resource');resource.add_argument('path')
    build=sub.add_parser('build-plugin');build.add_argument('destination',type=Path);build.add_argument('--host',required=True,choices=['codex','claude'])
    setup=sub.add_parser('setup');setup.add_argument('--development',action='store_true');setup.add_argument('--if-newer',action='store_true')
    update=sub.add_parser('update');update.add_argument('--host',choices=['codex','claude'])
    for name in ('profile-import','profile-export'):
        profile=sub.add_parser(name);profile.add_argument('path',type=Path);profile.add_argument('--name')
    trust=sub.add_parser('trust-host');trust.add_argument('host',choices=['codex','claude']);trust.add_argument('path',type=Path,nargs='?')
    init=sub.add_parser('init');init.add_argument('--name');init.add_argument('--replace',action='store_true');init.add_argument('--attach');init.add_argument('--reattach');init.add_argument('--kind',choices=['harness','product'],default='product')
    rename=sub.add_parser('rename');rename.add_argument('name')
    settings=sub.add_parser('config');settings.add_argument('action',nargs='?',choices=['set','unset','open']);settings.add_argument('key',nargs='?');settings.add_argument('value',nargs='?');settings.add_argument('--global',dest='everywhere',action='store_true')
    for name in ('backup','restore'):
        backup=sub.add_parser(name);backup.add_argument('path',type=Path)
    for name in ('collect','rebuild','observe-ci','service-install','service-uninstall'):sub.add_parser(name)
    serve=sub.add_parser('serve');serve.add_argument('--port',type=int,default=4319 if os.environ.get('OH_DASHBOARD_MODE')=='development' else 4318)
    args=parser.parse_args(argv);invocation=Path.cwd();root=(args.root or invocation).resolve()
    if args.data_home:
        os.environ['OH_DATA_HOME']=str(args.data_home.expanduser().resolve())
    try:
        from .storage import state_home
        enclosing=json.loads(os.environ.get('OH_OWNED_COMMAND','{}'))
        if (enclosing.get('root')==str(root) and enclosing.get('data_home')==str(state_home())
                and args.command not in ('status','plans','resource','review-check')
                and not (args.command=='config' and args.action is None)):
            raise Refused('Run OH helpers directly through the native tool using the packet helper prefix; do not nest them inside owned-command.')
        from . import native
        if args.command=='scope':
            result=(native.prepare_scope(root,read_json(args.manifest) if args.manifest else None,args.doc,args.track,args.workflow,_locator(args.human))
                    if args.action=='prepare' else native.approve_scope(root,args.scope_id,_locator(args.locator)))
        elif args.command=='attempt':
            result=native.admit(root,args.role) if args.action=='admit' else getattr(native,args.action)(root,args.attempt,_locator(args.locator))
        elif args.command=='review-check':
            from .review_report import check
            if args.text is not None and args.report:raise Refused('Supply the draft as text or a report file, not both')
            result=check(args.text if args.text is not None else read_json(args.report)['report'] if args.report else sys.stdin.read())
        elif args.command=='native-event':
            from .native_events import handle
            result=handle(root,args.host,json.load(sys.stdin))
        elif args.command=='native-control':
            from .cancellation import hook
            result=hook(root,args.host,json.load(sys.stdin))
        elif args.command=='owned-command':
            from .cancellation import owned_command
            raise SystemExit(owned_command(root,args.attempt,json.loads(args.argv)))
        elif args.command=='candidate':result=native.candidate(root)
        elif args.command=='evidence':result=native.attach_evidence(root,read_json(args.attachment))
        elif args.command=='complete':result=native.complete(root,args.attempt)
        elif args.command=='decision':result=native.decision(root,args.kind,_locator(args.locator),args.attempt,read_json(args.destination) if args.destination else None)
        elif args.command=='decision-request':
            from .decisions import prepare
            result=prepare(root,args.kind,args.attempt,args.rounds,args.run,args.also,args.repair)
        elif args.command=='finding-track':
            from .scope import track
            result=track(root,args.attempt,read_json(args.destination) if args.destination else None)
        elif args.command=='resume':result=native.resume(root,_locator(args.human),args.run)
        elif args.command=='status':
            from .workflow import active_file
            result=(native.saved_work(root) if args.saved else native.select(root)) if args.saved or active_file(root).exists() else {'status':'none','next':'Use /oh-propose <idea>, /oh-design <initiative>, or /oh-deliver <design or quick fix> (in Codex: $oh-propose, $oh-design, $oh-deliver).'}
        elif args.command=='review':result=native.review(root,shlex.join(args.arguments),_locator(args.human))
        elif args.command=='deliver':
            from .delivery import parse,listing
            selected=parse(' '.join(args.arguments))
            if selected['kind']=='list':result=listing(root)
            elif selected['kind']=='design':result=native.prepare_scope(root,doc=selected['doc'],track=selected['track'],human=_locator(args.human))
            else:result=selected
        elif args.command in ('prepare','prepare-design'):
            from .prepared import prepare
            result=prepare(root,manifest=args.manifest,review=args.review,pr=args.pr) if args.command=='prepare' else prepare(root,doc=args.doc,track=args.track)
        elif args.command=='verify':
            from .workflow import active_file
            if active_file(root).exists():result=native.verify(root,args.base,args.mode,attempt_id=args.attempt)
            else:
                if args.attempt:raise Refused('This verification belongs to a saved attempt; no active run is available')
                from .checks import run
                result=run(root,args.base,args.mode)
        elif args.command=='admission':
            from .worker_checks import admission
            result=admission(args.directory)
        elif args.command=='command-format':
            from .worker_checks import command_format
            result=command_format(root,args.attempt,json.loads(args.argv))
        elif args.command=='publication':
            from .publication import reconcile
            result=reconcile(root,args.pr)
        elif args.command=='ci-wait':
            from .publication import ci_wait
            result=ci_wait(root,args.pr,max(1,args.timeout))
        elif args.command=='pr-summary':
            from .publication import reference,render
            print(render(root,args.base or reference(root)));return
        elif args.command=='plans':
            from .plans import layout,check,listing
            where=layout(root)
            result=check(root,where) if args.action=='check' else listing(root) if args.action=='list' else {k:str(v) for k,v in where.items()}
        elif args.command=='resource':
            path=(HOME/args.path).resolve()
            if not path.is_relative_to(HOME):raise Refused('Resource outside OH')
            print(path.read_text());return
        elif args.command=='build-plugin':
            from .installation import build
            result=build(args.destination,args.host)
        elif args.command=='setup':
            from .installation import setup
            result=setup(development=args.development,if_newer=args.if_newer)
        elif args.command=='update':
            from .updater import update
            raise SystemExit(update(root,args.host))
        elif args.command.startswith('profile-'):
            from .profiles import import_profile,export_profile
            result=import_profile(root,args.path,args.name) if args.command=='profile-import' else export_profile(root,args.path)
        elif args.command=='init':
            from .registry import register
            from .config import ensure_project
            result=register(root,args.name,args.kind,attach=args.attach,reattach=args.reattach,replace=args.replace)|ensure_project(root)
        elif args.command=='trust-host':
            from .hosts import trust
            result=trust(args.host,args.path,root)
        elif args.command=='rename':
            from .registry import rename
            result=rename(root,args.name)
        elif args.command=='config':
            from .config import change,describe,open_settings
            if not args.action:result=describe(root)
            elif args.action=='open':result=open_settings(root)
            else:
                value=args.value
                if value and value.startswith('@'):value=(invocation/Path(value[1:]).expanduser()).read_text(encoding='utf-8-sig')
                result=change(root,args.key,value if args.action=='set' else None,scope='global' if args.everywhere else None)
        elif args.command in ('backup','restore'):
            from .backup import backup,restore
            result=backup(args.path) if args.command=='backup' else restore(args.path)
        elif args.command=='collect':
            from .telemetry import collect
            result={'ingested':collect()}
        elif args.command=='rebuild':
            from .telemetry import rebuild
            result=rebuild()
        elif args.command=='observe-ci':
            from .observability import observe_ci
            result=observe_ci(root)
        elif args.command=='serve':
            from .server import serve
            serve(args.port);return
        else:
            from .service import install,uninstall
            result=install() if args.command=='service-install' else uninstall()
        if result is not None:print(json.dumps(result,indent=2))
        if args.command=='review-check' and not result['valid']:raise SystemExit(1)
        if args.command=='verify':
            from .verification import check_failed
            checks=result.get('checks',[]) if isinstance(result,dict) else result
            if any(check_failed(check) for check in checks):raise SystemExit(1)
    except KeyboardInterrupt:
        print('OH: Native interruption ended this operation; owned cleanup was attempted.',file=sys.stderr)
        raise SystemExit(130)
    except (Refused,OSError,ValueError,KeyError) as exc:
        print(f'OH: {exc}',file=sys.stderr);raise SystemExit(2)
