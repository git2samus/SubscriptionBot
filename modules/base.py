import re, os, signal
import praw, psycopg2
import requests
import xml.etree.ElementTree as ET
from sys import exit
from datetime import datetime, timezone, timedelta
from time import sleep
from configparser import ConfigParser
from contextlib import closing
from unittest.mock import patch


class APIProcess(object):
    base36_pattern = '[0-9a-z]+'

    @patch('praw.config.configparser.RawConfigParser', new=ConfigParser)
    def __init__(self):
        # PRAW reads the env variable 'praw_site' automatically
        self.reddit = praw.Reddit()

        # check db connectivity and setup tables
        self.db = psycopg2.connect(os.getenv('DATABASE_URL'))
        self.init_db()

    def _to_short_id(self, full_id):
        """Remove prefix from base36 id"""
        return full_id.split('_').pop()

    def _to_full_id(self, kind, short_id):
        """Add prefix to base36 id"""
        prefix = self.reddit.config.kinds[kind]
        return f'{prefix}_{short_id}'

    def _exit_handler(self, signum, frame):
        # disconnect db
        self.db.commit()
        self.db.close()

        # end process
        exit(0)

    def init_db(self):
        source_version = os.getenv('SOURCE_VERSION')

        with closing(self.db.cursor()) as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kv_store(
                    key VARCHAR(256),
                    value VARCHAR(256),
                        CONSTRAINT kv_store_pkey PRIMARY KEY(key));
            """)
            self.db.commit()

            # get current db version (if any)
            cur.execute("""
                SELECT value FROM kv_store
                    WHERE key='version';
            """)
            res = cur.fetchone()

            if res is not None:
                db_version = res[0]
                if db_version != source_version:
                    raise Exception(f"Version mismatch (current: {source_version}; db: {db_version})")
            else:
                # create remaining tables and save version
                cur.execute("""
                    CREATE TABLE subscription(
                        submission_id VARCHAR(16),
                        user_name VARCHAR(256),
                            CONSTRAINT subscription_pkey PRIMARY KEY(submission_id, user_name));

                    CREATE TABLE comment(
                        submission_id VARCHAR(16),
                        user_name VARCHAR(256),
                        comment_date DATE,
                        comment_count INTEGER DEFAULT 0,
                            CONSTRAINT comment_pkey PRIMARY KEY(submission_id, user_name, comment_date));

                    INSERT INTO kv_store(key, value)
                        VALUES ('version', %s);
                """, (source_version,))
                self.db.commit()

    def setup_interrupt_handlers(self):
        signal.signal(signal.SIGINT, self._exit_handler)
        signal.signal(signal.SIGTERM, self._exit_handler)


class XMLProcess(APIProcess):
    ATOM_NS = {'atom': 'http://www.w3.org/2005/Atom'}

    def __init__(self, subreddit, path, kind_class):
        # create PRAW instance and db connection
        super().__init__()

        # create requests session to retrieve feeds
        self.http_session = requests.Session()
        self.http_session.headers.update({'user-agent': self.reddit.config.user_agent})

        # feed global params
        self.subreddit, self.path, self.kind_class = subreddit, path, kind_class
        self.kind = self.reddit.config.kinds[self.kind_class.__name__.lower()]

        # private (stateful) vars
        self._last_timestamp = None
        self._after_full_id = None
        self._db_key = f'{self.subreddit}_{self.path}_after_full_id'

    def _exit_handler(self, signum, frame):
        if self._after_full_id is not None:
            # save last id seen for this path
            with closing(self.db.cursor()) as cur:
                cur.execute("""
                    INSERT INTO kv_store(key, value)
                        VALUES(%s, %s)
                    ON CONFLICT ON CONSTRAINT kv_store_pkey
                        DO UPDATE SET value=%s WHERE kv_store.key=%s;
                """, (self._db_key, self._after_full_id,
                      self._after_full_id, self._db_key))
                self.db.commit()

        # terminate process
        super()._exit_handler(signum, frame)

    def _query_feed(self, **query):
        """Query the subreddit feed with the given params, return a list of entries from oldest to newest"""

        feed_url = f'https://www.reddit.com/r/{self.subreddit}/{self.path}/.rss'

        # feeds seem to be limited to 100 results per page
        query.setdefault('limit', 100)

        # the error message from the feed says not to request more than once every two seconds and has a retry counter but it doesn't seem reliable
        delay, max_delay = 15, 120
        while True:
            if self._last_timestamp is not None:
                wait = (self._last_timestamp + timedelta(seconds=delay) - datetime.utcnow()).total_seconds()
                if wait > 0:
                    #XXX log
                    print(f'@@@ wait {wait}s')
                    sleep(wait)

            response = self.http_session.get(feed_url, params=query)
            self._last_timestamp = datetime.utcnow()

            if response.text.startswith('<!doctype html>'):
                #XXX warning
                print(f'@@@ html doctype')
                print(response.text)
                pass
            else:
                root_elem = ET.fromstring(response.text)
                entries = root_elem.findall('atom:entry', self.ATOM_NS)

                if len(entries) > 0:
                    break

            delay = min(2 * delay, max_delay)

        result = []
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
            updated_dt = datetime.fromisoformat(updated).astimezone(timezone.utc)

            title = entry_elem.find('atom:title', self.ATOM_NS).text

            result.append({
                'author': author,
                'category': category,
                'content': content,
                'id': full_id,
                'link': link,
                'updated': updated_dt,
                'title': title,
            })

        result.reverse()
        return result

    def get_last_entry(self):
        """Retrieve the newest submission from the subreddit"""
        entries = self._query_feed(limit=1)
        self._after_full_id = entries[0]['id']

    def iter_entries(self, after=None, reset=False):
        """Infinite generator that yields entry dicts in the order they were published"""
        if reset:
            self.get_last_entry()
        elif after is None:
            # check if we've stored the id on the previous run
            with closing(self.db.cursor()) as cur:
                cur.execute("""
                    SELECT value FROM kv_store
                        WHERE key=%s;
                """, (self._db_key,))
                res = cur.fetchone()

            if res is not None:
                self._after_full_id = res[0]
            else:
                self.get_last_entry()
        elif re.fullmatch(self.kind + '_' + self.base36_pattern, after):
            # received full_id
            self._after_full_id = after
        elif re.fullmatch(self.base36_pattern, after):
            # received short_id
            self._after_full_id = f'{self.kind}_{after}'
        else:
            # extract id from submission url or raise ValueError
            after_short_id = self.kind_class.id_from_url(after)
            self._after_full_id = f'{self.kind}_{after_short_id}'

        while True:
            # we'll output from oldest to newest but Reddit shows newest first on its feed
            # in order to retrieve the entries published "after" the given one
            # we need to ask for the ones that appear "before" that one in the feed
            for entry_dict in self._query_feed(before=self._after_full_id):
                yield entry_dict
                # keep track of the id for the next _query_feed() call
                self._after_full_id = entry_dict['id']
