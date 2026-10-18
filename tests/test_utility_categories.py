"""Account category preferences preserve defaults, disabled widgets and saved data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from dashboard.database import db
from dashboard.navigation import utility_groups
from dashboard.widgets.manifest import Manifest, WidgetError
from dashboard.widgets import Context, Contributions
from test_security_boundaries import isolated_application, auth_post
from test_widget_api import document


class UtilityCategoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = self.restart()
        self.alice, self.bob = self.app.test_client(), self.app.test_client()
        for client, username in [(self.alice, 'category-alice'), (self.bob, 'category-bob')]:
            self.assertEqual(auth_post(client, '/register', {'username': username, 'password': 'category-fixture-passphrase'}).status_code, 302)

    def restart(self, profile=None):
        values = {'DASHBOARD_WIDGET_PROFILE': str(profile)} if profile else {}
        with patch.dict(os.environ, values):
            name, app = isolated_application(self.folder.name)
        self.addCleanup(lambda: sys.modules.pop(name, None))
        return app

    def state(self, client):
        response = client.get('/api/launcher/categories')
        self.assertEqual(response.status_code, 200)
        return response.json

    def change(self, client, method, path, data=None):
        token = self.state(client)['csrf_token']
        return client.open(path, method=method, json=data, headers={'X-CSRF-Token': token})

    def create(self, client, name='My work'):
        response = self.change(client, 'POST', '/api/launcher/categories', {'name': name})
        self.assertEqual(response.status_code, 201, response.json)
        return next(c for c in response.json['categories'] if c['name'] == name)

    def assign(self, client, category, utility='wordle'):
        return self.change(client, 'PUT', '/api/launcher/categories/utilities/' + utility, {'category': category})

    def test_defaults_and_account_owned_categories_drive_both_launcher_and_menu(self):
        state = self.state(self.alice)
        wordle = next(u for u in state['utilities'] if u['id'] == 'wordle')
        self.assertEqual(wordle['default_category'], 'Games')
        custom = self.create(self.alice)
        self.assertEqual(self.assign(self.alice, custom['name']).status_code, 200)
        for path in ['/', '/settings']:
            html = self.alice.get(path).text
            self.assertIn('My work', html)
            self.assertNotIn('My work', self.bob.get(path).text)
        html = self.alice.get('/').text
        self.assertIn('data-tile-id="wordle" data-category="My work"', html)
        self.assertIn('data-tile-id="wordle" data-category="Games"', self.bob.get('/').text)
        # Shared registration entries must never be mutated by a user's override.
        self.assertEqual(next(e for e in self.app.extensions['dashboard_widgets']['contributions'].navigation if e['id']=='wordle')['category'], 'Games')
        restarted = self.restart().test_client()
        self.assertEqual(auth_post(restarted, '/login', {'username': 'category-alice', 'password': 'category-fixture-passphrase'}).status_code, 302)
        self.assertEqual(next(u for u in self.state(restarted)['utilities'] if u['id']=='wordle')['category'], 'My work')

    def test_move_to_builtin_reset_and_delete_restore_defaults_without_touching_other_settings(self):
        custom = self.create(self.alice)
        with self.app.app_context():
            db().execute("INSERT INTO dashboard_user_settings VALUES(1,?,?)", (json.dumps({'existing': {'keep': True}}), 'original'))
            db().commit()
        self.assertEqual(self.assign(self.alice, 'Knowledge').status_code, 200)
        self.assertEqual(next(u for u in self.state(self.alice)['utilities'] if u['id']=='wordle')['category'], 'Knowledge')
        self.assertEqual(self.assign(self.alice, None).status_code, 200)
        self.assertEqual(next(u for u in self.state(self.alice)['utilities'] if u['id']=='wordle')['category'], 'Games')
        self.assign(self.alice, custom['name'])
        self.assertEqual(self.change(self.alice, 'DELETE', '/api/launcher/categories/' + str(custom['id'])).status_code, 200)
        self.assertEqual(next(u for u in self.state(self.alice)['utilities'] if u['id']=='wordle')['category'], 'Games')
        self.assertEqual(self.alice.get('/api/settings').json['settings']['existing'], {'keep': True})

    def test_settings_seeds_parallel_panel_tokens_before_first_api_requests(self):
        with self.alice.session_transaction() as session:
            session.pop('launcher_csrf', None)
            session.pop('api_keys_csrf', None)
        self.assertEqual(self.alice.get('/settings').status_code, 200)
        with self.alice.session_transaction() as session:
            category_token, key_token = session['launcher_csrf'], session['api_keys_csrf']
        self.assertNotEqual(category_token, key_token)
        self.assertEqual(self.alice.get('/api/account/keys').json['csrf_token'], key_token)
        self.assertEqual(self.state(self.alice)['csrf_token'], category_token)
        self.assertEqual(self.alice.post('/api/launcher/categories', json={'name':'First load'},
            headers={'X-CSRF-Token':category_token}).status_code, 201)

    def test_account_and_browser_csrf_boundaries(self):
        custom = self.create(self.alice)
        self.assertEqual(self.change(self.bob, 'DELETE', '/api/launcher/categories/' + str(custom['id'])).status_code, 404)
        self.assertEqual(self.assign(self.bob, custom['name']).status_code, 400)
        self.assertEqual(self.alice.post('/api/launcher/categories', json={'name': 'No token'}).status_code, 403)
        self.assertEqual(self.app.test_client().get('/api/launcher/categories').status_code, 401)
        self.assertEqual(self.alice.get('/api/launcher/categories', headers={'Authorization': 'Bearer invalid'}).status_code, 401)
        self.assertEqual(self.assign(self.alice, 'Games', 'unknown-widget').status_code, 404)
        self.assertIn('no-store', self.alice.get('/api/launcher/categories').headers['Cache-Control'])

    def test_invalid_duplicate_unicode_and_unknown_names_leave_saved_preferences(self):
        self.create(self.alice, 'Straße')
        for name in ['', '  ', 'x' * 65, 'hidden\nline', None, 5, 'STRASSE', 'gAmEs']:
            with self.subTest(name=name):
                self.assertEqual(self.change(self.alice, 'POST', '/api/launcher/categories', {'name': name}).status_code, 400)
        self.assign(self.alice, 'Straße')
        self.assertEqual(self.assign(self.alice, 'missing').status_code, 400)
        self.assertEqual(next(u for u in self.state(self.alice)['utilities'] if u['id']=='wordle')['category'], 'Straße')
        name = '<img src=x onerror=alert(1)>'
        self.create(self.alice, name)
        self.assign(self.alice, name)
        self.assertNotIn(name, self.alice.get('/').text)
        self.assertIn('&lt;img', self.alice.get('/').text)

    def test_saved_default_destination_survives_disabling_its_original_widgets(self):
        self.assign(self.alice, 'Knowledge')
        root = Path(__file__).resolve().parents[1]
        profile = json.loads((root / 'profiles/public.json').read_text())
        profile['widgets'].pop('wiki')
        profile['widgets'].pop('mind-maps')
        path = Path(self.folder.name) / 'without-knowledge.json'
        path.write_text(json.dumps(profile))
        client = self.restart(path).test_client()
        auth_post(client, '/login', {'username': 'category-alice', 'password': 'category-fixture-passphrase'})
        self.assertEqual(next(u for u in self.state(client)['utilities'] if u['id']=='wordle')['category'], 'Knowledge')
        self.assertIn('data-tile-id="wordle" data-category="Knowledge"', client.get('/').text)

    def test_personal_category_remains_manageable_when_new_widget_default_matches(self):
        root = Path(__file__).resolve().parents[1]
        profile = json.loads((root / 'profiles/public.json').read_text())
        profile['widgets'].pop('wordle')
        path = Path(self.folder.name) / 'no-games.json'
        path.write_text(json.dumps(profile))
        client = self.restart(path).test_client()
        auth_post(client, '/login', {'username': 'category-alice', 'password': 'category-fixture-passphrase'})
        custom = self.create(client, 'games')
        self.assign(client, 'games', 'wiki')
        enabled = self.restart().test_client()
        auth_post(enabled, '/login', {'username': 'category-alice', 'password': 'category-fixture-passphrase'})
        state = self.state(enabled)
        category = next(c for c in state['categories'] if c['name'].casefold()=='games')
        self.assertEqual(category['id'], custom['id'])
        self.assertFalse(category['default'])
        self.assertEqual(next(u for u in state['utilities'] if u['id']=='wiki')['override'], 'games')
        self.assertIn('data-tile-id="wordle" data-category="games"', enabled.get('/').text)
        self.assertEqual(self.change(enabled, 'DELETE', '/api/launcher/categories/' + str(custom['id'])).status_code, 200)
        self.assertIn('data-tile-id="wordle" data-category="Games"', enabled.get('/').text)
        self.assertIn('data-tile-id="wiki" data-category="Knowledge"', enabled.get('/').text)

    def test_category_limit_preserves_existing_names_and_other_accounts(self):
        with self.app.app_context():
            db().executemany('INSERT INTO utility_categories(user_id,name,name_key) VALUES(1,?,?)',
                             [(f'Group {i}', f'group {i}') for i in range(50)])
            db().commit()
        self.assertEqual(self.change(self.alice, 'POST', '/api/launcher/categories', {'name':'One more'}).status_code, 400)
        self.assertEqual(len([c for c in self.state(self.alice)['categories'] if not c['default']]), 50)
        self.create(self.bob, 'One more')

    def test_disabled_utility_assignments_survive_and_reappear(self):
        self.create(self.alice)
        self.assign(self.alice, 'My work')
        root = Path(__file__).resolve().parents[1]
        profile = json.loads((root / 'profiles/public.json').read_text())
        profile['widgets'].pop('wordle')
        path = Path(self.folder.name) / 'without-wordle.json'
        path.write_text(json.dumps(profile))
        disabled = self.restart(path).test_client()
        auth_post(disabled, '/login', {'username': 'category-alice', 'password': 'category-fixture-passphrase'})
        self.assertNotIn('wordle', {u['id'] for u in self.state(disabled)['utilities']})
        with self.app.app_context():
            self.assertEqual(db().execute("SELECT category FROM utility_category_assignments WHERE utility='wordle'").fetchone()[0], 'My work')
        enabled = self.restart().test_client()
        auth_post(enabled, '/login', {'username': 'category-alice', 'password': 'category-fixture-passphrase'})
        self.assertEqual(next(u for u in self.state(enabled)['utilities'] if u['id']=='wordle')['category'], 'My work')


class DefaultCategoryManifestTests(unittest.TestCase):
    def test_new_default_is_authoritative_and_old_navigation_contract_still_works(self):
        for data, expected in [(document(default_category='Personal tools'), 'Personal tools'), (document(), 'Legacy group')]:
            manifest = Manifest.from_dict(data)
            contributions = Contributions()
            Context(manifest, contributions).navigation('Legacy group', 'Example', 'example.index')
            self.assertEqual(contributions.navigation[0]['category'], expected)
            self.assertEqual(Manifest.from_dict(manifest.to_dict()), manifest)
        for value in ['', 'x' * 65, 'bad\nname', 42]:
            with self.subTest(value=value), self.assertRaises(WidgetError):
                Manifest.from_dict(document(default_category=value))

    def test_all_bundled_widgets_define_defaults(self):
        root = Path(__file__).resolve().parents[1] / 'dashboard/widgets/bundled_manifests'
        for path in root.glob('*/widget.json'):
            self.assertTrue(Manifest.from_dict(json.loads(path.read_text())).default_category, str(path))
