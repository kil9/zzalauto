# -*- encoding: utf-8 -*-

import os
import sys
import logging

from logentries import LogentriesHandler


POCKET_CONSUMER_KEY = os.environ['POCKET_CONSUMER_KEY']
POCKET_ACCESS_TOKEN = os.environ['POCKET_ACCESS_TOKEN']

DROPBOX_ACCESS_TOKEN = os.environ['DROPBOX_ACCESS_TOKEN']

NUMEROUS_AUTH_STRING = os.environ['NUMEROUS_AUTH_STRING']
NUMEROUS_METRIC_ID = os.environ['NUMEROUS_METRIC_ID']

LOGENTRIES_KEY = os.environ['LOGENTRIES_KEY']

RABBITMQ_BIGWIG_RX_URL = os.environ['RABBITMQ_BIGWIG_RX_URL']
RABBITMQ_BIGWIG_TX_URL = os.environ['RABBITMQ_BIGWIG_TX_URL']

RABBITMQ_QUEUE = 'zzalauto_jobqueue'

LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=LOG_FORMAT)

log = logging.getLogger(__name__)
log.addHandler(LogentriesHandler(LOGENTRIES_KEY))

