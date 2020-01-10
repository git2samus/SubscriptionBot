#!/usr/bin/env python3
"""Reddit SubscriptionBot

Usage: bot.py <command> [<args>...]
       bot.py -h | --help
       bot.py --version

Options:
    -h, --help                  Show this screen
    --version                   Show version

Environment Variables:
    PRAW_SITE                   The name of the bot and the corresponding section on praw.ini
    DATABASE_URL                URI of the Postgres instance to use

The bot.py commands are:
    feed                        Run the subreddit feed parser and comment on new topics
    inbox                       Run the inbox parser and update subscription lists
    comments                    Run the comment parser and track updates on topics
    notifications               Send the notifications for the tracked topics

See 'bot.py help <command>' for more information on a specific command.
"""
import os
from subprocess import run
from docopt import docopt, DocoptExit


__version__ = '1.0.0'

if __name__ == '__main__':
    global_args = docopt(__doc__, version=f'Reddit SubscriptionBot v{__version__}', options_first=True)

    # we'll use the lowercase variant of PRAW_SITE as the reference since that's what praw uses
    praw_site = os.environ.get('PRAW_SITE')
    if praw_site is not None:
        os.environ['praw_site'] = praw_site

    # check the arguments to see if any has set the value
    praw_site = os.environ.get('praw_site')
    if praw_site is None:
        raise DocoptExit("Missing PRAW_SITE value.\n")

    database_url = os.environ.get('DATABASE_URL')
    if database_url is None:
        raise DocoptExit("Missing DATABASE_URL value.\n")

    # continue processing args
    command, args = global_args['<command>'], global_args['<args>']
    subcommands = ('feed', 'inbox', 'comments', 'notifications')

    if command in subcommands:
        # run subcommand
        exit(run(['python3', f'modules/{command}.py', command] + args).returncode)

    if command == 'help' and args:
        help_command = args[0]

        if help_command in subcommands:
            # invoke subcommand's help
            exit(run(['python3', f'modules/{help_command}.py', '--help']).returncode)

        # invalid subcommand
        exit(f"{help_command} is not a bot.py command. See 'bot.py help'.")

    if command in ('help', None):
        # general help
        exit(run(['python3', 'bot.py', '--help']).returncode)

    # invalid subcommand
    exit(f"{command} is not a bot.py command. See 'bot.py help'.")
