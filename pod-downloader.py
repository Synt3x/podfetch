import requests
import os
import re
import argparse
import concurrent.futures
import email.utils
import hashlib
import json
import threading
import mimetypes
import random
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

# Longest message each notification service accepts
notifyLimits = {'discord': 2000, 'voidy': 4000, 'slack': 3000}

# Settings for all shows. main() replaces these with the values from config.json;
# these defaults are what a missing setting means
showProgress = False
hideSkipped = False
requestTimeout = 60
partialDir = os.path.join(tempfile.gettempdir(), 'podfetch')
maxRetries = 0
oldestFirst = False
logFile = None
maxSpeed = 0
skipInactiveDays = 0
debug = False
parallel = 1
dryRun = False

# With "parallel" above 1, several downloads update the counts and write messages at once
countLock = threading.Lock()
logLock = threading.Lock()

# Set on Ctrl+C, so downloads in progress stop straight away
stopEvent = threading.Event()

# Terminal colours, switched on in main() when the output supports them; the log file never gets them
useColor = False
colorCodes = {'bold': '1', 'dim': '2', 'red': '31', 'green': '32', 'yellow': '33', 'cyan': '36'}
colorPattern = re.compile(r'\033\[[0-9;]*m')

# Notes on shows for the overview before downloading, like an ended show still catching up, by folder name
planNotes = {}

# The download in progress for the progress bar, as (name, bytes done, total bytes); how many characters
# of progress bar are on screen, so it can be cleared; and when it was last drawn
activeDownloads = {}
progressLength = 0
lastProgressDraw = 0.0

# The config.json in use, so a finished inactive show can be disabled in it
configPath = os.path.join(scriptDir, 'config.json')

# Running count of what happened, for the summary and notifications at the end
totals = {'downloaded': 0, 'failed': 0, 'skipped': 0, 'failedShows': 0}
downloadedNames = []
failedNames = []
wouldDownload = {}

# Each show's title from its feed, like "2.5 Admins", by folder name; used in the summary and notifications
showTitles = {}

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

def paint(text, *styles):
    # Colour text for the terminal, like paint('✔', 'green'); plain text when colour is off
    if not useColor or not styles:
        return text
    return '\033[{0}m{1}\033[0m'.format(';'.join(colorCodes[style] for style in styles), text)

def enableColor():
    # Colour only in a terminal, and not when the NO_COLOR environment variable is set.
    # The Windows console needs colour codes switched on first; if that fails, stay plain
    if not sys.stdout.isatty() or 'NO_COLOR' in os.environ:
        return False
    if os.name != 'nt':
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False

def log(message):
    # Print a message, and also add it to the log file with the time when one is set.
    # The lock keeps lines from parallel downloads from mixing. The progress line is cleared
    # first and drawn again below the message, so messages never land in the middle of it
    with logLock:
        clearProgress()
        print(message, flush=True)
        if logFile:
            try:
                with open(logFile, 'a', encoding='utf-8') as f:
                    f.write('{0}  {1}\n'.format(time.strftime('%Y-%m-%d %H:%M:%S'), colorPattern.sub('', message)))
            except OSError as e:
                print('Could not write to log file {0}: {1}'.format(logFile, e))
        drawProgress()

def debugLog(message):
    # Details only shown with "debug": 1 or --debug, like where each episode is downloaded from
    if debug:
        log('  [debug] ' + message)

