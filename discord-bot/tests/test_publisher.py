import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock

from core import Store, EndpointTaken
from publisher import Publisher, GitHubError


class FakePublisher(Publisher):
    def __init__(self):
        super().__init__(None, "unused", "bsoding/onimai.site", "main")
        self.calls, self.tree_payloads, self.events = [], [], []
        self.published = False
        self.conflicts = 0
        self.extra_paths = []
        self.number = 0

    async def snapshot(self):
        files = ["index.html", "profile.js", "style.css", "assets/profile.png", "assets/background.mp4", "settings/names.txt", "settings/bios.txt", "settings/badges.txt", "settings/connections.txt"]
        tree = [{"path":"example/"+p,"type":"blob","sha":"blob-"+p,"mode":"100644"} for p in files]
        tree.extend({"path":p,"type":"tree","sha":"existing","mode":"040000"} for p in self.extra_paths)
        return "head" + str(self.number), "base-tree" + str(self.number), tree

    async def is_published(self, session):
        return self.published and bool(session.commit_sha)

    async def api(self, method, path, data=None):
        self.calls.append((method,path,data))
        if method == "GET" and path.startswith("/git/blobs/"):
            template = (Path(__file__).resolve().parents[2] / "example/index.html").read_bytes()
            return {"content":base64.b64encode(template).decode()}
        if path == "/git/trees":
            self.tree_payloads.append(data)
            return {"sha":"new-tree"}
        if method == "POST" and path == "/git/blobs":
            raw=base64.b64decode(data["content"])
            return {"sha":hashlib.sha1(("blob "+str(len(raw))+"\0").encode()+raw).hexdigest()}
        if path == "/git/commits":
            self.number += 1
            return {"sha":"commit"+str(self.number)}
        if method == "PATCH":
            self.events.append("update-ref")
            if self.conflicts:
                self.conflicts -= 1
                raise GitHubError(422)
            self.published = True
            return {"object":{"sha":data["sha"]}}
        if path.startswith("/compare/"):
            return {"status":"ahead" if self.published else "diverged"}
        raise AssertionError((method,path,data))


class PublisherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name)/"pages.sqlite3")
        self.session = self.store.reserve(123,456,"pollo")
        self.session = self.store.update(self.session.id, phase="review", names=["Pollo","pollo.exe"], bios=["hello","second bio"])
        self.publisher = FakePublisher()

    async def asyncTearDown(self):
        self.store.close()
        self.directory.cleanup()

    def save(self, sha):
        self.publisher.events.append("save-commit")
        self.store.update(self.session.id, commit_sha=sha)

    async def test_atomic_profile_commit_reuses_media_and_clears_badges(self):
        sha = await self.publisher.publish(self.session, self.save)
        self.assertEqual(sha, "commit1")
        self.assertEqual(self.publisher.events, ["save-commit","update-ref"])
        entries = {e["path"]:e for e in self.publisher.tree_payloads[0]["tree"]}
        self.assertTrue(all(path.startswith("pollo/") for path in entries))
        self.assertEqual(entries["pollo/assets/profile.png"]["sha"], "blob-assets/profile.png")
        self.assertEqual(entries["pollo/settings/names.txt"]["content"], "Pollo\npollo.exe\n")
        self.assertEqual(entries["pollo/settings/bios.txt"]["content"], "hello\n\nsecond bio\n")
        self.assertEqual(entries["pollo/settings/badges.txt"]["content"], "")
        self.assertEqual(entries["pollo/settings/connections.txt"]["content"], "")
        update = next(data for method,path,data in self.publisher.calls if method == "PATCH")
        self.assertFalse(update["force"])

    async def test_existing_profile_never_overwritten(self):
        self.publisher.extra_paths = ["Pollo"]
        with self.assertRaises(EndpointTaken):
            await self.publisher.publish(self.session, self.save)
        self.assertEqual(self.publisher.calls, [])

    async def test_saved_connections_are_in_the_atomic_profile_commit(self):
        session = self.store.update(self.session.id, connections={"GITHUB": "username", "X": "handle", "DISCORD": "123456789012345678", "EMAIL": "you@example.com"})
        await self.publisher.publish(session, self.save)
        entry = next(entry for entry in self.publisher.tree_payloads[0]["tree"] if entry["path"] == "pollo/settings/connections.txt")
        self.assertIn("GITHUB=username\n", entry["content"])
        self.assertIn("X=handle\n", entry["content"])
        self.assertIn("DISCORD=123456789012345678\n", entry["content"])
        self.assertIn("EMAIL=you@example.com\n", entry["content"])
        self.assertIn("INSTAGRAM=\n", entry["content"])

    async def test_branch_advance_rebuilds_commit_without_force(self):
        self.publisher.conflicts = 1
        sha = await self.publisher.publish(self.session, self.save)
        self.assertEqual(sha, "commit2")
        self.assertEqual(len(self.publisher.tree_payloads), 2)
        parents = [data["parents"] for method,path,data in self.publisher.calls if path == "/git/commits"]
        self.assertEqual(parents, [["head0"],["head1"]])

    async def test_restart_after_ref_update_does_not_duplicate_page(self):
        self.publisher.published = True
        session = self.store.update(self.session.id, commit_sha="already-committed", phase="publishing")
        result = await self.publisher.publish(session, self.save)
        self.assertEqual(result, "already-committed")
        self.assertEqual(self.publisher.calls, [])

    async def test_real_ancestry_logic(self):
        session = self.store.update(self.session.id, commit_sha="saved-commit")
        self.publisher.published = True
        self.assertTrue(await Publisher.is_published(self.publisher,session))
        self.publisher.published = False
        self.assertFalse(await Publisher.is_published(self.publisher,session))

    async def test_github_write_denial_is_identified_without_logging_credentials_or_uploaded_text(self):
        response = Mock(status=403, headers={"X-Accepted-GitHub-Permissions": "contents=write"})
        response.json = AsyncMock(return_value={"message": "Resource not accessible by personal access token"})
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        http = Mock(request=Mock(return_value=context))
        publisher = Publisher(http, "test-private-credential", "bsoding/onimai.site", "main")
        with self.assertLogs("onimai", level="ERROR") as logs:
            with self.assertRaises(GitHubError) as raised:
                await publisher.api("POST", "/git/trees", {"content": "test-private-upload"})
        self.assertEqual(raised.exception.status, 403)
        self.assertTrue(raised.exception.contents_write_denied)
        output = "\n".join(logs.output)
        self.assertIn("POST /git/trees returned HTTP 403", output)
        self.assertNotIn("test-private-credential", output)
        self.assertNotIn("test-private-upload", output)

    async def test_rate_limit_denial_is_not_reported_as_missing_repository_permissions(self):
        response = Mock(status=403, headers={"X-Accepted-GitHub-Permissions": "contents=write"})
        response.json = AsyncMock(return_value={"message": "API rate limit exceeded"})
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        publisher = Publisher(Mock(request=Mock(return_value=context)), "unused", "bsoding/onimai.site", "main")
        with self.assertLogs("onimai", level="ERROR"):
            with self.assertRaises(GitHubError) as raised:
                await publisher.api("POST", "/git/trees", {})
        self.assertFalse(raised.exception.contents_write_denied)

    async def test_uploads_are_binary_blobs_in_the_same_profile_commit(self):
        root=Path(self.directory.name)
        self.publisher.media_root=root
        directory=root/"uploads"/str(self.session.id)
        directory.mkdir(parents=True)
        data=b"uploaded-picture-bytes"
        path=directory/"photo.gif"
        path.write_bytes(data)
        entry={"path":path.relative_to(root).as_posix(),"filename":"profile.gif","original_name":"photo.gif","size":len(data),"sha256":hashlib.sha256(data).hexdigest()}
        session=self.store.update(self.session.id,media={"picture":entry,"background":None,"music":None})
        blobs=[]
        await self.publisher.publish(session,self.save,lambda kind,sha:blobs.append((kind,sha)))
        expected=hashlib.sha1(("blob "+str(len(data))+"\0").encode()+data).hexdigest()
        self.assertEqual(blobs,[("picture",expected)])
        entries={e["path"]:e for e in self.publisher.tree_payloads[0]["tree"]}
        self.assertEqual(entries["pollo/assets/profile.gif"]["sha"],expected)
        self.assertIn('avatar: "assets/profile.gif"',entries["pollo/index.html"]["content"])
        blob_data=next(payload for method,path,payload in self.publisher.calls if method=="POST" and path=="/git/blobs")
        self.assertEqual(base64.b64decode(blob_data["content"]),data)

    async def test_saved_blob_is_reused_on_retry(self):
        root=Path(self.directory.name)
        self.publisher.media_root=root
        directory=root/"uploads"/str(self.session.id)
        directory.mkdir(parents=True)
        data=b"picture-bytes"
        path=directory/"photo.png"
        path.write_bytes(data)
        entry={"path":path.relative_to(root).as_posix(),"filename":"profile.png","original_name":"photo.png","size":len(data),"sha256":hashlib.sha256(data).hexdigest(),"blob_sha":"previously-uploaded"}
        session=self.store.update(self.session.id,media={"picture":entry})
        await self.publisher.publish(session,self.save)
        self.assertFalse(any(method=="POST" and path=="/git/blobs" for method,path,_ in self.publisher.calls))
        entries=[e for e in self.publisher.tree_payloads[0]["tree"] if e["path"]=="pollo/assets/profile.png"]
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]["sha"],"previously-uploaded")

    def test_existing_top_level_files_and_case_variants_are_reserved(self):
        self.assertTrue(Publisher.exists([{"path":"JVBJ/index.html"}],"jvbj"))
        self.assertTrue(Publisher.exists([{"path":"CNAME"}],"cname"))
        self.assertFalse(Publisher.exists([{"path":"pollo-other/index.html"}],"pollo"))


if __name__ == "__main__":
    unittest.main()
