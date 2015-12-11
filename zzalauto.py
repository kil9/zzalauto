# -*- encoding: utf-8 -*-
import json
import logging
import os
import re
import shutil
import sys

from flask import Flask
from flask import render_template
import dropbox
import requests


app = Flask(__name__)
app.config.from_pyfile('config.py')
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, format=LOG_FORMAT)

log = logging.getLogger('zzalauto')

pocket_consumer_key = os.environ['POCKET_CONSUMER_KEY']
pocket_access_token = os.environ['POCKET_ACCESS_TOKEN']

dropbox_access_token = os.environ['DROPBOX_ACCESS_TOKEN']


@app.route('/')
def main():
    return render_template('base.html', contents='hello world!')

# TODO: get count per request
@app.route('/activate')
@app.route('/activate/<int:count>')
@app.route('/activate/<tag>')
def activate(tag='twitter', count=5):
    log.info('activated')

    ids, links = get_links_from_pocket(tag, count)
    if links: image_files = download_pics_from_twitter(links)
    upload_to_dropbox(image_files)
    archive_pocket_links(ids)

# TODO: 마지막엔 트윗들을 보여주는게 좋은 것 같다 
    return render_template('base.html', links=links)

def get_links_from_pocket(tag, count):
    log.info('get links from pocket. tag: {}, count: {}'.format(tag, count))
    request_url = 'https://getpocket.com/v3/get'

    data = {'consumer_key': pocket_consumer_key,
            'access_token': pocket_access_token,
            'sort': 'newest', # fixed
            'tag': tag,
            'count': count }

    resp = requests.post(request_url, data=data)
    if resp.status_code != 200:
        log.error('probably Pocket is gone wrong. response code: {}'.format(resp.status_code))
        return None
    parsed = resp.json()
    items = parsed['list']
    links = [items[key]['resolved_url'] for key in items]

    return items.keys(), links

def download_pics_from_twitter(links):
    log.info('download pics from twitter. n_links: {}'.format(len(links)))

    image_links = []

# TODO: do not download file if exists

    # collect direct links
    for link in links:
        resp = requests.get(link)
        if resp.status_code != 200:
            log.error('Could not read page. response code: {}, url: {}'.format(resp.status_code, link))
            return None

        # <meta  property="og:image" content="https://pbs.twimg.com/media/CV3MKISUYAAAkDi.png:large">
        image_match = re.compile('<meta\s*property=\"og:image\"\s*content="(?P<contents>[^"]*)">')

        searched = image_match.findall(resp.text)
        replaced = [link.replace(':large', ':orig') for link in searched]

        image_links += replaced

    # download actual files
    path = '/tmp/zzalauto'
    try:
        if not os.path.exists(path):
            os.makedirs(path)
    except OSError as ose:
        log.exception('could not access to path {}'.format(path))
        raise

    image_files = []
    for link in image_links:
        filename = link.split('/')[-1].replace(':orig', '')
        filepath = '{}/{}'.format(path, filename)
        resp = requests.get(link, stream=True)
        if resp.status_code == 200:
            with open(filepath, 'wb') as f:
                resp.raw.decode_content = True
                shutil.copyfileobj(resp.raw, f)
            image_files.append(filepath)
            log.debug('image file downloaded to {}'.format(filepath))

    return image_files

def upload_to_dropbox(image_files):

    client = dropbox.client.DropboxClient(dropbox_access_token)
    dropbox_path_pattern = '/Workflow/Twitter/{}'
    for image_file in image_files:
        dropbox_path = dropbox_path_pattern.format(image_file.split('/')[-1])
        with open(image_file, 'rb') as f:
            try:
                response = client.put_file(dropbox_path, f)
            except dropbox.rest.ErrorResponse as e:
                log.exception('Dropbox upload has failed')
                raise e

    return len(image_files)

def archive_pocket_links(ids):
    log.info('archive {} pocket links'.format(len(ids)))
    for id_ in ids:
        request_url = 'https://getpocket.com/v3/send'
        data = {'consumer_key': pocket_consumer_key,
                'access_token': pocket_access_token,
                'actions': json.dumps([{ 'action': 'archive', 'item_id': id_ }])
               }

        resp = requests.post(request_url, data=data)
        if resp.status_code == 200:
            print resp.text
        else:
            log.error('could not archived! {}'.format(id_))

if __name__ == '__main__':
    app.run(port=21000) # only for test
