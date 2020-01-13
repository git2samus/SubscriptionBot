#!/usr/bin/env python3
"""Reddit SubscriptionBot - Feed Parser

Usage: bot.py feed <subreddit> [--refresh=<interval>] [--sticky] [--after=<submission-url>] [--debug]
       bot.py feed -h | --help

Options:
    --refresh=<interval>        Interval in seconds at which the feed is requested, shorter intervals may be rate-limited by Reddit [default: 60]
    --sticky                    Whether or not to make bot comments sticky on posts (requires bot permissions on Reddit)
    --after=<submission-url>    Only process submissions newer than <submission-url> (if omitted will process any new submission since started)
                                Accepts Reddit IDs or URL formats supported by https://praw.readthedocs.io/en/latest/code_overview/models/submission.html#praw.models.Submission.id_from_url
    --debug                     Enable HTTP debugging
    -h, --help                  Show this screen

When invoked it'll start a process that will retrieve new submissions from the <subreddit> subreddit at <interval> seconds
For each new submission a comment from the bot will be posted following the 'bot_comment_template' string pattern from praw.ini
"""
import re, praw, requests, signal
import xml.etree.ElementTree as ET
from sys import exit
from praw.models import Submission
from docopt import docopt
from datetime import datetime, timedelta
from time import sleep
from configparser import ConfigParser
from unittest.mock import patch
from urllib.parse import urljoin, urlencode, quote
from utils import setup_http_debugging


class FeedProcess(object):
    ATOM_NS = {'atom': 'http://www.w3.org/2005/Atom'}

    @patch('praw.config.configparser.RawConfigParser', new=ConfigParser)
    def __init__(self, subreddit, interval, sticky):
        self.subreddit, self.interval, self.sticky = subreddit, int(interval), sticky

        self.reddit = praw.Reddit()

        self.http_session = requests.Session()
        self.http_session.headers.update({'user-agent': self.reddit.config.user_agent})

        self._last_timestamp = None

    def _exit_handler(self, signum, frame):
        exit(0)

    def _to_short_id(self, full_id):
        """Remove prefix from base36 id"""
        return full_id.split('_').pop()

    def _to_full_id(self, kind, short_id):
        """Add prefix to base36 id"""
        prefix = self.reddit.config.kinds[kind]
        return prefix + '_' + short_id

    def _query_feed(self, **query):
        """Query the subreddit feed with the given params, will block up to <interval> seconds since last request"""
        if self._last_timestamp is not None:
            delay = (self._last_timestamp + timedelta(seconds=self.interval) - datetime.utcnow()).total_seconds()

            if delay > 0:
                sleep(delay)

        feed_url = f'https://www.reddit.com/r/{self.subreddit}/new/.rss'
        response = self.http_session.get(feed_url, params=query)

        self._last_timestamp = datetime.utcnow()
        return response

    def _parse_feed(self, response):
        """Get a feed response and return a generator of submission ids"""
        root_elem = ET.fromstring(response.text)

        entries = root_elem.iterfind('atom:entry', self.ATOM_NS)
        for entry_elem in entries:
            author_elem = entry_elem.find('atom:author', self.ATOM_NS)
            author = {
                'name': author_elem.find('atom:name', self.ATOM_NS).text,
                'uri': author_elem.find('atom:uri', self.ATOM_NS).text,
            }

            category_elem = entry_elem.find('atom:category', self.ATOM_NS)
            category = category_elem.attrib

            content = entry_elem.find('atom:content', self.ATOM_NS).text

            full_id = entry_elem.find('atom:id', self.ATOM_NS).text

            link = entry_elem.find('atom:link', self.ATOM_NS).attrib['href']

            updated = entry_elem.find('atom:updated', self.ATOM_NS).text
            updated_dt = datetime.strptime(updated, '%Y-%m-%dT%H:%M:%S%z')

            title = entry_elem.find('atom:title', self.ATOM_NS).text

            yield {
                'author': author,
                'category': category,
                'content': content,
                'id': full_id,
                'link': link,
                'updated': updated_dt,
                'title': title,
            }

    def get_last_submission(self):
        """Retrieve the newest submission from the subreddit"""
        return self._query_feed(limit=1)

    def iter_submissions(self, after=None):
        """Infinite generator that yields submission ids in the order they were published"""
        submission_prefix = self.reddit.config.kinds['submission']
        base36_pattern = '[0-9a-z]{6}'

        if after is None:
            # retrieve last submission from feed
            last = self.get_last_submission()
            entries = tuple(self._parse_feed(last))
            after_full_id = entries[0]['id']
        elif re.fullmatch(submission_prefix + '_' + base36_pattern, after):
            # received full_id
            after_full_id = after
        elif re.fullmatch(base36_pattern, after):
            # received short_id
            after_full_id = self._to_full_id(after)
        else:
            # extract id from submission url or raise ValueError
            after_short_id = Submission.id_from_url(after)
            after_full_id = self._to_full_id('submission', after_short_id)

        while True:
            # we'll output from oldest to newest but Reddit shows newest first on its feed
            # in order to retrieve the entries published "after" the given one
            # we need to ask for the ones that appear "before" that one in the feed
            response = self._query_feed(before=after_full_id)
            for entry_dict in reversed(tuple(self._parse_feed(response))):
                yield entry_dict
                # keep track of the id for the next _query_feed() call
                after_full_id = entry_dict['id']

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
        submission.reply(comment_msg)

    def run(self, after=None):
        """Start process"""
        # setup interrupt handlers
        signal.signal(signal.SIGINT, self._exit_handler)
        signal.signal(signal.SIGTERM, self._exit_handler)

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
