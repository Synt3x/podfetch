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
  "shows": [
    {
      "show-url": "https://example.com/feed/podcast",
      "download-path": "/path/to/download/folder",
      "title-as-filename": 1
    }
  ]
}
```

### Configuration Options
| Field | Type | Description |
|---|---|---|
| `show-progressbar` | integer | Optional, top level (applies to all shows). `1` = show a download bar for each episode. Default `0` |
| `show-url` | string | URL of the podcast RSS feed |
| `download-path` | string | Local directory where episodes will be saved |
| `title-as-filename` | integer | `1` = use episode title as filename, `0` = use original filename from URL |
| `redownload` | integer | Optional. `1` = download every episode of this show again on each run, overwriting existing files. Default `0` |

## Usage
```bash
python pod-downloader.py
```

Episodes that are already downloaded are skipped. To download everything again for every show, overwriting existing files:

```bash
python pod-downloader.py --redownload
```
