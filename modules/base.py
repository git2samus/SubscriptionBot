import os, signal
import praw, psycopg2
from sys import exit
from configparser import ConfigParser
from contextlib import closing
from unittest.mock import patch


class BaseProcess(object):
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
        return prefix + '_' + short_id

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
                    key VARCHAR(32),
                    value VARCHAR(256),
                        CONSTRAINT kv_store_pkey PRIMARY KEY(key));
            """)
            self.db.commit()

            # get current db version (if any)
            cur.execute("""
                SELECT value FROM kv_store WHERE key='version';
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

                    CREATE TABLE comment_count(
                        submission_id VARCHAR(16),
                        submission_date DATE,
                        comment_count INTEGER DEFAULT 0,
                            CONSTRAINT comment_count_pkey PRIMARY KEY(submission_id, submission_date));

                    INSERT INTO kv_store(key, value) VALUES ('version', %s);
                """, (source_version,))
                self.db.commit()

    def run(self):
        # setup interrupt handlers
        signal.signal(signal.SIGINT, self._exit_handler)
        signal.signal(signal.SIGTERM, self._exit_handler)