def renderProgress(done, total, width):
    # The progress bar for the episode downloading, cut to fit width; without a known size, MB downloaded only
    megabyte = 1024 * 1024
    if total:
        filled = 30 * done // total
        line = '  [{0}] {1:3d}%  {2:.1f} / {3:.1f} MB'.format('#' * filled + '-' * (30 - filled), 100 * done // total, done / megabyte, total / megabyte)
    else:
        line = '  {0:.1f} MB'.format(done / megabyte)
    return line[:width]

def clearProgress():
    # Remove the progress line from the screen. Called with logLock held
    global progressLength
    if progressLength:
        sys.stdout.write('\r' + ' ' * progressLength + '\r')
        progressLength = 0

def drawProgress():
    # Draw the progress bar for the episode downloading, over the old one. Called with logLock held
    global progressLength, lastProgressDraw
    if not showProgress or not activeDownloads:
        return
    name, done, total = list(activeDownloads.values())[-1]
    line = renderProgress(done, total, shutil.get_terminal_size((100, 24)).columns - 1)
    sys.stdout.write('\r' + line + ' ' * max(0, progressLength - len(line)))
    sys.stdout.flush()
    progressLength = len(line)
    lastProgressDraw = time.monotonic()

def updateProgress(key, name, done, total, force=False):
    # Note how far a download has got, and redraw the progress line at most 5 times a second
    if not showProgress:
        return
    with logLock:
        activeDownloads[key] = (name, done, total)
        if force or time.monotonic() - lastProgressDraw >= 0.2:
            drawProgress()

def finishProgress(key):
    # Take a finished, failed or stopped download off the progress line
    if not showProgress:
        return
    with logLock:
        activeDownloads.pop(key, None)
        clearProgress()
        drawProgress()

def throttleDelay(done, elapsed, bytesPerSecond):
    # Seconds to pause so the average speed so far stays under the limit
    return max(0.0, done / bytesPerSecond - elapsed)

def downloadEpisode(episodeUrl, filename, filepath, releaseTime):
    # Returns True once the episode is saved, False if it failed, None if stopped with Ctrl+C

    # Save to a .part file first, then move it into place once complete. The .part name comes from the
    # full destination path, so two shows with the same episode filename can download at the same time.
    # It's shorter than the filename, so it fits wherever the filename does
    os.makedirs(partialDir, exist_ok=True)
    partialPath = os.path.join(partialDir, hashlib.sha1(os.path.abspath(filepath).encode('utf-8')).hexdigest()[:16] + '.part')

    # Smaller chunks when the speed is limited, so the pauses between them stay short
    chunkSize = 64 * 1024 if maxSpeed else 1024 * 1024

    # However this ends, take the download off the progress line
    try:
        return downloadAttempts(episodeUrl, filename, filepath, releaseTime, partialPath, chunkSize)
    finally:
        finishProgress(filepath)

def downloadAttempts(episodeUrl, filename, filepath, releaseTime, partialPath, chunkSize):
    # The download itself, for downloadEpisode. Same return values
    progressName = filename.rsplit('.',1)[0]

    # Try once, then up to maxRetries more times on timeouts, dropped connections and server errors
    for attempt in range(maxRetries + 1):
        if attempt > 0:
            log(paint('  ↻ Retrying ({0}/{1}) in {2}s'.format(attempt, maxRetries, retryDelay), 'yellow'))
            if stopEvent.wait(retryDelay):
                return None
        if stopEvent.is_set():
            return None
        try:
            # Stream to disk in chunks instead of holding the whole episode in memory
            with requests.get(episodeUrl, allow_redirects=True, stream=True, timeout=requestTimeout) as episodeResponse:
                # Skip this episode on an error status, so an error page isn't saved as audio
                if not episodeResponse.ok:
                    log(paint('✖ ', 'red') + 'Failed to download {0}: HTTP {1}'.format(filename, episodeResponse.status_code))
                    # Only server errors (5xx) are worth retrying; a 404 won't fix itself
                    if episodeResponse.status_code >= 500:
                        continue
                    return False
                total = int(episodeResponse.headers.get('Content-Length') or 0)
                done = 0
                started = time.monotonic()
                updateProgress(filepath, progressName, done, total, force=True)
                with open(partialPath, 'wb') as f:
                    for chunk in episodeResponse.iter_content(chunk_size=chunkSize):
                        # Ctrl+C: stop now, leaving the .part file; the next run downloads the episode again
                        if stopEvent.is_set():
                            return None
                        f.write(chunk)
                        done += len(chunk)
                        updateProgress(filepath, progressName, done, total)
                        # "max-speed": pause as needed to stay under the limit
                        if maxSpeed:
                            delay = throttleDelay(done, time.monotonic() - started, maxSpeed * 1024)
                            if delay > 0:
                                time.sleep(delay)
            shutil.move(partialPath, filepath)

            # Date the file by the episode's release, so sorting by date matches release order
            if releaseTime:
                os.utime(filepath, (releaseTime, releaseTime))
            return True
        except requests.RequestException as e:
            log(paint('✖ ', 'red') + 'Failed to download {0}: {1}'.format(filename, e))
        except OSError as e:
            # A file that can't be written won't fix itself on retry; skip it so the rest of the show still runs
            log(paint('✖ ', 'red') + 'Failed to save {0}: {1}'.format(filename, e))
            return False
    # Out of retries; the next run tries this episode again
    return False

def getReleaseTime(pubDate):
    # Turn an RSS date like "Thu, 22 Oct 2026 16:52:31 +0000" into a timestamp, or None if missing or unreadable
    try:
        return email.utils.parsedate_to_datetime(pubDate).timestamp()
    except (TypeError, ValueError):
        return None

def fetchFeed(feedUrl):
    # Fetch the RSS feed
    debugLog('Reading feed {0}'.format(feedUrl))
    feedResponse = requests.get(feedUrl, timeout=requestTimeout)
    feedResponse.raise_for_status()

    # Parse the raw bytes, so the XML declaration decides the text encoding instead of a guess
    return xmlreader.fromstring(feedResponse.content)

def buildEpisodes(feedRoot, downloadDir, useTitle):
    # Work out each episode's filename. Returns a list of episodes, oldest first

    # On Windows, keep names short enough that both the download path and the .part path fit within the
    # path limit, leaving room for the separator, a " (99)" number for repeated titles and a ".xxxx" extension
    nameLength = maxNameLength
    if os.name == 'nt':
        longestDir = max(len(os.path.abspath(downloadDir)), len(os.path.abspath(partialDir)) + len('.part'))
        nameLength = max(20, min(maxNameLength, maxPathLength - longestDir - 1 - 5 - 5))

    # Go through oldest episode first (feeds list the newest first),
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
        episodes.append({
            'title': (episodeTitle or '').strip(),
            'filename': filename,
            'url': episodeUrl,
            'releaseTime': getReleaseTime(episode.findtext('pubDate')),
        })
    return episodes

def selectEpisodes(episodes, skipEpisodes, maxEpisodes):
    # Drop episodes listed in "skip-episodes", then keep only the newest "max-episodes" (0 = all).
    # A skip entry matches an episode's title or its filename, with or without the extension, ignoring case
    skip = {entry.strip().lower() for entry in skipEpisodes}
    kept = [episode for episode in episodes
            if episode['title'].lower() not in skip
            and episode['filename'].lower() not in skip
            and episode['filename'].rsplit('.',1)[0].lower() not in skip]

    # The list is oldest first, so the newest are at the end
    if maxEpisodes > 0:
        kept = kept[-maxEpisodes:]
    return kept

def showName(show):
    # The show's folder name, used in messages and --show
    return os.path.basename(os.path.normpath(show['download-path']))

def displayName(name):
    # The feed's title for a show, like "2.5 Admins"; the folder name until its feed has been read
    return showTitles.get(name, name)

def isInactive(episodes, days, now=None):
    # True when the show's newest episode is more than this many days old, so it has probably ended.
    # Without any release dates in the feed, a show is never taken as inactive
    releaseTimes = [episode['releaseTime'] for episode in episodes if episode['releaseTime']]
    if days <= 0 or not releaseTimes:
        return False
    return (now if now is not None else time.time()) - max(releaseTimes) > days * 24 * 60 * 60

def disableShowInConfig(show):
    # Set "enabled": 0 on this show in config.json, changing only that value so the rest of the file stays
    # as you wrote it. The result is read back and saved only if exactly that one value changed.
    # Returns True once saved
    try:
        with open(configPath, 'r', encoding='utf-8') as f:
            text = f.read()
        before = json.loads(text)

        # The show's { ... } block is the one holding its feed URL; show blocks have no { } inside them
        quotedUrl = json.dumps(show['url'], ensure_ascii=False)
        position = text.find(quotedUrl)
        if position < 0 or text.find(quotedUrl, position + 1) >= 0:
            return False
        start = text.rfind('{', 0, position)
        end = text.find('}', position)
        if start < 0 or end < 0 or '}' in text[start:position]:
            return False
        block = text[start:end + 1]
        if re.search(r'"enabled"\s*:\s*1\b', block):
            newBlock = re.sub(r'("enabled"\s*:\s*)1\b', r'\g<1>0', block, count=1)
        elif '"enabled"' not in block:
            newBlock = block[:-1].rstrip() + ', "enabled": 0 }'
        else:
            return False
        newText = text[:start] + newBlock + text[end + 1:]

        # Check that the only change is this show's "enabled" before saving
        after = json.loads(newText)
        expected = json.loads(text)
        matches = [entry for entry in expected['shows'] if entry.get('url', entry.get('show-url')) == show['url']]
        if len(matches) != 1:
            return False
        matches[0]['enabled'] = 0
        if after != expected or after == before:
            return False

        with open(configPath, 'w', encoding='utf-8', newline='') as f:
            f.write(newText)
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False

def planPodcast(show, redownload, checkInactive=True):
    # Work out which of a show's episodes need downloading. Returns them in download order;
    # a dry run lists them and returns nothing, since nothing will be downloaded
    downloadDir = show['download-path']
    feedRoot = fetchFeed(show['url'])
    feedTitle = ' '.join((feedRoot.findtext('channel/title') or '').split())
    if feedTitle:
        showTitles[showName(show)] = feedTitle
    allEpisodes = buildEpisodes(feedRoot, downloadDir, show['title-as-filename'])

    episodes = selectEpisodes(allEpisodes, show.get('skip-episodes', []), show.get('max-episodes', 0))

    # "skip-inactive-days": skip shows with no new episode in that many days, unless picked with --show.
    # Only once every episode is downloaded, though: a show that ended still gets the ones you're missing
    if checkInactive and isInactive(allEpisodes, skipInactiveDays):
        newest = time.strftime('%Y-%m-%d', time.localtime(max(episode['releaseTime'] for episode in allEpisodes if episode['releaseTime'])))
        missing = sum(1 for episode in episodes if not os.path.isfile(os.path.join(downloadDir, episode['filename'])))
        if not missing and not redownload:
            # Nothing left to get, so turn the show off in config.json; later runs don't read its feed again
            name = paint(displayName(showName(show)), 'cyan')
            reason = 'all {0} episodes downloaded, no new episode since {1}'.format(len(episodes), newest)
            if dryRun:
                log('Would disable {0}: {1}'.format(name, reason))
            elif disableShowInConfig(show):
                log('Disabling {0}: {1} {2}'.format(name, reason, paint('· set "enabled": 1 to check it again', 'dim')))
            else:
                log(paint('⚠ ', 'yellow') + 'Skipping {0}: {1} {2}'.format(name, reason, paint('· could not set "enabled": 0 in config.json', 'dim')))
            return []
        # An ended show you're still missing episodes of: download them, and say why in the overview
        planNotes[showName(show)] = 'no new episode since {0}'.format(newest)

    # Create the download directory if it doesn't exist; a dry run changes nothing
    if not dryRun and not os.path.isdir(downloadDir):
        os.makedirs(downloadDir)

    # The list is oldest first; flip it back unless downloading in release order
    if not oldestFirst:
        episodes.reverse()

    planned = []
    for episode in episodes:
        filename = episode['filename']
        filepath = os.path.join(downloadDir, filename)

        # Download if missing, or again if redownload is on (overwrites the existing file)
        if redownload or not os.path.isfile(filepath):
            if dryRun:
                log('Would download {0} › {1}'.format(paint(displayName(showName(show)), 'cyan'), filename))
                totals['downloaded'] += 1
                wouldDownload[showName(show)] = wouldDownload.get(showName(show), 0) + 1
                continue
            planned.append({'show': showName(show), 'episode': episode, 'filepath': filepath})
        else:
            totals['skipped'] += 1
            if not hideSkipped:
                log('File {0} has already been downloaded'.format(filename))
    return planned

def downloadPlanned(job, number, total):
    # Download one episode from planPodcast and count the result. number and total give the
    # "[ 12/604 · 592 left]" counter, so you can see how far along the run is. The numbers are padded
    # to the same width on every line, so the show names line up
    episode = job['episode']
    filename = episode['filename']
    width = len(str(total))
    counter = '[{0:>{width}}/{1} · {2:>{width}} left]'.format(number, total, total - number, width=width)
    showLabel = paint(displayName(job['show']), 'cyan')
    log('{0} {1} › {2}'.format(paint(counter, 'dim'), showLabel, filename))
    debugLog('From {0}'.format(episode['url']))
    debugLog('Saving to {0}'.format(job['filepath']))
    try:
        result = downloadEpisode(episode['url'], filename, job['filepath'], episode['releaseTime'])
    except Exception as e:
        # Anything unexpected fails this one episode, not the whole run
        log(paint('✖ ', 'red') + 'Failed to download {0}: {1}'.format(filename, e))
        result = False

    # Stopped with Ctrl+C: neither downloaded nor failed
    if result is None:
        return
    with countLock:
        if result:
            size = os.path.getsize(job['filepath'])
            totals['downloaded'] += 1
            downloadedNames.append((job['show'], filename, size))
        else:
            totals['failed'] += 1
            failedNames.append((job['show'], filename))

    # Say when each download finishes: the progress line is cleared once it's done, and with several
    # downloads at once the starting lines alone don't show which have finished
    if result and (parallel > 1 or showProgress):
        log('{0} {1} {2} › {3} {4}'.format(' ' * len(counter), paint('✔', 'green'), showLabel, filename, paint('· ' + formatSize(size), 'dim')))

def runDownloads(jobs):
    # Download the planned episodes, "parallel" at a time. Ctrl+C stops every download in progress
    # straight away; returns False when stopped that way
    total = len(jobs)
    try:
        if parallel <= 1:
            for number, job in enumerate(jobs, 1):
                downloadPlanned(job, number, total)
        else:
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=parallel)
            pending = set()
            try:
                pending = {pool.submit(downloadPlanned, job, number, total) for number, job in enumerate(jobs, 1)}
                # Wait in short steps; Windows ignores Ctrl+C during a wait without a time limit
                while pending:
                    finished, pending = concurrent.futures.wait(pending, timeout=0.5)
            finally:
                # Leaving early (Ctrl+C): tell the downloads in progress to stop, and start no more
                if pending:
                    stopEvent.set()
                pool.shutdown(wait=True, cancel_futures=True)
    except KeyboardInterrupt:
        stopEvent.set()
        log('Stopped. Run again to carry on where it stopped')
        return False
    return True

