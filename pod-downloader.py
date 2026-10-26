import requests
import os
import re
import json
import shutil
import sys
import tempfile
import xml.etree.ElementTree as xmlreader
from urllib.parse import urlparse

# Characters not allowed in Windows filenames
invalidChars = ['<','>',':','"','/','\\','|','?','*']

# Unfinished downloads go here, outside the project, so they are safe to delete
partialDir = os.path.join(tempfile.gettempdir(), 'podfetch')

# Seconds to wait for the server to connect or send data before giving up
requestTimeout = 60

# Folder this script lives in, so config.json is found wherever it's run from
scriptDir = os.path.dirname(os.path.abspath(__file__))

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

def downloadPodcast(feedUrl, downloadDir, useTitle, redownload, showProgress):

    # Create the download directory if it doesn't exist
    if not os.path.isdir(downloadDir):
        os.makedirs(downloadDir)

    # Fetch the RSS feed
    feedResponse = requests.get(feedUrl, timeout=requestTimeout)
    feedResponse.raise_for_status()

    # Parse the RSS feed as XML
    feedRoot = xmlreader.fromstring(feedResponse.text)

    for episode in feedRoot.findall('.//channel/item'):
        episodeTitle = episode.findtext('title')
        enclosure = episode.find('enclosure')

        # Skip items without an audio file, instead of stopping the whole show
        if enclosure is None or not enclosure.get('url'):
            print('Skipping {0}: no audio file in feed'.format(episodeTitle or 'untitled item'))
            continue

        episodeUrl = enclosure.get('url')

        # Ignore any ?query or #fragment when reading the filename from the URL
        urlFilename = urlparse(episodeUrl).path.rsplit('/',1)[-1]

        # Build filename from episode title or URL
        if useTitle == 0 or not episodeTitle:
            # Strip path from URL, keep only the filename
            filename = urlFilename
        else:
            # Use episode title + file extension from URL
            extension = urlFilename.rsplit('.',1)[-1]
            filename = '{0}.{1}'.format(episodeTitle.strip(), extension)

        # Remove invalid Windows characters from filename
        for char in invalidChars:
            filename = filename.replace(char,'')

        # Collapse any runs of spaces left behind
        filename = re.sub(' {2,}', ' ', filename)

        filepath = os.path.join(downloadDir, filename)

        # Download if missing, or again if redownload is on (overwrites the existing file)
        if redownload or not os.path.isfile(filepath):
            print('Downloading {0} from url {1}'.format(filename, episodeUrl))
            # Save to a .part file first, then move it into place once complete
            os.makedirs(partialDir, exist_ok=True)
            partialPath = os.path.join(partialDir, filename + '.part')

            try:
                # Stream to disk in chunks instead of holding the whole episode in memory
                with requests.get(episodeUrl, allow_redirects=True, stream=True, timeout=requestTimeout) as episodeResponse:
                    # Skip this episode on an error status, so an error page isn't saved as audio
                    if not episodeResponse.ok:
                        print('Failed to download {0}: HTTP {1}'.format(filename, episodeResponse.status_code))
                        continue
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
            except requests.RequestException as e:
                # A timeout or dropped connection skips this episode; the next run retries it
                print('Failed to download {0}: {1}'.format(filename, e))
        else:
            print('File {0} has already been downloaded'.format(filename))

# Load podcast list from config file
with open(os.path.join(scriptDir, 'config.json'), 'r') as f:
    config = json.load(f)

# --redownload on the command line downloads every episode of every show again
redownloadAll = '--redownload' in sys.argv[1:]

# "show-progressbar": 1 in config.json shows a download bar for each episode
showProgress = config.get('show-progressbar', 0) == 1

for show in config['shows']:
    try:
        redownload = redownloadAll or show.get('redownload', 0) == 1
        downloadPodcast(show['show-url'], show['download-path'], show['title-as-filename'], redownload, showProgress)
    except Exception as e:
        print('Failed to process {0}: {1}'.format(show['show-url'], e))
