#!/usr/bin/env python3
"""Reddit SubscriptionBot - Inbox Parser

Usage: bot.py inbox [--debug]
       bot.py inbox -h | --help

Options:
    --debug                     Enable HTTP debugging
    -h, --help                  Show this screen

This command runs the process that monitors the bot's inbox for subscribe/unsusbscribe messages.
"""
import re
from praw.models import Message
from docopt import docopt
from contextlib import closing
from base import APIProcess
from utils import setup_http_debugging


class InboxProcess(APIProcess):
    message_re = re.compile(f'(Subscribe|Unsubscribe) ({APIProcess.base36_pattern})')

    def __init__(self):
        # create PRAW instance and db connection
        super().__init__()

        self._seen_items = []

    def _exit_handler(self, signum, frame):
        self._flush_seen()

        # terminate process
        super()._exit_handler(signum, frame)

    def _flush_seen(self):
        self.reddit.inbox.mark_read(self._seen_items)
        self._seen_items = []

    def _add_seen(self, item):
        self._seen_items.append(item)

        # https://praw.readthedocs.io/en/latest/code_overview/reddit/inbox.html#praw.models.Inbox.mark_read
        if len(self._seen_items) >= 25:
            self._flush_seen()

    def process_message(self, message):
        match = self.message_re.fullmatch(message.subject)
        if match:
            submission_short_id = match.group(2)
            # using 'name' instead of 'id' to avoid an extra request to the API
            user_name = message.author.name

            if match.group(1) == 'Subscribe':
                query_sql = """
                    INSERT INTO subscription(submission_id, user_name)
                        VALUES (%s, %s)
                    ON CONFLICT ON CONSTRAINT subscription_pkey
                        DO NOTHING;
                """
            else:
                query_sql = """
                    DELETE FROM subscription
                        WHERE submission_id=%s AND user_name=%s;
                """

            with closing(self.db.cursor()) as cur:
                cur.execute(query_sql, (submission_short_id, user_name))
                self.db.commit()
        else:
            self.forward_item(message)

    def forward_item(self, item):
        print(f'Forward {item.__class__}:{item}')

    def run(self):
        """Start process"""
        # setup interrupt handlers
        super().run()

        for item in self.reddit.inbox.stream():
            if isinstance(item, Message):
                self.process_message(item)
            else:
                self.forward_item(item)

            self._add_seen(item)


if __name__ == '__main__':
    args = docopt(__doc__)

    if args['--debug']:
        setup_http_debugging()

    inbox_process = InboxProcess()
    inbox_process.run()
