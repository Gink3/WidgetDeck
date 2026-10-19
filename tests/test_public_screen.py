"""Synthetic leaks; the restricted reference corpus never enters this repository."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('screen', Path(__file__).resolve().parents[1] / 'tools/screen_public.py')
screen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screen)


class PublicScreenTests(unittest.TestCase):
    def test_restricted_bytes_fail_even_when_renamed(self):
        payload = b'invented restricted fixture, no real source material'
        self.assertIn('restricted fingerprint', screen.reasons('static/renamed.bin', payload,
                      {hashlib.sha256(payload).hexdigest()}))

    def test_private_generated_and_secret_inputs_fail(self):
        for path in ('.env.production', '.aws/config', 'instance/data.sqlite',
                     'content-packs/example/data.json', 'frontend/node_modules/a.js', 'static/mindmaps/bundle.js',
                     'custom.sqlite.widget-migration-pending/journal.json', 'widget-migration-backups/saved.bin', '.widget-sources/object', 'candidate.generations/private.whl'):
            self.assertTrue(screen.reasons(path, b'synthetic', set()), path)
        secret = b'-----BEGIN ' + b'PRIVATE KEY-----'
        self.assertTrue(screen.reasons('unexpected.txt', secret, set()))
        self.assertTrue(screen.reasons('doc.txt', b'/home/' + b'invented/' + b'.env.production', set()))

    def test_synthetic_source_and_existing_notice_pass(self):
        self.assertEqual(screen.reasons('tests/fixture.json', b'{"name":"invented"}', set()), [])
        self.assertEqual(screen.reasons('dashboard/wordle/WORD-LIST-LICENSE', b'MIT License', set()), [])

    def test_missing_or_invalid_required_fingerprints_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hashes.json'
            for value in ('[]', '{}', '["invalid"]'):
                path.write_text(value)
                with self.assertRaises(ValueError):
                    screen.load_fingerprints(path, required=True)

    @unittest.skipUnless(shutil.which('git'), 'Git index fixture requires the host Git tool')
    def test_staged_screen_uses_index_not_worktree(self):
        with tempfile.TemporaryDirectory() as folder:
            subprocess.run(['git', 'init', '-q', folder], check=True)
            path = Path(folder) / 'fixture.txt'
            path.write_bytes(b'staged fixture')
            subprocess.run(['git', '-C', folder, 'add', 'fixture.txt'], check=True)
            path.write_bytes(b'later edit')
            self.assertEqual(list(screen.blobs(folder, staged=True)), [('fixture.txt', b'staged fixture')])

    @unittest.skipUnless(shutil.which('git'), 'Hook fixture requires Git')
    def test_hook_uses_private_local_configuration_and_fails_closed(self):
        import json
        import os
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(['git', 'init', '-q', folder], check=True)
            (root / 'tools').mkdir()
            shutil.copy2(Path(screen.__file__), root / 'tools/screen_public.py')
            hook = Path(screen.__file__).parents[1] / '.githooks/pre-commit'
            payload = b'independently authored restricted hook fixture'
            (root / 'fixture.txt').write_bytes(payload)
            subprocess.run(['git', '-C', folder, 'add', 'fixture.txt'], check=True)
            hashes = root / '.git/private-hashes.json'
            hashes.write_text(json.dumps([hashlib.sha256(payload).hexdigest()]))
            subprocess.run(['git', '-C', folder, 'config', '--local', 'widgetdeck.screenFingerprints', str(hashes)], check=True)
            env = {k: v for k, v in os.environ.items() if k != 'WIDGETDECK_RESTRICTED_SHA256'}
            run = lambda: subprocess.run(['sh', str(hook)], cwd=folder, env=env, capture_output=True)
            self.assertEqual(run().returncode, 1)
            (root / 'fixture.txt').write_bytes(b'lawful replacement fixture')
            subprocess.run(['git', '-C', folder, 'add', 'fixture.txt'], check=True)
            self.assertEqual(run().returncode, 0)
            hashes.unlink()
            self.assertEqual(run().returncode, 2)
