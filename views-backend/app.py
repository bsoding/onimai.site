"""Daily unique profile views, reachable only through a private tunnel socket."""
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from flask import Flask, request, jsonify, abort


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=2048,
        TRUSTED_HOSTS=['api.onimai.site'],
        DATABASE_PATH=os.environ.get('VIEWS_DATABASE', '/var/lib/onimai-views/views.sqlite3'),
        REGISTRY_PATH=os.environ.get('PROFILE_REGISTRY', '/var/lib/onimai-registry/profiles.json'),
        IP_SECRET=os.environ.get('VIEWS_IP_SECRET', ''),
        CLOCK=time.time,
        ALLOWED_ORIGINS={'https://onimai.site', 'https://www.onimai.site'},
    )
    if config:
        app.config.update(config)
    secret = app.config['IP_SECRET'].encode()
    if len(secret) < 32:
        raise RuntimeError('Set a private VIEWS_IP_SECRET of at least 32 characters.')
    database_path = Path(app.config['DATABASE_PATH'])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(database_path)
    db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS totals(endpoint TEXT PRIMARY KEY, views INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS visitors(endpoint TEXT, visitor TEXT, last_counted REAL NOT NULL, PRIMARY KEY(endpoint,visitor));
        CREATE TABLE IF NOT EXISTS tickets(token TEXT PRIMARY KEY, endpoint TEXT, visitor TEXT, issued REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS limits(key TEXT PRIMARY KEY, bucket INTEGER NOT NULL, requests INTEGER NOT NULL, expires REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS ticket_age ON tickets(issued);
        CREATE INDEX IF NOT EXISTS visitor_age ON visitors(last_counted);
    ''')
    db.close()

    def connect():
        db = sqlite3.connect(database_path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('BEGIN IMMEDIATE')
        return db

    def endpoint_exists(endpoint):
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9_-]{0,30}[a-z0-9])?', endpoint):
            return False
        try:
            return endpoint in json.loads(Path(app.config['REGISTRY_PATH']).read_text())
        except (OSError, ValueError):
            return False

    def visitor():
        # The production WSGI listener is a group-protected Unix socket, not TCP.
        # Never use client-provided X-Forwarded-For, X-Real-IP, or JSON IP fields.
        if request.headers.get('CF-Worker') or not re.fullmatch(r'[a-fA-F0-9]{16,32}(?:-[A-Z]{3})?', request.headers.get('CF-Ray', '')):
            abort(403)
        try:
            address = ipaddress.ip_address(request.headers.get('CF-Connecting-IP', ''))
        except ValueError:
            abort(403)
        if address == ipaddress.ip_address('2a06:98c0:3600::103') or not address.is_global:
            abort(403)
        if isinstance(address, ipaddress.IPv6Address) and address.scope_id:
            abort(403)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        normalized = str(ipaddress.ip_network(f'{address}/64', strict=False)) if address.version == 6 else str(address)
        return hmac.new(secret, normalized.encode(), hashlib.sha256).hexdigest()

    def rate(db, key, limit, period, now, persist=True):
        bucket = int(now // period)
        db.execute('INSERT INTO limits(key,bucket,requests,expires) VALUES(?,?,1,?) ON CONFLICT(key) DO UPDATE SET requests=CASE WHEN bucket=excluded.bucket THEN requests+1 ELSE 1 END,bucket=excluded.bucket,expires=excluded.expires', (key, bucket, (bucket + 1) * period))
        count = db.execute('SELECT requests FROM limits WHERE key=?', (key,)).fetchone()[0]
        if count > limit:
            db.commit()
            return jsonify(error='Rate limit exceeded'), 429, {'Retry-After': str(max(1, int(period - now % period)))}
        if persist:
            db.commit()
            db.execute('BEGIN IMMEDIATE')
        return None

    @app.after_request
    def response_headers(response):
        origin = request.headers.get('Origin')
        if origin in app.config['ALLOWED_ORIGINS']:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'none'"
        return response

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(413)
    def error_response(error):
        return jsonify(error=error.name), error.code

    @app.get('/health')
    def health():
        return jsonify(status='ok')

    @app.route('/v1/views/<endpoint>', methods=['GET', 'POST', 'OPTIONS'])
    @app.route('/v1/views/<endpoint>/challenge', methods=['POST', 'OPTIONS'])
    def views(endpoint):
        if not endpoint_exists(endpoint):
            abort(404)
        identity = visitor()
        origin = request.headers.get('Origin')
        if request.method != 'GET' and origin not in app.config['ALLOWED_ORIGINS']:
            abort(403)
        now = app.config['CLOCK']()
        db = connect()
        try:
            limited = rate(db, 'request:' + identity, 120, 60, now)
            if limited:
                return limited
            if request.method == 'OPTIONS':
                db.commit()
                return '', 204
            db.execute('DELETE FROM tickets WHERE issued<?', (now - 120,))
            db.execute('DELETE FROM visitors WHERE last_counted<?', (now - 86400,))
            db.execute('DELETE FROM limits WHERE expires<?', (now,))
            def total():
                row = db.execute('SELECT views FROM totals WHERE endpoint=?', (endpoint,)).fetchone()
                return row[0] if row else 0
            if request.method == 'GET':
                db.commit()
                return jsonify(views=total())
            if not request.is_json:
                abort(400)
            body = request.get_json()
            if not isinstance(body, dict):
                abort(400)
            limited = rate(db, 'write:' + identity, 12, 60, now)
            if limited:
                return limited
            if request.path.endswith('/challenge'):
                if body:
                    abort(400)
                token = secrets.token_urlsafe(32)
                db.execute('INSERT INTO tickets VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), endpoint, identity, now))
                db.commit()
                return jsonify(token=token, wait_ms=2200, expires_in=120)
            if set(body) != {'token'} or not isinstance(body['token'], str) or len(body['token']) > 100:
                abort(400)
            token = hashlib.sha256(body['token'].encode()).hexdigest()
            ticket = db.execute('SELECT * FROM tickets WHERE token=?', (token,)).fetchone()
            if not ticket or ticket['endpoint'] != endpoint or ticket['visitor'] != identity or now - ticket['issued'] > 120:
                abort(403)
            if now - ticket['issued'] < 2:
                db.commit()
                return jsonify(error='Please wait before recording this visit'), 425, {'Retry-After': '2'}
            db.execute('DELETE FROM tickets WHERE token=?', (token,))
            previous = db.execute('SELECT last_counted FROM visitors WHERE endpoint=? AND visitor=?', (endpoint, identity)).fetchone()
            counted = previous is None or now - previous[0] >= 86400
            if counted:
                limited = rate(db, 'daily:' + identity, 30, 86400, now, persist=False)
                if limited:
                    return limited
                db.execute('INSERT INTO totals VALUES(?,1) ON CONFLICT(endpoint) DO UPDATE SET views=views+1', (endpoint,))
                db.execute('INSERT OR REPLACE INTO visitors VALUES(?,?,?)', (endpoint, identity, now))
            count = total()
            db.commit()
            return jsonify(views=count, counted=counted)
        finally:
            db.rollback()
            db.close()
    return app


if __name__ != '__main__' and os.environ.get('VIEWS_IP_SECRET'):
    app = create_app()
