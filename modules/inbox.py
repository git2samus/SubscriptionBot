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
from base import BaseProcess
from utils import setup_http_debugging


class InboxProcess(BaseProcess):
    message_re = re.compile(f'(Subscribe|Unsubscribe) ({BaseProcess.base36_pattern})')

    def process_message(self, message):
        match = self.message_re.fullmatch(message.subject)
        if match:
            submission_short_id = match.group(2)
            # using 'name' instead of 'id' to avoid an extra request to the API
            user_name = message.author.name

            if match.group(1) == 'Subscribe':
                query_sql = """
                    INSERT INTO subscription(submission_id, user_name) VALUES (%s, %s)
                    ON CONFLICT ON CONSTRAINT subscription_pkey
                        DO NOTHING;
                """
            else:
                query_sql = """
                    DELETE FROM subscription WHERE submission_id=%s AND user_name=%s;
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

        seen_items = []
        for item in self.reddit.inbox.stream():
            if isinstance(item, Message):
                self.process_message(item)
            else:
                self.forward_item(item)

            # https://praw.readthedocs.io/en/latest/code_overview/reddit/inbox.html#praw.models.Inbox.mark_read
            seen_items.append(item)
            if len(seen_items) >= 25:
                self.reddit.inbox.mark_read(seen_items)


if __name__ == '__main__':
    args = docopt(__doc__)

    if args['--debug']:
        setup_http_debugging()

    inbox_process = InboxProcess()
    inbox_process.run()
