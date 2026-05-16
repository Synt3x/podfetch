import requests
import os
import json
import xml.etree.ElementTree as xmlreader

# Characters not allowed in Windows filenames
invalidChars = ['<','>',':','"','/','\\','|','?','*']

def downloadPodcast(feedUrl, downloadDir, useTitle):

    # Create the download directory if it doesn't exist
    if not os.path.isdir(downloadDir):
        os.makedirs(downloadDir)

    # Fetch the RSS feed
    feedResponse = requests.get(feedUrl)

    # Parse the RSS feed as XML
    feedRoot = xmlreader.fromstring(feedResponse.text)

    for episode in feedRoot.findall('.//channel/item'):
        episodeTitle = episode.find('title').text
        enclosure = episode.find('enclosure').attrib

        episodeUrl = enclosure['url']

        # Build filename from episode title or URL
        if useTitle == 0:
            # Strip path from URL, keep only the filename
            filename = episodeUrl.rsplit('/',1)[-1]
        else:
            # Use episode title + file extension from URL
            extension = episodeUrl.rsplit('/',1)[-1].rsplit('.',1)[-1]
            filename = '{0}.{1}'.format(episodeTitle, extension)

        # Remove invalid Windows characters from filename
        for char in invalidChars:
            filename = filename.replace(char,'')

        # Collapse any double spaces left behind
        filename = filename.replace('  ',' ')

        filepath = os.path.join(downloadDir, filename)

        if not os.path.isfile(filepath):
            print('Downloading {0} from url {1}'.format(filename, episodeUrl))
            episodeResponse = requests.get(episodeUrl, allow_redirects=True)
            with open(filepath, 'wb') as f:
                f.write(episodeResponse.content)
        else:
            print('File {0} has already been downloaded'.format(filename))

# Load podcast list from config file
with open("config.json", "r") as f:
    config = json.load(f)

for show in config['shows']:
    try:
        downloadPodcast(show['show-url'], show['download-path'], show['title-as-filename'])
    except Exception as e:
        print('Failed to process {0}: {1}'.format(show['show-url'], e))