def mixedOrder(queues, pick=random.choice):
    # Interleave the shows' download lists: each next download comes from a random show that
    # still has episodes left, so no one site gets every request in a row.
    # Each show's own episodes keep their order
    queues = [list(queue) for queue in queues if queue]
    while queues:
        queue = pick(queues)
        yield queue.pop(0)
        if not queue:
            queues.remove(queue)

def unmojibake(name):
    # Undo text that was decoded with the wrong encoding, like "Linuxâ€™s" back to "Linux’s"
    try:
        return name.encode('cp1252').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name

def looseName(filename):
    # A filename reduced to what matters for spotting the same episode under a slightly different name:
    # fixed encoding, single spaces, no trailing dots or spaces before the extension, lower case
    filename = unmojibake(filename)
    stem, dot, extension = filename.rpartition('.')
    if not dot:
        stem, extension = filename, ''
    stem = re.sub(r'\s+', ' ', stem).strip().rstrip('.').strip()
    return '{0}.{1}'.format(stem, extension).lower() if extension else stem.lower()

def checkShow(show, listLimit=20):
    # Report how a show's folder compares with its feed, without changing anything
    downloadDir = show['download-path']
    feedRoot = fetchFeed(show['url'])
    episodes = selectEpisodes(buildEpisodes(feedRoot, downloadDir, show['title-as-filename']),
                              show.get('skip-episodes', []), show.get('max-episodes', 0))
    files = sorted(f for f in os.listdir(downloadDir) if os.path.isfile(os.path.join(downloadDir, f))) if os.path.isdir(downloadDir) else []

    expected = {episode['filename'].lower(): episode['filename'] for episode in episodes}
    present = {f.lower() for f in files}
    byLooseName = {}
    for filename in expected.values():
        byLooseName.setdefault(looseName(filename), filename)

    duplicates, misnamed, notInFeed = [], [], []
    for f in files:
        if f.lower() in expected:
            continue
        match = byLooseName.get(looseName(f))
        if match is None:
            notInFeed.append(f)
        elif match.lower() in present:
            # The correctly named file is there too, so this one is a second copy
            duplicates.append((f, match))
        else:
            # Same episode under an older or garbled name; the next run would download it again
            misnamed.append((f, match))
    missing = [filename for key, filename in expected.items() if key not in present]

    log('== {0}: {1} episodes in feed, {2} downloaded, {3} missing'.format(
        showName(show), len(expected), len(expected) - len(missing), len(missing)))

    def listSection(heading, rows):
        if not rows:
            return
        log('  {0} ({1}):'.format(heading, len(rows)))
        for row in rows[:listLimit]:
            log('    ' + row)
        if len(rows) > listLimit:
            log('    ... and {0} more'.format(len(rows) - listLimit))

    listSection('Misnamed, will download again unless renamed', ['{0}  ->  {1}'.format(f, match) for f, match in misnamed])
    listSection('Possible duplicates', ['{0}  (same episode as {1})'.format(f, match) for f, match in duplicates])
    listSection('Not in the feed', notInFeed)
    return {'missing': missing, 'misnamed': misnamed, 'duplicates': duplicates, 'notInFeed': notInFeed}

