import requests
import os
import re
import email.utils
import json
import mimetypes
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as xmlreader
from urllib.parse import urlparse

# Characters not allowed in Windows filenames
invalidChars = ['<','>',':','"','/','\\','|','?','*']

# Folder this script lives in, so config.json is found wherever it's run from
scriptDir = os.path.dirname(os.path.abspath(__file__))

# Seconds to wait between retries of a failed download
retryDelay = 5

# Names Windows reserves for devices, which can't be used as filenames
reservedNames = {'CON', 'PRN', 'AUX', 'NUL'} | {'COM{0}'.format(i) for i in range(1, 10)} | {'LPT{0}'.format(i) for i in range(1, 10)}

# Longest filename (without extension) to keep; it's shortened further when the folder path is long
maxNameLength = 150

# Windows paths can't be longer than this
maxPathLength = 259

# Linux and macOS limit filenames to 255 bytes; accented characters and symbols take more than one.
# Leaves room for a " (99)" number and a ".xxxx" extension
maxNameBytes = 240

# Extensions for common podcast file types, used when the URL has none
typeExtensions = {
    'audio/mpeg': 'mp3', 'audio/mp3': 'mp3', 'audio/mp4': 'm4a', 'audio/x-m4a': 'm4a',
    'audio/aac': 'aac', 'audio/ogg': 'ogg', 'audio/opus': 'opus', 'video/mp4': 'mp4',
}

def getExtension(urlFilename, enclosureType):
    # Prefer the extension in the URL; otherwise go by the file type the feed declares
    if '.' in urlFilename:
        return urlFilename.rsplit('.',1)[-1]
    enclosureType = (enclosureType or '').split(';')[0].strip().lower()
    if enclosureType in typeExtensions:
        return typeExtensions[enclosureType]
    guessed = mimetypes.guess_extension(enclosureType) if enclosureType else None
    return guessed.lstrip('.') if guessed else ''

def cleanName(name, maxLength):
    # Turn line breaks, tabs and other control characters into spaces
    name = ''.join(' ' if ord(char) < 32 else char for char in name)

    # Remove invalid Windows characters from filename
    for char in invalidChars:
        name = name.replace(char,'')

    # Collapse any runs of spaces left behind
    name = re.sub(' {2,}', ' ', name)

    # Keep the name short enough for Windows, then drop trailing dots and spaces, which Windows doesn't allow
    name = name[:maxLength]
    while len(name.encode('utf-8')) > maxNameBytes:
        name = name[:-1]
    name = name.strip().rstrip('.').strip()

    # Avoid device names like CON or NUL, which Windows won't create as files
    if name.upper() in reservedNames:
        name = name + '_'
    return name

def log(message):
    # Print a message, and also add it to the log file with the time when one is set
    print(message)
    if logFile:
        try:
            with open(logFile, 'a', encoding='utf-8') as f:
                f.write('{0}  {1}\n'.format(time.strftime('%Y-%m-%d %H:%M:%S'), message))
        except OSError as e:
            print('Could not write to log file {0}: {1}'.format(logFile, e))

