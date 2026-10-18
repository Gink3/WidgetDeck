"""Fresh multi-worker initialization must not race on administrator creation."""
from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from flask import Flask
from werkzeug.security import check_password_hash, generate_password_hash
from dashboard.auth import bootstrap_admin, init_auth


class AdminBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = Flask(__name__, instance_path=self.folder.name)
        self.app.config['SECRET_KEY'] = 'isolated-test-secret'
        init_auth(self.app)

    def test_concurrent_workers_create_exactly_one_administrator(self):
        barrier = threading.Barrier(2)
        original_connect = sqlite3.connect
        class RacingConnection(sqlite3.Connection):
            def execute(connection, sql, *args, **kwargs):
                cursor = super().execute(sql, *args, **kwargs)
                if sql.startswith('SELECT id FROM dashboard_users WHERE username='):
                    barrier.wait(timeout=10)
                return cursor
        def connect(*args, **kwargs):
            return original_connect(*args, factory=RacingConnection, **kwargs)
        with patch.dict(os.environ, DASHBOARD_ADMIN_USERNAME='bootstrap-test',
                        DASHBOARD_ADMIN_PASSWORD='bootstrap-test-passphrase'), \
             patch('dashboard.auth.sqlite3.connect', side_effect=connect):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [pool.submit(bootstrap_admin, self.app) for _ in range(2)]
                for result in results:
                    result.result(timeout=20)
        with original_connect(self.app.config['DASHBOARD_DATABASE']) as connection:
            rows = connection.execute('SELECT username,password_hash,is_admin FROM dashboard_users').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 'bootstrap-test')
        self.assertEqual(rows[0][2], 1)
        self.assertTrue(check_password_hash(rows[0][1], 'bootstrap-test-passphrase'))

    def test_existing_case_insensitive_account_keeps_password_and_creation_date(self):
        password_hash = generate_password_hash('original-test-passphrase')
        with sqlite3.connect(self.app.config['DASHBOARD_DATABASE']) as connection:
            connection.execute('INSERT INTO dashboard_users(username,password_hash,created_at) VALUES(?,?,?)',
                               ('Existing', password_hash, 'old-date'))
        with patch.dict(os.environ, DASHBOARD_ADMIN_USERNAME='existing',
                        DASHBOARD_ADMIN_PASSWORD='replacement-test-passphrase'):
            bootstrap_admin(self.app)
        with sqlite3.connect(self.app.config['DASHBOARD_DATABASE']) as connection:
            rows = connection.execute('SELECT username,password_hash,is_admin,created_at FROM dashboard_users').fetchall()
        self.assertEqual(rows, [('Existing', password_hash, 1, 'old-date')])

    def test_missing_configuration_does_not_create_an_account(self):
        with patch.dict(os.environ, DASHBOARD_ADMIN_USERNAME='', DASHBOARD_ADMIN_PASSWORD=''):
            bootstrap_admin(self.app)
        with sqlite3.connect(self.app.config['DASHBOARD_DATABASE']) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM dashboard_users').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
