# Onimai Discord page creator

One slash command, with just one parameter:

```text
/create endpoint:pollo
```

The bot privately replies with the channel link to `create-<number>-<Discord user ID>` under **Create**. The opening reply contains no website URL. The wizard follows this order:

1. **Names / aliases:** click **Enter names** and enter one per line in the modal.
2. **Bio:** click **Enter bio** and separate rotating bios with a blank line in the modal.
3. **Profile picture:** send one PNG, JPG/JPEG, WEBP, GIF, or static SVG in the channel, up to 10 MB.
4. **Background:** send one PNG, JPG/JPEG, GIF, or MP4 in the channel, up to 25 MB.
5. **Music:** send one MP3 in the channel, up to 25 MB.
6. **Review:** publish, edit any field, or cancel.

Names and bios are accepted only through their buttons; ordinary channel messages never set them. Those two prompts retain their cropped reference images. Each media step has **Skip** to keep the default picture/background or use no music. Captions on attachments are ignored. Only the creator's uploads in the current step are accepted. Files with unsupported extensions, mismatched contents, or invalid media are rejected without advancing the wizard. Animated images retain their original bytes.

Publishing copies the current `example/` profile to `<endpoint>/` and commits all its files and uploaded media to `main` atomically. GitHub Pages serves `https://onimai.site/<endpoint>`. Image backgrounds disable the default video. MP4 backgrounds loop as video. Uploaded music is configured to play after the page's existing click-to-enter gesture. The bot checks the deployed text before announcing that the page is live. Names and bios rotate independently. Badges and connections start empty; the owner can add badges by editing `<endpoint>/settings/badges.txt`.

Each Discord user ID can have **three pages total**, across servers, and one unfinished wizard at a time. Drafts reserve a slot; cancelling an unpublished draft releases it immediately and deletes its creation channel after 15 seconds. Pending deletion timers survive bot restarts. Published pages keep counting even if their channel is deleted. Numbers are global, monotonically increasing wizard numbers, starting at 1; cancelled drafts can leave gaps. Existing manually created pages such as `jvbj/` are protected and do not count toward the bot's three-page allowance.

## Raspberry Pi service

The deployed service runs as the dedicated `onimai-bot` account:

```sh
sudo systemctl status onimai-bot
sudo journalctl -u onimai-bot -n 50 --no-pager
sudo systemctl restart onimai-bot
```

Code: `/opt/onimai-bot`. Secrets/configuration: `/etc/onimai-bot/environment` (root only). Session database: `/var/lib/onimai-bot/pages.sqlite3`. Draft media: `/var/lib/onimai-bot/uploads/<session number>/`. The service starts on boot and restarts after failures. Back up the database with SQLite's backup API and retain the uploads folder so unfinished wizards survive. Completed and cancelled drafts remove their local upload copies after publication/cancellation. The schema upgrade preserves existing page counts, endpoints and text; old unpublished reviews move to the picture step.

If publishing reports missing GitHub permissions, edit the exact fine-grained token installed as `GITHUB_TOKEN`: select `bsoding/onimai.site`, grant repository **Contents: Read and write**, and save. Editing a different token does not update the Pi's copy. A replacement token must be installed in `/etc/onimai-bot/environment`, followed by restarting `onimai-bot.service`. Drafts stay saved while access is unavailable. Permission errors include the HTTP status and request path in the service journal without logging credentials.

For a new installation, use Python 3.10+, create a virtual environment, install `requirements.txt`, and configure the environment using `.env.example`. `bot.py` reads process environment variables, not `.env` automatically. Install FFmpeg for its `ffprobe` media checker (`sudo apt install ffmpeg` on a Pi); it was already present on the deployed Pi. Create the service account, install `onimai-bot.service`, then enable it with `sudo systemctl enable --now onimai-bot`.

The bot needs **Manage Channels**, **View Channels**, **Send Messages**, **Read Message History**, **Embed Links**, and **Attach Files**, plus the `bot` and `applications.commands` invite scopes. Enable **Message Content Intent** in its Discord Developer Portal and retain `MESSAGE_CONTENT_ENABLED=true` so channel attachment metadata is available. The deployed application already has it enabled. Text is still accepted only through the modals. The bot deliberately requests no member/presence intents.

`DISCORD_GUILD_ID` limits the command to the intended server. `Create` is made automatically if it does not exist. Creation channels explicitly hide themselves from `@everyone`; only their creator, the bot, and Discord administrators can see them. Completed channels stay available as transcripts. Move them out of **Create** when it approaches Discord's 50-channel category limit.

The GitHub token needs repository **Contents: read/write** for `bsoding/onimai.site`. It is sent only to `api.github.com`; it is never placed in a page, commit, or channel. Uploads are stored privately under generated file names and published under canonical asset names. Image formats are verified; SVG scripts, entities and external resources are rejected. `ffprobe` validates MP3/MP4 media with a limited protocol list and a credential-free subprocess environment. Endpoint validation, a fresh repository check before publishing, non-forced branch updates, and SQLite reservations prevent path traversal, overwrites, and concurrent quota bypasses. A commit is recorded before moving the Git branch; retries/restarts check its ancestry before publishing again. Uploaded GitHub blobs are reused on retries. Wizard buttons and saved uploads continue working after bot restarts.

## Verification

```sh
python -m unittest discover -s tests -v
```

Tests cover quotas across restarts/users, legacy schema migration, concurrent reservations, cancelled drafts, endpoint collisions and traversal, safe HTML/script text, button-only names/bios, upload ordering/ownership/validation, saved media across restarts, page media settings, atomic publishing, commit recovery, and retries when `main` advances. Real MP3/MP4 probing tests run where `ffprobe` is installed (including the Pi). The live deployment checks bot login, guild command registration, service ownership, database integrity and installed file checksums. A real user's `/create` interaction must be tested in Discord; the bot token cannot impersonate a user to invoke a slash command.
