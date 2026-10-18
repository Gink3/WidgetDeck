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
                     'content-packs/example/data.json', 'frontend/node_modules/a.js', 'static/mindmaps/bundle.js'):
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
