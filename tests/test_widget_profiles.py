"""Public/default profile compatibility and external-provider app integration."""
import builtins
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from dashboard.database import db
from dashboard.widgets.__main__ import main
from dashboard.widgets.bundled import ROOT
from dashboard.widgets.profiles import resolve_profile
from test_security_boundaries import isolated_application, auth_post
from test_widget_api import document

PUBLIC = ROOT / 'profiles/public.json'
PUBLIC_IDS = {'wiki', 'mind-maps', 'kanban', 'wordle', 'image-converter'}


class WidgetProfileTests(unittest.TestCase):
    def create_app(self, folder, profile):
        with patch.dict(os.environ, DASHBOARD_WIDGET_PROFILE=str(profile)):
            name, app = isolated_application(folder)
        self.addCleanup(lambda: sys.modules.pop(name, None))
        return app

    def test_public_profile_imports_only_selected_utilities(self):
        original = builtins.__import__
        def core_import(name, *args, **kwargs):
            for module in ['dashboard.four_ad', 'dashboard.paint_rack', 'dashboard.flashcards',
                           'dashboard.chapter_painter', 'dashboard.zettelkasten']:
                if name.startswith(module):
                    raise AssertionError('Imported disabled utility: ' + name)
            return original(name, *args, **kwargs)
        with tempfile.TemporaryDirectory() as folder, patch('builtins.__import__', side_effect=core_import):
            app = self.create_app(folder, PUBLIC)
            self.assertEqual({m.id for m in app.extensions['dashboard_widgets']['manifests']}, PUBLIC_IDS)
            self.assertTrue(app.extensions['dashboard_widgets']['ready'])
            with app.app_context():
                tables = {r[0] for r in db().execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn('four_ad_records', tables)
            self.assertNotIn('frostgrave_parties', tables)
            self.assertNotIn('rdt_tables', tables)
            client = app.test_client()
            auth_post(client, '/register', {'username': 'public-only', 'password': 'public-profile-passphrase'})
            home = client.get('/').text
            for ident in PUBLIC_IDS:
                self.assertIn(f'data-widget-id="{ident}"', home)
            self.assertNotIn('data-widget-id="four-against-darkness"', home)
            self.assertNotIn('Four Against Darkness', client.get('/settings').text)
            services = client.get('/api/account/keys').json['services']
            self.assertEqual(set(services), {'wiki', 'mindmaps', 'kanban', 'wordle'})
            self.assertEqual(client.get('/four-ad').status_code, 404)
            self.assertEqual(client.get('/tools/frostgrave').status_code, 404)
            self.assertEqual(client.get('/api/search?q=board').json['unavailable'], [])
            with app.app_context():
                owner = db().execute('SELECT id FROM dashboard_users').fetchone()[0]
                db().execute("INSERT INTO launcher_visits VALUES(?,'paint-rack','old-paint','','now')", (owner,))
                db().commit()
            self.assertEqual(client.get('/api/launcher').json['recent'], [])


    def test_external_same_named_provider_replaces_only_explicit_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); package = root / 'widget'; package.mkdir()
            manifest = {**document(), 'id': 'wordle', 'provider': 'personal', 'name': 'Wordle'}
            (package / 'widget.json').write_text(json.dumps(manifest))
            profile = root / 'profile.json'
            profile.write_text(json.dumps(dict(schema_version=1, name='personal-test',
                sources=[dict(kind='local', repository='widget')],
                widgets={'wordle': dict(provider='personal', version='==1.0.0')})))
            module = types.ModuleType('example_widget')
            def factory(app, context):
                app.add_url_rule('/tools/wordle', 'personal_wordle', lambda: 'Personal implementation')
                context.navigation('Games', 'Wordle', 'personal_wordle')
            module.register = factory
            with patch.dict(sys.modules, example_widget=module):
                app = self.create_app(str(root / 'instance'), profile)
            client = app.test_client()
            auth_post(client, '/register', {'username': 'personal-test', 'password': 'personal-widget-passphrase'})
            self.assertEqual(client.get('/tools/wordle').text, 'Personal implementation')
            self.assertEqual(app.extensions['dashboard_widgets']['manifests'][0].identity, 'personal/wordle')
            self.assertNotIn('wordle.index', app.view_functions)

    def test_cli_validation_does_not_import_widgets_and_reports_bad_profiles(self):
        output = io.StringIO()
        with patch('dashboard.widgets.import_module', side_effect=AssertionError('Imported code')), contextlib.redirect_stdout(output):
            self.assertEqual(main(['validate', '--profile', str(PUBLIC)]), 0)
        self.assertEqual(len(json.loads(output.getvalue())['widgets']), 5)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.json'
            path.write_text(json.dumps(dict(schema_version=1, name='bad', sources=[],
                widgets={'wordle': dict(provider='unknown')})))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['validate', '--profile', str(path)]), 1)

    def test_capability_validation_occurs_before_registration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.json'
            path.write_text(json.dumps(dict(schema_version=1, name='bad', sources=[],
                widgets={'wordle': dict(provider='dashboard', capabilities=['mail'])})))
            with self.assertRaisesRegex(ValueError, 'undeclared'):
                resolve_profile(path)


if __name__ == '__main__':
    unittest.main()
