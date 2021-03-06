#!/usr/bin/env python3
"""Reddit SubscriptionBot

Usage: subscription_bot.py <command> [<args>...]
       subscription_bot.py -h | --help
       subscription_bot.py --version

Options:
    -h, --help                  Show this screen
    --version                   Show version

Environment Variables:
    PRAW_SITE                   The name of the config section on praw.ini for this process
    DATABASE_URL                URI of the Postgres instance to use

The subscription_bot.py commands are:
    feed                        Run the subreddit feed parser and comment on new topics
    inbox                       Run the inbox parser and update subscription lists
    comments                    Run the comment parser and track updates on topics
    notifications               Send the notifications for the tracked topics

See 'subscription_bot.py help <command>' for more information on a specific command.
"""
import os
from sys import exit
from docopt import docopt, DocoptExit

__version__ = '1.0.0'


if __name__ == '__main__':
    global_args = docopt(__doc__, version=f'Reddit SubscriptionBot v{__version__}', options_first=True)

    # we'll use the lowercase variant of PRAW_SITE as the reference since that's what praw uses
    praw_site = os.getenv('PRAW_SITE')
    if praw_site is not None:
        os.environ['praw_site'] = praw_site

    # check the arguments to see if any has set the value
    praw_site = os.getenv('praw_site')
    if praw_site is None:
        raise DocoptExit("Missing PRAW_SITE variable.\n")

    database_url = os.getenv('DATABASE_URL')
    if database_url is None:
        raise DocoptExit("Missing DATABASE_URL variable.\n")

    # communicate source version to the next step
    os.environ['SOURCE_VERSION'] = __version__

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
        exit(f"{help_command} is not a subscription_bot.py command. See 'subscription_bot.py help'.")

    if command in ('help', None):
        # general help
        os.execvp('python3', ['python3', 'subscription_bot.py', '--help'])

    # invalid subcommand
    exit(f"{command} is not a subscription_bot.py command. See 'subscription_bot.py help'.")
