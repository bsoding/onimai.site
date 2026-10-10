# Bio page template

Static guns.lol default-layout replica for **https://onimai.site/jvbj/**. There is no build step. All paths are relative, so the folder also works on other GitHub Pages sites.

## Your name, picture, and background

- **Name:** edit `assets/name.txt`. The first line becomes the display name, browser title, and default Discord card name. Keep the file as plain UTF-8 text. It is fetched without the browser cache.
- **Profile picture:** replace `assets/avatar.png`. Use the same filename, or change `PROFILE.avatar` near the top of `index.html` to another image inside `assets/`. PNG, JPG, WEBP, GIF, and SVG work.
- **Background video:** replace `assets/background.mp4`. MP4 with H.264 video is broadly supported. For WEBM, change `PROFILE.backgroundVideo` to `assets/background.webm`. Videos loop, fill the viewport, and begin after the visitor enters. Video audio uses the volume control too.
- **Image background / video fallback:** replace `assets/background.svg` or point `PROFILE.backgroundImage` to an image in `assets/`. Set `backgroundVideo: ""` for an image-only page. If the video is missing or unsupported, the fallback image remains visible.
- **Optional music:** add `assets/audio.mp3` and set `PROFILE.audio` to that path. The provided example video is silent. Music starts only after the visitor enters.

The included forest video and default avatar were created for this template. Replace them with your own media. After pushing replacements, allow GitHub Pages to finish deploying; an already open profile needs to be refreshed.

## Badges

Edit the `BADGES` array at the very top of `index.html`. Its order is the display order. These are local, cosmetic template badges, independent of any guns.lol account.

```js
const BADGES = [
  { icon: "premium", label: "Premium" },
  { icon: "verified", label: "Verified", color: "#a78bfa" },
  { image: "assets/badges/custom.png", label: "My badge" },
  { icon: "developer", label: "Developer", url: "https://github.com/your-name" },
];
```

Built-in badge icons: `premium`, `verified`, `staff`, `og`, `donor`, `booster`, `developer`, `gift`, `bug`, `star`, `heart`, `image-host`. Custom badges support PNG, JPG, WEBP, SVG, and animated GIF. `label` supplies the hover and keyboard tooltip. Set `hidden: true` to hide one, or use an empty array to remove them all.

## Other settings

The `PROFILE` object immediately below the badge list controls the bio, social links, optional location, accent, card transparency, particles, entry text, sound, and mouse tilt. Social links initially go to platform homepages; replace them with your own profile URLs. Custom social icons use the same `image` field as badges. Available social icons: `discord`, `github`, `spotify`, `youtube`, `instagram`, `globe`, `x`, `tiktok`, `twitch`, `telegram`, `mail`.

To make an icon copy your username instead of opening a URL:

```js
{ icon: "discord", label: "Discord", copy: "your.username" }
```

The view count is a manually configured display value (`PROFILE.views`), not a global analytics service. Set it to `null` to hide it. GitHub Pages cannot maintain a server-side counter on its own.

The Discord card starts as a static, offline example. Edit its settings or set `discord.enabled: false` to hide it. For live presence, join the [Lanyard Discord server](https://discord.gg/lanyard), then put your Discord user ID in `discord.userId`. The page reads the [public Lanyard API](https://github.com/Phineas/lanyard) every 30 seconds while visible. If that service is unavailable, it keeps the configured fallback. `discord.username` and `discord.avatar` optionally override the live account's name and picture.

Keyboard entry, focusable tooltips, accessible audio controls, mobile layouts, and reduced-motion preferences are supported. The top-right button pauses the video and particles. Text names, bios, and labels are rendered as text, so special characters are safe.

## Preview

Serve the repository root locally, then open `/jvbj/`:

```sh
python3 -m http.server 8000
```

Opening `index.html` directly as a `file://` URL cannot fetch `name.txt`; use a web server or GitHub Pages.

## Reference research

Built after reviewing the official [profile showcase](https://assets.guns.lol/profile_showcase.png), [layout guide](https://help.guns.lol/premium-guides/layout-settings), [badge guide](https://help.guns.lol/how-to-guides/profile-badges), [customization guide](https://help.guns.lol/getting-started/customization), and public [guns.lol profile](https://guns.lol/guns.lol). The classic layout uses a centered glass card, 120px circular avatar, glowing name, compact badge pill, Discord card, glowing social icons, and a lower-left view counter. The template uses original local graphics and its own implementation.

Typography uses [Satoshi from Fontshare](https://www.fontshare.com/fonts/satoshi), with a system sans-serif fallback if the external font service is unavailable. Social icons depict the named services; badge and interface SVGs are inline in `profile.js`.

Social crawlers generally do not execute JavaScript. If you want customized link previews, also edit the static `<title>`, description, and Open Graph tags in `index.html`.
