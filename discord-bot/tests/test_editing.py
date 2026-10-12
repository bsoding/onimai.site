import base64
import tempfile
import unittest
from pathlib import Path
from core import Store, UserError, CONNECTION_FIELDS
from editing import load_profile
from test_publisher import FakePublisher


class FakeEditor(FakePublisher):
    def __init__(self):
        super().__init__()
        html = (Path(__file__).resolve().parents[2]/'example/index.html').read_text(encoding='utf-8')
        self.html = html.replace('audio: ""', 'audio: "assets/keep.mp3"').replace('const BADGES = [', 'const BADGES = [\n // owner-added-badge')
        self.blobs = {'index.html':'old-index', 'settings/names.txt':'names', 'settings/bios.txt':'bios', 'settings/connections.txt':'connections', 'settings/badges.txt':'owner-badges', 'assets/profile.png':'old-picture', 'assets/keep.mp3':'old-music'}

    async def snapshot(self):
        _, _, tree = await super().snapshot()
        tree += [{'path':'pollo/'+path,'sha':sha,'type':'blob','mode':'100644'} for path, sha in self.blobs.items()]
        return 'head'+str(self.number), 'base-tree'+str(self.number), tree

    async def api(self, method, path, data=None):
        if method == 'GET' and path.startswith('/git/blobs/'):
            texts = {'old-index':self.html, 'names':'Pollo\n', 'bios':'hello\n', 'connections':'GITHUB=username\n', 'owner-badges':'owner\n'}
            if path.removeprefix('/git/blobs/') in texts:
                self.calls.append((method,path,data))
                return {'content':base64.b64encode(texts[path.removeprefix('/git/blobs/')].encode()).decode()}
        return await super().api(method,path,data)


class EditingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/'pages.sqlite3')
        self.page = self.store.reserve(123,456,'pollo')
        self.page = self.store.update(self.page.id, phase='published', names=['Pollo'], bios=['hello'])
        self.publisher = FakeEditor()

    async def asyncTearDown(self):
        self.store.close()
        self.temp.cleanup()

    async def edit(self):
        values = await load_profile(self.publisher,self.page)
        return self.store.start_edit(self.page.id,123,456,values)

    def save(self, session):
        return lambda commit:self.store.update(session.id,commit_sha=commit)

    async def test_edit_loads_live_values_and_preserves_owner_badges_and_media(self):
        edit = await self.edit()
        self.assertEqual(edit.connections['GITHUB'],'username')
        self.assertEqual(edit.media['music']['original_name'],'assets/keep.mp3')
        edit = self.store.update(edit.id,phase='review',bios=['new bio'],changes=['bio'])
        sha = await self.publisher.publish(edit,self.save(edit))
        entries = {entry['path']:entry for entry in self.publisher.tree_payloads[-1]['tree']}
        self.assertEqual(set(entries),{'pollo/index.html','pollo/settings/bios.txt','pollo/settings/revision.txt'})
        self.assertIn('audio: "assets/keep.mp3"',entries['pollo/index.html']['content'])
        self.assertIn('owner-added-badge',entries['pollo/index.html']['content'])
        self.store.finish_publish(edit.id,sha)
        self.assertEqual(self.store.count(123),1)
        self.assertEqual(self.store.get(self.page.id).bios,['new bio'])

    async def test_edit_works_at_three_page_limit_and_cancel_keeps_original(self):
        for endpoint in ['second','third']:
            page = self.store.reserve(123,456,endpoint)
            self.store.update(page.id,phase='published')
        edit = await self.edit()
        self.assertEqual(self.store.count(123),3)
        self.assertTrue(self.store.cancel(edit.id))
        self.assertEqual(self.store.get(self.page.id).phase,'published')
        self.assertEqual(self.store.count(123),3)

    async def test_other_users_cannot_start_edits_and_only_one_draft_can_exist(self):
        values = await load_profile(self.publisher,self.page)
        with self.assertRaises(UserError):
            self.store.start_edit(self.page.id,999,456,values)
        await self.edit()
        with self.assertRaises(UserError):
            await self.edit()

    async def test_concurrent_profile_change_prevents_overwrite(self):
        edit = await self.edit()
        edit = self.store.update(edit.id,phase='review',bios=['new'],changes=['bio'])
        self.publisher.blobs['index.html'] = 'changed-index'
        with self.assertRaises(UserError):
            await self.publisher.publish(edit,self.save(edit))
        self.assertEqual(self.publisher.tree_payloads,[])

    async def test_music_removal_preserves_badges_and_retries_are_idempotent(self):
        edit = await self.edit()
        edit = self.store.update(edit.id,phase='review',media={**edit.media,'music':None},changes=['music'])
        sha = await self.publisher.publish(edit,self.save(edit))
        index = next(entry for entry in self.publisher.tree_payloads[-1]['tree'] if entry['path']=='pollo/index.html')
        self.assertIn('audio: ""',index['content'])
        self.assertIn('owner-added-badge',index['content'])
        current = self.store.get(edit.id)
        calls = len(self.publisher.calls)
        self.assertEqual(await self.publisher.publish(current,self.save(current)),sha)
        self.assertEqual(len(self.publisher.calls),calls)

    async def test_edit_requires_a_change_and_survives_store_restart(self):
        edit = await self.edit()
        with self.assertRaises(UserError):
            await self.publisher.publish(edit,self.save(edit))
        self.store.close()
        self.store = Store(Path(self.temp.name)/'pages.sqlite3')
        current = self.store.active_for_user(123)
        self.assertEqual((current.kind,current.parent_id,current.connections['GITHUB']),('edit',self.page.id,'username'))

if __name__ == '__main__':
    unittest.main()
