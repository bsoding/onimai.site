"""Wait for the owner's Cloudflare approval, then finalize only Onimai's API."""
import base64
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path('/var/lib/onimai-tunnel')
CERT = ROOT / '.cloudflared/cert.pem'
CREDENTIALS = ROOT / 'credentials.json'
CONFIG = ROOT / 'config.yml'
STATUS = ROOT / 'setup-status.json'
CLOUDFLARED = '/usr/local/bin/cloudflared'


def status(phase, **fields):
    temporary = ROOT / 'setup-status.tmp'
    temporary.write_text(json.dumps({'phase': phase, 'updated_at': time.time(), **fields}))
    os.chmod(temporary, 0o600)
    temporary.replace(STATUS)


def run(*args):
    result = subprocess.run([CLOUDFLARED, 'tunnel', '--origincert', str(CERT), *args], text=True, capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError('Cloudflare command failed: ' + args[0])
    return result.stdout


def main():
    if CONFIG.is_file() and CREDENTIALS.is_file():
        status('configured', hostname='api.onimai.site')
        return
    if not CERT.is_file():
        status('starting_authorization')
        process = subprocess.Popen([CLOUDFLARED, 'tunnel', 'login'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            match = re.search(r'https://dash\.cloudflare\.com/argotunnel\?[^\s]+', line)
            if match:
                status('awaiting_authorization', url=match[0], hostname='api.onimai.site')
        if process.wait() or not CERT.is_file():
            raise RuntimeError('Cloudflare authorization did not finish.')
    status('verifying_domain')
    block = re.search(r'-----BEGIN ARGO TUNNEL TOKEN-----\s*(.*?)\s*-----END ARGO TUNNEL TOKEN-----', CERT.read_text(), re.S)
    if not block:
        raise RuntimeError('The Cloudflare certificate format was not recognized.')
    credential = json.loads(base64.b64decode(block[1]))
    if not re.fullmatch(r'[0-9a-f]{32}', credential['zoneID']):
        raise RuntimeError('The Cloudflare zone identity is invalid.')
    request = urllib.request.Request('https://api.cloudflare.com/client/v4/zones/' + credential['zoneID'] + '/dns_records?name=onimai.site&per_page=1', headers={'Authorization':'Bearer '+credential['apiToken'], 'User-Agent':'onimai-tunnel-setup'})
    with urllib.request.urlopen(request, timeout=20) as response:
        zone = json.load(response)
    if not zone.get('success') or not any(record.get('name') == 'onimai.site' for record in zone.get('result', [])):
        CERT.unlink(missing_ok=True)
        raise RuntimeError('Please select onimai.site when authorizing the tunnel.')
    status('creating_tunnel')
    if not CREDENTIALS.is_file():
        run('create', '--credentials-file', str(CREDENTIALS), 'onimai-profile-views')
    tunnel_id = json.loads(CREDENTIALS.read_text())['TunnelID']
    if not re.fullmatch(r'[0-9a-f-]{36}', tunnel_id):
        raise RuntimeError('Invalid tunnel identity.')
    status('routing_hostname', hostname='api.onimai.site')
    # No overwrite flag: an existing DNS record must never be replaced implicitly.
    run('route', 'dns', tunnel_id, 'api.onimai.site')
    configuration = f'''tunnel: {tunnel_id}
credentials-file: {CREDENTIALS}
ingress:
  - hostname: api.onimai.site
    service: unix:/run/onimai-views/api.sock
    originRequest:
      httpHostHeader: api.onimai.site
  - service: http_status:404
'''
    temporary = ROOT / 'config.tmp'
    temporary.write_text(configuration)
    os.chmod(temporary, 0o600)
    run('--config', str(temporary), 'ingress', 'validate')
    temporary.replace(CONFIG)
    CERT.unlink()  # Keep only this tunnel's credentials, not account management access.
    status('configured', hostname='api.onimai.site', tunnel_id=tunnel_id)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        status('failed', error=str(error) if isinstance(error, RuntimeError) else type(error).__name__)
        raise SystemExit(1)
