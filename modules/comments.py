#!/usr/bin/env python3
"""Reddit SubscriptionBot - Comment Parser

Usage: subscription_bot.py comments <subreddit> [(--after=<comment-url>|--reset-after)] [--debug]
       subscription_bot.py comments -h | --help

Options:
    --after=<comment-url>       Only process submissions newer than <comment-url> (if omitted will process any new comment since started)
                                Accepts Reddit IDs or URL formats supported by https://praw.readthedocs.io/en/v6.4.0/code_overview/models/comment.html#praw.models.Comment.id_from_url
                                When the process restarts it'll continue from the last comment seen unless overriden by this parameter
    --reset-after               Reset previously saved <comment-url> on database from previous runs
    --debug                     Enable HTTP debugging
    -h, --help                  Show this screen

When invoked it'll start a process that will retrieve comments from the <subreddit> subreddit, starting from <comment-url>
Each comment will be counted and grouped by day starting at "bot_comments_cutoff_time" from praw.ini
"""
from praw.models import Comment, Submission
from docopt import docopt
from datetime import time, timedelta
from contextlib import closing
from shared.base import XMLProcess
from shared.utils import setup_http_debugging


class CommentProcess(XMLProcess):
    def __init__(self, subreddit):
        # setup PRAW, db and http session
        super().__init__(subreddit, 'comments', Comment)

        self.cutoff_time = self.reddit.config.custom['bot_comments_cutoff_time']
        self.cutoff_time = time.fromisoformat(self.cutoff_time)

        if self.cutoff_time.utcoffset() is None:
            raise Exception("bot_comments_cutoff_time needs to be tz-aware")

    def _get_comment_date(self, updated):
        # comments are grouped by date and dates transition at the specified cutoff time
        comment_date = updated.date()

        if updated.timetz() < self.cutoff_time:
            comment_date = comment_date - timedelta(days=1)

        return comment_date

    def register_comment(self, entry_dict):
        submission_short_id = Submission.id_from_url(entry_dict['link'])
        comment_author = entry_dict['author']['name'][3:]
        comment_date = self._get_comment_date(entry_dict['updated'])

        with closing(self.db.cursor()) as cur:
            # create row to initialize counter then increment
            cur.execute("""
                INSERT INTO comment(submission_id, user_name, comment_date)
                    VALUES(%s, %s, %s)
                ON CONFLICT ON CONSTRAINT comment_pkey
                    DO NOTHING;

                    UPDATE comment SET comment_count = comment_count + 1
                    WHERE submission_id=%s AND user_name=%s AND comment_date=%s;
            """, (submission_short_id, comment_author, comment_date,
                  submission_short_id, comment_author, comment_date))
            self.db.commit()

    def run(self, after=None, reset=False):
        """Start process"""
        self.setup_interrupt_handlers()

        # process submissions
        blacklist = self.reddit.config.custom['bot_comments_blacklist']
        blacklist = {
            name.strip().lower()
            for name in blacklist.split(',')
        }

        for entry_dict in self.iter_entries(after, reset):
            author = entry_dict['author_name'].lower()

            if author not in blacklist:
                self.register_comment(entry_dict)


if __name__ == '__main__':
    args = docopt(__doc__)

    if args['--debug']:
        setup_http_debugging()

    subreddit = args['<subreddit>']
    comment_process = CommentProcess(subreddit)

    after, reset = args['--after'], args['--reset-after']
    comment_process.run(after, reset)
