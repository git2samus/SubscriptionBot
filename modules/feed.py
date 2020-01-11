#!/usr/bin/env python3
"""Reddit SubscriptionBot - Feed Parser

Usage: bot.py feed <subreddit> [--refresh=<interval>] [--sticky] [--after=<submission-url>]
       bot.py feed -h | --help

Options:
    --refresh=<interval>        Interval in seconds at which the feed is requested, shorter intervals may be rate-limited by Reddit [default: 60]
    --sticky                    Whether or not to make bot comments sticky on posts (requires bot permissions on Reddit)
    --after=<submission-url>    Only process submissions newer than <submission-url> (if omitted will process any new submission since started)
                                Accepts formats supported by https://praw.readthedocs.io/en/latest/code_overview/models/submission.html#praw.models.Submission.id_from_url
    -h, --help                  Show this screen

When invoked it'll start a process that will retrieve new submissions from the <subreddit> subreddit at <interval> seconds
For each new submission a comment from the bot will be posted following the 'bot_comment_template' string pattern from praw.ini
"""
import praw, requests
import xml.etree.ElementTree as ET
from praw.models import Submission
from docopt import docopt
from datetime import datetime, timedelta
from time import sleep
from utils import setup_http_debugging


class FeedProcess(object):
    ATOM_NS = {'atom': 'http://www.w3.org/2005/Atom'}

    def __init__(self, subreddit, interval, sticky):
        self.subreddit, self.interval, self.sticky = subreddit, int(interval), sticky

        self.reddit = praw.Reddit()

        self.http_session = requests.Session()
        self.http_session.headers.update({'user-agent': self.reddit.config.user_agent})

        self._last_timestamp = None

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

        entries = root_elem.findall('atom:entry', self.ATOM_NS)
        for entry_elem in entries:
            id_elem = entry_elem.find('atom:id', self.ATOM_NS)
            yield id_elem.text

    def get_last_submission(self):
        """Retrieve the newest submission from the subreddit"""
        return self._query_feed(limit=1)

    def iter_submissions(self, after_url=None):
        """Infinite generator that yields submission ids in the order they were published"""
        if after_url is None:
            # retrieve last submission from feed
            last = self.get_last_submission()
            entries = tuple(self._parse_feed(last))
            after_id = entries[0]
        else:
            # extract id from submission url or raise ValueError
            submission_id = Submission.id_from_url(after_url)
            submission_kind = self.reddit.config.kinds['submission']
            after_id = f'{submission_kind}_{submission_id}'

        while True:
            # we'll output from oldest to newest but Reddit shows newest first on its feed
            # in order to retrieve the entries published "after" the given one
            # we need to ask for the ones that appear "before" that one in the feed
            response = self._query_feed(before=after_id)
            for submission_id in reversed(tuple(self._parse_feed(response))):
                yield submission_id

            # update after_id with the newest retrieved and loop
            after_id = submission_id

    def run(self, after_url=None):
        """Start process"""
        for submission in self.iter_submissions(after_url):
            print(submission)


if __name__ == '__main__':
    args = docopt(__doc__)

    subreddit, interval, sticky = args['<subreddit>'], args['--refresh'], args['--sticky']
    feed_process = FeedProcess(subreddit, interval, sticky)

    after_url = args['--after']
    feed_process.run(after_url)