def formatSize(size):
    # A byte count as MB, or GB from 1 GB up
    if size >= 1024 ** 3:
        return '{0:.1f} GB'.format(size / 1024 ** 3)
    return '{0:.1f} MB'.format(size / 1024 ** 2)

def downloadedSize():
    # Total size of the episodes downloaded this run
    return sum(size for show, filename, size in downloadedNames)

def treeLines(rows):
    # Rows of (name, count, size, note) as a tree with the columns lined up:
    #   ├─ 2.5 Admins    9 ep   27.0 MB
    #   └─ Coder Radio   1 ep    3.0 MB
    # Names are padded before colouring, so colour codes don't upset the columns
    lines = []
    if rows:
        widths = [max(len(row[column]) for row in rows) for column in range(3)]
        for number, (name, count, size, note) in enumerate(rows):
            branch = '└─' if number == len(rows) - 1 else '├─'
            line = '  {0} {1}  {2}  {3}  {4}'.format(paint(branch, 'dim'), paint(name.ljust(widths[0]), 'cyan'),
                                                    count.rjust(widths[1]), paint(size.rjust(widths[2]), 'dim'), note)
            lines.append(line.rstrip())
    return lines

def overviewLines(shows, plans):
    # Before downloading: how many episodes each show will get, with notes like an ended show catching up
    #   ⇣ 512 episodes to download
    #     ├─ Linux Matters   53 ep
    #     └─ Self-Hosted      9 ep  · no new episode since 2025-05-30
    total = sum(len(planned) for planned in plans)
    rows = [(displayName(showName(show)), '{0} ep'.format(len(planned)), '',
             paint('· ' + planNotes[showName(show)], 'dim') if showName(show) in planNotes else '')
            for show, planned in zip(shows, plans) if planned]
    return [paint('⇣ {0} episode{1} to download'.format(total, '' if total == 1 else 's'), 'bold')] + treeLines(rows)

