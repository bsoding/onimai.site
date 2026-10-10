# Bio page template

Static guns.lol default-layout replica for **https://onimai.site/jvbj/**. There is no build step. All paths are relative, so the folder also works on other GitHub Pages sites.

## Text settings

Edit the plain UTF-8 files in **`jvbj/settings/`**. They are fetched without the browser cache each time the page loads. After pushing changes, allow GitHub Pages to deploy, then refresh the profile. No HTML edits are needed for the name, bios, built-in badges, or connections.

### `settings/name.txt`

The first line becomes the display name, browser title, and default Discord card name:

```text
jvbj
```

### `settings/bios.txt`

Separate bios with a **blank line**. Consecutive nonblank lines belong to the same bio, and their line breaks are preserved on the page. The typewriter rotates through the bios in order. A blank file hides the bio.

```text
somewhere on the internet

a really long paragraph blah blah blah
blah blah blah
```

### `settings/badges.txt`

Put one badge name per line, in display order. **Leave the file completely blank for no badges.**

```text
developer
owner
premium
```

Available names: `developer`, `owner`, `premium`, `verified`, `staff`, `og`, `donor`, `booster`, `gift`, `bug`, `star`, `heart`, `image-host`. Names are case-insensitive; unknown names are ignored. These are local, cosmetic template badges, independent of any guns.lol account.

For a custom image, color, label, or link, add a definition to the `BADGES` list near the top of `index.html`, then put its `id` (or built-in `icon` name) in `settings/badges.txt`:

```js
{ id: "custom", image: "assets/badges/custom.png", label: "My badge", color: "#a78bfa" }
```

```text
developer
custom
premium
```

Custom badges support PNG, JPG, WEBP, SVG, and animated GIF. `label` supplies the hover and keyboard tooltip; an optional `url` makes the badge clickable. A blank badge file still hides every badge, including custom definitions.

### `settings/connections.txt`

Use `PLATFORM=value`, one connection per line. They appear in file order. Platform names are case-insensitive. Empty values and unknown platforms are ignored; a blank file removes all social links.

```text
GITHUB=bsoding
YOUTUBE=jvbjvbj
```

Handles automatically become profile links. A leading `@` is optional. You can also supply a full HTTP/HTTPS URL, useful for channel IDs, Spotify artists, Discord invites, and custom destinations:

```text
INSTAGRAM=your.username
TWITCH=yourusername
TIKTOK=@yourusername
X=yourusername
TELEGRAM=yourusername
SPOTIFY=https://open.spotify.com/artist/your-artist-id
DISCORD=your.username
WEBSITE=onimai.site
EMAIL=you@example.com
```

Supported platforms: `GITHUB`, `YOUTUBE`, `INSTAGRAM`, `SPOTIFY`, `TWITCH`, `TIKTOK`, `X` / `TWITTER`, `TELEGRAM`, `DISCORD`, `WEBSITE`, `EMAIL` / `MAIL`. YouTube handles use `/@handle`; Spotify handles use `/user/handle`. Discord usernames are copied when clicked, numeric Discord user IDs open that profile, and full Discord invite URLs open the invite. Website values accept a domain or full URL. Email values create a mail link.

Blank lines and lines beginning with `#` are ignored in badges and connections. Windows line endings and UTF-8 BOMs are supported. If a settings file is missing or cannot be fetched, its HTML defaults are used; an existing empty file clears the corresponding section (an empty name uses the fallback name).

## Picture and background

- **Profile picture:** replace `assets/avatar.png`. Use the same filename, or change `PROFILE.avatar` near the top of `index.html` to another image inside `assets/`. PNG, JPG, WEBP, GIF, and SVG work.
- **Background video:** replace `assets/background.mp4`. MP4 with H.264 video is broadly supported. For WEBM, change `PROFILE.backgroundVideo` to `assets/background.webm`. Videos loop, fill the viewport, and begin after the visitor enters. Video audio uses the volume control too.
- **Image background / video fallback:** replace `assets/background.svg` or point `PROFILE.backgroundImage` to an image in `assets/`. Set `backgroundVideo: ""` for an image-only page. If the video is missing or unsupported, the fallback image remains visible.
- **Optional music:** add `assets/audio.mp3` and set `PROFILE.audio` to that path. The provided example video is silent. Music starts only after the visitor enters.

The included forest video and default avatar were created for this template. Replace them with your own media. After pushing replacements, allow GitHub Pages to finish deploying; an already open profile needs to be refreshed.

## Other settings

The `PROFILE` object near the top of `index.html` controls media paths, typewriter animation, optional location, accent, card transparency, particles, entry text, sound, and mouse tilt. Its name, bio, badge, and connection defaults are fallbacks for unavailable settings files.

The view count is a manually configured display value (`PROFILE.views`), not a global analytics service. Set it to `null` to hide it. GitHub Pages cannot maintain a server-side counter on its own.

The Discord card starts as a static, offline example. Edit its settings or set `discord.enabled: false` to hide it. For live presence, join the [Lanyard Discord server](https://discord.gg/lanyard), then put your Discord user ID in `discord.userId`. The page reads the [public Lanyard API](https://github.com/Phineas/lanyard) every 30 seconds while visible. If that service is unavailable, it keeps the configured fallback. `discord.username` and `discord.avatar` optionally override the live account's name and picture.

Keyboard entry, focusable tooltips, accessible audio controls, mobile layouts, and reduced-motion preferences are supported. The top-right button pauses the video and particles. Text names, bios, and labels are rendered as text, so special characters are safe.

## Preview

Serve the repository root locally, then open `/jvbj/`:

```sh
python3 -m http.server 8000
```

Opening `index.html` directly as a `file://` URL cannot fetch the settings files; use a web server or GitHub Pages.

## Reference research

Built after reviewing the official [profile showcase](https://assets.guns.lol/profile_showcase.png), [layout guide](https://help.guns.lol/premium-guides/layout-settings), [badge guide](https://help.guns.lol/how-to-guides/profile-badges), [customization guide](https://help.guns.lol/getting-started/customization), and public [guns.lol profile](https://guns.lol/guns.lol). The classic layout uses a centered glass card, 120px circular avatar, glowing name, compact badge pill, Discord card, glowing social icons, and a lower-left view counter. The template uses original local graphics and its own implementation.

Typography uses [Satoshi from Fontshare](https://www.fontshare.com/fonts/satoshi), with a system sans-serif fallback if the external font service is unavailable. Social icons depict the named services; badge and interface SVGs are inline in `profile.js`.

Social crawlers generally do not execute JavaScript. If you want customized link previews, also edit the static `<title>`, description, and Open Graph tags in `index.html`.
