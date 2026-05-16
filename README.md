> **Note:** This project is no longer maintained and is provided as-is.

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
Create a `download.json` file in the same directory as the script. The file should follow this structure:

```json
{
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
| `show-url` | string | URL of the podcast RSS feed |
| `download-path` | string | Local directory where episodes will be saved |
| `title-as-filename` | integer | `1` = use episode title as filename, `0` = use original filename from URL |

## Usage
```bash
python pod-downloader.py
```