def summaryLines():
    # The end-of-run summary: the totals, then a line per show that got anything, in the order they came up:
    #   ✔ 10 of 10 downloaded · 30.0 MB
    #     ├─ 2.5 Admins    9 ep   27.0 MB
    #     └─ Coder Radio   1 ep    3.0 MB
    # ✔ means everything worked, ⚠ that something failed
    hadFailure = totals['failed'] or totals['failedShows']
    rows = []
    if dryRun:
        heading = '◌ Dry run: would download {0}'.format(totals['downloaded'])
        rows = [(displayName(show), '{0} ep'.format(count), '', '') for show, count in wouldDownload.items()]
    else:
        attempted = totals['downloaded'] + totals['failed']
        mark = paint('⚠', 'yellow') if hadFailure else paint('✔', 'green')
        if attempted:
            heading = '{0} {1} of {2} downloaded · {3}'.format(mark, totals['downloaded'], attempted, formatSize(downloadedSize()))
        else:
            heading = '{0} Nothing new'.format(mark)
        if totals['failed']:
            heading += ' · {0} failed'.format(totals['failed'])
        shows = {}
        for show, filename, size in downloadedNames:
            counts = shows.setdefault(show, [0, 0, 0])
            counts[0] += 1
            counts[1] += size
        for show, filename in failedNames:
            shows.setdefault(show, [0, 0, 0])[2] += 1
        rows = [(displayName(show), '{0} ep'.format(downloaded), formatSize(size), paint('✖ {0} failed'.format(failed), 'red') if failed else '')
                for show, (downloaded, size, failed) in shows.items()]
    if totals['failedShows']:
        heading += ' · {0} show{1} could not be read'.format(totals['failedShows'], '' if totals['failedShows'] == 1 else 's')
    return [heading] + treeLines(rows)