def printProgress(done, total):
    # Redraw the bar on the same line; without a known size, show MB downloaded only
    doneMb = done / (1024 * 1024)
    if total:
        width = 30
        filled = width * done // total
        bar = '#' * filled + '-' * (width - filled)
        print('\r  [{0}] {1:3d}%  {2:.1f} / {3:.1f} MB'.format(bar, 100 * done // total, doneMb, total / (1024 * 1024)), end='', flush=True)
    else:
        print('\r  {0:.1f} MB'.format(doneMb), end='', flush=True)

def downloadEpisode(episodeUrl, filename, filepath, releaseTime):
    # Returns True once the episode is saved, False if it failed

    # Save to a .part file first, then move it into place once complete
    os.makedirs(partialDir, exist_ok=True)
    partialPath = os.path.join(partialDir, filename + '.part')

    # Try once, then up to maxRetries more times on timeouts, dropped connections and server errors
    for attempt in range(maxRetries + 1):
        if attempt > 0:
            log('  Retrying ({0}/{1}) in {2}s'.format(attempt, maxRetries, retryDelay))
            time.sleep(retryDelay)
        try:
            # Stream to disk in chunks instead of holding the whole episode in memory
            with requests.get(episodeUrl, allow_redirects=True, stream=True, timeout=requestTimeout) as episodeResponse:
                # Skip this episode on an error status, so an error page isn't saved as audio
                if not episodeResponse.ok:
                    log('Failed to download {0}: HTTP {1}'.format(filename, episodeResponse.status_code))
                    # Only server errors (5xx) are worth retrying; a 404 won't fix itself
                    if episodeResponse.status_code >= 500:
                        continue
                    return False
                total = int(episodeResponse.headers.get('Content-Length') or 0)
                done = 0
                with open(partialPath, 'wb') as f:
                    for chunk in episodeResponse.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                        done += len(chunk)
                        if showProgress:
                            printProgress(done, total)
                if showProgress:
                    print()
            shutil.move(partialPath, filepath)

            # Date the file by the episode's release, so sorting by date matches release order
            if releaseTime:
                os.utime(filepath, (releaseTime, releaseTime))
            return True
        except requests.RequestException as e:
            if showProgress:
                print()
            log('Failed to download {0}: {1}'.format(filename, e))
        except OSError as e:
            # A file that can't be written won't fix itself on retry; skip it so the rest of the show still runs
            if showProgress:
                print()
            log('Failed to save {0}: {1}'.format(filename, e))
            return False
    # Out of retries; the next run tries this episode again
    return False

def getReleaseTime(pubDate):
    # Turn an RSS date like "Thu, 22 Oct 2026 16:52:31 +0000" into a timestamp, or None if missing or unreadable
    try:
        return email.utils.parsedate_to_datetime(pubDate).timestamp()
    except (TypeError, ValueError):
        return None

def downloadPodcast(feedUrl, downloadDir, useTitle, redownload, maxEpisodes):

    # Create the download directory if it doesn't exist
    if not os.path.isdir(downloadDir):
        os.makedirs(downloadDir)

    # Fetch the RSS feed
    feedResponse = requests.get(feedUrl, timeout=requestTimeout)
    feedResponse.raise_for_status()

    # Parse the raw bytes, so the XML declaration decides the text encoding instead of a guess
    feedRoot = xmlreader.fromstring(feedResponse.content)

    # On Windows, keep names short enough that both the download path and the .part path fit within the
    # path limit, leaving room for the separator, a " (99)" number for repeated titles and a ".xxxx" extension
    nameLength = maxNameLength
    if os.name == 'nt':
        longestDir = max(len(os.path.abspath(downloadDir)), len(os.path.abspath(partialDir)) + len('.part'))
        nameLength = max(20, min(maxNameLength, maxPathLength - longestDir - 1 - 5 - 5))

    # Work out every filename first, oldest episode first (feeds list the newest first),
    # so a repeated title gets the same name no matter which order episodes download in
    episodes = []
    usedNames = set()
    for episode in reversed(feedRoot.findall('.//channel/item')):
        episodeTitle = episode.findtext('title')
        enclosure = episode.find('enclosure')

        # Skip items without an audio file, instead of stopping the whole show
        if enclosure is None or not enclosure.get('url'):
            log('Skipping {0}: no audio file in feed'.format(episodeTitle or 'untitled item'))
            continue

        episodeUrl = enclosure.get('url')

        # Ignore any ?query or #fragment when reading the filename from the URL
        urlFilename = urlparse(episodeUrl).path.rsplit('/',1)[-1]
        extension = getExtension(urlFilename, enclosure.get('type'))

        # Build filename from episode title or URL, without the extension
        if useTitle == 0 or not episodeTitle or not cleanName(episodeTitle, nameLength):
            # Strip path from URL, keep only the filename
            name = cleanName(urlFilename.rsplit('.',1)[0] if '.' in urlFilename else urlFilename, nameLength)
        else:
            name = cleanName(episodeTitle, nameLength)
        name = name or 'episode'

        # Number repeated names, so a second episode with the same title isn't taken as already downloaded.
        # Windows ignores case in filenames, so compare in lower case
        uniqueName = name
        count = 2
        while uniqueName.lower() in usedNames:
            uniqueName = '{0} ({1})'.format(name, count)
            count += 1
        usedNames.add(uniqueName.lower())

        filename = '{0}.{1}'.format(uniqueName, extension) if extension else uniqueName
        episodes.append((filename, episodeUrl, getReleaseTime(episode.findtext('pubDate'))))

    # "max-episodes" keeps only the newest ones; the list is oldest first, so take from the end
    if maxEpisodes > 0:
        episodes = episodes[-maxEpisodes:]

    # The list is oldest first; flip it back unless downloading in release order
    if not oldestFirst:
        episodes.reverse()

    for filename, episodeUrl, releaseTime in episodes:
        filepath = os.path.join(downloadDir, filename)

        # Download if missing, or again if redownload is on (overwrites the existing file)
        if redownload or not os.path.isfile(filepath):
            log('Downloading {0} from url {1}'.format(filename, episodeUrl))
            if downloadEpisode(episodeUrl, filename, filepath, releaseTime):
                totals['downloaded'] += 1
            else:
                totals['failed'] += 1
        else:
            totals['skipped'] += 1
            if not hideSkipped:
                log('File {0} has already been downloaded'.format(filename))

# Settings config.json may use, with the type each must be
settingTypes = {
    'show-progressbar': int, 'hide-skipped': int, 'timeout': int, 'temp-path': str,
    'retries': int, 'oldest-first': int, 'log-file': str, 'shows': list,
}
showSettingTypes = {
    'show-url': str, 'download-path': str, 'title-as-filename': int,
    'enabled': int, 'redownload': int, 'max-episodes': int,
}
requiredShowSettings = ['show-url', 'download-path', 'title-as-filename']

def checkSettings(settings, types, where, problems):
    # Note any setting with the wrong type, and warn about names we don't know, which are usually typos
    for key, value in settings.items():
        if key not in types:
            print('Warning: unknown setting "{0}" {1} is ignored. Check the spelling'.format(key, where))
        elif not isinstance(value, types[key]) or (types[key] is int and isinstance(value, bool)):
            problems.append('"{0}" {1} should be {2}'.format(key, where, 'a number' if types[key] is int else 'text' if types[key] is str else 'a list'))
        elif types[key] is int and value < 0:
            problems.append('"{0}" {1} can\'t be negative'.format(key, where))

def loadConfig():
    # Read config.json and check it, stopping with a clear message instead of a Python error
    configPath = os.path.join(scriptDir, 'config.json')
    if not os.path.isfile(configPath):
        sys.exit('config.json not found in {0}\nCopy config.json.example to config.json and edit it.'.format(scriptDir))
    try:
        with open(configPath, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        sys.exit('config.json has a mistake on line {0}, column {1}: {2}'.format(e.lineno, e.colno, e.msg))

    if not isinstance(config, dict) or not isinstance(config.get('shows'), list):
        sys.exit('config.json needs a "shows" list. See config.json.example')

    problems = []
    checkSettings(config, settingTypes, 'at the top of config.json', problems)
    if config.get('timeout') == 0:
        problems.append('"timeout" must be at least 1')
    for number, show in enumerate(config['shows'], 1):
        where = 'in show {0}'.format(number)
        if not isinstance(show, dict):
            problems.append('show {0} should be a {{ ... }} block'.format(number))
            continue
        for key in requiredShowSettings:
            if key not in show:
                problems.append('"{0}" is missing {1}'.format(key, where))
        checkSettings(show, showSettingTypes, where, problems)
    if problems:
        sys.exit('config.json has problems:\n  ' + '\n  '.join(problems))
    return config

# Log file isn't known until the config is read; messages before then go to the screen only
logFile = None

config = loadConfig()

# --redownload on the command line downloads every episode of every show again
redownloadAll = '--redownload' in sys.argv[1:]

# Settings for all shows; anything missing from config.json falls back to the default
# "show-progressbar": 1 shows a download bar for each episode. It's left off when output goes
# to a file or a scheduled task instead of a terminal, where the redrawn bar would garble the output
showProgress = config.get('show-progressbar', 0) == 1 and sys.stdout.isatty()
# "hide-skipped": 1 hides the line for each episode that's already downloaded
hideSkipped = config.get('hide-skipped', 0) == 1
# "timeout": seconds to wait for the server to connect or send data before giving up
requestTimeout = config.get('timeout', 60)
# "temp-path": where unfinished .part downloads go; outside the project so they are safe to delete
partialDir = config.get('temp-path') or os.path.join(tempfile.gettempdir(), 'podfetch')
# "retries": how many more times to try a failed download before moving on
maxRetries = config.get('retries', 0)
# "oldest-first": 1 downloads in release order instead of newest first
oldestFirst = config.get('oldest-first', 0) == 1
# "log-file": also write messages, with the time, to this file. A relative path is next to this script
logFile = config.get('log-file') or None
if logFile:
    logFile = os.path.join(scriptDir, logFile)

# Running count of what happened, for the summary at the end
totals = {'downloaded': 0, 'failed': 0, 'skipped': 0, 'failedShows': 0}

for show in config['shows']:
    # "enabled": 0 pauses a show without removing it from the config
    if show.get('enabled', 1) == 0:
        log('Skipping {0}: disabled in config'.format(show['show-url']))
        continue
    try:
        redownload = redownloadAll or show.get('redownload', 0) == 1
        # "max-episodes": only the newest this many episodes; 0 means all
        downloadPodcast(show['show-url'], show['download-path'], show['title-as-filename'], redownload, show.get('max-episodes', 0))
    except Exception as e:
        log('Failed to process {0}: {1}'.format(show['show-url'], e))
        totals['failedShows'] += 1

summary = 'Done: {0} downloaded, {1} failed, {2} already downloaded'.format(totals['downloaded'], totals['failed'], totals['skipped'])
if totals['failedShows']:
    summary += ', {0} show(s) could not be read'.format(totals['failedShows'])
log(summary)

# Exit with 1 when anything failed, so Task Scheduler or cron can tell
sys.exit(1 if totals['failed'] or totals['failedShows'] else 0)
