"""Reviewed migrations use disposable stores and invented data only."""
from contextlib import closing
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from flask import Flask
from dashboard.widgets import Manifest, WidgetError
from dashboard.widgets.__main__ import main
from dashboard.widgets.migrations import plan, execute
from dashboard.widgets.storage import prepare
from test_widget_api import document


class WidgetMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.database = self.root/'dashboard.sqlite'
        self.old = Manifest.from_dict({**document(), 'provider':'original'})
        self.new = Manifest.from_dict({**document(), 'provider':'replacement', 'version':'2.0.0',
            'storage_migrations': {'original/example': {'from_version':'>=1,<2','entry_point':'migration_fixture:copy'}}})
        self.app = Flask(__name__, instance_path=str(self.root))
        self.store = prepare(self.app,[self.old])['example']
        with self.store.connect() as connection:
            connection.execute('CREATE TABLE notes(id INTEGER PRIMARY KEY, owner INTEGER, body TEXT)')
            connection.execute("INSERT INTO notes VALUES(7,11,'invented fixture')")
        with sqlite3.connect(self.database) as connection:
            connection.execute('CREATE TABLE preferences(owner INTEGER, value TEXT)')
            connection.execute("INSERT INTO preferences VALUES(11,'preserve')")
        self.module = types.ModuleType('migration_fixture')
        self.calls = 0
        def copy(source,target):
            self.calls += 1
            target.execute('CREATE TABLE notes(id INTEGER PRIMARY KEY, owner INTEGER, body TEXT)')
            target.executemany('INSERT INTO notes VALUES(?,?,?)', source.execute('SELECT * FROM notes').fetchall())
        self.module.copy = copy
        self.patch = patch.dict(sys.modules,migration_fixture=self.module);self.patch.start();self.addCleanup(self.patch.stop)

    def proposed(self, manifest=None):
        return plan(manifest or self.new,self.database,'original','1.0.0','2.0.0')

    def apply(self, manifest=None, **overrides):
        target = manifest or self.new
        return execute(target,self.database,'original','1.0.0','2.0.0',
            plan_id=overrides.get('plan_id',self.proposed(target)['plan_id']),offline=overrides.get('offline',True))

    def binding(self):
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute('SELECT provider,version FROM widget_provider_bindings').fetchone()

    def test_metadata_roundtrip_and_invalid_declarations(self):
        self.assertEqual(Manifest.from_dict(self.new.to_dict()),self.new)
        for declarations in [[], {'wrong/other':{'from_version':'>=1','entry_point':'m:f'}},
            {'original/example':{'from_version':'','entry_point':'m:f'}},
            {'original/example':{'from_version':'broken','entry_point':'m:f'}},
            {'original/example':{'from_version':'>=1','entry_point':'call()'}},
            {'original/example':{'from_version':'>=1','entry_point':'m:f','extra':True}}]:
            with self.subTest(value=declarations),self.assertRaises(WidgetError):
                Manifest.from_dict({**document(),'storage_migrations':declarations})

    def test_dry_run_does_not_import_code_or_change_stores(self):
        before = self.database.read_bytes()
        with patch('dashboard.widgets.migrations.import_module',side_effect=AssertionError('Imported hook')):
            proposed = self.proposed()
        self.assertFalse(proposed['already_applied'])
        self.assertFalse(Path(proposed['target_database']).exists())
        self.assertEqual(self.database.read_bytes(),before)
        self.assertEqual(self.calls,0)

    def test_reviewed_migration_is_repeatable_and_preserves_old_data_preferences(self):
        result = self.apply()
        self.assertTrue(result['already_applied'])
        backup=Path(result['backup_directory'])
        with closing(sqlite3.connect(backup/'dashboard.sqlite')) as connection:
            self.assertEqual(connection.execute('SELECT provider FROM widget_provider_bindings').fetchone()[0],'original')
        self.assertEqual((backup/'dashboard.sqlite').stat().st_mode & 0o777,0o600)
        self.assertEqual(self.binding(),('replacement','2.0.0'))
        self.apply()
        self.assertEqual(self.calls,1)
        new = prepare(Flask(__name__,instance_path=str(self.root)),[self.new])['example']
        for store in [self.store,new]:
            with store.connect() as connection:
                self.assertEqual(tuple(connection.execute('SELECT * FROM notes').fetchone()),(7,11,'invented fixture'))
        prepare(Flask(__name__,instance_path=str(self.root)),[])
        prepare(Flask(__name__,instance_path=str(self.root)),[self.new])
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute('SELECT value FROM preferences').fetchone()[0],'preserve')
        with self.assertRaisesRegex(WidgetError,'reviewed storage migration'):
            prepare(Flask(__name__,instance_path=str(self.root)),[self.old])

    def test_backup_failure_prevents_hook_import_and_binding_changes(self):
        with patch('dashboard.widgets.migrations._backup',side_effect=OSError('backup failed')):
            with patch('dashboard.widgets.migrations.import_module',side_effect=AssertionError('Imported hook')):
                with self.assertRaisesRegex(WidgetError,'Cannot back up'):self.apply()
        self.assertEqual(self.binding(),('original','1.0.0'))

    def test_failed_callback_rolls_back_data_and_binding_without_logging_payload(self):
        original=self.module.copy
        def fail(source,target):
            original(source,target)
            raise RuntimeError('private message body must not be surfaced')
        self.module.copy=fail
        with self.assertRaisesRegex(WidgetError,'rolled back') as error:self.apply()
        self.assertNotIn('private message',str(error.exception))
        self.assertEqual(self.binding(),('original','1.0.0'))
        target = Path(self.proposed()['target_database'])
        with sqlite3.connect(target) as connection:
            self.assertFalse(connection.execute("SELECT 1 FROM sqlite_master WHERE name='notes'").fetchone())
        self.module.copy=original
        self.apply()
        self.assertEqual(self.binding(),('replacement','2.0.0'))

    def test_sql_commit_and_executescript_cannot_escape_rollback(self):
        for operation in [lambda c:c.commit(),lambda c:c.executescript('CREATE TABLE escaped(value TEXT);')]:
            def fail(source,target):
                target.execute('CREATE TABLE pending(value TEXT)')
                operation(target)
            self.module.copy=fail
            with self.assertRaisesRegex(WidgetError,'rolled back'):self.apply()
            self.assertEqual(self.binding(),('original','1.0.0'))
            with sqlite3.connect(self.proposed()['target_database']) as connection:
                self.assertFalse(connection.execute("SELECT 1 FROM sqlite_master WHERE name IN ('pending','escaped')").fetchone())

    def test_missing_offline_approval_stale_plan_and_incompatible_source_fail_before_import(self):
        incompatible=Manifest.from_dict({**self.new.to_dict(),'storage_migrations':{}})
        with patch('dashboard.widgets.migrations.import_module',side_effect=AssertionError('Imported hook')):
            for call in [lambda:self.apply(offline=False),lambda:self.apply(plan_id='stale'),
                         lambda:self.proposed(incompatible),
                         lambda:plan(self.new,self.database,'original','1.1.0','2.0.0'),
                         lambda:plan(self.new,self.database,'original','1.0.0','2.1.0')]:
                with self.assertRaises(WidgetError):call()
        self.assertEqual(self.binding(),('original','1.0.0'))

    def test_source_connection_is_readonly_and_registry_is_not_exposed_to_callback(self):
        for sql,on_source in [("DELETE FROM notes",True),
                              ("UPDATE registry.widget_provider_bindings SET provider='bad'",False)]:
            def fail(source,target): (source if on_source else target).execute(sql)
            self.module.copy=fail
            with self.assertRaisesRegex(WidgetError,'rolled back'):self.apply()
        self.assertEqual(self.binding(),('original','1.0.0'))
        with self.store.connect() as connection:self.assertEqual(connection.execute('SELECT COUNT(*) FROM notes').fetchone()[0],1)

    def test_additional_nested_databases_require_explicit_file_aware_migration(self):
        nested=self.store.directory/'attachments';nested.mkdir()
        (nested/'data.sqlite').write_bytes(b'invented second store')
        self.assertEqual(self.proposed()['source_files'],['attachments/data.sqlite'])
        with patch('dashboard.widgets.migrations.import_module',side_effect=AssertionError('Imported hook')):
            with self.assertRaisesRegex(WidgetError,'File-bearing'):self.apply()
        self.assertEqual(self.binding(),('original','1.0.0'))

    def test_files_and_non_durable_cross_database_journals_fail_safely(self):
        directory=self.store.directory
        (directory/'attachment.txt').write_text('invented attachment')
        with self.assertRaisesRegex(WidgetError,'File-bearing'):self.apply()
        self.assertEqual((directory/'attachment.txt').read_text(),'invented attachment')
        (directory/'attachment.txt').unlink()
        with closing(sqlite3.connect(self.database)) as connection:connection.execute('PRAGMA journal_mode=WAL')
        with self.assertRaisesRegex(WidgetError,'rollback journals'):self.apply()
        self.assertEqual(self.binding(),('original','1.0.0'))

    def test_abrupt_process_exit_after_binding_update_recovers_both_databases(self):
        proposed = self.proposed()
        (self.root/'migration_fixture.py').write_text("def copy(source,target):\n target.execute('CREATE TABLE notes(id INTEGER, owner INTEGER, body TEXT)')\n target.executemany('INSERT INTO notes VALUES(?,?,?)',source.execute('SELECT * FROM notes').fetchall())\n")
        code = """import json,os,sys
from dashboard.widgets import Manifest
import dashboard.widgets.migrations as migration
args=json.load(sys.stdin)
sys.path.insert(0,args['root'])
migration.timestamp=lambda:os._exit(17)
migration.execute(Manifest.from_dict(args['manifest']),args['database'],'original','1.0.0','2.0.0',plan_id=args['plan_id'],offline=True)
"""
        result=subprocess.run([sys.executable,'-c',code],input=json.dumps(dict(root=str(self.root),
            manifest=self.new.to_dict(),database=str(self.database),plan_id=proposed['plan_id'])),text=True,capture_output=True)
        self.assertEqual(result.returncode,17,result.stderr)
        self.assertEqual(self.binding(),('original','1.0.0'))
        with closing(sqlite3.connect(proposed['target_database'])) as connection:
            self.assertFalse(connection.execute("SELECT 1 FROM sqlite_master WHERE name='notes'").fetchone())
        self.apply()
        self.assertEqual(self.binding(),('replacement','2.0.0'))

    def test_failed_migration_preserves_preexisting_destination_rows(self):
        target = Path(self.proposed()['target_database']);target.parent.mkdir(parents=True)
        with sqlite3.connect(target) as connection:
            connection.execute('CREATE TABLE previous(value TEXT)')
            connection.execute("INSERT INTO previous VALUES('keep destination')")
        def fail(source,target):
            target.execute("UPDATE previous SET value='changed'")
            raise RuntimeError('failed')
        self.module.copy=fail
        with self.assertRaises(WidgetError):self.apply()
        with closing(sqlite3.connect(target)) as connection:
            self.assertEqual(connection.execute('SELECT value FROM previous').fetchone()[0],'keep destination')
        self.assertEqual(self.binding(),('original','1.0.0'))

    def test_legacy_to_isolated_and_reviewed_return_preserve_owned_records(self):
        root=self.root/'legacy';root.mkdir()
        canonical=Manifest.from_dict({**document(),'id':'wordle','provider':'dashboard',
            'entry_point':'dashboard.widgets.bundled:register_widget'})
        original=prepare(Flask(__name__,instance_path=str(root)),[canonical])['wordle']
        with original.connect() as connection:
            connection.execute('CREATE TABLE legacy_notes(id INTEGER PRIMARY KEY, owner INTEGER, body TEXT)')
            connection.execute("INSERT INTO legacy_notes VALUES(7,11,'legacy fixture')")
            connection.execute('CREATE TABLE preferences(owner INTEGER,value TEXT)')
            connection.execute("INSERT INTO preferences VALUES(11,'keep')")
        alternative=Manifest.from_dict({**self.new.to_dict(),'id':'wordle','storage_migrations':{
            'dashboard/wordle':{'from_version':'>=1,<2','entry_point':'migration_fixture:forward'}}})
        def forward(source,target):
            target.execute('CREATE TABLE notes(id INTEGER PRIMARY KEY,owner INTEGER,body TEXT)')
            target.executemany('INSERT INTO notes VALUES(?,?,?)',source.execute('SELECT * FROM legacy_notes').fetchall())
        self.module.forward=forward
        proposed=plan(alternative,root/'dashboard.sqlite','dashboard','1.0.0','2.0.0')
        execute(alternative,root/'dashboard.sqlite','dashboard','1.0.0','2.0.0',plan_id=proposed['plan_id'],offline=True)
        store=prepare(Flask(__name__,instance_path=str(root)),[alternative])['wordle']
        with store.connect() as connection:connection.execute("UPDATE notes SET body='new fixture'")
        returned=Manifest.from_dict({**canonical.to_dict(),'version':'1.1.0','storage_migrations':{
            'replacement/wordle':{'from_version':'>=2,<3','entry_point':'migration_fixture:reverse'}}})
        def reverse(source,target):
            target.executemany('UPDATE legacy_notes SET body=? WHERE id=? AND owner=?',
                [(r['body'],r['id'],r['owner']) for r in source.execute('SELECT * FROM notes')])
        self.module.reverse=reverse
        proposed=plan(returned,root/'dashboard.sqlite','replacement','2.0.0','1.1.0')
        execute(returned,root/'dashboard.sqlite','replacement','2.0.0','1.1.0',plan_id=proposed['plan_id'],offline=True)
        with original.connect() as connection:
            self.assertEqual(tuple(connection.execute('SELECT * FROM legacy_notes').fetchone()),(7,11,'new fixture'))
            self.assertEqual(connection.execute('SELECT value FROM preferences').fetchone()[0],'keep')
        self.assertTrue(prepare(Flask(__name__,instance_path=str(root)),[returned])['wordle'].legacy)

    def test_source_layout_is_bound_to_the_reviewed_plan(self):
        approved=self.proposed()['plan_id']
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE widget_provider_bindings SET storage_kind='legacy'")
        self.assertNotEqual(self.proposed()['plan_id'],approved)
        with patch('dashboard.widgets.migrations.import_module',side_effect=AssertionError('Imported hook')):
            with self.assertRaisesRegex(WidgetError,'Plan changed'):self.apply(plan_id=approved)

    def test_cli_requires_reviewed_plan_and_is_metadata_only_by_default(self):
        package=self.root/'package';package.mkdir()
        (package/'widget.json').write_text(json.dumps(self.new.to_dict()))
        profile=self.root/'profile.json'
        profile.write_text(json.dumps(dict(schema_version=1,name='migration-test',
            sources=[dict(kind='local',repository=str(package))],widgets={'example':dict(provider='replacement')})))
        args=['migrate','--profile',str(profile),'--widget','example','--database',str(self.database),
            '--from-provider','original','--from-version','1.0.0','--to-version','2.0.0']
        output=io.StringIO()
        with patch('dashboard.widgets.migrations.import_module',side_effect=AssertionError('Imported hook')), contextlib.redirect_stdout(output):
            self.assertEqual(main(args),0)
        ident=json.loads(output.getvalue())['plan_id']
        with contextlib.redirect_stderr(io.StringIO()):self.assertEqual(main(args+['--reviewed','--offline']),1)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args+['--reviewed','--offline','--plan-id',ident]),0)
        self.assertEqual(self.binding(),('replacement','2.0.0'))
