# -*- encoding: utf-8 -*-
import datetime
import json
import logging
import os
import re
import shutil
import sys
import tempfile

from flask import Flask
from flask import render_template
import dropbox
import requests

import api_keys


app = Flask(__name__)
app.config.from_pyfile('config.py')
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, format=LOG_FORMAT)

log = logging.getLogger('zzalauto')

pocket_consumer_key = os.environ['POCKET_CONSUMER_KEY']
pocket_access_token = os.environ['POCKET_ACCESS_TOKEN']

dropbox_access_token = os.environ['DROPBOX_ACCESS_TOKEN']

numerous_auth_string = os.environ['NUMEROUS_AUTH_STRING']
numerous_metric_id = os.environ['NUMEROUS_METRIC_ID']

class StopPipeline(Exception):
    def __init__(self, msg):
        self.msg = msg

@app.route('/')
def main():
    return render_template('index.html', contents='zzalauto')

@app.route('/activate')
@app.route('/activate/<int:count>')
@app.route('/activate/<tag>')
@app.route('/activate/<tag>/<int:count>')
def activate(tag=None, count=5):
    log.info('activated for tag: {}, count: {}'.format(tag, count))

    if tag in ('notag', 'untagged', '_untagged_'):
        tag = '_untagged_'

    prefix = 'zzalauto-'
    link_results = []
    try:
        tmp_path = tempfile.mkdtemp(prefix=prefix)
    except OSError as ose:
        log.exception('could not access to path {}'.format(tmp_path))
        raise ose

    try:
        ids, links = get_links_from_pocket(tag, count)
        image_files, link_results = download_pics_from_twitter(links, tmp_path)
        n_success = upload_to_dropbox(image_files)

        archive_pocket_links(ids)
        metric_add(n_success)
        contents = '{} pics are downloaded for {} links'.format(
                     len(image_files), len(links))
        log.info('finished: {}'.format(contents))
    except StopPipeline as e:
        log.error(e.msg)
        contents = e.msg

    try:
        shutil.rmtree(tmp_path)
    except OSError as e:
        log.exception('failed to remove tmp directory')
        raise e

    return render_template('index.html', link_results=link_results, contents=contents)

def get_links_from_pocket(tag, count):
    log.debug('get links from pocket. tag: {}, count: {}'.format(tag, count))
    request_url = 'https://getpocket.com/v3/get'

    data = {'consumer_key': pocket_consumer_key,
            'access_token': pocket_access_token,
            'sort': 'newest', # fixed
            'count': count }
    if tag is not None: data['tag'] = tag

    resp = requests.post(request_url, data=data)
    if resp.status_code != 200:
        msg = 'failed to get links from Pocket({} {})'.format(
                resp.status_code, resp.headers['X-Error'])
        log.error(msg)
        raise StopPipeline(msg)
    parsed = resp.json()
    items = parsed['list']

    links = [item['given_url'] for item in items.values()]

    return items.keys(), links

def download_pics_from_twitter(links, tmp_path):
    log.debug('download pics from twitter. n_links: {}'.format(len(links)))

    image_links = []
    link_results = []

    # collect direct links
    for link in links:
        resp = requests.get(link)
        if resp.status_code == 404:
            link_results.append({'link': link, 'result': 'deleted'})
            continue
        elif resp.status_code != 200:
            msg = 'Could not read page. response code: {}, url: {}'.format(
                    resp.status_code, link)
            raise StopPipeline(msg)

        # <meta  property="og:image" content="https://pbs.twimg.com/media/CV3MKISUYAAAkDi.png:large">
        image_match = re.compile(
                '<meta\s*property=\"og:image\"\s*content="(?P<contents>[^"]*)">')

        searched = image_match.findall(resp.text)
        replaced = [s_link.replace(':large', ':orig') for s_link in searched]

        if 'profile_images' in replaced:
            link_results.append({'link': link, 'result': 'only profile pictures'})
            continue # skip profile picture

        if 'ext_tw_video_thumb' in replaced:
            link_results.append({'link': link, 'result': 'only videos'})
            continue # skip video

        link_results.append({'link': link, 'result': '{} pictures downloaded'.format(len(replaced))})

        image_links += replaced

    # download actual files
    image_files = []
    for link in image_links:
        filename = link.split('/')[-1].replace(':orig', '')
        filepath = '{}/{}'.format(tmp_path, filename)
        if os.path.exists(filepath):
            continue
        resp = requests.get(link, stream=True)
        if resp.status_code == 200:
            with open(filepath, 'wb') as f:
                resp.raw.decode_content = True
                shutil.copyfileobj(resp.raw, f)
            image_files.append(filepath)
            log.debug('image file downloaded to {}'.format(filepath))
        else:
            msg = 'failed to download image file {} from {}'.format(filepath, link)
            #raise StopPipeline(msg)
    return image_files, link_results

