#!/usr/bin/env python3
"""Reddit SubscriptionBot - Feed Parser

Usage: subscription_bot.py feed <subreddit> [--sticky] [(--after=<submission-url>|--reset-after)] [--debug]
       subscription_bot.py feed -h | --help

Options:
    --sticky                    Whether or not to make bot comments sticky on posts (requires bot permissions on Reddit)
    --after=<submission-url>    Only process submissions newer than <submission-url> (if omitted will process any new submission since started)
                                Accepts Reddit IDs or URL formats supported by https://praw.readthedocs.io/en/v6.4.0/code_overview/models/submission.html#praw.models.Submission.id_from_url
                                When the process restarts it'll continue from the last submission seen unless overriden by this parameter
    --reset-after               Reset previously saved <submission-url> on database from previous runs
    --debug                     Enable HTTP debugging
    -h, --help                  Show this screen

When invoked it'll start a process that will retrieve new submissions from the <subreddit> subreddit, starting from <submission-url>
For each new submission a comment from the bot will be posted following the 'bot_comment_template' string pattern from praw.ini
"""
from praw.models import Submission
from docopt import docopt
from urllib.parse import urljoin, urlencode, quote
from shared.base import XMLProcess
from shared.utils import setup_http_debugging


class FeedProcess(XMLProcess):
    def __init__(self, subreddit, sticky):
        # setup PRAW, db and http session
        super().__init__(subreddit, 'new', Submission)

        self.sticky = sticky

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

    def run(self, after=None, reset=False):
        """Start process"""
        self.setup_interrupt_handlers()

        # process submissions
        for entry_dict in self.iter_entries(after, reset):
            self.add_bot_comment(entry_dict)


if __name__ == '__main__':
    args = docopt(__doc__)

    if args['--debug']:
        setup_http_debugging()

    subreddit, sticky = args['<subreddit>'], args['--sticky']
    feed_process = FeedProcess(subreddit, sticky)

    after, reset = args['--after'], args['--reset-after']
    feed_process.run(after, reset)
