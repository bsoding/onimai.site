"""Validation and durable wizard state, independent of Discord/network access."""
from __future__ import annotations

import html
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MAX_PAGES = 3
ACTIVE_PHASES = ("creating", "names", "bio", "review", "publishing")
RESERVED = {"assets", "example", "discord-bot", "api", "admin", "www", "create", "settings"}


class UserError(ValueError):
    """An error safe to present to the page creator."""


class PageLimit(UserError):
    pass


class EndpointTaken(UserError):
    pass


def validate_endpoint(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9_-]{0,30}[a-z0-9])?", value):
        raise UserError("Use 1–32 letters, numbers, hyphens, or underscores. Start and end with a letter or number.")
    if value in RESERVED:
        raise EndpointTaken("That endpoint is reserved. Please choose another name.")
    return value


def clean_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in value):
        raise UserError("Please use ordinary text without control characters.")
    return value


def parse_names(value: str) -> list[str]:
    names = list(dict.fromkeys(line.strip() for line in clean_text(value).splitlines() if line.strip()))
    if not 1 <= len(names) <= 10 or any(len(name) > 80 for name in names):
        raise UserError("Send 1–10 names/aliases, one per line, with up to 80 characters per name.")
    return names


def parse_bios(value: str) -> list[str]:
    value = clean_text(value)
    bios = [part.strip() for part in re.split(r"\n\s*\n", value) if part.strip()]
    if not 1 <= len(bios) <= 5 or len(value) > 1800 or any(len(bio) > 600 for bio in bios):
        raise UserError("Send 1–5 bios, separated by a blank line. Each can have up to 600 characters, with 1,800 total.")
    return bios


def script_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def profile_html(template: str, names: list[str], bios: list[str]) -> str:
    """Update fallback text and sharing metadata without treating user text as code."""
    result, count = re.subn(r'fallbackName:\s*"(?:[^"\\]|\\.)*"', lambda _: "fallbackName: " + script_json(names[0]), template, count=1)
    if count != 1:
        raise RuntimeError("The example profile is missing fallbackName.")
    result, count = re.subn(r'\bbio:\s*\[[^\n]*\]', lambda _: "bio: " + script_json(bios), result, count=1)
    if count != 1:
        raise RuntimeError("The example profile is missing its fallback bio array.")
    name, bio = html.escape(names[0], quote=True), html.escape(bios[0].replace("\n", " ")[:160], quote=True)
    result = re.sub(r"<title>.*?</title>", lambda _: f"<title>{name}</title>", result, count=1, flags=re.S)
    for attribute, key, value in [("name", "description", bio), ("property", "og:title", name), ("property", "og:description", bio)]:
        result = re.sub(rf'<meta {attribute}="{key}" content="[^"]*">', lambda _, a=attribute, k=key, v=value: f'<meta {a}="{k}" content="{v}">', result, count=1)
    result = re.sub(r'(<span id="nameText">).*?(</span>)', lambda m: m[1] + name + m[2], result, count=1, flags=re.S)
    result = re.sub(r'(<span id="bioText">).*?(</span>)', lambda m: m[1] + html.escape(bios[0]) + m[2], result, count=1, flags=re.S)
    return result


@dataclass(frozen=True)
class Session:
    id: int
    user_id: int
    guild_id: int
    endpoint: str
    phase: str
    channel_id: int | None
    names: list[str]
    bios: list[str]
    prompt_id: int | None
    last_message_id: int | None
    commit_sha: str | None
    created_at: str


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL, guild_id TEXT NOT NULL,
                endpoint TEXT NOT NULL COLLATE NOCASE,
                phase TEXT NOT NULL DEFAULT 'creating', channel_id TEXT,
                names TEXT NOT NULL DEFAULT '[]', bios TEXT NOT NULL DEFAULT '[]',
                prompt_id TEXT, last_message_id TEXT, commit_sha TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS reserved_endpoint
                ON sessions(endpoint) WHERE phase != 'cancelled';
            CREATE INDEX IF NOT EXISTS user_sessions ON sessions(user_id);
        """)

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def _session(row: sqlite3.Row | None) -> Session | None:
        if row is None:
            return None
        data = dict(row)
        for field in ("user_id", "guild_id", "channel_id", "prompt_id", "last_message_id"):
            data[field] = int(data[field]) if data[field] is not None else None
        data["names"], data["bios"] = json.loads(data["names"]), json.loads(data["bios"])
        return Session(**data)

    def get(self, session_id: int) -> Session | None:
        return self._session(self.db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())

    def for_channel(self, channel_id: int) -> Session | None:
        return self._session(self.db.execute("SELECT * FROM sessions WHERE channel_id=? AND phase != 'cancelled'", (str(channel_id),)).fetchone())

    def active_for_user(self, user_id: int) -> Session | None:
        return self._session(self.db.execute("SELECT * FROM sessions WHERE user_id=? AND phase IN ('creating','names','bio','review','publishing') ORDER BY id LIMIT 1", (str(user_id),)).fetchone())

    def active(self) -> list[Session]:
        return [self._session(row) for row in self.db.execute("SELECT * FROM sessions WHERE phase IN ('creating','names','bio','review','publishing') ORDER BY id")]

    def count(self, user_id: int) -> int:
        return self.db.execute("SELECT count(*) FROM sessions WHERE user_id=? AND phase != 'cancelled'", (str(user_id),)).fetchone()[0]

    def reserve(self, user_id: int, guild_id: int, endpoint: str) -> Session:
        endpoint = validate_endpoint(endpoint)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.count(user_id) >= MAX_PAGES:
                raise PageLimit("You can create up to 3 pages per Discord user ID. You have used all 3 slots.")
            cursor = self.db.execute("INSERT INTO sessions(user_id,guild_id,endpoint) VALUES(?,?,?)", (str(user_id), str(guild_id), endpoint))
            self.db.commit()
            return self.get(cursor.lastrowid)
        except sqlite3.IntegrityError:
            self.db.rollback()
            raise EndpointTaken("That endpoint is already being created. Please choose another name.") from None
        except Exception:
            self.db.rollback()
            raise

    def update(self, session_id: int, **fields) -> Session:
        allowed = {"phase", "channel_id", "names", "bios", "prompt_id", "last_message_id", "commit_sha"}
        if not fields or not set(fields) <= allowed:
            raise ValueError("Invalid session update")
        values = [json.dumps(v, ensure_ascii=False) if k in ("names", "bios") else str(v) if k.endswith("_id") and v is not None else v for k,v in fields.items()]
        with self.db:
            self.db.execute("UPDATE sessions SET " + ",".join(k + "=?" for k in fields) + " WHERE id=?", (*values,session_id))
        return self.get(session_id)

    def cancel(self, session_id: int) -> bool:
        with self.db:
            cursor = self.db.execute("UPDATE sessions SET phase='cancelled' WHERE id=? AND phase IN ('creating','names','bio','review')", (session_id,))
        return cursor.rowcount == 1
