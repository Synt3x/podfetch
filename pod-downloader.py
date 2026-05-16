import requests
import os
import json
import xml.etree.ElementTree as xmlreader

# Invalid characters in filename
invalidChars = ['<','>',':','"','/','\\','|','?','*']

def getPod(rss, data, bFilename):

    if os.path.isdir(data) == False:
        os.makedirs(data)

    # get the rss-feed
    req = requests.get(rss)

    # rss to xml
    root = xmlreader.fromstring(req.text)

    for item in root.findall('.//channel/item'):
        title = item.find('title').text
        enclosure = item.find('enclosure').attrib

        url = enclosure['url']

        # Filename from title or url?
        if bFilename == 0:
            # Remove everything before last slash and return the data
            filename = url.rsplit('/',1)[-1]
        else:
            extention = url.rsplit('/',1)[-1].rsplit('.',1)[-1]
            filename = '{0}.{1}'.format(title,extention)

        # Invalid Windows characters
        for char in invalidChars:
            filename = filename.replace(char,'')

        # Fixed annoying mistakes in filename
        filename = filename.replace('  ',' ')

        if not os.path.isfile(data + '/' + filename):
            print('Downloading {0} from url {1}'.format(filename, url))
            req  = requests.get(url, allow_redirects=True)
            open(data + '/' + filename, 'wb').write(req.content)
        else:
            print ('File {0} has already been downloaded'.format(filename))

for i in json.load(open("config.json","r"))['shows']:
    getPod(i['show-url'],i['download-path'],i['title-as-filename'])