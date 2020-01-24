import os, signal
import praw, psycopg2
from sys import exit
from configparser import ConfigParser
from unittest.mock import patch


class BaseProcess(object):
    base36_pattern = '[0-9a-z]{6}'

    @patch('praw.config.configparser.RawConfigParser', new=ConfigParser)
    def __init__(self):
        # PRAW reads the env variable 'praw_site' automatically
        self.reddit = praw.Reddit()
        self.db = psycopg2.connect(os.getenv('DATABASE_URL'))

    def _to_short_id(self, full_id):
        """Remove prefix from base36 id"""
        return full_id.split('_').pop()

    def _to_full_id(self, kind, short_id):
        """Add prefix to base36 id"""
        prefix = self.reddit.config.kinds[kind]
        return prefix + '_' + short_id

    def _exit_handler(self, signum, frame):
        exit(0)

    def run(self):
        # setup interrupt handlers
        signal.signal(signal.SIGINT, self._exit_handler)
        signal.signal(signal.SIGTERM, self._exit_handler)
