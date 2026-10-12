"""Onimai's /create command and private, restart-safe page wizard."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import uuid
from pathlib import Path

import aiohttp
import discord
from discord import app_commands

from core import Store, Session, UserError, EndpointTaken, MEDIA_PHASES, CONNECTION_FIELDS, CONNECTION_GROUPS, CONNECTION_PHASES, validate_endpoint, parse_names, parse_bios, parse_connections, next_phase
from media import check_attachment, validate_media, upload_path, clean_uploads
from publisher import Publisher, GitHubError
from editing import load_profile
from profile_registry import write_registry

LOG = logging.getLogger("onimai")
ROOT = Path(__file__).resolve().parent
CANCEL_DELETE_DELAY = 15


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value == "replace_me":
        raise RuntimeError(f"Set {name} in the service environment.")
    return value


def preview_names(names: list[str]) -> str:
    value = discord.utils.escape_markdown("\n".join(names))
    # Discord counts UTF-16 units. Keep long emoji aliases inside its field limit.
    encoded = value.encode("utf-16-le")
    if len(encoded) > 2048:
        return encoded[:2046].decode("utf-16-le", errors="ignore") + "…"
    return value or "—"


def preview_connections(connections: dict) -> str:
    value = discord.utils.escape_markdown("\n".join(f"{label}: {connections[key]}" for key, label, _ in CONNECTION_FIELDS if connections.get(key)))
    encoded = value.encode("utf-16-le")
    if len(encoded) > 800:
        return encoded[:798].decode("utf-16-le", errors="ignore") + "…"
    return value or "No connections"


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
            await self.bot.accept_text(self.session_id, interaction.user.id, self.field, self.text.value, interaction.id)
            await interaction.edit_original_response(content="Saved. Continue in your creation channel.")
        except UserError as exc:
            await interaction.edit_original_response(content=str(exc))
        except Exception:
            LOG.exception("Modal save failed for session %s", self.session_id)
            await interaction.edit_original_response(content="Your draft is saved. Please try the input button again.")


class ConnectionsModal(discord.ui.Modal):
    def __init__(self, bot: BioBot, session: Session):
        page = CONNECTION_PHASES.index(session.phase)
        super().__init__(title=f"Connections {page + 1}/{len(CONNECTION_GROUPS)} · Optional", timeout=600)
        self.bot, self.session_id, self.phase = bot, session.id, session.phase
        self.inputs = {}
        for key, label, example in CONNECTION_GROUPS[page]:
            field = discord.ui.TextInput(
                custom_id=key, style=discord.TextStyle.short, placeholder=example,
                default=session.connections.get(key) or None, required=False, max_length=200,
            )
            self.inputs[key] = field
            self.add_item(discord.ui.Label(text=label, description="Leave blank for no connection.", component=field))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.accept_connections(self.session_id, interaction.user.id, self.phase, {key: field.value for key, field in self.inputs.items()}, interaction.id)
            await interaction.edit_original_response(content="Saved. Continue with the latest prompt in your creation channel.")
        except UserError as exc:
            await interaction.edit_original_response(content=str(exc))
        except Exception:
            LOG.exception("Connections save failed for session %s", self.session_id)
            await interaction.edit_original_response(content="Your draft is saved. Please try the connections button again.")


class PagePickerView(discord.ui.View):
    def __init__(self, bot: BioBot, user_id: int, pages: list[Session]):
        super().__init__(timeout=180)
        selector = discord.ui.Select(placeholder="Choose your page to edit", options=[discord.SelectOption(label=page.endpoint, value=page.endpoint) for page in pages])
        async def select(interaction):
            if interaction.user.id != user_id:
                await interaction.response.send_message("Only the page owner can choose a page.", ephemeral=True)
                return
            await bot.edit_page(interaction, selector.values[0])
        selector.callback = select
        self.add_item(selector)


class WizardView(discord.ui.View):
    def __init__(self, bot: BioBot, session: Session):
        super().__init__(timeout=None)
        self.bot, self.session_id = bot, session.id
        if session.phase in ("names", "bio"):
            self.button("Enter names" if session.phase == "names" else "Enter bio", session.phase, discord.ButtonStyle.primary)
        if session.phase in MEDIA_PHASES:
            self.button("Skip", "skip_" + session.phase, discord.ButtonStyle.secondary)
            if session.kind == 'edit':
                self.button("Remove music" if session.phase == 'music' else "Use site default", "reset_" + session.phase, discord.ButtonStyle.secondary)
        if session.phase in CONNECTION_PHASES:
            page = CONNECTION_PHASES.index(session.phase) + 1
            self.button(f"Enter connections {page}/{len(CONNECTION_GROUPS)}", session.phase, discord.ButtonStyle.primary)
            self.button("Skip remaining connections", "skip_" + session.phase, discord.ButtonStyle.secondary)
        if session.phase in ("review", "publishing"):
            self.button(("Submit changes" if session.kind == 'edit' else "Publish page") if session.phase == "review" else "Retry publish", "publish", discord.ButtonStyle.success)
        if session.phase == "review":
            self.button("Edit names", "edit_names", discord.ButtonStyle.secondary)
            self.button("Edit bio", "edit_bio", discord.ButtonStyle.secondary)
            for kind in MEDIA_PHASES:
                self.button("Edit " + kind, "edit_" + kind, discord.ButtonStyle.secondary)
            self.button("Edit connections", "edit_connections", discord.ButtonStyle.secondary)
        if session.phase in ("names", "bio", *MEDIA_PHASES, *CONNECTION_PHASES, "review"):
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
            if action in ("names", "bio", *CONNECTION_PHASES):
                if session.phase != action:
                    await interaction.response.send_message("Use the buttons on the latest prompt.", ephemeral=True)
                    return
                await interaction.response.send_modal(ConnectionsModal(self.bot, session) if action in CONNECTION_PHASES else TextModal(self.bot, session, action))
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                if action == "publish":
                    await self.bot.publish_session(session.id)
                    current = self.bot.store.get(session.id)
                    await interaction.edit_original_response(content="Your page was submitted. The website link is in this channel." if current.phase == "published" else "Check the latest message in this channel to retry.")
                elif action.startswith("reset_"):
                    await self.bot.skip_media(session.id, interaction.user.id, action.removeprefix("reset_"), interaction.id, reset=True)
                    await interaction.edit_original_response(content="Updated. Review your page before submitting the changes.")
                elif action.startswith("skip_"):
                    phase = action.removeprefix("skip_")
                    if phase in CONNECTION_PHASES:
                        await self.bot.skip_connections(session.id, interaction.user.id, phase, interaction.id)
                    else:
                        await self.bot.skip_media(session.id, interaction.user.id, phase, interaction.id)
                    await interaction.edit_original_response(content="Skipped. Continue with the latest prompt in this channel.")
                else:
                    async with self.bot.user_lock(session.user_id):
                        session = self.bot.store.get(session.id)
                        if session.phase not in ("names", "bio", *MEDIA_PHASES, *CONNECTION_PHASES, "review"):
                            raise UserError("This draft is being published or has already finished.")
                        if action == "cancel":
                            self.bot.store.cancel(session.id, delete_after=time.time() + CANCEL_DELETE_DELAY)
                            self.bot.task(self.bot.delete_cancelled_channel(session.id))
                            clean_uploads(self.bot.data_root, session)
                            await interaction.channel.send("Edit cancelled. Your published page is unchanged. This channel will be deleted in 15 seconds." if session.kind == 'edit' else "Draft cancelled. Your page slot is available again. This channel will be deleted in 15 seconds.", allowed_mentions=discord.AllowedMentions.none())
                            if session.prompt_id:
                                await self.bot.clear_buttons(interaction.channel, session.prompt_id)
                            await interaction.edit_original_response(content="Edit cancelled. Your published page is unchanged. This channel will be deleted in 15 seconds." if session.kind == 'edit' else "Cancelled. This channel will be deleted in 15 seconds. You can use /create for a new endpoint.")
                        else:
                            field = action.removeprefix("edit_")
                            if field not in ("names", "bio", *MEDIA_PHASES, "connections"):
                                raise UserError("Use the latest prompt's buttons.")
                            if session.prompt_id:
                                await self.bot.clear_buttons(interaction.channel, session.prompt_id)
                            session = self.bot.store.update(session.id, phase=CONNECTION_PHASES[0] if field == "connections" else field, prompt_id=None, last_message_id=interaction.id)
                            await self.bot.send_prompt(session)
                            await interaction.edit_original_response(content="Continue with the latest prompt in this channel.")
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
        database_path = Path(os.environ.get("DATABASE_PATH", str(ROOT / "data/pages.sqlite3")))
        self.data_root = database_path.resolve().parent
        self.store = Store(database_path)
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

        @self.tree.command(name="edit", description="Edit one of your published onimai.site pages.")
        @app_commands.guild_only()
        @app_commands.describe(endpoint="Your existing page username; leave blank to choose a page")
        async def edit(interaction: discord.Interaction, endpoint: str | None = None):
            await self.edit_page(interaction, endpoint)

        @edit.autocomplete('endpoint')
        async def edit_autocomplete(interaction, current):
            return [app_commands.Choice(name=page.endpoint, value=page.endpoint) for page in self.store.pages_for_user(interaction.user.id) if current.lower() in page.endpoint][:25]

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
        self.publisher = Publisher(self.http_session, required("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY", "bsoding/onimai.site"), os.environ.get("GITHUB_BRANCH", "main"), self.data_root)
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
            if os.environ.get('PROFILE_REGISTRY'):
                self.task(self.sync_profile_registry())

    async def sync_profile_registry(self):
        while True:
            try:
                _, _, tree = await self.publisher.snapshot()
                write_registry(os.environ['PROFILE_REGISTRY'], tree)
            except Exception:
                LOG.exception("Could not refresh the known profile registry")
            await asyncio.sleep(300)

    async def edit_page(self, interaction: discord.Interaction, endpoint: str | None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        session = None
        channel = None
        try:
            if interaction.guild_id != self.guild_id:
                raise UserError("Use /edit in the Onimai server.")
            await asyncio.wait_for(self.recovered.wait(), timeout=25)
            async with self.user_lock(interaction.user.id):
                active = self.store.active_for_user(interaction.user.id)
                if active:
                    active_channel = self.get_channel(active.channel_id) if active.channel_id else None
                    if active.phase == 'creating' and not active.channel_id:
                        channels = await interaction.guild.fetch_channels()
                        active_channel = next((item for item in channels if isinstance(item, discord.TextChannel) and (item.topic or '').startswith(f'onimai-bot session:{active.id} |')), None)
                        if active_channel:
                            active = self.store.update(active.id, channel_id=active_channel.id, phase='review' if active.kind == 'edit' else 'names')
                    if active.channel_id and active_channel is None:
                        try:
                            active_channel = await self.fetch_channel(active.channel_id)
                        except discord.NotFound:
                            pass
                    if active_channel:
                        if not active.prompt_id:
                            await self.send_prompt(active, active_channel)
                        await interaction.edit_original_response(content=f"Continue your current draft in {active_channel.mention}. Finish or cancel it before opening another.")
                        return
                    if active.phase == 'publishing':
                        raise UserError("Your previous submission is still being published. Please try again shortly.")
                    self.store.cancel(active.id)
                    clean_uploads(self.data_root, active)
                pages = self.store.pages_for_user(interaction.user.id)
                if not pages:
                    raise UserError("You don't have a published page to edit yet. Use /create first.")
                if endpoint is None and len(pages) > 1:
                    await interaction.edit_original_response(content="Choose which page to edit.", view=PagePickerView(self, interaction.user.id, pages))
                    return
                endpoint = validate_endpoint(endpoint) if endpoint is not None else pages[0].endpoint
                page = next((page for page in pages if page.endpoint == endpoint), None)
                if not page:
                    raise UserError("You can only edit pages created by your Discord account.")
                values = await load_profile(self.publisher, page)
                category = await self.get_category(interaction.guild)
                if len(category.channels) >= 50:
                    raise UserError("The Create category is full. Ask the owner to move completed channels.")
                session = self.store.start_edit(page.id, interaction.user.id, interaction.guild_id, values)
                overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False), interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, embed_links=True, attach_files=True, manage_channels=True), interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)}
                channel = await interaction.guild.create_text_channel(f"edit-{session.id}-{session.user_id}", category=category, overwrites=overwrites, topic=f"onimai-bot session:{session.id} | {self.site}/{endpoint}", reason="Onimai /edit private profile editor")
                session = self.store.update(session.id, phase='review', channel_id=channel.id)
                await self.send_prompt(session, channel)
                await interaction.edit_original_response(content=f"Edit your page in {channel.mention}.", view=None)
        except UserError as exc:
            await interaction.edit_original_response(content=str(exc))
        except discord.Forbidden:
            if session and not channel:
                self.store.cancel(session.id)
            await interaction.edit_original_response(content="I need channel and message permissions to open the editor. Your published page is unchanged.")
        except Exception:
            LOG.exception("Could not open the profile editor")
            await interaction.edit_original_response(content="I couldn't open the editor. Your published page is unchanged; try /edit again shortly.")

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
                    active_channel = self.get_channel(active.channel_id) if active.channel_id else None
                    if active.phase == "creating" and not active.channel_id:
                        channels = await interaction.guild.fetch_channels()
                        recovered_channel = next((c for c in channels if isinstance(c, discord.TextChannel) and (c.topic or "").startswith(f"onimai-bot session:{active.id} |")), None)
                        if recovered_channel:
                            active = self.store.update(active.id, phase="names", channel_id=recovered_channel.id)
                            active_channel = recovered_channel
                            await self.send_prompt(active, active_channel)
                    if active.channel_id and active_channel is None:
                        try:
                            active_channel = await self.fetch_channel(active.channel_id)
                        except discord.NotFound:
                            pass
                    if active_channel:
                        if not active.prompt_id:
                            await self.send_prompt(active, active_channel)
                        await interaction.edit_original_response(content=f"Continue your current page in <#{active.channel_id}>. Finish or cancel it before starting another.")
                        return
                    if active.phase == "publishing":
                        raise UserError("Your previous page is still being published. Please try again shortly.")
                    self.store.cancel(active.id)
                    clean_uploads(self.data_root, active)
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
                await self.send_prompt(session, channel)
                await interaction.edit_original_response(content=f"Continue in {channel.mention}.")
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

    async def delete_cancelled_channel(self, session_id: int):
        session = self.store.get(session_id)
        if not session or session.phase != "cancelled" or session.delete_after is None:
            return
        await asyncio.sleep(max(0, session.delete_after - time.time()))
        async with self.user_lock(session.user_id):
            session = self.store.get(session_id)
            if not session or session.phase != "cancelled" or session.delete_after is None or session.channel_id is None:
                return
            try:
                channel = self.get_channel(session.channel_id) or await self.fetch_channel(session.channel_id)
                await channel.delete(reason="Onimai page draft cancelled; 15-second grace period ended")
            except discord.NotFound:
                pass
            except discord.HTTPException:
                LOG.exception("Could not delete cancelled creation channel for session %s", session_id)
                return
            self.store.update(session_id, delete_after=None)

    async def send_prompt(self, session: Session, channel=None):
        channel = channel or self.get_channel(session.channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(session.channel_id)
            except discord.NotFound:
                raise UserError("The creation channel is unavailable.") from None
        view = WizardView(self, session)
        file = None
        if session.phase == "names":
            content = "Click **Enter names** to add your names/aliases (one per line)."
            embed = discord.Embed(title="Step 1 · Names / aliases", description="These names rotate in the highlighted name area. Enter 1–10 names, up to 80 characters each, using the button below.", color=0xA369B9)
            file = discord.File(ROOT / "assets/names.png", filename="names.png")
            embed.set_image(url="attachment://names.png")
        elif session.phase == "bio":
            content = "Click **Enter bio** to add your bio."
            embed = discord.Embed(title="Step 2 · Bio", description="This is the text beneath your names. Use the button below. For rotating bios, separate each with a blank line: up to 5 bios, 600 characters each and 1,800 total.", color=0xA369B9)
            file = discord.File(ROOT / "assets/bio.png", filename="bio.png")
            embed.set_image(url="attachment://bio.png")
        elif session.phase in MEDIA_PHASES:
            prompts = {
                "picture": ("Step 3 · Profile picture", "Please send your profile picture in this channel.", "Send one PNG, JPG, WEBP, GIF, or SVG image, up to 10 MB. Click **Skip** to keep the default picture."),
                "background": ("Step 4 · Profile background", "Please send your profile background in this channel.", "You can send a PNG, JPG, GIF, or MP4 in this channel, up to 25 MB. Click **Skip** to keep the default background."),
                "music": ("Step 5 · Profile music", "Please send your profile music as an MP3 in this channel.", "Send one MP3 music file, up to 25 MB. Music plays after visitors click to enter. Click **Skip** for no music."),
            }
            title, content, description = prompts[session.phase]
            if session.kind == 'edit':
                description = "Send the replacement file in this channel. Click **Skip** to keep the current file, or **Remove music** / **Use site default** to reset it."
            embed = discord.Embed(title=title, description=description, color=0xA369B9)
        elif session.phase in CONNECTION_PHASES:
            page = CONNECTION_PHASES.index(session.phase)
            content = f"Click **Enter connections {page + 1}/{len(CONNECTION_GROUPS)}** to add your connections. Leave blank for no connection."
            services = ", ".join(label for _, label, _ in CONNECTION_GROUPS[page])
            embed = discord.Embed(title=f"Step 6 · Connections {page + 1}/{len(CONNECTION_GROUPS)}", description=f"{services}\n\nEach field shows an example of the format. Leave blank for no connection. Click **Skip remaining connections** if you have no more to add.", color=0xA369B9)
        else:
            content = ("Choose any Edit button below, then click Submit changes. Your published page stays available while you edit." if session.kind == 'edit' else "Review your page, then click Publish page.") if session.phase == "review" else "Publishing is waiting for a retry. Your draft is saved."
            bio_preview = discord.utils.escape_markdown("\n\n".join(session.bios)) or "—"
            description = "Names and bios will rotate independently.\n\n**Bio**\n" + bio_preview
            embed = discord.Embed(title=f"onimai.site/{session.endpoint}", description=description, color=0xA369B9)
            embed.add_field(name="Names / aliases", value=preview_names(session.names), inline=False)
            for kind in MEDIA_PHASES:
                entry = session.media.get(kind)
                value = discord.utils.escape_markdown(entry["original_name"][:250]) if entry else "No music" if kind == "music" else "Site default"
                encoded = value.encode("utf-16-le")
                if len(encoded) > 400:
                    value = encoded[:398].decode("utf-16-le", errors="ignore") + "…"
                embed.add_field(name={"picture":"Profile picture", "background":"Background", "music":"Music"}[kind], value=value, inline=True)
            embed.add_field(name="Connections", value=preview_connections(session.connections), inline=False)
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
            if session.kind == 'edit':
                fields['changes'] = sorted(set(session.changes) | {field})
            if message_id:
                fields["last_message_id"] = message_id
            fields["phase"] = next_phase(values if field == "names" else session.names, values if field == "bio" else session.bios, session.media, session.connections)
            session = self.store.update(session.id, **fields)
            if old_prompt:
                await self.clear_buttons(self.get_channel(session.channel_id), old_prompt)
            await self.send_prompt(session)

    async def accept_connections(self, session_id: int, user_id: int, phase: str, values: dict[str, str], message_id: int):
        async with self.user_lock(user_id):
            session = self.store.get(session_id)
            if not session or session.user_id != user_id or session.phase != phase or phase not in CONNECTION_PHASES:
                raise UserError("Use the connections button on the latest prompt.")
            if session.last_message_id and message_id <= session.last_message_id:
                raise UserError("That popup is out of date. Use the latest connections button.")
            page = CONNECTION_PHASES.index(phase)
            keys = {key for key, _, _ in CONNECTION_GROUPS[page]}
            if not set(values) <= keys:
                raise UserError("Use the fields in the current connections popup.")
            connections = {**session.connections, **parse_connections({key: values.get(key, "") for key in keys})}
            following = CONNECTION_PHASES[page + 1] if page + 1 < len(CONNECTION_PHASES) else next_phase(session.names, session.bios, session.media, connections)
            current = self.store.update(session.id, connections=connections, phase=following, prompt_id=None, last_message_id=message_id, changes=sorted(set(session.changes) | {'connections'}) if session.kind == 'edit' else session.changes)
            if session.prompt_id:
                await self.clear_buttons(self.get_channel(session.channel_id), session.prompt_id)
            await self.send_prompt(current)

    async def skip_connections(self, session_id: int, user_id: int, phase: str, checkpoint: int):
        async with self.user_lock(user_id):
            session = self.store.get(session_id)
            if not session or session.user_id != user_id or session.phase != phase or phase not in CONNECTION_PHASES:
                raise UserError("Use the Skip button on the latest connections prompt.")
            remaining = CONNECTION_GROUPS[CONNECTION_PHASES.index(phase):]
            connections = {**session.connections, **{key: session.connections.get(key, "") for fields in remaining for key, _, _ in fields}}
            current = self.store.update(session.id, connections=connections, phase=next_phase(session.names, session.bios, session.media, connections), prompt_id=None, last_message_id=checkpoint)
            if session.prompt_id:
                await self.clear_buttons(self.get_channel(session.channel_id), session.prompt_id)
            await self.send_prompt(current)

    async def skip_media(self, session_id: int, user_id: int, kind: str, checkpoint: int, *, reset: bool = False):
        async with self.user_lock(user_id):
            session = self.store.get(session_id)
            if not session or session.user_id != user_id or session.phase != kind or kind not in MEDIA_PHASES:
                raise UserError("Use the Skip button on the latest upload prompt.")
            old_entry = session.media.get(kind)
            if reset and session.kind != 'edit':
                raise UserError("Use the current upload prompt's buttons.")
            keep = session.kind == 'edit' and not reset
            media = dict(session.media) if keep else {**session.media, kind:None}
            current = self.store.update(session.id, media=media, phase=next_phase(session.names, session.bios, media, session.connections), prompt_id=None, last_message_id=checkpoint, changes=sorted(set(session.changes) | {kind}) if reset else session.changes)
            if old_entry and old_entry.get('path') and not keep:
                upload_path(self.data_root, session.id, old_entry["path"]).unlink(missing_ok=True)
            if session.prompt_id:
                await self.clear_buttons(self.get_channel(session.channel_id), session.prompt_id)
            await self.send_prompt(current)

    async def accept_upload(self, session_id: int, user_id: int, kind: str, attachments: list, message_id: int):
        async with self.user_lock(user_id):
            session = self.store.get(session_id)
            if not session or session.user_id != user_id or session.phase != kind or kind not in MEDIA_PHASES:
                raise UserError("Send the file requested by the latest upload prompt.")
            if session.last_message_id and message_id <= session.last_message_id:
                return
            if len(attachments) != 1:
                raise UserError("Please send one file at a time in this channel, or click Skip.")
            attachment = attachments[0]
            extension = check_attachment(kind, attachment.filename, attachment.size)
            directory = self.data_root / "uploads" / str(session.id)
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            file_id = uuid.uuid4().hex
            temporary = directory / (file_id + ".part")
            destination = directory / (file_id + extension)
            saved = False
            try:
                await asyncio.wait_for(attachment.save(temporary), timeout=60)
                check_attachment(kind, attachment.filename, temporary.stat().st_size)
                await asyncio.to_thread(validate_media, temporary, kind, extension)
                temporary.replace(destination)
                entry = {
                    "path":destination.relative_to(self.data_root).as_posix(),
                    "filename":("profile" if kind == "picture" else "background_music" if kind == "music" else "background") + extension,
                    "original_name":attachment.filename,
                    "size":destination.stat().st_size,
                    "sha256":hashlib.sha256(destination.read_bytes()).hexdigest(),
                }
                media = {**session.media, kind:entry}
                current = self.store.update(session.id, media=media, phase=next_phase(session.names, session.bios, media, session.connections), prompt_id=None, last_message_id=message_id, changes=sorted(set(session.changes) | {kind}) if session.kind == 'edit' else session.changes)
                saved = True
                previous = session.media.get(kind)
                if previous and previous.get('path'):
                    upload_path(self.data_root, session.id, previous["path"]).unlink(missing_ok=True)
                if session.prompt_id:
                    await self.clear_buttons(self.get_channel(session.channel_id), session.prompt_id)
                await self.send_prompt(current)
            finally:
                temporary.unlink(missing_ok=True)
                if not saved:
                    destination.unlink(missing_ok=True)

    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or message.guild.id != self.guild_id:
            return
        session = self.store.for_channel(message.channel.id)
        if not session or message.author.id != session.user_id:
            return
        try:
            if session.phase in ("names", "bio"):
                await message.channel.send("Please click **Enter names**." if session.phase == "names" else "Please click **Enter bio**.")
                return
            if session.phase in CONNECTION_PHASES:
                await message.channel.send("Please click **Enter connections**. Leave blank in the popup for no connection.")
                return
            if session.phase not in MEDIA_PHASES:
                return
            await self.accept_upload(session.id, message.author.id, session.phase, message.attachments, message.id)
        except UserError as exc:
            await message.channel.send(str(exc))
        except Exception:
            LOG.exception("Upload save failed for session %s", session.id)
            await message.channel.send("Your draft is saved. Please try sending the file again for the latest upload prompt.")

    def save_media_blob(self, session_id: int, kind: str, sha: str):
        session = self.store.get(session_id)
        media = {**session.media, kind:{**session.media[kind], "blob_sha":sha}}
        self.store.update(session_id, media=media)

    async def publish_session(self, session_id: int):
        original = self.store.get(session_id)
        async with self.user_lock(original.user_id):
            session = self.store.get(session_id)
            if session.phase == "published":
                return
            if session.phase not in ("review","publishing") or not session.names or not session.bios:
                raise UserError("Complete the names and bio steps before publishing.")
            if session.phase == "review" and next_phase(session.names, session.bios, session.media, session.connections) != "review":
                raise UserError("Complete or skip the media and connections steps before submitting your page.")
            if session.kind == 'edit':
                parent = self.store.get(session.parent_id)
                if not parent or parent.user_id != session.user_id or parent.endpoint != session.endpoint or parent.phase != 'published' or parent.kind != 'create':
                    raise UserError("The original page ownership could not be verified.")
            channel = self.get_channel(session.channel_id)
            session = self.store.update(session.id, phase="publishing")
            try:
                sha = await self.publisher.publish(session, lambda commit: self.store.update(session.id, commit_sha=commit), lambda kind, blob: self.save_media_blob(session.id, kind, blob))
            except EndpointTaken as exc:
                session = self.store.update(session.id, phase="review")
                if channel:
                    await channel.send(str(exc))
                    await self.send_prompt(session)
                return
            except UserError as exc:
                current = self.store.get(session.id)
                session = self.store.update(session.id, phase='publishing' if current.commit_sha else 'review')
                if channel:
                    await channel.send(str(exc))
                    await self.send_prompt(session)
                return
            except Exception as exc:
                LOG.error("Publish session %s failed (%s%s)", session.id, type(exc).__name__, f", HTTP {exc.status}" if isinstance(exc, GitHubError) else "")
                current = self.store.get(session.id)
                # Keep uncertain commits locked against cancellation and edits. A retry
                # checks commit ancestry before attempting a second publication.
                session = self.store.update(session.id, phase="publishing" if current.commit_sha else "review")
                if channel:
                    if isinstance(exc, GitHubError) and exc.contents_write_denied:
                        await channel.send("Publishing is blocked by the bot's GitHub permissions. Ask the site owner to enable repository Contents: Read and write. Your draft is saved; retry after that is fixed.")
                    else:
                        await channel.send("Publishing couldn't finish. Your draft is saved. Please use the latest publish button to retry.")
                    await self.send_prompt(session)
                return
            session = self.store.finish_publish(session.id, sha)
            clean_uploads(self.data_root, session)
            if os.environ.get('PROFILE_REGISTRY'):
                try:
                    _, _, tree = await self.publisher.snapshot()
                    write_registry(os.environ['PROFILE_REGISTRY'], tree)
                except Exception:
                    LOG.exception("Could not refresh the profile registry after publication")
            if channel:
                if original.prompt_id:
                    await self.clear_buttons(channel, original.prompt_id)
                await channel.send(f"Your page has been submitted: <{self.site}/{session.endpoint}>\nA message will be sent here when it is published (est. ~1 min)")
                self.task(self.wait_for_site(session))
            LOG.info("Published /%s in commit %s", session.endpoint, sha[:12])

    async def wait_for_site(self, session: Session):
        expected = str(session.id)
        channel = self.get_channel(session.channel_id)
        try:
            for _ in range(20):
                try:
                    async with self.http_session.get(f"{self.site}/{session.endpoint}/settings/revision.txt?commit={session.commit_sha}", timeout=aiohttp.ClientTimeout(total=12)) as response:
                        if response.status == 200 and (await response.text()).strip() == expected:
                            if channel:
                                await channel.send(f"Your changes are published: <{self.site}/{session.endpoint}>" if session.kind == 'edit' else f"Your bio page is live: <{self.site}/{session.endpoint}>")
                            return
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
                await asyncio.sleep(15)
            if channel:
                await channel.send(f"Your page is submitted, but the website is still deploying. Try <{self.site}/{session.endpoint}> shortly.")
        except Exception:
            LOG.exception("Website availability check failed for session %s", session.id)

    async def recover(self):
        try:
            for session in self.store.pending_deletions():
                self.task(self.delete_cancelled_channel(session.id))
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
                            session = self.store.update(session.id, phase="review" if session.kind == 'edit' else "names", channel_id=channel.id)
                        else:
                            self.store.cancel(session.id)
                            continue
                    if session.phase == "publishing":
                        await self.publish_session(session.id)
                        continue
                    if channel is None:
                        if self.store.cancel(session.id):
                            clean_uploads(self.data_root, session)
                        continue
                    if session.phase in MEDIA_PHASES:
                        after_id = max(session.last_message_id or 0, session.prompt_id or 0)
                        after = discord.Object(id=after_id) if after_id else discord.utils.parse_time(session.created_at)
                        async for message in channel.history(limit=100, after=after, oldest_first=True):
                            current = self.store.get(session.id)
                            if current.phase not in MEDIA_PHASES:
                                break
                            if message.author.id == current.user_id and not message.author.bot and message.attachments:
                                try:
                                    await self.accept_upload(current.id, current.user_id, current.phase, message.attachments, message.id)
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
            async with self.user_lock(session.user_id):
                if self.store.cancel(session.id):
                    clean_uploads(self.data_root, session)

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
    bot = BioBot()
    try:
        bot.run(required("DISCORD_TOKEN"), log_handler=None)
    except discord.PrivilegedIntentsRequired:
        LOG.error("Enable Message Content Intent in the Discord Developer Portal, or set MESSAGE_CONTENT_ENABLED=false to use input buttons.")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
