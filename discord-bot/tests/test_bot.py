import asyncio
import os
import tempfile
import hashlib
import json
import base64
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from bot import BioBot, WizardView
from core import UserError


class Attachment:
    def __init__(self, filename, content):
        self.filename, self.content, self.size = filename, content, len(content)

    async def save(self, path):
        Path(path).write_bytes(self.content)
        return len(self.content)


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        values = {"DISCORD_GUILD_ID":"456","DATABASE_PATH":str(Path(self.directory.name)/"pages.sqlite3")}
        self.previous = {key:os.environ.get(key) for key in values}
        for key,value in values.items():
            os.environ[key]=value
        self.bot = BioBot()
        self.channel = Mock()
        self.channel.id, self.channel.mention = 777, "<#777>"
        self.channel.send = AsyncMock(side_effect=lambda *args, **kwargs: SimpleNamespace(id=1000+self.channel.send.call_count))
        self.channel.get_partial_message.return_value.edit = AsyncMock()
        self.channel.delete = AsyncMock()
        self.bot.get_channel = Mock(return_value=self.channel)
        self.bot.recovered.set()
        self.bot.publisher = SimpleNamespace(ensure_available=AsyncMock(), publish=AsyncMock(return_value="committed"))
        self.session = self.bot.store.reserve(123,456,"pollo")
        self.session = self.bot.store.update(self.session.id, phase="names", channel_id=777)
        self.completed_media = {"picture":None,"background":None,"music":None}

    async def asyncTearDown(self):
        await self.bot.close()
        for call in self.channel.send.call_args_list:
            if "file" in call.kwargs:
                call.kwargs["file"].close()
        for key,value in self.previous.items():
            if value is None:
                os.environ.pop(key,None)
            else:
                os.environ[key]=value
        self.directory.cleanup()

    async def test_names_then_bio_then_review_with_images(self):
        await self.bot.send_prompt(self.session)
        first = self.channel.send.call_args.kwargs
        self.assertEqual(first["content"], "Click **Enter names** to add your names/aliases (one per line).")
        self.assertEqual(first["file"].filename, "names.png")
        first["file"].close()
        await self.bot.accept_text(self.session.id,123,"names","Pollo\npollo.exe",1010)
        self.assertEqual(self.bot.store.get(self.session.id).phase,"bio")
        self.assertEqual(self.channel.send.call_args.kwargs["file"].filename,"bio.png")
        self.channel.send.call_args.kwargs["file"].close()
        await self.bot.accept_text(self.session.id,123,"bio","hello\n\nsecond bio",1020)
        current = self.bot.store.get(self.session.id)
        self.assertEqual(current.phase,"picture")
        self.assertEqual(current.bios,["hello","second bio"])
        self.assertEqual(current.last_message_id,1020)
        for checkpoint,kind,expected in [(1030,"picture","background"),(1040,"background","music"),(1050,"music","review")]:
            await self.bot.skip_media(self.session.id,123,kind,checkpoint)
            self.assertEqual(self.bot.store.get(self.session.id).phase,expected)
        self.assertEqual([b.label for b in self.channel.send.call_args.kwargs["view"].children],["Publish page","Edit names","Edit bio","Edit picture","Edit background","Edit music","Cancel"])

    async def test_other_users_and_stale_modal_cannot_edit(self):
        with self.assertRaises(UserError):
            await self.bot.accept_text(self.session.id,999,"names","hijacked")
        self.bot.store.update(self.session.id, phase="review")
        with self.assertRaises(UserError):
            await self.bot.accept_text(self.session.id,123,"names","stale")
        self.assertEqual(self.bot.store.get(self.session.id).names,[])

    async def test_invalid_input_keeps_current_step(self):
        with self.assertRaises(UserError):
            await self.bot.accept_text(self.session.id,123,"names","")
        self.assertEqual(self.bot.store.get(self.session.id).phase,"names")

    async def test_channel_text_never_sets_names_or_bios(self):
        message=SimpleNamespace(author=SimpleNamespace(id=123,bot=False),guild=SimpleNamespace(id=456),channel=self.channel,id=1100,content="typed in channel",attachments=[])
        await self.bot.on_message(message)
        self.assertEqual(self.bot.store.get(self.session.id).names,[])
        self.assertEqual(self.bot.store.get(self.session.id).phase,"names")
        self.assertIn("Enter names",self.channel.send.call_args.args[0])
        self.bot.store.update(self.session.id,phase="bio",names=["Pollo"])
        await self.bot.on_message(message)
        self.assertEqual(self.bot.store.get(self.session.id).bios,[])
        self.assertEqual(self.bot.store.get(self.session.id).phase,"bio")
        self.assertIn("Enter bio",self.channel.send.call_args.args[0])

    async def test_button_modal_saves_names_and_moves_to_bio(self):
        interaction=Mock()
        interaction.user.id,interaction.channel_id,interaction.guild_id,interaction.id=123,777,456,1100
        interaction.response.send_modal=AsyncMock()
        view=WizardView(self.bot,self.session)
        await view.children[0].callback(interaction)
        modal=interaction.response.send_modal.call_args.args[0]
        modal.text._value="Pollo\npollo.exe"
        interaction.response.defer=AsyncMock()
        interaction.edit_original_response=AsyncMock()
        await modal.on_submit(interaction)
        self.assertEqual(self.bot.store.get(self.session.id).names,["Pollo","pollo.exe"])
        self.assertEqual(self.bot.store.get(self.session.id).phase,"bio")

    async def test_uploads_advance_in_order_and_preserve_bytes_across_store_reopen(self):
        self.bot.store.update(self.session.id,phase="picture",names=["Pollo"],bios=["hello"])
        png=(Path(__file__).resolve().parents[1]/"assets/names.png").read_bytes()
        await self.bot.accept_upload(self.session.id,123,"picture",[Attachment("../my-picture.PNG",png)],1100)
        current=self.bot.store.get(self.session.id)
        self.assertEqual(current.phase,"background")
        picture_path=self.bot.data_root/current.media["picture"]["path"]
        self.assertEqual(picture_path.read_bytes(),png)
        self.assertEqual(current.media["picture"]["filename"],"profile.png")
        self.assertEqual(current.media["picture"]["sha256"],hashlib.sha256(png).hexdigest())
        fixture=json.loads((Path(__file__).parent/"fixtures/media.json").read_text())
        from subprocess import CompletedProcess
        with patch("media.shutil.which",return_value="ffprobe"),patch("media.subprocess.run",return_value=CompletedProcess([],0,stdout=b'{"format":{"format_name":"mov,mp4"},"streams":[{"codec_type":"video"}]}')):
            await self.bot.accept_upload(self.session.id,123,"background",[Attachment("video.mp4",base64.b64decode(fixture["mp4"]))],1200)
        self.assertEqual(self.bot.store.get(self.session.id).phase,"music")
        with patch("media.shutil.which",return_value="ffprobe"),patch("media.subprocess.run",return_value=CompletedProcess([],0,stdout=b'{"format":{"format_name":"mp3"},"streams":[{"codec_type":"audio","codec_name":"mp3"}]}')):
            await self.bot.accept_upload(self.session.id,123,"music",[Attachment("song.mp3",base64.b64decode(fixture["mp3"]))],1300)
        self.assertEqual(self.bot.store.get(self.session.id).phase,"review")
        from core import Store
        self.bot.store.close()
        self.bot.store=Store(self.bot.data_root/"pages.sqlite3")
        current=self.bot.store.get(self.session.id)
        self.assertEqual(set(current.media),{"picture","background","music"})
        self.assertEqual(picture_path.read_bytes(),png)

    async def test_invalid_or_other_users_uploads_cannot_advance(self):
        self.bot.store.update(self.session.id,phase="picture",names=["Pollo"],bios=["hello"])
        for uid,attachments in [(999,[Attachment("a.png",b"bad")]),(123,[Attachment("a.png",b"bad")]),(123,[Attachment("a.exe",b"bad")]),(123,[Attachment("a.png",b"bad"),Attachment("b.png",b"bad")])]:
            with self.assertRaises(UserError):
                await self.bot.accept_upload(self.session.id,uid,"picture",attachments,1100)
            self.assertEqual(self.bot.store.get(self.session.id).phase,"picture")
        self.assertEqual(list((self.bot.data_root/"uploads"/str(self.session.id)).iterdir()),[])

    async def test_stale_skip_cannot_skip_later_stage(self):
        self.bot.store.update(self.session.id,phase="background",names=["Pollo"],bios=["hello"],media={"picture":None})
        with self.assertRaises(UserError):
            await self.bot.skip_media(self.session.id,123,"picture",1100)
        self.assertEqual(self.bot.store.get(self.session.id).phase,"background")

    async def test_editing_text_after_media_does_not_repeat_upload_steps(self):
        self.bot.store.update(self.session.id,phase="bio",names=["Pollo"],bios=["old"],media=self.completed_media)
        await self.bot.accept_text(self.session.id,123,"bio","edited",1100)
        self.assertEqual(self.bot.store.get(self.session.id).phase,"review")

    async def test_cancel_and_channel_deletion_remove_draft_files(self):
        self.bot.store.update(self.session.id,phase="picture",names=["Pollo"],bios=["hello"])
        png=(Path(__file__).resolve().parents[1]/"assets/names.png").read_bytes()
        await self.bot.accept_upload(self.session.id,123,"picture",[Attachment("photo.png",png)],1100)
        self.assertTrue((self.bot.data_root/"uploads"/str(self.session.id)).exists())
        await self.bot.on_guild_channel_delete(self.channel)
        self.assertEqual(self.bot.store.count(123),0)
        self.assertFalse((self.bot.data_root/"uploads"/str(self.session.id)).exists())

    async def test_cancel_releases_slot_and_deletes_channel_only_after_15_seconds(self):
        session = self.bot.store.update(self.session.id, prompt_id=999)
        interaction = Mock()
        interaction.user.id, interaction.channel_id, interaction.guild_id = 123, 777, 456
        interaction.channel = self.channel
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        waiting, elapsed = asyncio.Event(), asyncio.Event()

        async def wait_for_countdown(delay):
            self.assertEqual(delay, 15)
            waiting.set()
            await elapsed.wait()

        with patch("bot.time.time", return_value=1000), patch("bot.asyncio.sleep", side_effect=wait_for_countdown):
            view = WizardView(self.bot, session)
            await next(button for button in view.children if button.label == "Cancel").callback(interaction)
            await waiting.wait()
            self.assertEqual(self.bot.store.count(123), 0)
            self.assertEqual(self.bot.store.get(session.id).phase, "cancelled")
            self.channel.delete.assert_not_awaited()
            self.assertIn("15 seconds", interaction.edit_original_response.call_args.kwargs["content"])
            self.channel.get_partial_message.return_value.edit.assert_awaited_once_with(view=None)
            elapsed.set()
            await asyncio.gather(*tuple(self.bot.background_tasks))
        self.channel.delete.assert_awaited_once()
        self.assertEqual(self.bot.store.pending_deletions(), [])

    async def test_restart_recovers_overdue_cancelled_channel_deletion(self):
        self.bot.store.cancel(self.session.id, delete_after=0)
        self.bot.get_guild = Mock(return_value=SimpleNamespace(id=456))
        self.bot.get_category = AsyncMock()
        await self.bot.recover()
        await asyncio.gather(*tuple(self.bot.background_tasks))
        self.channel.delete.assert_awaited_once()
        self.assertEqual(self.bot.store.pending_deletions(), [])

    async def test_deletion_never_removes_active_publishing_or_published_channels(self):
        for phase in ("names", "publishing", "published"):
            self.bot.store.update(self.session.id, phase=phase, delete_after=0)
            await self.bot.delete_cancelled_channel(self.session.id)
        self.channel.delete.assert_not_awaited()

    async def test_cancelled_channel_already_deleted_clears_pending_timer(self):
        self.bot.store.cancel(self.session.id, delete_after=0)
        self.channel.delete.side_effect = discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Channel")
        await self.bot.delete_cancelled_channel(self.session.id)
        self.assertEqual(self.bot.store.pending_deletions(), [])

    async def test_publish_cannot_bypass_the_media_steps(self):
        self.bot.store.update(self.session.id,phase="review",names=["Pollo"],bios=["hello"])
        with self.assertRaises(UserError):
            await self.bot.publish_session(self.session.id)
        self.bot.publisher.publish.assert_not_awaited()

    async def test_maximum_bios_and_emoji_aliases_fit_discord_embed_limits(self):
        names=["*"+str(n)+"🐈"*78 for n in range(10)]
        bios=["*"*598 for _ in range(3)]
        media={kind:{"original_name":"_*"*125+"🐈"*100} for kind in self.completed_media}
        session=self.bot.store.update(self.session.id,phase="review",names=names,bios=bios,media=media)
        await self.bot.send_prompt(session)
        embed=self.channel.send.call_args.kwargs["embed"]
        units=lambda value:len(value.encode("utf-16-le"))//2
        self.assertLessEqual(units(embed.description),4096)
        self.assertTrue(all(units(field.value)<=1024 for field in embed.fields))
        self.assertIn("\\*"*598,embed.description)
        self.assertNotIn("Badges", embed.description)
        self.assertLessEqual(units(embed.description)+sum(units(f.value)+units(f.name) for f in embed.fields)+units(embed.title)+units(embed.footer.text),6000)

    async def test_restart_reads_replies_only_after_latest_edit_prompt(self):
        self.bot.store.update(self.session.id,phase="picture",names=["Pollo"],bios=["hello"],prompt_id=2000,last_message_id=1900)
        self.bot.get_guild=Mock(return_value=SimpleNamespace(id=456))
        self.bot.get_category=AsyncMock()
        async def empty_history(**kwargs):
            if False:
                yield None
        self.channel.history=Mock(side_effect=empty_history)
        self.channel.fetch_message=AsyncMock(return_value=SimpleNamespace(id=2000))
        await self.bot.recover()
        self.assertEqual(self.channel.history.call_args.kwargs["after"].id,2000)
        self.channel.fetch_message.assert_awaited_once_with(2000)

    async def test_repeat_create_returns_same_private_channel(self):
        interaction = Mock()
        interaction.guild_id, interaction.user.id = 456,123
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        await self.bot.create_page(interaction,"another")
        interaction.response.defer.assert_awaited_once_with(ephemeral=True,thinking=True)
        self.assertIn("<#777>",interaction.edit_original_response.call_args.kwargs["content"])
        self.assertNotIn("Let's create",interaction.edit_original_response.call_args.kwargs["content"])
        self.assertNotIn("https://",interaction.edit_original_response.call_args.kwargs["content"])
        self.assertEqual(self.bot.store.count(123),1)
        self.bot.publisher.ensure_available.assert_not_awaited()
        self.channel.send.call_args.kwargs["file"].close()

    async def test_new_create_has_private_overwrites_correct_number_and_ephemeral_link(self):
        interaction=Mock()
        interaction.guild_id, interaction.user.id=456,999
        interaction.response.defer=AsyncMock()
        interaction.edit_original_response=AsyncMock()
        interaction.guild.create_text_channel=AsyncMock(return_value=self.channel)
        category=SimpleNamespace(channels=[])
        self.bot.get_category=AsyncMock(return_value=category)
        await self.bot.create_page(interaction,"newpage")
        kwargs=interaction.guild.create_text_channel.call_args.kwargs
        self.assertIs(kwargs["category"],category)
        self.assertFalse(kwargs["overwrites"][interaction.guild.default_role].view_channel)
        self.assertTrue(kwargs["overwrites"][interaction.user].view_channel)
        self.assertEqual(interaction.guild.create_text_channel.call_args.args[0],"create-2-999")
        self.assertIn("<#777>",interaction.edit_original_response.call_args.kwargs["content"])
        interaction.response.defer.assert_awaited_once_with(ephemeral=True,thinking=True)

    async def test_first_prompt_does_not_wait_for_gateway_channel_cache(self):
        self.bot.get_channel=Mock(return_value=None)
        self.bot.fetch_channel=AsyncMock(side_effect=AssertionError("New channel was already returned by Discord"))
        interaction=Mock()
        interaction.guild_id,interaction.user.id=456,999
        interaction.response.defer=AsyncMock()
        interaction.edit_original_response=AsyncMock()
        interaction.guild.create_text_channel=AsyncMock(return_value=self.channel)
        self.bot.get_category=AsyncMock(return_value=SimpleNamespace(channels=[]))
        await self.bot.create_page(interaction,"uncached")
        self.assertEqual(self.channel.send.call_args.kwargs["content"],"Click **Enter names** to add your names/aliases (one per line).")
        self.assertIn("<#777>",interaction.edit_original_response.call_args.kwargs["content"])
        self.bot.fetch_channel.assert_not_awaited()

    async def test_fourth_published_page_stops_before_channel_or_github_mutations(self):
        self.bot.store.update(self.session.id,phase="published")
        for endpoint in ["second","third"]:
            session=self.bot.store.reserve(123,456,endpoint)
            self.bot.store.update(session.id,phase="published")
        interaction=Mock()
        interaction.guild_id,interaction.user.id=456,123
        interaction.response.defer=AsyncMock()
        interaction.edit_original_response=AsyncMock()
        await self.bot.create_page(interaction,"fourth")
        self.assertIn("all 3 slots",interaction.edit_original_response.call_args.kwargs["content"])
        self.bot.publisher.ensure_available.assert_not_awaited()
        interaction.guild.create_text_channel.assert_not_called()

    async def test_publish_with_lost_response_keeps_slot_locked(self):
        self.bot.store.update(self.session.id,phase="review",names=["Pollo"],bios=["hello"],media=self.completed_media)
        async def lost_response(session,save,save_media):
            save("uncertain-commit")
            raise asyncio.TimeoutError()
        self.bot.publisher.publish.side_effect=lost_response
        await self.bot.publish_session(self.session.id)
        session=self.bot.store.get(self.session.id)
        self.assertEqual(session.phase,"publishing")
        self.assertFalse(self.bot.store.cancel(session.id))
        self.assertEqual([b.label for b in WizardView(self.bot,session).children],["Retry publish"])

    async def test_failure_before_commit_allows_safe_retry_and_cancel(self):
        self.bot.store.update(self.session.id,phase="review",names=["Pollo"],bios=["hello"],media=self.completed_media)
        self.bot.publisher.publish.side_effect=asyncio.TimeoutError()
        await self.bot.publish_session(self.session.id)
        self.assertEqual(self.bot.store.get(self.session.id).phase,"review")
        self.assertTrue(self.bot.store.cancel(self.session.id))

    async def test_successful_publish_consumes_slot_and_announces_commit(self):
        self.bot.store.update(self.session.id,phase="review",names=["Pollo"],bios=["hello"],media=self.completed_media)
        self.bot.wait_for_site=AsyncMock()
        self.channel.send=AsyncMock(return_value=SimpleNamespace(id=3000))
        await self.bot.publish_session(self.session.id)
        await asyncio.sleep(0)
        self.assertEqual(self.bot.store.get(self.session.id).phase,"published")
        self.assertEqual(self.bot.store.get(self.session.id).commit_sha,"committed")
        self.assertEqual(self.bot.store.count(123),1)
        self.assertIn("https://onimai.site/pollo",self.channel.send.call_args.args[0])

    async def test_deleted_unpublished_channel_releases_draft_only(self):
        await self.bot.on_guild_channel_delete(self.channel)
        self.assertEqual(self.bot.store.count(123),0)
        session=self.bot.store.reserve(123,456,"newpage")
        self.bot.store.update(session.id,phase="published",channel_id=777)
        await self.bot.on_guild_channel_delete(self.channel)
        self.assertEqual(self.bot.store.count(123),1)

    def test_slash_command_has_only_endpoint_parameter(self):
        commands=self.bot.tree.get_commands()
        self.assertEqual([c.name for c in commands],["create"])
        self.assertEqual([p.name for p in commands[0].parameters],["endpoint"])
        self.assertTrue(commands[0].parameters[0].required)


if __name__ == "__main__":
    unittest.main()
