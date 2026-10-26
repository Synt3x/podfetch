# Pod Downloader
A simple Python script that downloads podcast episodes from RSS feeds based on a JSON configuration file.

## Requirements
- Python 3
- `requests` library

Install dependencies with:

```bash
pip install requests
```

## Configuration
Copy `config.json.example` to `config.json` and edit it to list the shows you want. The file should follow this structure:

```json
{
  "show-progressbar": 1,
  "hide-skipped": 1,
  "timeout": 60,
  "temp-path": "",
  "retries": 3,
  "oldest-first": 0,
  "log-file": "",
  "shows": [
    {
      "show-url": "https://example.com/feed/podcast",
      "download-path": "/path/to/download/folder",
      "title-as-filename": 1,
      "enabled": 1,
      "max-episodes": 0
    }
  ]
}
```

### Settings for all shows
These go at the top level and are all optional. A missing setting uses its default.

| Field | Type | Description |
|---|---|---|
| `show-progressbar` | integer | `1` = show a download bar for each episode. It stays off when output goes to a file or scheduled task rather than a terminal. Default `0` |
| `hide-skipped` | integer | `1` = don't print a line for each episode that's already downloaded. Default `0` |
| `timeout` | integer | Seconds to wait for a server to connect or send data before giving up. Default `60` |
| `temp-path` | string | Folder for unfinished `.part` downloads. Anything left there is safe to delete. Empty or missing = `podfetch` folder in the OS temp directory |
| `retries` | integer | How many more times to try a download that timed out, dropped or got a server error (5xx), waiting 5 seconds between tries. Default `0` |
| `oldest-first` | integer | `1` = download in release order instead of newest first. Default `0` |
| `log-file` | string | Also write every message, with the time, to this file. A relative path is next to the script. Empty or missing = no log file |

### Settings for each show
| Field | Type | Description |
|---|---|---|
| `show-url` | string | URL of the podcast RSS feed |
| `download-path` | string | Local directory where episodes will be saved |
| `title-as-filename` | integer | `1` = use episode title as filename, `0` = use original filename from URL |
| `enabled` | integer | Optional. `0` = skip this show without removing it from the config. Default `1` |
| `max-episodes` | integer | Optional. Only download the newest this many episodes. Default `0` = all |
| `redownload` | integer | Optional. `1` = download every episode of this show again on each run, overwriting existing files. Default `0` |

## Usage
```bash
python pod-downloader.py
```

Episodes that are already downloaded are skipped. To download everything again for every show, overwriting existing files:

```bash
python pod-downloader.py --redownload
```

Each run ends with a summary such as `Done: 3 downloaded, 1 failed, 318 already downloaded`. Downloaded files are dated by the episode's release date. The script exits with code `1` when any download or feed failed, so a scheduled task can tell.

### Filenames
Characters that aren't allowed in Windows filenames are removed on every system, so names stay the same wherever you run it. When two episodes share a title, later ones are numbered, like `Bonus (2).mp3`. Long titles are shortened to fit filename and path limits.
