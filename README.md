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

Stop it any time with Ctrl+C; the next run carries on where it stopped. Each run ends with a summary such as `Done: 3 downloaded, 1 failed, 318 already downloaded`.

## Commands
| Command | What it does |
|---|---|
| `python pod-downloader.py` | Download every episode that's missing, for every enabled show |
| `--dry-run` | List what would be downloaded. Downloads, creates and logs nothing |
| `--show NAME` | Only this show, by its folder name or part of it, for example `--show 2.5admins` or `--show unplugged`. Can be given more than once. Runs the show even if it's disabled or inactive |
| `--check` | Compare each show's folder with its feed, without changing anything. See [Checking your library](#checking-your-library) |
| `--redownload` | Download every episode again, overwriting existing files |

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
  "shows": [
    {
      "show-url": "https://2.5admins.com/feed/podcast/",
      "download-path": "/podcast/2.5admins",
      "title-as-filename": 1,
      "enabled": 1,
      "max-episodes": 0,
      "skip-episodes": []
    }
  ]
}
```

Only `shows`, and in each show `show-url`, `download-path` and `title-as-filename`, are required. Anything else that's missing uses its default. A misspelled setting name gets a warning, and other mistakes in the file get a message saying what to fix.

### Settings for all shows
| Field | Type | Description |
|---|---|---|
| `show-progressbar` | integer | `1` = show a download bar for each episode. It stays off when output goes to a file or scheduled task rather than a terminal. Default `0` |
| `hide-skipped` | integer | `1` = don't print a line for each episode that's already downloaded. Default `0` |
| `timeout` | integer | Seconds to wait for a server to connect or send data before giving up. Default `60` |
| `temp-path` | string | Folder for unfinished `.part` downloads. Anything left there is safe to delete. Empty or missing = `podfetch` folder in the OS temp directory |
| `retries` | integer | How many more times to try a download that timed out, dropped or got a server error (5xx), waiting 5 seconds between tries. Default `0` |
| `oldest-first` | integer | `1` = download each show in release order instead of newest first. Default `0` |
| `random-show` | integer | `1` = read every feed first, then take each next download from a random show, so one site doesn't get all the requests in a row. Each show's episodes keep their order. Default `0` = finish one show before starting the next |
| `max-speed` | integer | Download speed limit in KB/s, for example `5000` for about 5 MB/s. Default `0` = no limit |
| `skip-inactive-days` | integer | Skip a show whose newest episode is older than this many days, as it has probably ended. `90` is about three months. `--show` still runs it. Default `0` = never skip |
| `log-file` | string | Also write every message, with the time, to this file. A relative path is next to the script. Empty or missing = no log file |
| `notify` | list | Where to send a message after a run. See [Notifications](#notifications) |
| `notify-when` | string | `changes` = when anything downloaded or failed, `failures` = only when something failed, `always` = after every run. Default `changes` |

### Settings for each show
| Field | Type | Description |
|---|---|---|
| `show-url` | string | URL of the podcast RSS feed |
| `download-path` | string | Folder where episodes are saved. Its name is also the show's name in messages and for `--show` |
| `title-as-filename` | integer | `1` = name files after the episode title, `0` = use the original filename from the URL |
| `enabled` | integer | Optional. `0` = skip this show without removing it from the config. Default `1` |
| `max-episodes` | integer | Optional. Only download the newest this many episodes. Default `0` = all |
| `skip-episodes` | list | Optional. Episodes never to download, by title or filename, for example `["2.5 Admins 100: Episode Title"]` or `["2.5 Admins 100 Episode Title.mp3"]`. Matches the whole title, ignoring case |
| `redownload` | integer | Optional. `1` = download every episode of this show again on each run, overwriting existing files. Default `0` |

## Notifications
After a run, the script can post a short report to Discord, Slack or Voidy: how many episodes downloaded, their titles and anything that failed. Add one entry to `notify` for each place to post:

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

It also says how many episodes are missing. Nothing is changed.

## Running it on a schedule
The script exits with code `1` when any download or feed failed, and `0` otherwise, so Task Scheduler or cron can tell whether a run worked. With `log-file` set, you can see later what each run did.

## Tests
The tests use Python's built-in `unittest` and need no network access:

```bash
python -m unittest discover -s tests
```
