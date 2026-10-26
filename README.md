# Pod Downloader
A Python script that downloads podcast episodes from RSS feeds into one folder per show. Run it again any time: episodes you already have are skipped, so only new ones are downloaded.

## Quick start
1. Install Python 3 and the `requests` library:
   ```bash
   pip install requests
   ```
2. Copy `config.json.example` to `config.json`, then set each show's feed URL and folder.
3. Check what it would download, without downloading anything:
   ```bash
   python pod-downloader.py --dry-run
   ```
4. Download:
   ```bash
   python pod-downloader.py
   ```

It reads every feed first, with a line like `◌ Reading feeds 3/10 · linux unplugged` so you can see how far it's got, and shows what it's about to download, by show, then downloads, counting as it goes so you can see how many are done and how many are left:

```
⇣ 512 episodes to download
  ├─ Linux Matters   53 ep
  ├─ Ask The Hosts   41 ep
  └─ Self-Hosted      9 ep  · no new episode since 2025-05-30

[  1/512 · 511 left] Linux Matters › LMP84.mp3
                     ✔ Linux Matters › LMP84.mp3 · 34.0 MB
[  2/512 · 510 left] Ask The Hosts › Ask The Hosts – Episode 31.mp3
```

In a terminal the output is in colour: finished episodes green, warnings yellow and failures red. Set the `NO_COLOR` environment variable to turn colour off. The log file is always plain text.

Stop it any time with Ctrl+C. Downloads in progress stop straight away, and the next run carries on where it stopped. Each run ends with a summary of what's new, by show, using each feed's own title:

```
✔ 10 of 10 downloaded · 30.0 MB
  ├─ 2.5 Admins   9 ep  27.0 MB
  └─ Coder Radio  1 ep   3.0 MB
```

`✔` means everything worked. `⚠` means something failed, and the shows with failures are marked `✖`.

## Commands
| Command | What it does |
|---|---|
| `python pod-downloader.py` | Download every episode that's missing, for every enabled show |
| `--dry-run` | List what would be downloaded. Downloads, creates and logs nothing |
| `--show NAME` | Only this show, by its folder name or part of it, for example `--show 2.5admins` or `--show unplugged`. Can be given more than once. Runs the show even if it's disabled or inactive |
| `--check` | Compare each show's folder with its feed, without changing anything. See [Checking your library](#checking-your-library) |
| `--redownload` | Download every episode again, overwriting existing files |
| `--debug` | Show extra details for this run, like the `debug` setting |

Options can be combined, for example `python pod-downloader.py --show 2.5admins --dry-run`.

## Configuration
`config.json` has settings for all shows at the top, then a list of shows:

```json
{
  "show-progressbar": 1,
  "hide-skipped": 1,
  "timeout": 60,
  "temp-path": "",
  "retries": 3,
  "oldest-first": 0,
  "random-show": 1,
  "max-speed": 0,
  "skip-inactive-days": 90,
  "log-file": "podfetch.log",
  "notify": [
    { "type": "discord", "url": "https://discord.com/api/webhooks/..." }
  ],
  "notify-when": "changes",
  "podcast-folder": "/podcast",
  "shows": [
    {
      "url": "https://2.5admins.com/feed/podcast/",
      "folder": "2.5admins",
      "title-as-filename": 1,
      "enabled": 1,
      "max-episodes": 0,
      "skip-episodes": []
    }
  ]
}
```

Episodes are saved in `podcast-folder` + each show's `folder`, so the example above saves 2.5 Admins episodes in `/podcast/2.5admins`. Only `podcast-folder` and `shows`, and in each show `url`, `folder` and `title-as-filename`, are required. Anything else that's missing uses its default. A misspelled setting name gets a warning, and other mistakes in the file get a message saying what to fix.

