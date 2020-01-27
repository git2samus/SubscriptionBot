#!/usr/bin/env python3
"""Reddit SubscriptionBot - Feed Parser

Usage: bot.py feed <subreddit> [--refresh=<interval>] [--sticky] [--after=<submission-url>] [--debug]
       bot.py feed -h | --help

Options:
    --refresh=<interval>        Interval in seconds at which the feed is requested, shorter intervals may be rate-limited by Reddit [default: 60]
    --sticky                    Whether or not to make bot comments sticky on posts (requires bot permissions on Reddit)
    --after=<submission-url>    Only process submissions newer than <submission-url> (if omitted will process any new submission since started)
                                Accepts Reddit IDs or URL formats supported by https://praw.readthedocs.io/en/v6.4.0/code_overview/models/submission.html#praw.models.Submission.id_from_url
                                When the process restarts it'll continue from the last submission seen unless overriden by this parameter
    --debug                     Enable HTTP debugging
    -h, --help                  Show this screen

When invoked it'll start a process that will retrieve new submissions from the <subreddit> subreddit at <interval> seconds
For each new submission a comment from the bot will be posted following the 'bot_comment_template' string pattern from praw.ini
"""
import re
import requests
import xml.etree.ElementTree as ET
from praw.models import Submission
from docopt import docopt
from datetime import datetime, timedelta
from time import sleep
from contextlib import closing
from urllib.parse import urljoin, urlencode, quote
from base import XMLProcess
from utils import setup_http_debugging


class FeedProcess(XMLProcess):
    def __init__(self, subreddit, interval, sticky):
        # setup PRAW, db and http session
        super().__init__(subreddit, interval)

        self.sticky = sticky

        self._after_full_id = None

    def _exit_handler(self, signum, frame):
        if self._after_full_id is not None:
            with closing(self.db.cursor()) as cur:
                cur.execute("""
                    INSERT INTO kv_store(key, value) VALUES('feed_after_full_id', %s)
                    ON CONFLICT ON CONSTRAINT kv_store_pkey
                        DO UPDATE SET value=%s WHERE kv_store.key='feed_after_full_id';
                """, (self._after_full_id, self._after_full_id,))
                self.db.commit()

        # terminate process
        super()._exit_handler(signum, frame)

    def iter_submissions(self, after=None):
        """Infinite generator that yields submission dicts in the order they were published"""
        submission_prefix = self.reddit.config.kinds['submission']

        if after is None:
            # check if we've stored the id on the previous run
            with closing(self.db.cursor()) as cur:
                cur.execute("""
                    SELECT value FROM kv_store WHERE key='feed_after_full_id';
                """)
                res = cur.fetchone()

            if res is not None:
                self._after_full_id = res[0]
            else:
                # retrieve last submission from feed
                last = self.get_last_submission('new')
                entries = tuple(self._parse_feed(last))
                self._after_full_id = entries[0]['id']
        elif re.fullmatch(submission_prefix + '_' + self.base36_pattern, after):
            # received full_id
            self._after_full_id = after
        elif re.fullmatch(self.base36_pattern, after):
            # received short_id
            self._after_full_id = self._to_full_id(after)
        else:
            # extract id from submission url or raise ValueError
            after_short_id = Submission.id_from_url(after)
            self._after_full_id = self._to_full_id('submission', after_short_id)

        while True:
            # we'll output from oldest to newest but Reddit shows newest first on its feed
            # in order to retrieve the entries published "after" the given one
            # we need to ask for the ones that appear "before" that one in the feed
            response = self._query_feed('new', before=self._after_full_id)
            for entry_dict in reversed(tuple(self._parse_feed(response))):
                yield entry_dict
                # keep track of the id for the next _query_feed() call
                self._after_full_id = entry_dict['id']

    def add_bot_comment(self, entry_dict):
        """Comment on the given submission with the links to subscribe/unsubscribe"""
        send_message_url = urljoin(self.reddit.config.reddit_url, '/message/compose/')

        bot_username = self.reddit.config.custom['bot_username']
        submission_short_id = self._to_short_id(entry_dict['id'])

        subscribe_message_params = {
            'to': bot_username,
            'subject': 'Subscribe ' + submission_short_id,
            'message': self.reddit.config.custom['bot_subscribe_message_template'].format(**entry_dict),
        }
        subscribe_link = send_message_url + '?' + urlencode(subscribe_message_params, quote_via=quote, safe='')

        unsubscribe_message_params = {
            'to': bot_username,
            'subject': 'Unsubscribe ' + submission_short_id,
            'message': self.reddit.config.custom['bot_unsubscribe_message_template'].format(**entry_dict),
        }
        unsubscribe_link = send_message_url + '?' + urlencode(unsubscribe_message_params, quote_via=quote, safe='')

        comment_template = self.reddit.config.custom['bot_submission_comment_template']
        comment_msg = comment_template.format(
            subscribe_link=subscribe_link,
            unsubscribe_link=unsubscribe_link,
            **self.reddit.config.custom
        )

        submission = self.reddit.submission(id=submission_short_id)
        comment = submission.reply(comment_msg)

        if self.sticky:
            comment.mod.distinguish(sticky=True)

    def run(self, after=None):
        """Start process"""
        # setup interrupt handlers
        super().run()

        # process submissions
        for entry_dict in self.iter_submissions(after):
            self.add_bot_comment(entry_dict)


if __name__ == '__main__':
    args = docopt(__doc__)

    if args['--debug']:
        setup_http_debugging()

    subreddit, interval, sticky = args['<subreddit>'], args['--refresh'], args['--sticky']
    feed_process = FeedProcess(subreddit, interval, sticky)

    after = args['--after']
    feed_process.run(after)
