"""Load owned profiles and update only the fields changed in an edit draft."""
import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

from core import UserError, CONNECTION_FIELDS, parse_names, parse_bios, connections_text, profile_html
from media import upload_path, EXTENSIONS


async def text_blob(publisher, sha):
    blob = await publisher.api('GET', '/git/blobs/' + sha)
    return base64.b64decode(blob['content']).decode('utf-8')


def setting(html, key):
    match = re.search(r'\b' + key + r':\s*("(?:[^"\\]|\\.)*")', html)
    return json.loads(match[1]) if match else ''


async def load_profile(publisher, page):
    _, _, tree = await publisher.snapshot()
    prefix = page.endpoint + '/'
    blobs = {entry['path'][len(prefix):]: entry['sha'] for entry in tree if entry['type'] == 'blob' and entry['path'].startswith(prefix)}
    if 'index.html' not in blobs:
        raise UserError("That published page is no longer in the repository.")
    html = await text_blob(publisher, blobs['index.html'])
    async def text(path):
        return await text_blob(publisher, blobs[path]) if path in blobs else ''
    names = parse_names((await text('settings/names.txt')) or '\n'.join(page.names))
    bios = parse_bios((await text('settings/bios.txt')) or '\n\n'.join(page.bios))
    connections = {key: '' for key, _, _ in CONNECTION_FIELDS}
    for line in (await text('settings/connections.txt')).splitlines():
        key, separator, value = line.partition('=')
        key = {'TWITTER': 'X', 'MAIL': 'EMAIL'}.get(key.strip().upper(), key.strip().upper())
        if separator and key in connections and value.strip():
            connections[key] = value.strip()
    media = {}
    for kind, value in [('picture', setting(html, 'avatar')), ('background', setting(html, 'backgroundVideo') or setting(html, 'backgroundImage')), ('music', setting(html, 'audio'))]:
        media[kind] = {'source': 'existing', 'original_name': value or ('No music' if kind == 'music' else 'Site default')}
    return {'names': names, 'bios': bios, 'connections': connections, 'media': media, 'source_blobs': blobs, 'changes': []}


async def publish_edit(publisher, session, save_commit, save_media):
    from publisher import GitHubError
    if await publisher.is_published(session):
        return session.commit_sha
    if not session.changes:
        raise UserError("Choose a field to edit before submitting your changes.")
    media_entries, media_paths = [], {}
    for kind, entry in session.media.items():
        if kind not in session.changes or not entry or entry.get('source') == 'existing':
            continue
        extension = Path(entry['filename']).suffix
        prefix = {'picture': 'profile', 'background': 'background', 'music': 'background_music'}[kind]
        if extension not in EXTENSIONS[kind] or entry['filename'] != prefix + extension or publisher.media_root is None:
            raise UserError("The saved upload is unavailable. Upload it again.")
        path = upload_path(publisher.media_root, session.id, entry['path'])
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise UserError("Your saved upload changed. Upload it again.")
        sha = entry.get('blob_sha')
        if not sha:
            sha = (await publisher.api('POST', '/git/blobs', {'encoding': 'base64', 'content': base64.b64encode(data).decode()}))['sha']
            if save_media:
                save_media(kind, sha)
        relative = 'assets/' + entry['filename']
        media_paths[kind] = relative
        media_entries.append({'path': session.endpoint + '/' + relative, 'mode': '100644', 'type': 'blob', 'sha': sha})
    for attempt in range(4):
        head, base_tree, tree = await publisher.snapshot()
        prefix = session.endpoint + '/'
        current = {entry['path'][len(prefix):]: entry['sha'] for entry in tree if entry['type'] == 'blob' and entry['path'].startswith(prefix)}
        touched = {'index.html'}
        for field, path in [('names', 'settings/names.txt'), ('bio', 'settings/bios.txt'), ('connections', 'settings/connections.txt')]:
            if field in session.changes:
                touched.add(path)
        for kind in ('picture', 'background', 'music'):
            if kind not in session.changes:
                continue
            entry = session.media.get(kind)
            if entry and entry.get('filename'):
                touched.add('assets/' + entry['filename'])
            elif kind != 'music' and not entry:
                touched.add('assets/profile.png' if kind == 'picture' else 'assets/background.mp4')
                if kind == 'background':
                    touched.add('assets/background.svg')
        if any(current.get(path) != session.source_blobs.get(path) for path in touched):
            raise UserError("This page changed since you opened the editor. Cancel this edit and reopen /edit to load the latest version.")
        if 'index.html' not in current:
            raise UserError("The original profile is unavailable.")
        html = await text_blob(publisher, current['index.html'])
        entries = list(media_entries)
        paths = dict(media_paths)
        for kind in ('picture', 'background', 'music'):
            if kind not in session.changes or session.media.get(kind):
                continue
            if kind == 'music':
                paths[kind] = ''
                continue
            relative = 'assets/profile.png' if kind == 'picture' else 'assets/background.mp4'
            template = next((entry for entry in tree if entry['path'] == 'example/' + relative and entry['type'] == 'blob'), None)
            if not template:
                raise UserError("The default media is unavailable.")
            paths[kind] = relative
            entries.append({'path': session.endpoint + '/' + relative, 'mode': '100644', 'type': 'blob', 'sha': template['sha']})
            if kind == 'background':
                poster = next((entry for entry in tree if entry['path'] == 'example/assets/background.svg' and entry['type'] == 'blob'), None)
                if poster:
                    entries.append({'path': prefix + 'assets/background.svg', 'mode': '100644', 'type': 'blob', 'sha': poster['sha']})
                    html = re.sub(r'\bbackgroundImage:\s*"(?:[^"\\]|\\.)*"', 'backgroundImage: "assets/background.svg"', html, count=1)
                    html = re.sub(r'\bposter="[^"]*"', 'poster="assets/background.svg"', html, count=1)
        overrides = {'index.html': profile_html(html, session.names, session.bios, paths, preserve_media=True), 'settings/revision.txt': str(session.id) + '\n'}
        if 'names' in session.changes:
            overrides['settings/names.txt'] = '\n'.join(session.names) + '\n'
        if 'bio' in session.changes:
            overrides['settings/bios.txt'] = '\n\n'.join(session.bios) + '\n'
        if 'connections' in session.changes:
            overrides['settings/connections.txt'] = connections_text(session.connections)
        entries += [{'path': prefix + path, 'mode': '100644', 'type': 'blob', 'content': value} for path, value in overrides.items()]
        new_tree = await publisher.api('POST', '/git/trees', {'base_tree': base_tree, 'tree': entries})
        commit = await publisher.api('POST', '/git/commits', {'message': 'Edit bio page /' + session.endpoint, 'tree': new_tree['sha'], 'parents': [head]})
        save_commit(commit['sha'])
        try:
            await publisher.api('PATCH', '/git/refs/heads/' + quote(publisher.branch, safe=''), {'sha': commit['sha'], 'force': False})
            return commit['sha']
        except GitHubError as exc:
            if exc.status not in (409, 422) or attempt == 3:
                raise
    raise RuntimeError("Edit publication exhausted its retries.")
