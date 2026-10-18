"""Managed-file migration recovery uses only disposable synthetic stores."""
from contextlib import closing
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

from flask import Flask
from dashboard.widgets import WidgetError
from dashboard.widgets.__main__ import main
from dashboard.widgets import migration_files as files
from dashboard.widgets.migrations import plan, execute
from dashboard.widgets.storage import prepare
import test_widget_migrations as fixture


class FileMigrationTests(unittest.TestCase):
    setUp = fixture.WidgetMigrationTests.setUp
    binding = fixture.WidgetMigrationTests.binding

    def proposed(self):
        return plan(self.new, self.database, 'original', '1.0.0', '2.0.0', copy_files=True)

    def apply(self, ident=None):
        return execute(self.new, self.database, 'original', '1.0.0', '2.0.0',
                       plan_id=ident or self.proposed()['plan_id'], offline=True, copy_files=True)

    def attachment(self, name='attachments/note.txt', value=b'independently authored fixture'):
        path = self.store.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return path

    def test_reviewed_copy_preserves_source_preferences_backups_and_repeat(self):
        original = self.attachment()
        source_bytes = original.read_bytes()
        proposed = self.proposed()
        with patch('dashboard.widgets.migrations.import_module', side_effect=AssertionError('imported')):
            self.assertEqual(self.proposed()['plan_id'], proposed['plan_id'])
        result = self.apply()
        target = files.directory(proposed, 'target') / 'attachments/note.txt'
        self.assertEqual(target.read_bytes(), source_bytes)
        self.assertEqual(original.read_bytes(), source_bytes)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        backup = Path(result['backup_directory']) / original.relative_to(self.root)
        self.assertEqual(backup.read_bytes(), source_bytes)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.binding(), ('replacement', '2.0.0'))
        self.apply(proposed['plan_id'])
        self.assertEqual(self.calls, 1)
        prepare(Flask(__name__, instance_path=str(self.root)), [])
        prepare(Flask(__name__, instance_path=str(self.root)), [self.new])
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute('SELECT value FROM preferences').fetchone()[0], 'preserve')
        self.assertFalse(files.pending(self.database).exists())

    def test_file_contents_and_copy_mode_are_bound_to_approval(self):
        source = self.attachment()
        proposed = self.proposed()
        plain = plan(self.new, self.database, 'original', '1.0.0', '2.0.0')
        self.assertNotEqual(plain['plan_id'], proposed['plan_id'])
        source.write_bytes(b'changed fixture')
        with patch('dashboard.widgets.migrations.import_module', side_effect=AssertionError('imported')):
            with self.assertRaisesRegex(WidgetError, 'Plan changed'):
                self.apply(proposed['plan_id'])
        self.assertEqual(self.binding(), ('original', '1.0.0'))

    def test_conflicting_target_files_are_never_overwritten(self):
        self.attachment()
        target = files.directory(self.proposed(), 'target') / 'attachments/note.txt'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'preserve destination')
        with self.assertRaisesRegex(WidgetError, 'conflicts'):
            self.apply()
        self.assertEqual(target.read_bytes(), b'preserve destination')
        self.assertEqual(self.calls, 0)
        self.assertEqual(self.binding(), ('original', '1.0.0'))
        self.assertFalse(files.pending(self.database).exists())

    def test_identical_and_target_only_files_survive(self):
        original = self.attachment()
        target = files.directory(self.proposed(), 'target')
        (target / 'attachments').mkdir(parents=True)
        (target / 'attachments/note.txt').write_bytes(original.read_bytes())
        (target / 'keep.txt').write_bytes(b'keep target fixture')
        self.apply()
        self.assertEqual((target / 'keep.txt').read_bytes(), b'keep target fixture')
        self.assertEqual((target / 'attachments/note.txt').read_bytes(), original.read_bytes())

    def test_secondary_sqlite_snapshot_contains_committed_wal_records(self):
        path = self.store.directory / 'attachments/extra.db'
        path.parent.mkdir()
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('CREATE TABLE records(id INTEGER PRIMARY KEY,owner INTEGER,body TEXT)')
            connection.execute("INSERT INTO records VALUES(31,11,'nested fixture')")
            connection.commit()
            proposed = self.proposed()
            result = self.apply()
            copied = files.directory(proposed, 'target') / 'attachments/extra.db'
            backup = Path(result['backup_directory']) / path.relative_to(self.root)
            for saved in (copied, backup):
                with closing(sqlite3.connect(saved)) as restored:
                    self.assertEqual(restored.execute('SELECT * FROM records').fetchone(), (31, 11, 'nested fixture'))
                self.assertFalse(saved.with_name(saved.name + '-wal').exists())
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM records').fetchone()[0], 1)

    def test_partial_install_failure_restores_sql_and_existing_target_files(self):
        self.attachment('a.txt', b'fixture a')
        self.attachment('b.txt', b'fixture b')
        proposed = self.proposed()
        target = files.directory(proposed, 'target')
        target.mkdir(parents=True)
        (target / 'keep.txt').write_bytes(b'keep')
        original = files.install
        def fail(database, journal):
            original(database, {**journal, 'entries': journal['entries'][:1]})
            raise OSError('invented private error')
        with patch.object(files, 'install', side_effect=fail):
            with self.assertRaisesRegex(WidgetError, 'rolled back') as error:
                self.apply()
        self.assertNotIn('private error', str(error.exception))
        self.assertEqual(self.binding(), ('original', '1.0.0'))
        self.assertEqual((target / 'keep.txt').read_bytes(), b'keep')
        self.assertFalse((target / 'a.txt').exists())
        self.assertFalse((target / 'b.txt').exists())
        with closing(sqlite3.connect(target / 'data.sqlite')) as connection:
            self.assertFalse(connection.execute("SELECT 1 FROM sqlite_master WHERE name='notes'").fetchone())
        self.assertFalse(files.pending(self.database).exists())

    def test_changes_during_staging_invalidate_approval_before_import(self):
        source = self.attachment()
        original = files.stage
        def changed(proposed):
            journal = original(proposed)
            source.write_bytes(b'new fixture')
            return journal
        with patch.object(files, 'stage', side_effect=changed):
            with patch('dashboard.widgets.migrations.import_module', side_effect=AssertionError('imported')):
                with self.assertRaisesRegex(WidgetError, 'Plan changed during staging'):
                    self.apply()
        self.assertEqual(self.binding(), ('original', '1.0.0'))

    def crash(self, after_commit):
        self.attachment('a.txt', b'fixture a')
        self.attachment('b.txt', b'fixture b')
        proposed = self.proposed()
        (self.root / 'migration_fixture.py').write_text(
            "def copy(source,target):\n target.execute('CREATE TABLE notes(id INTEGER,owner INTEGER,body TEXT)')\n target.executemany('INSERT INTO notes VALUES(?,?,?)',source.execute('SELECT * FROM notes').fetchall())\n")
        code = '''import json,os,sys
from dashboard.widgets import Manifest
from dashboard.widgets import migration_files as files
from dashboard.widgets.migrations import execute
args=json.load(sys.stdin)
sys.path.insert(0,args['root'])
if args['after_commit']:
 files.recover=lambda *a,**k:os._exit(27)
else:
 original=files.install
 def partial(database,journal):
  original(database,{**journal,'entries':journal['entries'][:1]})
  os._exit(26)
 files.install=partial
execute(Manifest.from_dict(args['manifest']),args['database'],'original','1.0.0','2.0.0',plan_id=args['plan_id'],offline=True,copy_files=True)
'''
        result = subprocess.run([sys.executable, '-c', code], input=json.dumps(dict(
            root=str(self.root), manifest=self.new.to_dict(), database=str(self.database),
            plan_id=proposed['plan_id'], after_commit=after_commit)), text=True, capture_output=True)
        self.assertEqual(result.returncode, 27 if after_commit else 26, result.stderr)
        return proposed

    def test_process_exit_before_sql_commit_requires_offline_rollback_recovery(self):
        proposed = self.crash(False)
        for selected in ([], [self.old], [self.new]):
            with self.assertRaisesRegex(WidgetError, 'Unfinished file migration'):
                prepare(Flask(__name__, instance_path=str(self.root)), selected)
        with self.assertRaisesRegex(WidgetError, 'offline recovery'):
            files.recover(self.database)
        with self.assertRaisesRegex(WidgetError, 'Unfinished file migration'):
            self.apply(proposed['plan_id'])
        self.assertEqual(files.recover(self.database, offline=True), dict(recovered=True, committed=False))
        self.assertEqual(self.binding(), ('original', '1.0.0'))
        target = files.directory(proposed, 'target')
        self.assertFalse((target / 'a.txt').exists())
        self.assertFalse((target / 'b.txt').exists())
        self.apply()
        self.assertEqual((target / 'a.txt').read_bytes(), b'fixture a')

    def test_process_exit_after_commit_preserves_files_and_repeat_is_noop(self):
        proposed = self.crash(True)
        self.assertEqual(files.recover(self.database, offline=True), dict(recovered=True, committed=True))
        self.assertEqual(self.binding(), ('replacement', '2.0.0'))
        for name in ('a.txt', 'b.txt'):
            self.assertTrue((files.directory(proposed, 'target') / name).is_file())
        self.apply(proposed['plan_id'])
        self.assertEqual(self.calls, 0)

    def test_recovery_preserves_unexpected_modified_files_for_manual_review(self):
        proposed = self.crash(False)
        target = files.directory(proposed, 'target') / 'a.txt'
        target.write_bytes(b'operator changed fixture')
        with self.assertRaisesRegex(WidgetError, 'changed'):
            files.recover(self.database, offline=True)
        self.assertEqual(target.read_bytes(), b'operator changed fixture')
        self.assertTrue(files.pending(self.database).is_dir())

    def test_committed_missing_file_is_restored_from_staging(self):
        proposed = self.crash(True)
        target = files.directory(proposed, 'target') / 'a.txt'
        target.unlink()
        self.assertTrue(files.recover(self.database, offline=True)['committed'])
        self.assertEqual(target.read_bytes(), b'fixture a')

    def test_invalid_recovery_path_cannot_remove_outside_files(self):
        self.crash(False)
        outside = self.root / 'outside.txt'
        outside.write_bytes(b'preserve outside fixture')
        journal_path = files.pending(self.database) / 'journal.json'
        journal = json.loads(journal_path.read_text())
        journal['entries'][0]['path'] = '../outside.txt'
        journal_path.write_text(json.dumps(journal))
        with self.assertRaisesRegex(WidgetError, 'Invalid migration recovery path'):
            files.recover(self.database, offline=True)
        self.assertEqual(outside.read_bytes(), b'preserve outside fixture')
        self.assertTrue(files.pending(self.database).exists())

    def test_target_content_changes_also_invalidate_review(self):
        self.attachment()
        target = files.directory(self.proposed(), 'target') / 'keep.txt'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'original destination fixture')
        approved = self.proposed()['plan_id']
        target.write_bytes(b'changed destination fixture')
        with self.assertRaisesRegex(WidgetError, 'Plan changed'):
            self.apply(approved)
        self.assertEqual(target.read_bytes(), b'changed destination fixture')

    def test_staging_only_interruption_and_cli_recovery_are_repeatable(self):
        files.pending(self.database).mkdir(mode=0o700)
        (files.pending(self.database) / 'partial.tmp').write_bytes(b'invented fixture')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['recover-migration', '--database', str(self.database)]), 1)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['recover-migration', '--database', str(self.database), '--offline']), 0)
        self.assertFalse(json.loads(output.getvalue())['committed'])
        self.assertFalse(files.recover(self.database, offline=True)['recovered'])
        self.assertEqual(self.binding(), ('original', '1.0.0'))

    def test_symlinks_fail_before_hook_and_cannot_escape_recovery(self):
        outside = self.root / 'outside.txt'
        outside.write_bytes(b'keep outside fixture')
        (self.store.directory / 'link').symlink_to(outside)
        with self.assertRaisesRegex(WidgetError, 'symbolic'):
            self.proposed()
        (self.store.directory / 'link').unlink()
        proposed = self.crash(False)
        target = files.directory(proposed, 'target') / 'a.txt'
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaisesRegex(WidgetError, 'symbolic'):
            files.recover(self.database, offline=True)
        self.assertEqual(outside.read_bytes(), b'keep outside fixture')