def upload_to_dropbox(image_files):
    log.debug('upload to dropbox for {} files'.format(len(image_files)))
    n_success = 0
    client = dropbox.client.DropboxClient(dropbox_access_token)

    parent_dir = '/Workflow/Twitter/'
    timestamp = datetime.datetime.now().strftime('%Y%m%d')
    dir_name = 'zzalauto-{}'.format(timestamp)
    working_dir = '{}/{}'.format(parent_dir, dir_name)

    try:
        client.file_create_folder(working_dir)
    except dropbox.rest.ErrorResponse as e:
        if not e.status == 403:
            msg = '{}: {}'.format(e.status, e.reason)
            log.exception('failed to upload to Dropbox: {}'.format(e.error_msg))
            raise StopPipeline(msg)

    for image_file in image_files:
        dropbox_path = '{}/{}'.format(working_dir, image_file.split('/')[-1])
        with open(image_file, 'rb') as f:
            try:
                resp = client.put_file(dropbox_path, f, overwrite=True)
                log.debug('uploaded to dropbox: {}({})'.format(resp['path'], resp['size']))
                n_success += 1
            except dropbox.rest.ErrorResponse as e:
                log.exception('failed to upload to Dropbox: {}'.format(e.error_msg))
                msg = '{}: {}'.format(e.status, e.reason)
                raise StopPipeline(msg)
    return n_success

def archive_pocket_links(ids):
    log.debug('archive {} pocket links'.format(len(ids)))
    for id_ in ids:
        request_url = 'https://getpocket.com/v3/send'
        data = {'consumer_key': pocket_consumer_key,
                'access_token': pocket_access_token,
                'actions': json.dumps([{ 'action': 'archive', 'item_id': id_ }])}

        resp = requests.post(request_url, data=data)
        if resp.status_code != 200:
            msg = 'Pocket item could not be archived: {}'.format(id_)
            raise StopPipeline(msg)
    return

@app.route('/metric/set/<int:value>')
def metric_set(value):
    try:
        result = manage_metric(value, None)
    except StopPipeline as e:
        log.exception(e.msg)
        result = e.msg
    return result

@app.route('/metric/add/<int:value>')
def metric_add(value):
    try:
        result = manage_metric(value, 'ADD')
    except StopPipeline as e:
        log.exception(e.msg)
        result = e.msg
    return result

def manage_metric(value, action):
    log.debug('update metric for {}, action: {}'.format(value, action))
    request_url_pattern = 'https://api.numerousapp.com/v2/metrics/{}/events'
    request_url = request_url_pattern.format(numerous_metric_id)

    headers = {'Authorization': numerous_auth_string,
               'Content-Type': 'application/json' }
    payload = {'Value': value }
    if action == 'ADD': payload['action'] = action
    data = json.dumps(payload)
    resp = requests.post(request_url, headers=headers, data=data)
    if resp.status_code not in (200, 201):
        msg = 'failed to update metric'
        raise StopPipeline(msg)

    result = 'metric is updated to: {}\n'.format(resp.json()['value'])
    return result

if __name__ == '__main__':
    app.run(port=21000, debug=True) # only for test
