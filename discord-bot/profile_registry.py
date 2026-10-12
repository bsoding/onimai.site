"""Publish only known profile endpoints for the isolated views service."""
import json
import os
import tempfile
from pathlib import Path
from core import validate_endpoint, UserError


def write_registry(path, tree):
    path = Path(path)
    files = {entry['path'] for entry in tree if entry['type'] == 'blob'}
    profiles = []
    for file in files:
        if file.count('/') == 1 and file.endswith('/index.html'):
            endpoint = file.split('/')[0]
            if endpoint + '/profile.js' not in files:
                continue
            try:
                profiles.append(validate_endpoint(endpoint))
            except UserError:
                pass
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False, encoding='utf-8') as stream:
        json.dump(sorted(set(profiles)), stream)
        temporary = Path(stream.name)
    os.chmod(temporary, 0o640)
    temporary.replace(path)