### Settings for all shows
| Field | Type | Description |
|---|---|---|
| `show-progressbar` | integer | `1` = show a download bar for each episode, with a `✔` line as each one finishes. It's off when `parallel` is above `1`, and when output goes to a file or scheduled task rather than a terminal. Default `0` |
| `hide-skipped` | integer | `1` = don't print a line for each episode that's already downloaded. Default `0` |
| `timeout` | integer | Seconds to wait for a server to connect or send data before giving up. Default `60` |
| `temp-path` | string | Folder for unfinished `.part` downloads. Anything left there is safe to delete. Empty or missing = `podfetch` folder in the OS temp directory |
| `retries` | integer | How many more times to try a download that timed out, dropped or got a server error (5xx), waiting 5 seconds between tries. Default `0` |
| `oldest-first` | integer | `1` = download each show in release order instead of newest first. Default `0` |
| `random-show` | integer | `1` = read every feed first, then take each next download from a random show, so one site doesn't get all the requests in a row. Each show's episodes keep their order. Default `0` = finish one show before starting the next |
| `parallel` | integer | How many episodes download at the same time. `2` or `3` is faster while staying gentle on the sites; more mostly hits the same few servers harder. Above `1` there's no progress bar; a `✔` line shows as each episode finishes instead, and a warning at the start says so if `show-progressbar` is on. Default `1` |
| `max-speed` | integer | Download speed limit in KB/s for each download, for example `5000` for about 5 MB/s. With `parallel`, the total can be that many times higher. Default `0` = no limit |
| `skip-inactive-days` | integer | Disable a show whose newest episode is older than this many days, as it has probably ended. `90` is about three months. The script first checks that you have every episode: if any are missing it downloads them, and only once the show is complete does it set `"enabled": 0` on it in `config.json`, so later runs don't check it again. Set it back to `1` to re-enable the show. `--show` still runs it, and `--dry-run` only says what it would disable. Default `0` = never disable |
| `debug` | integer | `1` = show extra details: each feed URL as it's read, where each episode is downloaded from and saved to, and how each notification was answered. Notification URLs are never shown, as they can hold secrets. Default `0` |
| `log-file` | string | Also write every message, with the time, to this file. A relative path is next to the script. Empty or missing = no log file |
| `notify` | list | Where to send a message after a run. See [Notifications](#notifications) |
| `notify-when` | string | `changes` = when anything downloaded or failed, `failures` = only when something failed, `always` = after every run. Default `changes` |
| `podcast-folder` | string | The folder all shows go in. Each show is saved in its `folder` inside it. The older name `download-path` still works here |

### Settings for each show
| Field | Type | Description |
|---|---|---|
| `url` | string | URL of the podcast RSS feed. The older name `show-url` still works |
| `folder` | string | The show's folder inside `podcast-folder`. It's also how `--show` finds the show |
| `title-as-filename` | integer | `1` = name files after the episode title, `0` = use the original filename from the URL |
| `enabled` | integer | Optional. `0` = skip this show without removing it from the config. Default `1` |
| `max-episodes` | integer | Optional. Only download the newest this many episodes. Default `0` = all |
| `skip-episodes` | list | Optional. Episodes never to download, by title or filename, for example `["2.5 Admins 100: Episode Title"]` or `["2.5 Admins 100 Episode Title.mp3"]`. Matches the whole title, ignoring case |
| `redownload` | integer | Optional. `1` = download every episode of this show again on each run, overwriting existing files. Default `0` |

## Notifications
After a run, the script can post a short report to Discord, Slack or Voidy: how many episodes downloaded and their total size, then one line per show with its episode count, size and any failures. For example:

```
podfetch: 10 new episodes (125.4 MB), 1 failed
• 2.5 Admins: 9 episodes (77.0 MB)
• Late Night Linux: 1 episode (48.4 MB), 1 failed
```

Add one entry to `notify` for each place to post:

```json
"notify": [
  { "type": "discord", "url": "https://discord.com/api/webhooks/..." },
  { "type": "slack", "url": "https://hooks.slack.com/services/..." },
  { "type": "voidy", "url": "https://voidy.example.com/api/webhooks/1/..." }
]
```

Each `url` is an incoming webhook URL from that service. In Voidy, an admin creates one under Admin → Rooms and retention → the room → Webhooks.

A Voidy bot works too. Use the bot's room URL and add its token, which is sent as an `Authorization: Bot …` header:

```json
{ "type": "voidy", "url": "https://voidy.example.com/api/bot/rooms/ROOM_ID/messages", "token": "vbot_..." }
```

Long reports are cut to fit each service's message limit. A dry run sends nothing. Keep tokens and webhook URLs in `config.json`, which git ignores, and never in `config.json.example`.

## Filenames
Characters that aren't allowed in Windows filenames are removed on every system, so names stay the same wherever you run it. For example, `2.5 Admins 214: No VLANs` is saved as `2.5 Admins 214 No VLANs.mp3`. Line breaks, trailing spaces and trailing dots are removed too.

When two episodes share a title, later ones are numbered, like `Bonus (2).mp3`. Long titles are shortened to fit filename and path limits. Downloaded files are dated by the episode's release date, so sorting by date matches release order.

## Checking your library
`--check` compares each show's folder with its feed and lists:
- **Misnamed**: an episode you have under an older or garbled name, for example with a trailing space before `.mp3` or `â€™` instead of `’`. The next run would download it again unless you rename the file to the name shown.
- **Possible duplicates**: a second copy of an episode next to the correctly named one.
- **Not in the feed**: files the feed doesn't list, such as episodes the show removed.

It also says how many episodes are missing. Nothing is changed, and the script never deletes episodes: many feeds only list recent episodes, so a file missing from the feed is usually still one you want.

## Running it on a schedule
The script exits with code `1` when any download or feed failed, and `0` otherwise, so Task Scheduler or cron can tell whether a run worked. With `log-file` set, you can see later what each run did.

## Tests
The tests use Python's built-in `unittest` and need no network access:

```bash
python -m unittest discover -s tests
```
