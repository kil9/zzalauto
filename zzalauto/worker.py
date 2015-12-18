# -*- encoding: utf-8 -*-

import datetime
import json
import os
import re
import shutil
import sys
import tempfile

import dropbox
import pika
import requests

from config import *
from zzalauto import metric_add, StopPipeline


def get_links_from_pocket(tag, count):
    log.debug('get links from pocket. tag: {}, count: {}'.format(tag, count))
    request_url = 'https://getpocket.com/v3/get'

    data = {'consumer_key': POCKET_CONSUMER_KEY,
            'access_token': POCKET_ACCESS_TOKEN,
            'sort': 'newest',  # fixed
            'count': count}
    if tag is not None:
        data['tag'] = tag

    resp = requests.post(request_url, data=data)
    if resp.status_code != 200:
        msg = 'failed to get links from Pocket({} {})'.format(
                resp.status_code, resp.headers['X-Error'])
        raise StopPipeline(msg)
    parsed = resp.json()
    items = parsed['list']

    if len(items) == 0:
        msg = 'pocket is empty'
        raise StopPipeline(msg)

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

# <meta  property="og:image"
#        content="https://pbs.twimg.com/media/CV3MKISUYAAAkDi.png:large">
        image_match = re.compile(
            '<meta\s*property=\"og:image\"\s*content="(?P<contents>[^"]*)">')

        searched = image_match.findall(resp.text)
        replaced = [s_link.replace(':large', ':orig') for s_link in searched]

        if replaced and 'profile_images' in replaced[0]:
            link_results.append(
                    {'link': link, 'result': 'only profile pictures'})
            continue  # skip profile picture

        if replaced and 'ext_tw_video_thumb' in replaced[0]:
            link_results.append({'link': link, 'result': 'only videos'})
            continue  # skip video

        link_results.append(
                {'link': link,
                 'result': '{} pictures downloaded'.format(len(replaced))})

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
            msg = \
                'failed to download image file {} from {}'.format(
                    filepath, link)
            # raise StopPipeline(msg)
    return image_files, link_results


def upload_to_dropbox(image_files):
    log.debug('upload to dropbox for {} files'.format(len(image_files)))
    n_success = 0
    client = dropbox.client.DropboxClient(DROPBOX_ACCESS_TOKEN)

    parent_dir = '/Workflow/Twitter/'
    timestamp = datetime.datetime.now().strftime('%Y%m%d')
    dir_name = 'zzalauto-{}'.format(timestamp)
    working_dir = '{}/{}'.format(parent_dir, dir_name)

    try:
        client.file_create_folder(working_dir)
    except dropbox.rest.ErrorResponse as e:
        if not e.status == 403:
            msg = '{}: {}'.format(e.status, e.reason)
            log.exception(
                'failed to upload to Dropbox: {}'.format(e.error_msg))
            raise StopPipeline(msg)

    for image_file in image_files:
        dropbox_path = '{}/{}'.format(working_dir, image_file.split('/')[-1])
        with open(image_file, 'rb') as f:
            try:
                resp = client.put_file(dropbox_path, f, overwrite=True)
                log.debug('uploaded to dropbox: {}({})'.format(
                          resp['path'], resp['size']))
                n_success += 1
            except dropbox.rest.ErrorResponse as e:
                log.exception('failed to upload to Dropbox: {}'.format(
                                e.error_msg))
                msg = '{}: {}'.format(e.status, e.reason)
                raise StopPipeline(msg)
    return n_success


def archive_pocket_links(ids):
    log.debug('archive {} pocket links'.format(len(ids)))
    for id_ in ids:
        request_url = 'https://getpocket.com/v3/send'
        data = {'consumer_key': POCKET_CONSUMER_KEY,
                'access_token': POCKET_ACCESS_TOKEN,
                'actions': json.dumps([{'action': 'archive', 'item_id': id_}])}

        resp = requests.post(request_url, data=data)
        if resp.status_code != 200:
            msg = 'Pocket item could not be archived: {}'.format(id_)
            raise StopPipeline(msg)
    return


def zzalauto_callback(ch, method, properties, body):
    log.info(" [x] Received %r" % (body,))

    prefix = 'zzalauto-'
    link_results = []
    try:
        tmp_path = tempfile.mkdtemp(prefix=prefix)
    except OSError as ose:
        log.exception('could not access to path {}'.format(tmp_path))
        raise ose

    try:
        tag = ''
        count = body
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

    for result in link_results:
        log.info('result - link {0[link]} : {0[result]}'.format(result))
    log.info('contents: {}'.format(contents))
    return 'callback finished'


def consume():
    connection = \
        pika.BlockingConnection(pika.URLParameters(RABBITMQ_BIGWIG_RX_URL))
    channel = connection.channel()
    channel.queue_declare(queue=RABBITMQ_QUEUE)

    channel.basic_consume(zzalauto_callback, queue=RABBITMQ_QUEUE, no_ack=True)
    log.info(' [*] Waiting for messages. To exit press CTRL+C')

    channel.start_consuming()

    return 'consume finished'

if __name__ == '__main__':
    consume()
