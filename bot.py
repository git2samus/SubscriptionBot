#!/usr/bin/env python3
"""Reddit SubscriptionBot

Usage: bot.py <command> [<args>...]
       bot.py -h | --help
       bot.py --version

Options:
    -h, --help                  Show this screen
    --version                   Show version

Environment Variables:
    PRAW_SITE                   The name of the config section on praw.ini for this process
    DATABASE_URL                URI of the Postgres instance to use

The bot.py commands are:
    feed                        Run the subreddit feed parser and comment on new topics
    inbox                       Run the inbox parser and update subscription lists
    comments                    Run the comment parser and track updates on topics
    notifications               Send the notifications for the tracked topics

See 'bot.py help <command>' for more information on a specific command.
"""
import os
import psycopg2
from sys import exit
from contextlib import closing
from docopt import docopt, DocoptExit

__version__ = '1.0.0'


def init_db(database_url):
    with closing(psycopg2.connect(database_url)) as conn:
        with closing(conn.cursor()) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kv_store(key VARCHAR(32) PRIMARY KEY, value VARCHAR(256));
            """)
            conn.commit()

            cur.execute("""
                SELECT value FROM kv_store WHERE key = 'version';
            """)
            res = cur.fetchone()

            if res is not None:
                db_version = res[0]
                if db_version != __version__:
                    raise Exception(f"Version mismatch (current: {__version__}; db: {db_version})")
            else:
                cur.execute("""
                    CREATE TABLE subscription(submission_id CHAR(6), user_id CHAR(6), PRIMARY KEY(submission_id, user_id));
                    CREATE TABLE comment_count(submission_id CHAR(6), submission_date DATE, comment_count INTEGER DEFAULT 0, PRIMARY KEY(submission_id, submission_date));
                    INSERT INTO kv_store VALUES('version', %s);
                """, (__version__,))
                conn.commit()


if __name__ == '__main__':
    global_args = docopt(__doc__, version=f'Reddit SubscriptionBot v{__version__}', options_first=True)

    # we'll use the lowercase variant of PRAW_SITE as the reference since that's what praw uses
    praw_site = os.getenv('PRAW_SITE')
    if praw_site is not None:
        os.environ['praw_site'] = praw_site

    # check the arguments to see if any has set the value
    praw_site = os.getenv('praw_site')
    if praw_site is None:
        raise DocoptExit("Missing PRAW_SITE value.\n")

    database_url = os.getenv('DATABASE_URL')
    if database_url is None:
        raise DocoptExit("Missing DATABASE_URL value.\n")

    # check db connectivity and setup tables
    init_db(database_url)

    # continue processing args
    command, args = global_args['<command>'], global_args['<args>']
    subcommands = ('feed', 'inbox', 'comments', 'notifications')

    if command in subcommands:
        # run subcommand
        os.execvp('python3', ['python3', f'modules/{command}.py', command] + args)

    if command == 'help' and args:
        help_command = args[0]

        if help_command in subcommands:
            # invoke subcommand's help
            os.execvp('python3', ['python3', f'modules/{help_command}.py', '--help'])

        # invalid subcommand
        exit(f"{help_command} is not a bot.py command. See 'bot.py help'.")

    if command in ('help', None):
        # general help
        os.execvp('python3', ['python3', 'bot.py', '--help'])

    # invalid subcommand
    exit(f"{command} is not a bot.py command. See 'bot.py help'.")
