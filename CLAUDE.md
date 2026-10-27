# podfetch

A single-file Python podcast downloader: `pod-downloader.py` reads RSS feeds listed in `config.json` and saves episodes into one folder per show. The README describes every setting and command; keep it up to date with any change.

## Working on it
- Run the tests after every change: `python -m unittest discover -s tests`. They need no network; `requests` is mocked with `FakeResponse`. Add or update tests with each change.
- The script's filename has a hyphen, so tests import it with importlib as `podfetch`.
- Match the existing style: camelCase names, a comment above each function saying what it does and why, user-facing messages in plain English.
- Commit and push finished work straight to `main`. No feature branches.
- `config.json` is the owner's real config. It's gitignored and holds a Voidy bot token: never commit it, never print notification URLs or tokens (not even in debug output), and back it up before any git branch switch or merge, as a switch once deleted it.
- `config.json.example` is the committed example; update it when adding a setting.
- `feeds/` (local feed files) is gitignored.

## Things that must not change by accident
- **Filenames.** Episodes already on disk are found by name, so changing how names are built would make every show download again or rename everything. The rules live in `tidyName`, `cleanName`, `splitTitle`, `renderName` and `formatName`. If a change alters names, check a `--dry-run` against the real library first and expect renames, never re-downloads.
- **`.podfetch.json`** in each show folder records feed episode ID (`guid`) → filename. It's how renamed or reformatted episodes are recognised. Keep it backward compatible.
- The script never deletes episodes. Only rename, download, or leave alone.

## How a run decides what to do with an episode
1. A file with the expected name exists → skip, and record it in `.podfetch.json`.
2. `.podfetch.json` lists the episode's ID under another name that exists → rename.
3. A file with the old title-or-URL name (`legacyFilename`) exists → rename.
4. Otherwise download; with `skip-deleted: 1`, an episode recorded earlier but now missing is skipped.

## The owner's setup
- Library: `Z:\` (`\\stormwind\audio\podcasts`, a Samba share), one folder per show. It keeps created dates set by `setFileDates`.
- `filename-format` is `{show} - {date} - {episode} - {title}`, for example `2.5 Admins - 2026-10-22 - 322 - Internet Defrigeration.mp3`.
- Ubuntu Podcast has ended; its `url` is a list of local files: `feeds/ubuntu-podcast-feed-<timestamp>.xml`, saved archive.org copies of the old feed (ubuntupodcast.org's feed now redirects to Linux Matters), plus `feeds/ubuntu-podcast-archive.xml`, built from the official archive.org uploads (`ubuntu-podcast-season-01` … `-08`) with dates from the old blog's post URLs. S07E00 has no known date; S06E30 never existed.
- Linux After Dark also reads an archive.org copy of its feed, for episode 0.
- Ask before deleting anything on `Z:\` or posting test notifications.
