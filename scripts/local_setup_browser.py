#!/usr/bin/env python3
"""Loopback-only browser access via ordinary SSH commands (no TCP forwarding)."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shlex
import subprocess

REMOTE = '''import sys,json,urllib.request,urllib.error
p=json.load(sys.stdin)
assert p['path'] in ['/auth/status','/auth/login','/auth/token']
r=urllib.request.Request('http://127.0.0.1:8001'+p['path'],data=None if p['method']=='GET' else p['body'].encode(),headers={'Authorization':p['authorization'],'Content-Type':'application/json'})
try:
 with urllib.request.urlopen(r,timeout=50) as x: print(json.dumps({'status':x.status,'body':x.read().decode()}))
except urllib.error.HTTPError as x: print(json.dumps({'status':x.code,'body':x.read().decode()}))
'''
STATIC = Path(__file__).resolve().parents[1] / 'src/monarch_mcp_server/static'
FILES = {'/': ('login.html', 'text/html'), '/setup.js': ('setup.js', 'application/javascript'), '/setup.css': ('setup.css', 'text/css')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18001)
    parser.add_argument('--ssh-host', default='joseperiban@media.anaideia.dev')
    parser.add_argument('--identity', default=str(Path.home() / '.ssh/id_ed25519'))
    args = parser.parse_args()
    authority = f'127.0.0.1:{args.port}'
    origin = 'http://' + authority

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log request paths, headers, bodies, or credentials.

        def send(self, code, body, content_type='application/json'):
            raw = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            for k, v in {'Content-Type': content_type, 'Content-Length': str(len(raw)), 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def dispatch(self):
            # Prevent DNS rebinding and cross-origin browser requests to the relay.
            if self.headers.get('Host') != authority or self.headers.get('Origin', origin) != origin:
                return self.send(403, '{"error":"origin_rejected"}')
            if self.command == 'GET' and self.path in FILES:
                filename, content_type = FILES[self.path]
                return self.send(200, (STATIC / filename).read_bytes(), content_type)
            if (self.command, self.path) not in {('GET','/auth/status'),('POST','/auth/login'),('POST','/auth/token')}:
                return self.send(404, '{"error":"not_found"}')
            auth = self.headers.get('Authorization', '')
            if not auth.startswith('Bearer ') or len(auth) > 1024:
                return self.send(401, '{"error":"unauthorized"}')
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0 or length > 16384:
                    return self.send(413, '{"error":"body_too_large"}')
                body = self.rfile.read(length).decode()
                payload = json.dumps({'path':self.path,'method':self.command,'authorization':auth,'body':body})
                command = 'docker exec -i monarch-mcp-monarch-mcp-1 python -c ' + shlex.quote(REMOTE)
                result = subprocess.run(['ssh','-o','IdentityAgent=none','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',args.identity,args.ssh_host,command],input=payload,text=True,capture_output=True,timeout=60,check=True)
                data = json.loads(result.stdout)
                self.send(data['status'], data['body'])
            except (ValueError, OSError, subprocess.SubprocessError):
                self.send(503, '{"error":"setup_connection_unavailable"}')

        do_GET = dispatch
        do_POST = dispatch

    print(f'Monarch setup: {origin}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
