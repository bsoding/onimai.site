# Copy this profile

Copy the entire `example/` folder to a new folder named after the user. From the repository root:

```sh
cp -R example yourusername
```

After committing and pushing, the profile is available at **https://onimai.site/yourusername/**. No build step is needed.

## Change the text

Edit the files inside the copied folder's `settings/` directory:

- `names.txt`: separate names with a blank line. Multiple names cycle through the typewriter.
- `bios.txt`: separate bios with a blank line. Names and bios animate independently.
- `badges.txt`: one badge name per line, such as `developer` or `premium`. It starts blank for no badges.
- `connections.txt`: fill in the platforms you want, such as `GITHUB=yourusername`. Every supported platform is listed; blank values stay hidden.

## Replace the media

- Replace `assets/profile.png` with the user's picture.
- Replace `assets/background.mp4` with the user's video. The included default is a small, silent forest loop.
- `assets/background.svg` is the poster and image fallback. `assets/avatar.svg` is the picture error fallback.
- Music starts disabled. Add `assets/background_music.mp3` and set `PROFILE.audio` near the top of `index.html` to `"assets/background_music.mp3"` to enable it after clicking to enter.

The default picture is neutral. Badges, connections, and Discord presence start hidden. The card layout, settings, styles, scripts, and default media are all included, so the copied folder works independently of `jvbj/`.

## Automatic membership date

The small **User since** line reads the oldest GitHub commit for the copied folder's `index.html`. Its path is detected from the page URL, so no username or date changes are needed in the code. It appears after the new folder has been committed and pushed; later edits do not reset the date.

The `jvbj` override in `PROFILE.membership.dates` only applies to a folder named `jvbj`. Copies under other names use their own GitHub history. If using another repository, update `PROFILE.membership.repository` and `branch` in `index.html`.

GitHub's public API requires no token. The date is cached in the visitor's browser. An unavailable or rate-limited lookup leaves the line hidden until a later visit can retrieve a real date.

For the full badge list and advanced options, see [the profile guide](../jvbj/README.md).
