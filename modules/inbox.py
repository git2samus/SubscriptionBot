#!/usr/bin/env python3
"""Reddit SubscriptionBot - Inbox Parser

Usage: bot.py inbox [--debug]
       bot.py inbox -h | --help

Options:
    --debug                     Enable HTTP debugging
    -h, --help                  Show this screen

This command runs the process that monitors the bot's inbox for subscribe/unsusbscribe messages.
"""
from praw.models import Message
from docopt import docopt
from base import BaseProcess
from utils import setup_http_debugging


class InboxProcess(BaseProcess):
    def process_message(self, item):
        print(f'Process {item.__class__}:{item}')

    def forward_message(self, item):
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
                self.forward_message(item)

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
