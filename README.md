# Pod Downloader
Downloads podcast episodes from RSS feeds into one folder per show. Run it any time: episodes you already have are skipped.

## Quick start
```bash
pip install requests
cp config.json.example config.json   # then set each show's feed URL and folder
python pod-downloader.py --dry-run   # see what it would download
python pod-downloader.py             # download
```
It lists what's new by show, downloads with a running count (`[ 1/512 · 511 left] Linux Matters › LMP84.mp3`), and ends with a summary: `✔` means everything worked, while `⚠` means something failed, and the shows that failed are marked `✖`. Ctrl+C stops it straight away, and the next run carries on from there. Set `NO_COLOR` to turn colour off. The exit code is `1` if any feed or download failed, for cron or Task Scheduler.

## Commands
| Option | What it does |
|---|---|
| `--dry-run` | List what would be downloaded. Changes and logs nothing |
| `--show NAME` | Only this show, by folder name or part of it (`--show unplugged`). Repeatable. Runs it even if disabled |
| `--check` | List misnamed files, possible duplicates and files not in the feed, and count missing episodes. Changes nothing |
| `--redownload` | Download every episode again, overwriting files |
| `--debug` | Extra details for this run |

## Configuration
`config.json` has global settings, then a `shows` list (see `config.json.example`). Only `podcast-folder`, `shows`, and each show's `url` and `folder` are required. You get a warning for a misspelled setting.

| Global setting | Default | Description |
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
| `skip-inactive-days` | `0` | Disable a show whose newest episode is older than this. Missing episodes are downloaded first, then `"enabled": 0` is written to `config.json` |
| `skip-deleted` | `0` | `1` = don't download an episode again after you delete it |
| `debug` | `0` | `1` = show feed URLs, download paths and notification replies (never notification URLs) |
| `log-file` | none | Also write every message, with the time, to this file. Relative to the script |
| `notify` | none | Where to post a report. See [Notifications](#notifications) |
| `notify-when` | `changes` | `changes`, `failures` or `always` |

| Show setting | Default | Description |
|---|---|---|
| `url` | required | Feed URL, or a list of feeds read as one show. A feed can be a local file (`"feeds/old.xml"`, relative to `config.json`) or an archive.org copy with older episodes (put `id_` after the date for the raw feed). Older name: `show-url` |
| `folder` | required | Folder inside `podcast-folder`, and what `--show` matches |
| `name` | feed title | Show name in filenames and messages |
| `filename-format` | global | Format for this show only |
| `title-as-filename` | `1` | Without a format: `1` = use the episode title, `0` = use the URL's filename |
| `enabled` | `1` | `0` = skip this show |
| `max-episodes` | `0` | Only the newest this many. `0` = all |
| `skip-episodes` | `[]` | Titles or filenames never to download (whole match, ignoring case) |
| `redownload` | `0` | `1` = download every episode again on each run |

## Notifications
After a run, a short report (episodes and size per show, plus failures) can go to Discord, Slack or Voidy. Add `{ "type": "discord", "url": "…" }` to `notify` for each place to post, where `type` is `discord`, `slack` or `voidy` and `url` is an incoming webhook URL. A Voidy admin creates one under Admin → Rooms and retention → the room → Webhooks. For a Voidy bot, use `…/api/bot/rooms/ROOM_ID/messages` plus `"token": "vbot_…"`. Long reports are cut to fit, and dry runs send nothing. Keep secrets in `config.json`, never in `config.json.example`.

## Filenames
`filename-format` combines `{show}` (the `name` or feed title), `{date}` (`2026-10-22`), `{episode}` (`007` or `S14E30`, from the feed or the title) and `{title}` (without the show name and number). `{show} - {date} - {episode} - {title}` gives `2.5 Admins - 2026-10-22 - 322 - Internet Defrigeration.mp3`.

Empty parts are dropped along with their separator, and long titles are shortened. A format with an unknown part, or missing `{date}`, `{episode}` or `{title}`, stops the run. You get a `⚠` warning when a show's newest episode has no number but most others do. In every case, characters Windows doesn't allow are removed, duplicate names get `(2)`, and files are dated by release date.

Each show folder has a `.podfetch.json` mapping each episode's feed ID (`guid`) to its file. So when you change the format, or a show edits a title, the file is renamed rather than downloaded again. Files from before `.podfetch.json` existed are found by their old name. Use `--dry-run` to preview renames. Deleting `.podfetch.json` is safe, as it's rebuilt. podfetch never deletes episodes.

## Tests
`python -m unittest discover -s tests` (no network needed).
