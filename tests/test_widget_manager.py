"""Exact source/candidate workflows on independent synthetic Git repositories."""
import io
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
import tarfile
import unittest
from unittest.mock import patch

from dashboard.widgets import manager
from dashboard.widgets import WidgetError
from dashboard.widgets.__main__ import main
from test_widget_api import document


@unittest.skipUnless(shutil.which('git'), 'Source management fixtures require Git')
class WidgetManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.core, self.widget = self.root / 'core', self.root / 'widget'
        for path in (self.core, self.widget):
            path.mkdir()
            self.git(path, 'init', '-q')
            self.git(path, 'config', 'user.name', 'Synthetic fixture')
            self.git(path, 'config', 'user.email', 'fixture@example.invalid')
        self.write(self.core, 'dashboard/widgets/manifest.py', "API_VERSION = Version('1.4.0')\n")
        self.write(self.core, 'profiles/public.json', json.dumps(dict(schema_version=1, name='public', sources=[], widgets={})))
        self.write(self.core, 'requirements.txt', '')
        self.write(self.widget, 'package/widget.json', json.dumps({**document(), 'provider': 'fixture'}))
        self.write(self.widget, 'package/pyproject.toml', '[project]\nname="independent-fixture-widget"\nversion="1.0.0"\n')
        self.write(self.widget, 'package/module.py', 'raise RuntimeError("must not import during management")\n')
        for path in (self.core, self.widget):
            self.commit(path)
            self.git(path, 'tag', 'v1.0.0')
        self.profile = self.root / 'profile.json'
        self.config = dict(schema_version=1, name='fixture', core=dict(repository='core', ref='HEAD'),
            widgets=[dict(repository='widget', subdirectory='package', ref='HEAD', id='example', provider='fixture')])
        self.save()
        self.lockfile, self.cache = self.root / 'lock.json', self.root / 'cache'

    def git(self, repo, *args):
        return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, repo, name, value):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def commit(self, repo):
        self.git(repo, 'add', '.')
        self.git(repo, 'commit', '-qm', 'Synthetic fixture')

    def save(self):
        self.profile.write_text(json.dumps(self.config))

    def lock(self):
        return manager.lock(self.profile, self.lockfile, self.cache)

    def test_heads_tags_source_identity_and_exact_hashes_without_hook_import(self):
        locked = self.lock()
        self.assertEqual(locked['widgets'][0]['revision'], self.git(self.widget, 'rev-parse', 'HEAD'))
        self.assertEqual(locked['widgets'][0]['metadata']['provider'], 'fixture')
        self.assertEqual(len(locked['widgets'][0]['archive_sha256']), 64)
        self.config['core']['ref'] = 'v1.0.0'
        self.config['widgets'][0]['ref'] = 'v1.0.0'
        self.save()
        self.assertEqual(self.lock()['core']['revision'], locked['core']['revision'])
        self.assertEqual(self.lockfile.stat().st_mode & 0o777, 0o600)

    def test_dirty_or_failed_source_update_preserves_old_lock(self):
        self.lock()
        before = self.lockfile.read_bytes()
        self.write(self.widget, 'uncommitted', 'fixture')
        with self.assertRaisesRegex(WidgetError, 'Commit or stash'):
            self.lock()
        self.assertEqual(self.lockfile.read_bytes(), before)
        (self.widget / 'uncommitted').unlink()
        self.config['widgets'][0]['ref'] = 'missing-tag'
        self.save()
        with self.assertRaises(WidgetError):
            self.lock()
        self.assertEqual(self.lockfile.read_bytes(), before)

    def test_provider_and_dependency_failures_preserve_previous_selection(self):
        self.lock()
        before = self.lockfile.read_bytes()
        metadata = {**document(), 'provider': 'other'}
        for metadata in (metadata, {**document(), 'provider': 'fixture', 'dependencies': {'missing': '>=1'}}):
            self.write(self.widget, 'package/widget.json', json.dumps(metadata))
            self.commit(self.widget)
            with self.assertRaises(WidgetError):
                self.lock()
            self.assertEqual(self.lockfile.read_bytes(), before)

    def test_sync_uses_locked_commit_even_after_branch_moves_and_excludes_unselected_files(self):
        locked = self.lock()
        self.write(self.widget, 'package/module.py', 'changed fixture\n')
        self.write(self.widget, 'unselected-secret-fixture.txt', 'independently authored fixture')
        self.commit(self.widget)
        destination = self.root / 'sources'
        manager.sync(self.lockfile, destination, self.cache)
        self.assertIn('must not import', (destination / 'widgets/example/module.py').read_text())
        self.assertFalse((destination / 'widgets/example/unselected-secret-fixture.txt').exists())
        self.assertEqual(json.loads((destination / 'source-lock.json').read_text()), locked)

    def test_corrupt_archive_and_dirty_sync_leave_previous_pointer_intact(self):
        self.lock()
        destination = self.root / 'sources'
        manager.sync(self.lockfile, destination, self.cache)
        before = destination.resolve()
        locked = json.loads(self.lockfile.read_text())
        locked['widgets'][0]['archive_sha256'] = '0' * 64
        self.lockfile.write_text(json.dumps(locked))
        with self.assertRaisesRegex(WidgetError, 'differs'):
            manager.sync(self.lockfile, destination, self.cache)
        self.assertEqual(destination.resolve(), before)
        self.lock()
        self.write(self.widget, 'uncommitted', 'fixture')
        with self.assertRaisesRegex(WidgetError, 'Commit or stash'):
            manager.sync(self.lockfile, destination, self.cache)
        self.assertEqual(destination.resolve(), before)

    def test_remote_branch_and_tag_fetch_resolve_to_exact_local_fixture_commit(self):
        url = 'https://source.example.invalid/widget.git'
        self.config['widgets'][0]['repository'] = url
        self.config['widgets'][0]['ref'] = 'v1.0.0'
        self.save()
        original = manager._run
        def transport(*args, **kwargs):
            # The production URL validator still runs; only transport is loopbacked.
            return original(*(str(self.widget) if a == url else a for a in args), **kwargs)
        with patch.object(manager, '_run', side_effect=transport):
            locked = self.lock()
            manager.sync(self.lockfile, self.root / 'sources', self.cache)
        self.assertEqual(locked['widgets'][0]['repository'], url)
        self.assertEqual(locked['widgets'][0]['revision'], self.git(self.widget, 'rev-parse', 'HEAD'))

    def test_links_and_unsafe_inputs_rejected_before_publication(self):
        self.lock()
        before = self.lockfile.read_bytes()
        (self.widget / 'package/link').symlink_to('/outside-fixture')
        self.commit(self.widget)
        with self.assertRaisesRegex(WidgetError, 'links'):
            self.lock()
        self.assertEqual(self.lockfile.read_bytes(), before)
        for directory in ('../outside', '/outside', 'bad:object'):
            self.config['widgets'][0]['subdirectory'] = directory
            self.save()
            with self.assertRaises(WidgetError):
                self.lock()

    def test_tampered_source_bytes_are_rejected_before_any_build_tool(self):
        self.lock()
        sources = self.root / 'sources'
        manager.sync(self.lockfile, sources, self.cache)
        (sources / 'widgets/example/module.py').write_text('tampered fixture')
        with patch.object(manager, '_run', side_effect=AssertionError('tool ran')):
            with self.assertRaisesRegex(WidgetError, 'changed'):
                manager.build(self.lockfile, sources, self.root / 'candidate')

    def test_build_failure_keeps_previous_runtime_pointer_and_generation(self):
        self.lock()
        sources, destination = self.root / 'sources', self.root / 'candidate'
        manager.sync(self.lockfile, sources, self.cache)
        _, previous = manager._generation(destination)
        (previous / 'retained').write_text('old candidate')
        manager._publish(destination, previous)
        with patch.object(manager, '_run', side_effect=WidgetError('fixture build failure')):
            with self.assertRaisesRegex(WidgetError, 'build failure'):
                manager.build(self.lockfile, sources, destination)
        self.assertEqual(destination.resolve(), previous)
        self.assertEqual((destination / 'retained').read_text(), 'old candidate')
        self.assertEqual(list(previous.parent.iterdir()), [previous])

    def test_unowned_destination_is_not_overwritten(self):
        self.lock()
        destination = self.root / 'sources'
        destination.mkdir()
        (destination / 'retained').write_text('user data')
        with self.assertRaisesRegex(WidgetError, 'manager-owned'):
            manager.sync(self.lockfile, destination, self.cache)
        self.assertEqual((destination / 'retained').read_text(), 'user data')

    def test_cli_management_commands_do_not_change_legacy_runtime_commands(self):
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['lock', '--profile', str(self.profile), '--output', str(self.lockfile), '--cache', str(self.cache)]), 0)
            self.assertEqual(main(['sync', '--lock', str(self.lockfile), '--destination', str(self.root / 'sources'), '--cache', str(self.cache)]), 0)

    def test_archive_hashes_do_not_depend_on_tree_archive_wall_clock(self):
        revision = self.git(self.widget, 'rev-parse', 'HEAD')
        data = manager._archive(self.widget, revision, 'package')
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            self.assertTrue(archive.getmembers())
            self.assertEqual({member.mtime for member in archive.getmembers()}, {0})
        self.assertEqual(data, manager._archive(self.widget, revision, 'package'))
