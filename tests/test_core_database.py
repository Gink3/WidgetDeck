"""Upgrade contracts for shared persistence independent of optional 4AD."""
import builtins
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from dashboard import database
from dashboard.auth import init_auth, register_auth_routes


class CoreDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = Flask(__name__, root_path=str(Path(__file__).resolve().parents[1]),
                         instance_path=self.directory.name)
        self.app.config.update(TESTING=True, SECRET_KEY='isolated-test-secret')

    def test_authentication_works_without_importing_or_initializing_four_ad(self):
        original = builtins.__import__

        def import_without_four_ad(name, *args, **kwargs):
            if name.startswith('dashboard.four_ad'):
                raise AssertionError('Core authentication imported optional 4AD')
            return original(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=import_without_four_ad):
            init_auth(self.app)
            register_auth_routes(self.app)
            self.app.add_url_rule('/', 'home', lambda: 'home')
            client = self.app.test_client()
            client.get('/register')
            with client.session_transaction() as cookie:
                csrf = cookie['auth_csrf_token']
            response = client.post('/register', data={
                'username': 'core-only', 'password': 'isolated-test-password',
                'csrf_token': csrf,
            })
            self.assertEqual(response.status_code, 302)
            client.post('/logout')
            client.get('/login')
            with client.session_transaction() as cookie:
                csrf = cookie['auth_csrf_token']
            self.assertEqual(client.post('/login', data={
                'username': 'core-only', 'password': 'isolated-test-password',
                'csrf_token': csrf,
            }).status_code, 302)
            with self.app.app_context():
                tables = {r[0] for r in database.db().execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn('dashboard_users', tables)
                self.assertNotIn('four_ad_records', tables)

    def test_legacy_database_shim_can_be_imported_without_private_packages(self):
        import importlib.util
        path = Path(__file__).resolve().parents[1] / 'dashboard/four_ad/models.py'
        spec = importlib.util.spec_from_file_location('legacy_database_shim', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIs(module.db, database.db)
        with self.assertRaises(AttributeError):
            getattr(module, '__path__')

    def test_canonical_database_setting_is_used_when_legacy_is_absent(self):
        filename = str(Path(self.directory.name) / 'custom.sqlite')
        self.app.config['DASHBOARD_DATABASE'] = filename
        init_auth(self.app)
        self.assertEqual(self.app.config['FOUR_AD_DATABASE'], filename)
        with self.app.app_context():
            self.assertEqual(database.db().execute('PRAGMA database_list').fetchone()[2], filename)
            self.assertEqual(database.db().execute('SELECT count(*) FROM dashboard_users').fetchone()[0], 0)

    def test_legacy_setting_preserves_existing_data_and_initialization_is_repeatable(self):
        filename = str(Path(self.directory.name) / 'legacy.sqlite')
        with sqlite3.connect(filename) as connection:
            connection.execute('CREATE TABLE preserved(id INTEGER PRIMARY KEY, value TEXT)')
            connection.execute("INSERT INTO preserved VALUES(7,'existing')")
        self.app.config['FOUR_AD_DATABASE'] = filename
        database.init_database(self.app)
        database.init_database(self.app)
        init_auth(self.app)
        self.assertEqual(self.app.config['DASHBOARD_DATABASE'], filename)
        with self.app.app_context():
            self.assertEqual(database.db().execute('SELECT value FROM preserved WHERE id=7').fetchone()[0], 'existing')
            self.assertEqual(database.db().execute('SELECT count(*) FROM dashboard_users').fetchone()[0], 0)
        self.assertEqual(self.app.teardown_appcontext_funcs.count(database.close_database), 1)

    def test_legacy_runtime_override_and_imports_share_connection(self):
        from dashboard.four_ad import models
        database.init_database(self.app)
        filename = str(Path(self.directory.name) / 'override.sqlite')
        self.app.config['FOUR_AD_DATABASE'] = filename
        with self.app.app_context():
            self.assertIs(models.db(), database.db())
            self.assertEqual(models.db().execute('PRAGMA database_list').fetchone()[2], filename)
            connection = models.db()
            database.close_database()
            models.close_database()
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')
            self.assertIsNot(database.db(), connection)
        self.assertIs(models.timestamp, database.timestamp)

    def test_explicit_distinct_settings_are_not_rewritten(self):
        legacy = str(Path(self.directory.name) / 'legacy.sqlite')
        canonical = str(Path(self.directory.name) / 'canonical.sqlite')
        self.app.config.update(FOUR_AD_DATABASE=legacy, DASHBOARD_DATABASE=canonical)
        database.init_database(self.app)
        self.assertEqual(self.app.config['DASHBOARD_DATABASE'], canonical)
        self.assertEqual(self.app.config['FOUR_AD_DATABASE'], legacy)
        with self.app.app_context():
            self.assertEqual(database.db().execute('PRAGMA database_list').fetchone()[2], legacy)


if __name__ == '__main__':
    unittest.main()
