"""Provider selection and source-binding regressions."""
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard.widgets import Manifest, WidgetError
from dashboard.widgets.sources import Candidate, Selection, Source, installed_candidates, select
from test_widget_api import document


def candidate(provider='dashboard', version='1.0.0', repository='/tmp/widgets', **overrides):
    manifest = Manifest.from_dict({**document(), 'provider': provider, 'version': version, **overrides})
    return Candidate(manifest, Source('local', repository))


class WidgetSourceTests(unittest.TestCase):
    def test_matching_names_require_explicit_provider_and_never_fall_back(self):
        public, personal = candidate(), candidate('personal')
        result = select([public, personal], {'example': Selection('personal')})
        self.assertIs(result['example'], personal)
        with self.assertRaisesRegex(WidgetError, 'No compatible'):
            select([public], {'example': Selection('personal')})
        self.assertEqual(select([public, personal], {}), {})
        with self.assertRaisesRegex(WidgetError, 'binding changed'):
            select([personal], {'example': Selection('personal')},
                   bindings={'personal/example': Source('local', '/tmp/old-source')})

    def test_latest_compatible_version_is_selected_and_prerelease_is_opt_in(self):
        old = candidate(version='1.0.0')
        new = candidate(version='1.2.0')
        breaking = candidate(version='2.0.0', core_api='>=2')
        prerelease = candidate(version='1.3.0rc1')
        versions = [old, new, breaking, prerelease]
        self.assertIs(select(versions, {'example': Selection('dashboard', '>=1,<2')})['example'], new)
        self.assertIs(select(versions, {'example': Selection('dashboard', '==1.3.0rc1')})['example'], prerelease)
        with self.assertRaises(WidgetError):
            select(versions, {'example': Selection('dashboard', '>=2')})

    def test_same_identity_cannot_be_rebound_or_duplicated(self):
        first = candidate()
        for second in [candidate(repository='/tmp/other'), candidate()]:
            with self.assertRaises(WidgetError):
                select([first, second], {'example': Selection('dashboard')})

    def test_local_paths_are_canonical_and_cannot_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / 'package'; package.mkdir()
            (package / 'widget.json').write_text(json.dumps(document()))
            selected = Candidate.local(root, 'package')
            self.assertEqual(selected.manifest.identity, 'dashboard/example')
            for subdir in ['../outside', '/absolute']:
                with self.assertRaises(WidgetError):
                    Source('local', str(root), subdir)
            (root/'escape').symlink_to(root.parent, target_is_directory=True)
            with self.assertRaises(WidgetError):
                Source('local', str(root), 'escape')

    def test_git_sources_reject_embedded_credentials_and_unsafe_schemes(self):
        for url in ['https://github.com/owner/repo.git', 'ssh://git@github.com/owner/repo.git', 'git@github.com:owner/repo.git']:
            self.assertEqual(Source('git', url).repository, url)
        for url in ['https://token@github.com/repo', 'https://user:password@github.com/repo',
                    'http://github.com/repo', 'file:///tmp/repo', 'https://github.com/repo?token=value',
                    'https://[broken', 'ssh://git@github.com:invalid/repo']:
            with self.assertRaises(WidgetError):
                Source('git', url)

    def test_installed_discovery_never_imports_entry_point(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / 'widget.json'; manifest.write_text(json.dumps(document()))
            distribution = types.SimpleNamespace(files=['example/widget.json'], version='1.0.0',
                name='example-widget', locate_file=lambda _: manifest)
            entry = types.SimpleNamespace(name='example', value='example_widget:register', dist=distribution)
            with patch('dashboard.widgets.sources.entry_points', return_value=[entry]), \
                 patch('dashboard.widgets.import_module', side_effect=AssertionError('Imported code')):
                result = installed_candidates()
            self.assertEqual(result[0].source, Source('installed', 'example-widget'))
            entry.value = 'different:register'
            with patch('dashboard.widgets.sources.entry_points', return_value=[entry]), self.assertRaises(WidgetError):
                installed_candidates()


if __name__ == '__main__':
    unittest.main()
