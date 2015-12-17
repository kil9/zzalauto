# -*- encoding: utf-8 -*-

from flask import Flask
from flask import render_template
import pika

from config import *


app = Flask(__name__)

@app.route('/')
def main():
    return render_template('index.html', contents='zzalauto')


def enqueue_run(message='5'):
    log.debug('received event to publish: {}'.format(message))

    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_BIGWIG_TX_URL))
    channel = connection.channel()

    channel.queue_declare(queue=RABBITMQ_QUEUE)

    channel.basic_publish(exchange='', routing_key=RABBITMQ_QUEUE, body=message)

    connection.close()
    return 'published event. limit: {}'.format(message)

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


if __name__ == '__main__':
    app.run(port=5000, debug=True) # only for test
