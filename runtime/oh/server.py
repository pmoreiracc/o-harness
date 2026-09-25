from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import socketserver
from urllib.parse import parse_qs, urlparse
from .config import HOME
from .telemetry import analytics, collect, connect, rows


def filters(query):
    end=datetime.now(timezone.utc);start=end-timedelta(days=14)
    result={'from':query.get('from',[start.isoformat()])[0],'to':query.get('to',[end.isoformat()])[0]}
    a=datetime.fromisoformat(result['from']);b=datetime.fromisoformat(result['to'])
    if a.tzinfo is None or b.tzinfo is None:raise ValueError('Use timezone-aware date bounds')
    result['from']=a.astimezone(timezone.utc).isoformat(timespec='milliseconds')
    result['to']=b.astimezone(timezone.utc).isoformat(timespec='milliseconds')
    if a>=b or (b-a).days>3660:raise ValueError('Choose a valid range of up to ten years')
    for key in ('project','difficulty','kind','version','model','phase'):
        if query.get(key):result[key]=query[key][0]
    return result


def overview(query):
    current=filters(query)
    a=datetime.fromisoformat(current['from']);b=datetime.fromisoformat(current['to'])
    baseline=current|{'from':(a-(b-a)).isoformat(),'to':a.isoformat()}
    if query.get('baseline_version'):
        baseline=current|{'version':query['baseline_version'][0]}
    if query.get('baseline_from') and query.get('baseline_to'):
        baseline=current|{'from':query['baseline_from'][0],'to':query['baseline_to'][0]}
        baseline.update(filters({'from':[baseline['from']],'to':[baseline['to']]}))
    with connect(readonly=True) as db:
        result=analytics(db,current);past=analytics(db,baseline)
    # Use the same difficulty weights in both periods so a harder task mix is not a regression.
    current_levels={d['difficulty']:d for d in result['difficulty']}
    past_levels={d['difficulty']:d for d in past['difficulty']}
    matched=sorted(current_levels.keys() & past_levels.keys())
    weights={k:min(current_levels[k]['completed'],past_levels[k]['completed']) for k in matched}
    total=sum(weights.values());comparison={'tasks_per_period':total,'samples':{},'current':{},'baseline':{}}
    for key in ('wall_ms','reviews','first_pass','autonomous'):
        sample={'first_pass':'quality_samples','autonomous':'autonomy_samples'}.get(key,'completed')
        weights={k:min(current_levels[k][sample],past_levels[k][sample]) for k in matched}
        valid=[k for k in matched if weights[k] and current_levels[k][key] is not None and past_levels[k][key] is not None]
        denominator=sum(weights[k] for k in valid)
        comparison['samples'][key]=denominator
        if key=='first_pass':comparison['tasks_per_period']=denominator
        for name,levels in [('current',current_levels),('baseline',past_levels)]:
            comparison[name][key]=sum(levels[k][key]*weights[k] for k in valid)/denominator if denominator else None
    return result|{'baseline':past,'range':current,'baseline_range':baseline,
                  'matched_difficulties':matched,'comparison':comparison}



class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def send(self,code,body,kind='application/json'):
        data=(json.dumps(body).encode() if kind=='application/json' else body)
        self.send_response(code)
        self.send_header('Content-Type',kind+'; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers();self.wfile.write(data)

    def trusted(self):
        return self.headers.get('Host') in (f'localhost:{self.server.server_port}',f'127.0.0.1:{self.server.server_port}')

    def do_GET(self):
        if not self.trusted():self.send(403,{'error':'Localhost access only'});return
        url=urlparse(self.path);query=parse_qs(url.query)
        try:
            if url.path=='/api/overview':self.send(200,overview(query))
            elif url.path=='/api/task':
                with connect(readonly=True) as db:
                    from .observability import details
                    detail=details(db,query['run'][0],query['task'][0])
                self.send(200,detail)
            elif url.path=='/api/health':self.send(200,{'ok':True,'collector_error':self.server.collector_error,'analysis_error':self.server.analysis_error,'analysis_running':self.server.analysis_lock.locked(),'analysis_result':self.server.analysis_result})
            elif url.path=='/api/session':self.send(200,{'token':self.server.token})
            elif url.path in ('/','/app.js','/style.css'):
                name={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[url.path]
                kind={'/':'text/html','/app.js':'text/javascript','/style.css':'text/css'}[url.path]
                self.send(200,(HOME/'dashboard'/name).read_bytes(),kind)
            else:self.send(404,{'error':'Not found'})
        except (ValueError,KeyError) as exc:self.send(400,{'error':str(exc)})
        except Exception:self.send(503,{'error':'Analytics temporarily unavailable; task evidence is unaffected'})

    def do_POST(self):
        if not self.trusted() or self.headers.get('X-OH-Token')!=self.server.token:
            self.send(403,{'error':'Reload the local dashboard before requesting analysis'});return
        origin=self.headers.get('Origin')
        if origin not in (f'http://localhost:{self.server.server_port}',f'http://127.0.0.1:{self.server.server_port}'):
            self.send(403,{'error':'Same-origin requests only'});return
        # AI analysis is an explicit user action, never part of a dashboard GET.
        if self.path!='/api/suggestions':self.send(404,{'error':'Not found'});return
        if not self.server.analysis_lock.acquire(blocking=False):
            self.send(409,{'error':'Analysis is already running'});return
        def work():
            try:
                from .suggestions import generate
                self.server.analysis_error=None
                self.server.analysis_result=generate(HOME,'codex')
            except Exception as exc:
                self.server.analysis_error=str(exc)
            finally:self.server.analysis_lock.release()
        threading.Thread(target=work,daemon=True).start()
        self.send(202,{'status':'requested'})


class LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        # Binding localhost must not wait for the machine's DNS/reverse-DNS configuration.
        socketserver.TCPServer.server_bind(self)
        self.server_name='localhost';self.server_port=self.server_address[1]


def serve(port=4318):
    with connect():pass
    server=LocalServer(('127.0.0.1',port),Handler)
    server.token=secrets.token_urlsafe(32);server.collector_error=None
    server.analysis_lock=threading.Lock();server.analysis_error=None;server.analysis_result=None
    stop=threading.Event()
    def collector():
        while not stop.is_set():
            try:collect();server.collector_error=None
            except Exception as exc:server.collector_error=str(exc)
            stop.wait(1)
    threading.Thread(target=collector,daemon=True).start()
    print(f'OH dashboard: http://localhost:{server.server_port}',flush=True)
    try:server.serve_forever()
    finally:stop.set();server.server_close()
