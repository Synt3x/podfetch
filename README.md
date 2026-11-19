# Pod Downloader
Downloads podcast episodes from RSS feeds into one folder per show. Run it any time: episodes you already have are skipped.

## Quick start
```bash
pip install requests
cp config.json.example config.json   # then set each show's feed URL and folder
python pod-downloader.py --dry-run   # see what it would download
python pod-downloader.py             # download
```

It reads every feed, lists what's new by show, then downloads with a running count:

```
⇣ 512 episodes to download
  ├─ Linux Matters   53 ep
  └─ Self-Hosted      9 ep  · no new episode since 2025-05-30

[  1/512 · 511 left] Linux Matters › LMP84.mp3
```

It ends with a summary: `✔` means everything worked, while `⚠` means something failed, and the shows that failed are marked `✖`. Ctrl+C stops it straight away, and the next run carries on from there. Set `NO_COLOR` to turn colour off.

## Commands
| Option | What it does |
|---|---|
| *(none)* | Download everything missing, for every enabled show |
| `--dry-run` | List what would be downloaded. Changes and logs nothing |
| `--show NAME` | Only this show, by folder name or part of it (`--show unplugged`). Repeatable. Runs it even if disabled |
| `--check` | Compare folders with feeds, changing nothing. See [Checking your library](#checking-your-library) |
| `--redownload` | Download every episode again, overwriting files |
| `--debug` | Extra details for this run |

Options combine, for example `--show 2.5admins --dry-run`.

## Configuration
`config.json` has global settings, then a list of shows. Only `podcast-folder`, `shows`, and each show's `url` and `folder` are required.

```json
{
  "podcast-folder": "/podcast",
  "filename-format": "{show} - {date} - {episode} - {title}",
  "shows": [
    { "url": "https://2.5admins.com/feed/podcast/", "folder": "2.5admins" }
  ]
}
```

This saves 2.5 Admins episodes in `/podcast/2.5admins`. You get a warning for a misspelled setting, and a message saying what to fix for any other mistake.

### Global settings
| Setting | Default | Description |
|---|---|---|
| `podcast-folder` | required | Folder all shows go in. Older name: `download-path` |
| `filename-format` | title as-is | How episodes are named. See [Filenames](#filenames) |
| `show-progressbar` | `0` | `1` = progress bar per episode (terminal only, and only when `parallel` is `1`) |
| `hide-skipped` | `0` | `1` = no line for episodes already downloaded |
| `timeout` | `60` | Seconds to wait for a server before giving up |
| `retries` | `0` | Extra tries after a timeout, dropped connection or 5xx error, 5 s apart |
| `temp-path` | OS temp | Folder for unfinished `.part` files. Safe to clear |
| `oldest-first` | `0` | `1` = download in release order instead of newest first |
| `random-show` | `0` | `1` = take each download from a random show, so one site doesn't get every request in a row |
| `parallel` | `1` | Downloads at the same time. `2`–`3` is a good limit |
| `max-speed` | `0` | KB/s limit per download. `0` = no limit |
| `skip-inactive-days` | `0` | Disable a show whose newest episode is older than this. Missing episodes are downloaded first, then `"enabled": 0` is written to `config.json`. Set it back to `1` to re-enable |
| `skip-deleted` | `0` | `1` = don't download an episode again after you delete it |
| `debug` | `0` | `1` = show feed URLs, download paths and notification replies (never notification URLs) |
| `log-file` | none | Also write every message, with the time, to this file. Relative to the script |
| `notify` | none | Where to post a report. See [Notifications](#notifications) |
| `notify-when` | `changes` | `changes`, `failures` or `always` |

### Show settings
| Setting | Default | Description |
|---|---|---|
| `url` | required | Feed URL, or a list of feeds read as one show. A feed can be a local file such as `"feeds/old.xml"`, relative to `config.json` (`feeds/` is gitignored), or an [archive.org](https://web.archive.org) copy with older episodes: put `id_` after the date to get the raw feed, like `http://web.archive.org/web/20190607030207id_/https://…/feed/`. Older name: `show-url` |
| `folder` | required | Folder inside `podcast-folder`, and what `--show` matches |
| `name` | feed title | Show name in filenames and messages |
| `filename-format` | global | Format for this show only |
| `title-as-filename` | `1` | Without a format: `1` = use the episode title, `0` = use the URL's filename |
| `enabled` | `1` | `0` = skip this show |
| `max-episodes` | `0` | Only the newest this many. `0` = all |
| `skip-episodes` | `[]` | Titles or filenames never to download (whole match, ignoring case) |
| `redownload` | `0` | `1` = download every episode again on each run |

## Notifications
After a run, a short report can go to Discord, Slack or Voidy:

```
podfetch: 10 new episodes (125.4 MB), 1 failed
• 2.5 Admins: 9 episodes (77.0 MB)
• Late Night Linux: 1 episode (48.4 MB), 1 failed
```

```json
"notify": [
  { "type": "discord", "url": "https://discord.com/api/webhooks/..." },
  { "type": "slack",   "url": "https://hooks.slack.com/services/..." },
  { "type": "voidy",   "url": "https://voidy.example.com/api/webhooks/1/..." },
  { "type": "voidy",   "url": "https://voidy.example.com/api/bot/rooms/ROOM_ID/messages", "token": "vbot_..." }
]
```

Each `url` is an incoming webhook URL. In Voidy, an admin creates one under Admin → Rooms and retention → the room → Webhooks. For a Voidy bot, use its room URL plus `token` (sent as `Authorization: Bot …`). Long reports are cut to fit, and dry runs send nothing. Keep secrets in `config.json`, never in `config.json.example`.

## Filenames
With `"{show} - {date} - {episode} - {title}"`:

```
2.5 Admins - 2026-10-22 - 322 - Internet Defrigeration.mp3
Ubuntu Podcast - 2021-09-30 - S14E30 - Final Episode Recorded.mp3
Late Night Linux - 2026-10-20 - 408.mp3
```

| Part | What it is |
|---|---|
| `{show}` | The show's `name`, or the feed title |
| `{date}` | Release date, `2026-10-22` |
| `{episode}` | Number padded to 3 digits (`007`) or `S14E30`, from the feed's episode tag or the title (`214:`, `Episode 408`, `\| CR 57`) |
| `{title}` | Episode title without the show name and number at its start |

Empty parts are dropped along with their separator, and long titles are shortened. A format with an unknown part, or missing `{date}`, `{episode}` or `{title}`, stops the run. You get a `⚠` warning when a show's newest episode has no number but most others do.

Without a format, the title is used as-is (`2.5 Admins 214: No VLANs` → `2.5 Admins 214 No VLANs.mp3`). In every case, characters Windows doesn't allow are removed on all systems, duplicate names get `(2)`, and names fit path limits. Files are dated by release date, including the created date on Windows where the drive allows it.

### Renames, not re-downloads
Each show folder has a `.podfetch.json` mapping each episode's feed ID (`guid`) to its file. When you change `filename-format`, or a show edits a title, the next run renames the file instead of downloading it again:

```
↻ Renamed 2.5 Admins › 2.5 Admins 214 No VLANs.mp3 → 2.5 Admins - 2024-09-12 - 214 - No VLANs.mp3
```

Files from before `.podfetch.json` existed are found by their old name. Use `--dry-run` to preview renames. Deleting `.podfetch.json` is safe, as it's rebuilt.

## Checking your library
`--check` lists, per show:
- **Misnamed**: episodes under an old or garbled name (a trailing space, or `â€™` instead of `’`) that would download again unless renamed
- **Possible duplicates**: a second copy next to the correctly named file
- **Not in the feed**: files the feed doesn't list

It also counts missing episodes. It changes nothing, and podfetch never deletes episodes.

## Scheduling
The script exits with `1` if any feed or download failed and `0` otherwise, for Task Scheduler or cron. Set `log-file` to keep a record of each run.

## Tests
```bash
python -m unittest discover -s tests
```
No network needed.