def buildNotifyMessage(limit):
    # A short report of the run, cut to fit the service's message limit
    heading = 'podfetch: {0} new episode{1}'.format(totals['downloaded'], '' if totals['downloaded'] == 1 else 's')
    if downloadedNames:
        heading += ' ({0})'.format(formatSize(downloadedSize()))
    if totals['failed']:
        heading += ', {0} failed'.format(totals['failed'])
    if totals['failedShows']:
        heading += ', {0} show(s) could not be read'.format(totals['failedShows'])

    lines = [heading]
    lines += ['• {0}: {1} ({2})'.format(displayName(show), filename.rsplit('.',1)[0], formatSize(size)) for show, filename, size in downloadedNames]
    if failedNames:
        lines.append('Failed:')
        lines += ['• {0}: {1}'.format(displayName(show), filename.rsplit('.',1)[0]) for show, filename in failedNames]

    # Add lines until the next one wouldn't fit, then say how many were left out
    message = lines[0]
    for number, line in enumerate(lines[1:], 1):
        remaining = len(lines) - number
        if len(message) + 1 + len(line) + len('\n... and 9999 more') > limit:
            return message + '\n... and {0} more'.format(remaining)
        message += '\n' + line
    return message

def notifyPayload(serviceType, message):
    # Slack takes "text"; Discord takes "content", and Voidy accepts the Discord format
    if serviceType == 'slack':
        return {'text': message}
    return {'content': message, 'username': 'podfetch'}

def sendNotifications(notify, notifyWhen):
    # "notify-when": "changes" sends when anything downloaded or failed, "failures" only on a failure,
    # "always" after every run
    hadFailure = totals['failed'] or totals['failedShows']
    if notifyWhen == 'failures' and not hadFailure:
        return
    if notifyWhen == 'changes' and not (totals['downloaded'] or hadFailure):
        return

    for target in notify:
        serviceType = target['type']
        message = buildNotifyMessage(notifyLimits[serviceType])
        # A Voidy bot posts with its token in a header; webhook URLs carry their secret in the URL instead
        headers = {'Authorization': 'Bot ' + target['token']} if target.get('token') else {}
        try:
            response = requests.post(target['url'], json=notifyPayload(serviceType, message), headers=headers, timeout=requestTimeout)
            # The URL can hold the webhook's secret, so it isn't shown, even in debug output
            debugLog('Sent {0} notification: HTTP {1}'.format(serviceType, response.status_code))
            if not response.ok:
                log('Could not send {0} notification: HTTP {1}'.format(serviceType, response.status_code))
        except requests.RequestException as e:
            log('Could not send {0} notification: {1}'.format(serviceType, e))

# Settings config.json may use, with the type each must be
settingTypes = {
    'show-progressbar': int, 'hide-skipped': int, 'timeout': int, 'temp-path': str,
    'retries': int, 'oldest-first': int, 'log-file': str, 'max-speed': int,
    'skip-inactive-days': int, 'random-show': int, 'debug': int, 'parallel': int, 'notify': list, 'notify-when': str,
    'podcast-folder': str, 'shows': list,
}
showSettingTypes = {
    'url': str, 'folder': str, 'title-as-filename': int,
    'enabled': int, 'redownload': int, 'max-episodes': int, 'skip-episodes': list,
}
requiredShowSettings = ['url', 'folder', 'title-as-filename']
notifyWhenChoices = ['changes', 'failures', 'always']

