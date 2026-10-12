"""Private LAN setup link that creates a fresh Cloudflare approval in the morning."""
import hmac
import ipaddress
import json
import os
import secrets
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path('/var/lib/onimai-tunnel')
TOKEN_FILE = ROOT/'setup-link-token'
STATUS = ROOT/'setup-status.json'
if not TOKEN_FILE.exists():
    TOKEN_FILE.write_text(secrets.token_urlsafe(32))
    os.chmod(TOKEN_FILE,0o600)
TOKEN = TOKEN_FILE.read_text().strip()
ALLOWED = ipaddress.ip_network('192.168.86.0/24')
job = None
rates = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # The capability URL must never be written to access logs.

    def do_GET(self):
        global job
        if ipaddress.ip_address(self.client_address[0]) not in ALLOWED or not hmac.compare_digest(urlsplit(self.path).path, '/setup/'+TOKEN):
            self.send_error(404)
            return
        bucket = int(time.time()//60)
        previous_bucket,count = rates.get(self.client_address[0],(bucket,0))
        count = count+1 if bucket == previous_bucket else 1
        rates[self.client_address[0]] = (bucket,count)
        if count > 10:
            self.send_error(429)
            return
        state = json.loads(STATUS.read_text()) if STATUS.exists() else {}
        if state.get('phase') == 'configured':
            self.send_response(200)
            self.send_header('Content-Type','text/plain; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(b'The Onimai tunnel is configured. You can close this page.')
            return
        if job is None or job.poll() is not None:
            # Discard an earlier login URL before starting a fresh authorization.
            STATUS.unlink(missing_ok=True)
            job = subprocess.Popen(['/opt/onimai-views/.venv/bin/python','/opt/onimai-views/setup_tunnel.py'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                state = json.loads(STATUS.read_text())
            except (OSError,ValueError):
                state = {}
            url = state.get('url','')
            if state.get('phase') == 'awaiting_authorization' and url.startswith('https://dash.cloudflare.com/argotunnel?'):
                self.send_response(303)
                self.send_header('Location',url)
                self.send_header('Cache-Control','no-store')
                self.send_header('Referrer-Policy','no-referrer')
                self.end_headers()
                return
            if state.get('phase') == 'failed' or job.poll() is not None:
                break
            time.sleep(0.1)
        self.send_response(503)
        self.send_header('Content-Type','text/plain; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Retry-After','3')
        self.end_headers()
        self.wfile.write(b'Tunnel setup is starting or needs attention. Refresh shortly. Select onimai.site when Cloudflare asks.')


HTTPServer(('192.168.86.36',8877),Handler).serve_forever()
