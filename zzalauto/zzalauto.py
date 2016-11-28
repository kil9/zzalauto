# -*- encoding: utf-8 -*-

import json

from flask import Flask
from flask import render_template
import pika
import requests

from config import *


app = Flask(__name__)


class StopPipeline(Exception):
    def __init__(self, msg):
        self.msg = msg


@app.route('/')
def main():
    return render_template('index.html', contents='zzalauto')


def enqueue_run(message='5'):
    log.debug('received event to publish: {}'.format(message))

    connection = \
        pika.BlockingConnection(pika.URLParameters(RABBITMQ_BIGWIG_TX_URL))
    channel = connection.channel()

    channel.queue_declare(queue=RABBITMQ_QUEUE)

    channel.basic_publish(
            exchange='', routing_key=RABBITMQ_QUEUE, body=message)

    connection.close()
    return 'published event. limit: {}\n'.format(message)


@app.route('/run')
@app.route('/run/<int:count>')
@app.route('/run/<tag>')
@app.route('/run/<tag>/<int:count>')
def run(tag=None, count=5):
    log.info('activated for tag: {}, count: {}'.format(tag, count))

# TODO: tag is ignored for now
    if tag in ('notag', 'untagged', '_untagged_'):
        tag = '_untagged_'

    try:
        msg = enqueue_run(str(count))
    except:
        msg = 'failed to enqueue zzalauto run event'
        log.error(msg)
    return msg


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
    request_url = request_url_pattern.format(NUMEROUS_METRIC_ID)

    headers = {'Authorization': NUMEROUS_AUTH_STRING,
               'Content-Type': 'application/json'}
    payload = {'Value': value}
    if action == 'ADD':
        payload['action'] = action
    data = json.dumps(payload)
    resp = requests.post(request_url, headers=headers, data=data)
    if resp.status_code not in (200, 201):
        msg = 'failed to update metric'
        raise StopPipeline(msg)

    result = 'metric is updated to: {}\n'.format(resp.json()['value'])
    return result


if __name__ == '__main__':
    app.run(port=5000, debug=True)  # only for test
