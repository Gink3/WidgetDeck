import tempfile
import unittest
from flask import g, jsonify, request
from test_dashboard_tools import test_app
from dashboard.auth import current_user
from dashboard.four_ad.models import db


class KanbanApiKeyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = test_app(self.directory.name)
        self.app.config.update(DASHBOARD_KANBAN_API_KEY='test-only-key', DASHBOARD_KANBAN_API_USERNAME='Test')
        self.use_auth = False
        @self.app.before_request
        def real_auth():
            if not self.use_auth:
                return None
            g.pop('dashboard_user', None)
            if not current_user():
                return jsonify(error='Sign in is required.'), 401
        self.client = self.app.test_client()
        self.client.post('/tools/kanban', data={'name': 'Dashboard'})
        self.client.post('/tools/kanban', data={'name': 'Other board'}, headers={'X-Test-User': '2'})
        with self.app.app_context():
            self.board = db().execute('SELECT id FROM kanban_boards WHERE user_id=1').fetchone()[0]
            self.foreign = db().execute('SELECT id FROM kanban_boards WHERE user_id=2').fetchone()[0]
            column = db().execute('SELECT id FROM kanban_columns WHERE board_id=?', (self.board,)).fetchone()[0]
        self.client.post(f'/tools/kanban/{self.board}/items', data={'column_id': column, 'title': 'Task', 'notes': 'Do this'})
        self.use_auth = True
        self.headers = {'Authorization': 'Bearer test-only-key'}

    def test_valid_key_reads_only_its_account_and_preserves_session_login(self):
        result = self.client.get('/api/tools/kanban/boards', headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual([b['name'] for b in result.json['boards']], ['Dashboard'])
        self.assertEqual(self.client.get(f'/api/tools/kanban/boards/{self.foreign}', headers=self.headers).status_code, 404)
        item = self.client.get(f'/api/tools/kanban/boards/{self.board}', headers=self.headers).json['board']['items'][0]
        self.assertEqual(self.client.get(f"/api/tools/kanban/items/{item['id']}", headers=self.headers).status_code, 200)
        with self.client.session_transaction() as session:
            session['user_id'] = 2
        self.assertEqual(self.client.get('/api/tools/kanban/boards').json['boards'][0]['name'], 'Other board')

    def test_key_cannot_write_or_access_other_tools_or_fall_back_to_cookie(self):
        with self.client.session_transaction() as session:
            session['user_id'] = 1
        for method, path in [('POST', '/tools/kanban'), ('PATCH', '/api/tools/kanban/items/1'),
                             ('POST', f'/api/tools/kanban/boards/{self.board}/items'),
                             ('POST', '/api/tools/kanban/items/1/transfer'),
                             ('DELETE', '/api/tools/kanban/items/1'),
                             ('POST', '/api/tools/kanban/efforts'),
                             ('PUT', '/api/tools/kanban/items/1/efforts'),
                             ('DELETE', '/api/tools/kanban/efforts/1'),
                             ('GET', '/tools/kanban'), ('GET', '/tools/wiki/api/pages')]:
            self.assertEqual(self.client.open(path, method=method, headers=self.headers).status_code, 401)
        self.assertEqual(self.client.get('/api/tools/kanban/boards', headers={'Authorization': 'Bearer wrong'}).status_code, 401)

    def test_missing_configuration_and_bad_keys_fail_closed(self):
        for authorization in ['', 'Bearer wrong', 'Basic test-only-key', 'Bearer']:
            self.assertEqual(self.client.get('/api/tools/kanban/boards', headers={'Authorization': authorization}).status_code, 401)
        self.app.config['DASHBOARD_KANBAN_API_USERNAME'] = 'Missing'
        self.assertEqual(self.client.get('/api/tools/kanban/boards', headers=self.headers).status_code, 401)
        self.app.config['DASHBOARD_KANBAN_API_USERNAME'] = 'Test'
        self.app.config['DASHBOARD_KANBAN_API_KEY'] = ''
        self.assertEqual(self.client.get('/api/tools/kanban/boards', headers=self.headers).status_code, 401)
