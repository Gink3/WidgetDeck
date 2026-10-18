"""Existing-data upgrades, persistent claims and separate provider storage."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from dashboard.widgets import API_VERSION, Manifest, WidgetError, register
from dashboard.widgets.storage import prepare
from test_widget_api import document


def manifest(provider='first', ident='example', **overrides):
    return Manifest.from_dict({**document(), 'provider': provider, 'id': ident, **overrides})


class WidgetStorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def app(self):
        return Flask(__name__, instance_path=str(self.root))

    def test_storage_api_has_its_own_compatible_minor_version(self):
        self.assertIn(API_VERSION, manifest(core_api='>=1.2,<2').core_api)
        self.assertIn(API_VERSION, manifest(core_api='>=1.1,<2').core_api)

    def test_concurrent_first_startups_cannot_claim_the_same_id_for_different_providers(self):
        barrier = threading.Barrier(2)
        def claim(provider):
            app = self.app()
            barrier.wait(timeout=5)
            try:
                prepare(app, [manifest(provider)])
                return 'accepted'
            except WidgetError:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, ['first', 'second']))
        self.assertCountEqual(results, ['accepted', 'rejected'])

    def test_provider_swap_after_disable_is_rejected_before_any_factory_import(self):
        prepare(self.app(), [manifest()])
        prepare(self.app(), [])
        with patch('dashboard.widgets.import_module', side_effect=AssertionError('Imported code')):
            with self.assertRaisesRegex(WidgetError, 'reviewed storage migration'):
                register(self.app(), [manifest('replacement')])
        storage = prepare(self.app(), [manifest()])['example']
        self.assertFalse(storage.legacy)

    def test_disable_reenable_and_version_upgrade_preserve_provider_data(self):
        original = prepare(self.app(), [manifest()])['example']
        with original.connect() as connection:
            connection.execute('CREATE TABLE records(id INTEGER PRIMARY KEY, owner INTEGER, value TEXT)')
            connection.execute("INSERT INTO records VALUES(7,11,'saved')")
        prepare(self.app(), [])
        upgraded = prepare(self.app(), [manifest(version='1.1.0')])['example']
        self.assertEqual(upgraded, original)
        with upgraded.connect() as connection:
            self.assertEqual(tuple(connection.execute('SELECT * FROM records').fetchone()), (7,11,'saved'))
        with self.assertRaises(RuntimeError), upgraded.connect() as connection:
            connection.execute("UPDATE records SET value='uncommitted'")
            raise RuntimeError('rollback')
        with upgraded.connect() as connection:
            self.assertEqual(connection.execute('SELECT value FROM records').fetchone()[0], 'saved')

    def test_different_providers_get_distinct_databases_and_file_directories(self):
        first = prepare(self.app(), [manifest()])['example']
        # A separate installation may choose the other provider for this logical ID.
        other = Flask(__name__, instance_path=str(self.root / 'other'))
        second = prepare(other, [manifest('second')])['example']
        self.assertEqual(first.database.relative_to(self.root).as_posix(),
                         'widget-storage/first/example/data.sqlite')
        self.assertEqual(second.database.relative_to(self.root / 'other').as_posix(),
                         'widget-storage/second/example/data.sqlite')
        self.assertNotEqual(first.directory, second.directory)

    def test_old_data_reserves_original_provider_even_when_disabled_on_first_upgrade(self):
        database = self.root / 'dashboard.sqlite'
        with sqlite3.connect(database) as connection:
            connection.execute('CREATE TABLE wordle_games(id INTEGER PRIMARY KEY, data TEXT)')
            connection.execute("INSERT INTO wordle_games VALUES(1,'retained')")
            connection.execute('CREATE TABLE four_ad_records(id TEXT, data TEXT)')
            connection.execute("INSERT INTO four_ad_records VALUES('guild','retained')")
            connection.execute('CREATE TABLE user_settings(user_id INTEGER, data TEXT)')
            connection.execute("INSERT INTO user_settings VALUES(1,'preferences')")
        prepare(self.app(), [])
        for ident in ['wordle', 'four-against-darkness']:
            with self.assertRaisesRegex(WidgetError, 'reviewed storage migration'):
                prepare(self.app(), [manifest('replacement', ident)])
        canonical = manifest('dashboard', 'wordle',
                             entry_point='dashboard.widgets.bundled:register_widget')
        storage = prepare(self.app(), [canonical])['wordle']
        self.assertTrue(storage.legacy)
        self.assertEqual(storage.database, database)
        with storage.connect() as connection:
            self.assertEqual(connection.execute('SELECT data FROM wordle_games').fetchone()[0], 'retained')
            self.assertEqual(connection.execute('SELECT data FROM user_settings').fetchone()[0], 'preferences')

    def test_all_claims_roll_back_if_one_selection_is_rejected(self):
        prepare(self.app(), [manifest()])
        with self.assertRaises(WidgetError):
            prepare(self.app(), [manifest(ident='new'), manifest('replacement')])
        with sqlite3.connect(self.root / 'dashboard.sqlite') as connection:
            ids = [row[0] for row in connection.execute('SELECT widget_id FROM widget_provider_bindings')]
        self.assertEqual(ids, ['example'])

    def test_failed_factory_keeps_claim_so_partially_written_data_cannot_be_reassigned(self):
        module = types.ModuleType('example_widget')
        def fail(app, context):
            with context.storage.connect() as connection:
                connection.execute('CREATE TABLE saved(value TEXT)')
                connection.execute("INSERT INTO saved VALUES('keep')")
            raise RuntimeError('initializer failed after writing data')
        module.register = fail
        with patch.dict(sys.modules, example_widget=module), self.assertRaises(WidgetError):
            register(self.app(), [manifest()])
        with self.assertRaisesRegex(WidgetError, 'reviewed storage migration'):
            prepare(self.app(), [manifest('replacement')])
        with prepare(self.app(), [manifest()])['example'].connect() as connection:
            self.assertEqual(connection.execute('SELECT value FROM saved').fetchone()[0], 'keep')

    def test_explicit_legacy_database_override_controls_registry_and_namespaces(self):
        app = self.app()
        override = self.root / 'custom.sqlite'
        app.config['FOUR_AD_DATABASE'] = str(override)
        storage = prepare(app, [manifest()])['example']
        self.assertTrue(override.exists())
        self.assertFalse((self.root / 'dashboard.sqlite').exists())
        self.assertEqual(storage.database.parent, self.root / 'widget-storage/first/example')

    def test_same_provider_cannot_silently_switch_from_legacy_to_isolated_storage(self):
        canonical = manifest('dashboard', 'wordle',
                             entry_point='dashboard.widgets.bundled:register_widget')
        prepare(self.app(), [canonical])
        with self.assertRaisesRegex(WidgetError, 'reviewed storage migration'):
            prepare(self.app(), [manifest('dashboard', 'wordle')])


if __name__ == '__main__':
    unittest.main()
