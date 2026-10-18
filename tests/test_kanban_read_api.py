import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from flask import g
from test_dashboard_tools import test_app
from dashboard.four_ad.models import db


class KanbanReadApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = test_app(self.directory.name)
        self.client = self.app.test_client()

    def board(self, name='Dashboard', owner=1):
        response = self.client.post('/tools/kanban', data={'name': name, 'column_name': ['To do', 'In Progress', 'Done']}, headers={'X-Test-User': str(owner)})
        return int(parse_qs(urlparse(response.location).query)['board'][0])

    def test_discovery_exact_names_duplicates_and_owner_scope(self):
        first = self.board()
        second = self.board()
        self.board('Dashboard extra')
        foreign = self.board(owner=2)
        result = self.client.get('/api/tools/kanban/boards?name=dashboard')
        self.assertEqual(result.status_code, 200)
        self.assertEqual({b['id'] for b in result.json['boards']}, {first, second})
        self.assertEqual(result.headers['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client.get(f'/api/tools/kanban/boards/{foreign}').status_code, 404)
        self.assertEqual(self.client.get('/api/tools/kanban/boards/99999').status_code, 404)
        self.assertEqual(self.client.get('/api/tools/kanban/boards?name=Missing').json['boards'], [])

    def test_snapshot_preserves_all_notes_and_visual_order_without_writes(self):
        ident = self.board()
        empty = self.client.get(f'/api/tools/kanban/boards/{ident}').json['board']
        self.assertEqual(empty['items'], [])
        columns = empty['columns']
        for column, title in [(columns[1], 'Later column'), (columns[0], 'First card'), (columns[0], 'Second card')]:
            self.client.post(f'/tools/kanban/{ident}/items', data={'column_id': column['id'], 'title': title, 'notes': 'Line one\n\n- acceptance criterion\nUnicode: café'})
        with self.app.app_context():
            before = [tuple(row) for row in db().execute('SELECT * FROM kanban_items')]
            history = db().execute('SELECT COUNT(*) FROM kanban_item_history').fetchone()[0]
        result = self.client.get(f'/api/tools/kanban/boards/{ident}')
        items = result.json['board']['items']
        self.assertEqual([item['title'] for item in items], ['First card', 'Second card', 'Later column'])
        self.assertEqual(items[0]['column_name'], 'To do')
        self.assertEqual(items[0]['notes'], 'Line one\n\n- acceptance criterion\nUnicode: café')
        self.assertEqual(items[0]['revision'], 0)
        self.assertIn('updated_at', items[0])
        self.assertEqual(self.client.get(f"/api/tools/kanban/items/{items[0]['id']}").json['item']['title'], 'First card')
        with self.app.app_context():
            self.assertEqual(before, [tuple(row) for row in db().execute('SELECT * FROM kanban_items')])
            self.assertEqual(history, db().execute('SELECT COUNT(*) FROM kanban_item_history').fetchone()[0])

    def test_read_endpoints_require_login(self):
        @self.app.before_request
        def anonymous():
            g.dashboard_user = None
        for path in ['/api/tools/kanban/boards', '/api/tools/kanban/boards/1']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json['error'], 'Sign in is required.')
