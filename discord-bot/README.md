# Onimai Discord page creator

One slash command, with just one parameter:

```text
/create endpoint:pollo
```

The bot privately replies with a link to `create-<number>-<Discord user ID>` under **Create**. It asks for names/aliases (one per line), then bios (a blank line between rotating bios). Both prompts include a cropped reference image from the profile template and an input button. The review has **Publish page**, **Edit names**, **Edit bio**, and **Cancel** buttons.

Publishing copies the current `example/` profile to `<endpoint>/` and commits all its files to `main` atomically. GitHub Pages serves `https://onimai.site/<endpoint>`. The bot checks the deployed text before announcing that the page is live. Names and bios rotate independently. The default avatar and background are retained. Badges and connections start empty; the owner can add badges by editing `<endpoint>/settings/badges.txt`.

Each Discord user ID can have **three pages total**, across servers, and one unfinished wizard at a time. Drafts reserve a slot; cancelling an unpublished draft releases it. Published pages keep counting even if their channel is deleted. Numbers are global, monotonically increasing wizard numbers, starting at 1; cancelled drafts can leave gaps. Existing manually created pages such as `jvbj/` are protected and do not count toward the bot's three-page allowance.

## Raspberry Pi service

The deployed service runs as the dedicated `onimai-bot` account:

```sh
sudo systemctl status onimai-bot
sudo journalctl -u onimai-bot -n 50 --no-pager
sudo systemctl restart onimai-bot
```

Code: `/opt/onimai-bot`. Secrets/configuration: `/etc/onimai-bot/environment` (root only). Session database: `/var/lib/onimai-bot/pages.sqlite3`. The service starts on boot and restarts after failures. Back up the database with SQLite's backup API; retain it during updates so page limits and ownership survive.

For a new installation, use Python 3.10+, create a virtual environment, install `requirements.txt`, and configure the environment using `.env.example`. `bot.py` reads process environment variables, not `.env` automatically. Create the service account, install `onimai-bot.service`, then enable it with `sudo systemctl enable --now onimai-bot`.

The bot needs **Manage Channels**, **View Channels**, **Send Messages**, **Read Message History**, **Embed Links**, and **Attach Files**, plus the `bot` and `applications.commands` invite scopes. Enable **Message Content Intent** in its Discord Developer Portal to accept typed replies. The supplied application already had it enabled during deployment. If disabled later, set `MESSAGE_CONTENT_ENABLED=false`; the **Enter names** and **Enter bio** modal buttons still work. The bot deliberately requests no member/presence intents.

`DISCORD_GUILD_ID` limits the command to the intended server. `Create` is made automatically if it does not exist. Creation channels explicitly hide themselves from `@everyone`; only their creator, the bot, and Discord administrators can see them. Completed channels stay available as transcripts. Move them out of **Create** when it approaches Discord's 50-channel category limit.

The GitHub token needs repository **Contents: read/write** for `bsoding/onimai.site`. It is sent only to `api.github.com`; it is never placed in a page, commit, or channel. Endpoint validation, a fresh repository check before publishing, non-forced branch updates, and SQLite reservations prevent path traversal, overwrites, and concurrent quota bypasses. A commit is recorded before moving the Git branch; retries/restarts check its ancestry before publishing again. Wizard buttons and saved replies continue working after bot restarts.

## Verification

```sh
python -m unittest discover -s tests -v
```

Tests cover quotas across restarts/users, concurrent reservations, cancelled drafts, endpoint collisions and traversal, safe HTML/script text, wizard transitions and ownership, atomic publishing, commit recovery, and retries when `main` advances. The live deployment checks bot login, guild command registration, permissions, category creation, service ownership, restart persistence, and installed file checksums. A real user's `/create` interaction must be tested in Discord; the bot token cannot impersonate a user to invoke a slash command.
