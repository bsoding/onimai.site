"""Onimai's /create command and private, restart-safe page wizard."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import aiohttp
import discord
from discord import app_commands

from core import Store, Session, UserError, EndpointTaken, validate_endpoint, parse_names, parse_bios
from publisher import Publisher

LOG = logging.getLogger("onimai")
ROOT = Path(__file__).resolve().parent


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value == "replace_me":
        raise RuntimeError(f"Set {name} in the service environment.")
    return value


class TextModal(discord.ui.Modal):
    def __init__(self, bot: BioBot, session: Session, field: str):
        super().__init__(title="Your names / aliases" if field == "names" else "Your bio", timeout=600)
        self.bot, self.session_id, self.field = bot, session.id, field
        self.text = discord.ui.TextInput(
            label="Names / aliases — one per line" if field == "names" else "Bio — blank line between different bios",
            style=discord.TextStyle.paragraph,
            placeholder="Pollo\npollo.exe" if field == "names" else "somewhere on the internet\n\nyour other bio",
            default="\n".join(session.names) if field == "names" else "\n\n".join(session.bios),
            max_length=810 if field == "names" else 1800,
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.accept_text(self.session_id, interaction.user.id, self.field, self.text.value)
            await interaction.edit_original_response(content="Saved. Continue in your creation channel.")
        except UserError as exc:
            await interaction.edit_original_response(content=str(exc))
        except Exception:
            LOG.exception("Modal save failed for session %s", self.session_id)
            await interaction.edit_original_response(content="Your draft is saved. Please try the input button again.")


class WizardView(discord.ui.View):
    def __init__(self, bot: BioBot, session: Session):
        super().__init__(timeout=None)
        self.bot, self.session_id = bot, session.id
        if session.phase in ("names", "bio"):
            self.button("Enter names" if session.phase == "names" else "Enter bio", session.phase, discord.ButtonStyle.primary)
        if session.phase in ("review", "publishing"):
            self.button("Publish page" if session.phase == "review" else "Retry publish", "publish", discord.ButtonStyle.success)
        if session.phase == "review":
            self.button("Edit names", "edit_names", discord.ButtonStyle.secondary)
            self.button("Edit bio", "edit_bio", discord.ButtonStyle.secondary)
        if session.phase in ("names", "bio", "review"):
            self.button("Cancel", "cancel", discord.ButtonStyle.danger)

    def button(self, label: str, action: str, style: discord.ButtonStyle):
        button = discord.ui.Button(label=label, style=style, custom_id=f"onimai:{self.session_id}:{action}")

        async def callback(interaction: discord.Interaction):
            session = self.bot.store.get(self.session_id)
            if session is None or interaction.user.id != session.user_id or interaction.channel_id != session.channel_id or interaction.guild_id != session.guild_id:
                await interaction.response.send_message("Only the page creator can use these buttons.", ephemeral=True)
                return
            if session.phase in ("published", "cancelled", "creating"):
                await interaction.response.send_message("This wizard is already finished or is still starting.", ephemeral=True)
                return
            if action in ("names", "bio"):
                if session.phase != action:
                    await interaction.response.send_message("Use the buttons on the latest prompt.", ephemeral=True)
                    return
                await interaction.response.send_modal(TextModal(self.bot, session, action))
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                if action == "publish":
                    await self.bot.publish_session(session.id)
                    current = self.bot.store.get(session.id)
                    await interaction.edit_original_response(content="Your page was committed. The website link is in this channel." if current.phase == "published" else "Check the latest message in this channel to retry.")
                else:
                    async with self.bot.user_lock(session.user_id):
                        session = self.bot.store.get(session.id)
                        if session.phase not in ("names", "bio", "review"):
                            raise UserError("This draft is being published or has already finished.")
                        if action == "cancel":
                            self.bot.store.cancel(session.id)
                            await interaction.channel.send("Draft cancelled. Your page slot is available again.", allowed_mentions=discord.AllowedMentions.none())
                            if session.prompt_id:
                                await self.bot.clear_buttons(interaction.channel, session.prompt_id)
                            await interaction.edit_original_response(content="Cancelled. You can use /create for a new endpoint.")
                        else:
                            field = "names" if action == "edit_names" else "bio"
                            session = self.bot.store.update(session.id, phase=field, prompt_id=None)
                            await self.bot.send_prompt(session)
                            await interaction.edit_original_response(content="Reply to the latest prompt in this channel.")
            except UserError as exc:
                await interaction.edit_original_response(content=str(exc))
            except Exception:
                LOG.exception("Wizard action %s failed for session %s", action, session.id)
                await interaction.edit_original_response(content="Your draft is saved. Please try the latest button again.")

        button.callback = callback
        self.add_item(button)


class BioBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = os.environ.get("MESSAGE_CONTENT_ENABLED", "true").lower() == "true"
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.guild_id = int(required("DISCORD_GUILD_ID"))
        self.site = os.environ.get("SITE_URL", "https://onimai.site").rstrip("/")
        self.category_name = os.environ.get("CREATE_CATEGORY_NAME", "Create")
        self.store = Store(os.environ.get("DATABASE_PATH", str(ROOT / "data/pages.sqlite3")))
        self.tree = app_commands.CommandTree(self)
        self.locks: dict[int, asyncio.Lock] = {}
        self.category_lock = asyncio.Lock()
        self.recovered = asyncio.Event()
        self.recovery_started = False
        self.background_tasks: set[asyncio.Task] = set()

        @self.tree.command(name="create", description="Create a bio page @ onimai.site. Endpoint is the username, e.g. onimai.site/jvbj.")
        @app_commands.guild_only()
        @app_commands.describe(endpoint="Username where your profile is hosted, e.g. pollo for onimai.site/pollo")
        async def create(interaction: discord.Interaction, endpoint: str):
            await self.create_page(interaction, endpoint)

        @self.tree.error
        async def command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            LOG.error("Slash command failed: %s", type(error).__name__)
            message = "I couldn't start the page wizard. Please try /create again."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)

    def user_lock(self, user_id: int) -> asyncio.Lock:
        return self.locks.setdefault(user_id, asyncio.Lock())

    def task(self, coro):
        task = asyncio.create_task(coro)
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        return task

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession()
        self.publisher = Publisher(self.http_session, required("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY", "bsoding/onimai.site"), os.environ.get("GITHUB_BRANCH", "main"))
        for session in self.store.active():
            if session.prompt_id and session.phase != "creating":
                self.add_view(WizardView(self, session), message_id=session.prompt_id)
        guild = discord.Object(id=self.guild_id)
        self.tree.copy_global_to(guild=guild)
        commands = await self.tree.sync(guild=guild)
        LOG.info("Synced %s slash command(s) to guild %s", len(commands), self.guild_id)

    async def on_ready(self):
        LOG.info("Connected as %s (%s)", self.user.name, self.user.id)
        if not self.recovery_started:
            self.recovery_started = True
            self.task(self.recover())

    async def get_category(self, guild: discord.Guild) -> discord.CategoryChannel:
        async with self.category_lock:
            matches = [c for c in guild.categories if c.name.casefold() == self.category_name.casefold()]
            if len(matches) > 1:
                raise UserError("There are multiple Create categories. Ask the server owner to keep one.")
            if matches:
                return matches[0]
            return await guild.create_category(self.category_name, overwrites={guild.default_role:discord.PermissionOverwrite(view_channel=False), guild.me:discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, embed_links=True, attach_files=True, manage_channels=True)}, reason="Onimai /create page wizard")

    async def create_page(self, interaction: discord.Interaction, endpoint: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        session = None
        channel = None
        try:
            if interaction.guild_id != self.guild_id:
                raise UserError("Use /create in the Onimai server.")
            await asyncio.wait_for(self.recovered.wait(), timeout=25)
            endpoint = validate_endpoint(endpoint)
            async with self.user_lock(interaction.user.id):
                active = self.store.active_for_user(interaction.user.id)
                if active:
                    if active.phase == "creating" and not active.channel_id:
                        channels = await interaction.guild.fetch_channels()
                        recovered_channel = next((c for c in channels if isinstance(c, discord.TextChannel) and (c.topic or "").startswith(f"onimai-bot session:{active.id} |")), None)
                        if recovered_channel:
                            active = self.store.update(active.id, phase="names", channel_id=recovered_channel.id)
                            await self.send_prompt(active)
                    if active.channel_id and self.get_channel(active.channel_id):
                        if not active.prompt_id:
                            await self.send_prompt(active)
                        await interaction.edit_original_response(content=f"Continue your current page in <#{active.channel_id}>. Finish or cancel it before starting another.")
                        return
                    if active.phase == "publishing":
                        raise UserError("Your previous page is still being published. Please try again shortly.")
                    self.store.cancel(active.id)
                if self.store.count(interaction.user.id) >= 3:
                    raise UserError("You can create up to 3 pages per Discord user ID. You have used all 3 slots.")
                await self.publisher.ensure_available(endpoint)
                category = await self.get_category(interaction.guild)
                if len(category.channels) >= 50:
                    raise UserError("The Create category is full. Ask the server owner to move completed channels out of it.")
                session = self.store.reserve(interaction.user.id, interaction.guild_id, endpoint)
                overwrites = {
                    interaction.guild.default_role:discord.PermissionOverwrite(view_channel=False),
                    interaction.guild.me:discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, embed_links=True, attach_files=True, manage_channels=True),
                    interaction.user:discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
                }
                channel = await interaction.guild.create_text_channel(f"create-{session.id}-{session.user_id}", category=category, overwrites=overwrites, topic=f"onimai-bot session:{session.id} | {self.site}/{endpoint}", reason="Onimai /create private page wizard")
                session = self.store.update(session.id, channel_id=channel.id, phase="names")
                await self.send_prompt(session)
                await interaction.edit_original_response(content=f"Let's create **{self.site}/{endpoint}**. Continue in {channel.mention}.")
        except UserError as exc:
            await interaction.edit_original_response(content=str(exc))
        except discord.Forbidden:
            if session and channel is None:
                self.store.cancel(session.id)
            LOG.error("Missing Discord channel/message permissions")
            await interaction.edit_original_response(content=f"Your channel is {channel.mention}, but I couldn't send the prompt. Ask the server owner to allow Send Messages, Embed Links and Attach Files." if channel else "I need Manage Channels, View Channels, Send Messages, Read Message History, Embed Links and Attach Files in this server.")
        except Exception:
            if session and channel is None:
                # If Discord accepted channel creation but the response was lost, startup
                # recovery will match its session topic before releasing the reservation.
                LOG.exception("Creation outcome uncertain for session %s", session.id)
                await interaction.edit_original_response(content="Channel creation couldn't finish. Your draft is saved; please try /create again.")
            else:
                LOG.exception("Could not start creation wizard")
                await interaction.edit_original_response(content=f"Your draft is saved in {channel.mention}. Please try /create again." if channel else "I couldn't reach the publishing service. Please try /create again shortly.")

    async def clear_buttons(self, channel, message_id: int):
        try:
            await channel.get_partial_message(message_id).edit(view=None)
        except (discord.NotFound, discord.Forbidden):
            pass

    async def send_prompt(self, session: Session):
        channel = self.get_channel(session.channel_id)
        if channel is None:
            raise UserError("The creation channel is unavailable.")
        view = WizardView(self, session)
        file = None
        if session.phase == "names":
            content = "Please type your names/aliases for your page (one per line)."
            embed = discord.Embed(title="Step 1 · Names / aliases", description="These names rotate in the highlighted name area. Send 1–10 names, up to 80 characters each. You can also use **Enter names**.", color=0xA369B9)
            file = discord.File(ROOT / "assets/names.png", filename="names.png")
            embed.set_image(url="attachment://names.png")
        elif session.phase == "bio":
            content = "Please type your bio for your page."
            embed = discord.Embed(title="Step 2 · Bio", description="This is the text beneath your names. For rotating bios, separate each with a blank line. Use up to 5 bios, 600 characters each and 1,800 total. You can also use **Enter bio**.", color=0xA369B9)
            file = discord.File(ROOT / "assets/bio.png", filename="bio.png")
            embed.set_image(url="attachment://bio.png")
        else:
            content = "Review your page, then click Publish page." if session.phase == "review" else "Publishing is waiting for a retry. Your draft and page slot are saved."
            embed = discord.Embed(title=f"onimai.site/{session.endpoint}", description="Names and bios will rotate independently. Your page uses the site's default avatar and background. Badges start empty and are added by the site owner.", color=0xA369B9)
            embed.add_field(name="Names / aliases", value=discord.utils.escape_markdown("\n".join(session.names))[:1024] or "—", inline=False)
            embed.add_field(name="Bio", value=discord.utils.escape_markdown("\n\n".join(session.bios))[:2200] or "—", inline=False)
        embed.set_footer(text="Only you and server administrators can see this creation channel.")
        kwargs = {"content":content,"embed":embed,"view":view}
        if file:
            kwargs["file"] = file
        message = await channel.send(**kwargs)
        self.store.update(session.id, prompt_id=message.id)

    async def accept_text(self, session_id: int, user_id: int, field: str, text: str, message_id: int | None = None):
        async with self.user_lock(user_id):
            session = self.store.get(session_id)
            if not session or session.user_id != user_id:
                raise UserError("Only the page creator can edit this draft.")
            if session.phase != field:
                raise UserError("That step is already finished. Use the latest prompt or its edit buttons.")
            if message_id and session.last_message_id and message_id <= session.last_message_id:
                return
            values = parse_names(text) if field == "names" else parse_bios(text)
            old_prompt = session.prompt_id
            fields = {"names" if field == "names" else "bios":values,"prompt_id":None}
            if message_id:
                fields["last_message_id"] = message_id
            fields["phase"] = "review" if field == "bio" or session.bios else "bio"
            session = self.store.update(session.id, **fields)
            if old_prompt:
                await self.clear_buttons(self.get_channel(session.channel_id), old_prompt)
            await self.send_prompt(session)

    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or message.guild.id != self.guild_id:
            return
        session = self.store.for_channel(message.channel.id)
        if not session or message.author.id != session.user_id or session.phase not in ("names","bio"):
            return
        try:
            if not message.content and not self.intents.message_content:
                await message.channel.send("Please use the Enter names / Enter bio button on the latest prompt.")
                return
            await self.accept_text(session.id, message.author.id, session.phase, message.content, message.id)
        except UserError as exc:
            await message.channel.send(str(exc))
        except Exception:
            LOG.exception("Text save failed for session %s", session.id)
            await message.channel.send("Your draft is saved. Please try the latest input button.")

    async def publish_session(self, session_id: int):
        original = self.store.get(session_id)
        async with self.user_lock(original.user_id):
            session = self.store.get(session_id)
            if session.phase == "published":
                return
            if session.phase not in ("review","publishing") or not session.names or not session.bios:
                raise UserError("Complete the names and bio steps before publishing.")
            channel = self.get_channel(session.channel_id)
            session = self.store.update(session.id, phase="publishing")
            try:
                sha = await self.publisher.publish(session, lambda commit: self.store.update(session.id, commit_sha=commit))
            except EndpointTaken as exc:
                session = self.store.update(session.id, phase="review")
                if channel:
                    await channel.send(str(exc))
                    await self.send_prompt(session)
                return
            except Exception as exc:
                LOG.error("Publish session %s failed (%s)", session.id, type(exc).__name__)
                current = self.store.get(session.id)
                # Keep uncertain commits locked against cancellation and edits. A retry
                # checks commit ancestry before attempting a second publication.
                session = self.store.update(session.id, phase="publishing" if current.commit_sha else "review")
                if channel:
                    await channel.send("Publishing couldn't finish. Your draft is saved. Please use the latest publish button to retry.")
                    await self.send_prompt(session)
                return
            session = self.store.update(session.id, phase="published", commit_sha=sha, prompt_id=None)
            if channel:
                if original.prompt_id:
                    await self.clear_buttons(channel, original.prompt_id)
                await channel.send(f"Your page has been committed: <{self.site}/{session.endpoint}>\nGitHub Pages is deploying it. I'll check when it is available.")
                self.task(self.wait_for_site(session))
            LOG.info("Published /%s in commit %s", session.endpoint, sha[:12])

    async def wait_for_site(self, session: Session):
        expected = "\n".join(session.names)
        channel = self.get_channel(session.channel_id)
        try:
            for _ in range(20):
                try:
                    async with self.http_session.get(f"{self.site}/{session.endpoint}/settings/names.txt?commit={session.commit_sha}", timeout=aiohttp.ClientTimeout(total=12)) as response:
                        if response.status == 200 and (await response.text()).strip() == expected:
                            if channel:
                                await channel.send(f"Your bio page is live: <{self.site}/{session.endpoint}>")
                            return
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
                await asyncio.sleep(15)
            if channel:
                await channel.send(f"Your page is committed, but the website is still deploying. Try <{self.site}/{session.endpoint}> shortly.")
        except Exception:
            LOG.exception("Website availability check failed for session %s", session.id)

    async def recover(self):
        try:
            guild = self.get_guild(self.guild_id)
            if not guild:
                LOG.error("Configured guild is unavailable. Invite this bot to guild %s.", self.guild_id)
                return
            await self.get_category(guild)
            for session in self.store.active():
                try:
                    channel = self.get_channel(session.channel_id) if session.channel_id else None
                    if session.phase == "creating":
                        channel = next((c for c in guild.text_channels if (c.topic or "").startswith(f"onimai-bot session:{session.id} |")), None)
                        if channel:
                            session = self.store.update(session.id, phase="names", channel_id=channel.id)
                        else:
                            self.store.cancel(session.id)
                            continue
                    if session.phase == "publishing":
                        await self.publish_session(session.id)
                        continue
                    if channel is None:
                        self.store.cancel(session.id)
                        continue
                    if session.phase in ("names","bio"):
                        after = discord.Object(id=session.last_message_id or session.prompt_id) if session.last_message_id or session.prompt_id else discord.utils.parse_time(session.created_at)
                        async for message in channel.history(limit=100, after=after, oldest_first=True):
                            current = self.store.get(session.id)
                            if current.phase not in ("names","bio"):
                                break
                            if message.author.id == current.user_id and not message.author.bot and message.content:
                                try:
                                    await self.accept_text(current.id, current.user_id, current.phase, message.content, message.id)
                                except UserError:
                                    pass
                    session = self.store.get(session.id)
                    if session.prompt_id:
                        try:
                            await channel.fetch_message(session.prompt_id)
                            continue
                        except discord.NotFound:
                            pass
                    await self.send_prompt(session)
                except Exception:
                    LOG.exception("Recovery failed for session %s", session.id)
            LOG.info("Wizard recovery complete; %s active session(s)", len(self.store.active()))
        except Exception:
            LOG.exception("Could not initialize creation category")
        finally:
            self.recovered.set()

    async def on_guild_channel_delete(self, channel):
        session = self.store.for_channel(channel.id)
        if session:
            self.store.cancel(session.id)

    async def close(self):
        for task in tuple(self.background_tasks):
            task.cancel()
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
        await super().close()
        if hasattr(self, "http_session"):
            await self.http_session.close()
        self.store.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    discord.utils.setup_logging(level=logging.INFO, root=False)
    bot = BioBot()
    try:
        bot.run(required("DISCORD_TOKEN"), log_handler=None)
    except discord.PrivilegedIntentsRequired:
        LOG.error("Enable Message Content Intent in the Discord Developer Portal, or set MESSAGE_CONTENT_ENABLED=false to use input buttons.")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