def checkSettings(settings, types, where, problems):
    # Note any setting with the wrong type, and warn about names we don't know, which are usually typos
    for key, value in settings.items():
        if key not in types:
            print('Warning: unknown setting "{0}" {1} is ignored. Check the spelling'.format(key, where))
        elif not isinstance(value, types[key]) or (types[key] is int and isinstance(value, bool)):
            problems.append('"{0}" {1} should be {2}'.format(key, where, 'a number' if types[key] is int else 'text' if types[key] is str else 'a list'))
        elif types[key] is int and value < 0:
            problems.append('"{0}" {1} can\'t be negative'.format(key, where))

def loadConfig(configPath):
    # Read config.json and check it, stopping with a clear message instead of a Python error
    if not os.path.isfile(configPath):
        sys.exit('config.json not found in {0}\nCopy config.json.example to config.json and edit it.'.format(os.path.dirname(configPath)))
    try:
        with open(configPath, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        sys.exit('config.json has a mistake on line {0}, column {1}: {2}'.format(e.lineno, e.colno, e.msg))

    if not isinstance(config, dict) or not isinstance(config.get('shows'), list):
        sys.exit('config.json needs a "shows" list. See config.json.example')

    # "download-path" is the old name for the top-level "podcast-folder"; configs that use it keep working
    if 'podcast-folder' not in config and 'download-path' in config:
        config['podcast-folder'] = config.pop('download-path')

    problems = []
    checkSettings(config, settingTypes, 'at the top of config.json', problems)
    if config.get('timeout') == 0:
        problems.append('"timeout" must be at least 1')
    if config.get('parallel') == 0:
        problems.append('"parallel" must be at least 1')
    if isinstance(config.get('notify-when'), str) and config['notify-when'] not in notifyWhenChoices:
        problems.append('"notify-when" should be one of: {0}'.format(', '.join(notifyWhenChoices)))
    if isinstance(config.get('notify'), list):
        for number, target in enumerate(config['notify'], 1):
            if not isinstance(target, dict) or target.get('type') not in notifyLimits or not isinstance(target.get('url'), str) or not target['url'].startswith(('http://', 'https://')):
                problems.append('notify entry {0} needs a "type" ({1}) and a "url" starting with http:// or https://'.format(number, ', '.join(notifyLimits)))
            elif 'token' in target and (target['type'] != 'voidy' or not isinstance(target['token'], str)):
                problems.append('notify entry {0}: "token" is only for "voidy" bots, as text'.format(number))
    for number, show in enumerate(config['shows'], 1):
        where = 'in show {0}'.format(number)
        if not isinstance(show, dict):
            problems.append('show {0} should be a {{ ... }} block'.format(number))
            continue
        # "show-url" is the old name for "url"; configs that use it keep working
        if 'url' not in show and 'show-url' in show:
            show['url'] = show.pop('show-url')
        for key in requiredShowSettings:
            if key not in show:
                problems.append('"{0}" is missing {1}'.format(key, where))
        checkSettings(show, showSettingTypes, where, problems)

        # A show's episodes go in its "folder" inside the top-level "podcast-folder". The full path is kept
        # in the show as "download-path"; one written in config.json is ignored (warned about above)
        if 'folder' in show and isinstance(show['folder'], str):
            if not isinstance(config.get('podcast-folder'), str) or not config['podcast-folder']:
                problems.append('"folder" {0} needs "podcast-folder" at the top of config.json, the folder all shows go in'.format(where))
            else:
                show['download-path'] = os.path.join(config['podcast-folder'], show['folder'])
        if isinstance(show.get('skip-episodes'), list) and not all(isinstance(entry, str) for entry in show['skip-episodes']):
            problems.append('"skip-episodes" {0} should be a list of episode titles or filenames'.format(where))
    if problems:
        sys.exit('config.json has problems:\n  ' + '\n  '.join(problems))
    return config

def applySettings(config):
    # Set the settings for all shows from config.json; anything missing falls back to the default
    global showProgress, hideSkipped, requestTimeout, partialDir, maxRetries, oldestFirst, logFile, maxSpeed, skipInactiveDays, debug, parallel
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
    logFile = os.path.join(scriptDir, config['log-file']) if config.get('log-file') else None
    # "max-speed": download speed limit in KB/s for each episode; 0 means no limit
    maxSpeed = config.get('max-speed', 0)
    # "skip-inactive-days": skip a show whose newest episode is older than this many days; 0 means never
    skipInactiveDays = config.get('skip-inactive-days', 0)
    # "debug": 1 shows extra details, like the feed URLs and where each episode is downloaded from
    debug = config.get('debug', 0) == 1
    # "parallel": how many episodes download at the same time. Above 1 there's no progress bar
    parallel = config.get('parallel', 1)
    if parallel > 1:
        showProgress = False

def pickShows(shows, names):
    # The shows --show asks for, matched by folder name, or by part of the folder name or feed URL
    if not names:
        return [show for show in shows if show.get('enabled', 1) != 0]
    picked = []
    for name in names:
        name = name.lower()
        matches = [show for show in shows if showName(show).lower() == name]
        if not matches:
            matches = [show for show in shows if name in showName(show).lower() or name in show['url'].lower()]
        if not matches:
            sys.exit('No show matches "{0}". Shows in config.json: {1}'.format(name, ', '.join(showName(show) for show in shows)))
        picked += [show for show in matches if show not in picked]
    return picked

def parseArguments(arguments):
    parser = argparse.ArgumentParser(description='Download podcast episodes from the RSS feeds in config.json.')
    parser.add_argument('--redownload', action='store_true', help='download every episode again, overwriting existing files')
    parser.add_argument('--debug', action='store_true', help='show extra details, like where each episode is downloaded from')
    parser.add_argument('--dry-run', action='store_true', help='list what would be downloaded, without downloading or changing anything')
    parser.add_argument('--check', action='store_true', help='compare each folder with its feed: missing, misnamed, duplicate and extra files')
    parser.add_argument('--show', action='append', metavar='NAME', help='only this show, by folder name or part of it; can be used more than once')
    parser.add_argument('--config', default=os.path.join(scriptDir, 'config.json'), help=argparse.SUPPRESS)
    return parser.parse_args(arguments)

def main(arguments=None):
    global dryRun, logFile, configPath

    # When output goes to a file or scheduled task, Windows may not be able to show characters like ✔ or
    # some in episode titles; replace those instead of stopping with an error
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')

    options = parseArguments(sys.argv[1:] if arguments is None else arguments)
    stopEvent.clear()
    planNotes.clear()
    configPath = options.config
    config = loadConfig(configPath)
    applySettings(config)
    dryRun = options.dry_run
    global useColor
    useColor = enableColor()

    # The progress bar and parallel downloads don't mix; say so first thing, so it's not a surprise
    if config.get('show-progressbar', 0) == 1 and parallel > 1:
        log(paint('⚠ No progress bar while "parallel" is {0}'.format(parallel), 'yellow') + paint(' · set "show-progressbar": 0 to hide this', 'dim'))

    if options.debug:
        global debug
        debug = True

    # A dry run or check only reports, so it doesn't add to the log file
    if options.dry_run or options.check:
        logFile = None

    # --show picks shows by name and runs them even when "enabled" is 0; otherwise every enabled show runs
    shows = pickShows(config['shows'], options.show)
    if not options.show:
        disabled = [showName(show) for show in config['shows'] if show.get('enabled', 1) == 0]
        if disabled:
            log(paint('Disabled: ' + ', '.join(disabled), 'dim'))

    if options.check:
        for show in shows:
            try:
                checkShow(show)
            except Exception as e:
                log('Failed to check {0}: {1}'.format(showName(show), e))
        return 0

    def plan(show):
        # A show's download list, or nothing when its feed can't be read
        try:
            # --redownload on the command line downloads every episode of every show again
            redownload = options.redownload or show.get('redownload', 0) == 1
            return planPodcast(show, redownload, checkInactive=not options.show)
        except Exception as e:
            log('Failed to process {0}: {1}'.format(show['url'], e))
            totals['failedShows'] += 1
            return []

    # Read every feed first, so the total is known and each download can show how many are left.
    # "random-show": 1 mixes the shows' downloads in random order; otherwise each show is finished
    # before the next one starts
    plans = [plan(show) for show in shows]
    if config.get('random-show', 0) == 1:
        jobs = list(mixedOrder(plans))
    else:
        jobs = [job for planned in plans for job in planned]

    # What's about to download, by show, before it starts. A dry run shows the same in its summary
    if jobs and not dryRun:
        log('')
        for line in overviewLines(shows, plans):
            log(line)
        log('')
    completed = runDownloads(jobs)

    log('')
    for line in summaryLines():
        log(line)

    # Stopped with Ctrl+C: no notification, and exit code 130 as for any interrupted program
    if not completed:
        return 130

    # "notify": tell Discord, Slack or Voidy how the run went
    if config.get('notify') and not dryRun:
        sendNotifications(config['notify'], config.get('notify-when', 'changes'))

    # Exit with 1 when anything failed, so Task Scheduler or cron can tell
    return 1 if totals['failed'] or totals['failedShows'] else 0

if __name__ == '__main__':
    sys.exit(main())
