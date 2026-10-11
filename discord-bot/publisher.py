"""Publish a profile atomically using the GitHub Git Database API."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from urllib.parse import quote

import aiohttp

from core import EndpointTaken, Session, UserError, profile_html


class GitHubError(RuntimeError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"GitHub returned HTTP {status}")


class Publisher:
    def __init__(self, http: aiohttp.ClientSession, token: str, repository: str, branch: str):
        self.http, self.token = http, token
        self.repository, self.branch = repository, branch
        self.base = "https://api.github.com/repos/" + repository
        self.lock = asyncio.Lock()

    async def api(self, method: str, path: str, data: dict | None = None):
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "onimai-create-bot"}
        async with self.http.request(method, self.base + path, json=data, headers=headers, timeout=aiohttp.ClientTimeout(total=35)) as response:
            if response.status >= 400:
                await response.read()
                raise GitHubError(response.status)
            return await response.json()

    async def snapshot(self):
        ref = await self.api("GET", "/git/ref/heads/" + quote(self.branch, safe=""))
        commit = await self.api("GET", "/git/commits/" + ref["object"]["sha"])
        tree = await self.api("GET", "/git/trees/" + commit["tree"]["sha"] + "?recursive=1")
        if tree.get("truncated"):
            raise RuntimeError("Repository tree is too large to inspect safely.")
        return ref["object"]["sha"], commit["tree"]["sha"], tree["tree"]

    @staticmethod
    def exists(tree: list[dict], endpoint: str) -> bool:
        return any(entry["path"].split("/",1)[0].casefold() == endpoint.casefold() for entry in tree)

    async def ensure_available(self, endpoint: str) -> None:
        _, _, tree = await self.snapshot()
        if self.exists(tree, endpoint):
            raise EndpointTaken("That endpoint already exists on onimai.site. Please choose another name.")

    async def is_published(self, session: Session) -> bool:
        if not session.commit_sha:
            return False
        comparison = await self.api("GET", "/compare/" + session.commit_sha + "..." + quote(self.branch,safe=""))
        return comparison["status"] in ("ahead", "identical")

    async def publish(self, session: Session, save_commit: Callable[[str], None]) -> str:
        async with self.lock:
            if await self.is_published(session):
                return session.commit_sha
            for attempt in range(4):
                head, base_tree, tree = await self.snapshot()
                if self.exists(tree, session.endpoint):
                    raise EndpointTaken("That endpoint was taken before publishing. Cancel this draft and choose another endpoint.")
                template = [entry for entry in tree if entry["type"] == "blob" and entry["path"].startswith("example/")]
                paths = {entry["path"][len("example/"):] for entry in template}
                if not {"index.html", "profile.js", "style.css", "assets/profile.png", "assets/background.mp4"} <= paths:
                    raise RuntimeError("The example profile template is incomplete.")
                index_entry = next(entry for entry in template if entry["path"] == "example/index.html")
                blob = await self.api("GET", "/git/blobs/" + index_entry["sha"])
                import base64
                template_html = base64.b64decode(blob["content"]).decode("utf-8")
                overrides = {
                    "index.html": profile_html(template_html, session.names, session.bios),
                    "settings/names.txt": "\n".join(session.names) + "\n",
                    "settings/bios.txt": "\n\n".join(session.bios) + "\n",
                    "settings/badges.txt": "",
                    "settings/connections.txt": "",
                }
                entries = [{"path":session.endpoint + "/" + entry["path"][len("example/"):], "mode":entry["mode"], "type":"blob", "sha":entry["sha"]} for entry in template if entry["path"][len("example/"):] not in overrides]
                entries += [{"path":session.endpoint + "/" + path, "mode":"100644", "type":"blob", "content":content} for path,content in overrides.items()]
                new_tree = await self.api("POST", "/git/trees", {"base_tree":base_tree,"tree":entries})
                new_commit = await self.api("POST", "/git/commits", {"message":"Create bio page /" + session.endpoint,"tree":new_tree["sha"],"parents":[head]})
                # Save intent BEFORE moving the branch, so a lost response/restart is recoverable.
                save_commit(new_commit["sha"])
                try:
                    await self.api("PATCH", "/git/refs/heads/" + quote(self.branch,safe=""), {"sha":new_commit["sha"],"force":False})
                    return new_commit["sha"]
                except GitHubError as exc:
                    if exc.status not in (409,422) or attempt == 3:
                        raise
            raise RuntimeError("Publishing exhausted its retries.")
