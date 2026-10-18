"""Task API contracts, credential scopes and atomic cross-board transfers."""
import hashlib
import json
import tempfile
import unittest

from flask import g
from dashboard.auth import current_user
from dashboard.four_ad.models import db
from test_dashboard_tools import test_app


class KanbanTaskApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = test_app(self.directory.name)
        self.use_auth = False
        @self.app.before_request
        def real_auth():
            if self.use_auth:
                g.pop('dashboard_user', None)
                current_user()
        self.client = self.app.test_client()
        for name, owner in [('Source', 1), ('Destination', 1), ('Foreign', 2)]:
            self.client.post('/tools/kanban', data={'name': name}, headers={'X-Test-User': str(owner)})
        with self.app.app_context():
            self.boards = {r['name']: r['id'] for r in db().execute('SELECT * FROM kanban_boards')}
            self.columns = {name: db().execute('SELECT id FROM kanban_columns WHERE board_id=? ORDER BY position',
                                              (ident,)).fetchone()[0] for name, ident in self.boards.items()}
            for token, level in [('dash_writer', 'write'), ('dash_reader', 'read'), ('dash_other_service', None)]:
                permissions = {'kanban': level} if level else {'wiki': 'write'}
                db().execute('INSERT INTO dashboard_api_keys(user_id,name,token_hash,prefix,permissions,created_at) VALUES(1,?,?,?,?,?)',
                             (token, hashlib.sha256(token.encode()).hexdigest(), token, json.dumps(permissions), '2026-01-01'))
            db().commit()
        self.use_auth = True
        self.headers = {'Authorization': 'Bearer dash_writer'}

    def create(self, title='Task', board='Source', **extra):
        return self.client.post(f'/api/tools/kanban/boards/{self.boards[board]}/items',
                                json={'title': title, 'column_id': self.columns[board], **extra}, headers=self.headers)

    def detail(self, ident):
        return self.client.get(f'/api/tools/kanban/items/{ident}', headers=self.headers).json['item']

    def snapshot(self, board):
        return self.client.get(f'/api/tools/kanban/boards/{self.boards[board]}', headers=self.headers).json['board']

    def test_create_edit_move_and_browser_compatibility(self):
        result = self.create(notes='Original\nUnicode café')
        self.assertEqual(result.status_code, 201)
        item = result.json['item']
        self.assertEqual(result.headers['Location'], f"/api/tools/kanban/items/{item['id']}")
        self.assertEqual(item['revision'], 0)
        self.assertEqual(item['history'][0]['action'], 'created')
        column = self.snapshot('Source')['columns'][1]['id']
        result = self.client.patch(result.headers['Location'], json={'title': 'Edited', 'notes': 'Plan',
                                   'column_id': column, 'revision': 0}, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['item']['revision'], 1)
        with self.client.session_transaction() as session:
            session['user_id'] = 1
        response = self.client.post(f"/tools/kanban/{self.boards['Source']}/items",
                                    data={'title': 'Browser card', 'column_id': column})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.snapshot('Source')['items']), 2)

    def test_validation_does_not_create_or_truncate_data(self):
        path = f"/api/tools/kanban/boards/{self.boards['Source']}/items"
        valid = {'title': 'Task', 'column_id': self.columns['Source']}
        for payload in [None, [], {}, {**valid, 'title': ' '}, {**valid, 'title': 'x'*161},
                        {**valid, 'notes': 'x'*5001}, {**valid, 'notes': None},
                        {**valid, 'column_id': True}, {**valid, 'column_id': self.columns['Destination']}]:
            self.assertEqual(self.client.post(path, json=payload, headers=self.headers).status_code, 400)
        self.assertEqual(self.snapshot('Source')['items'], [])
        self.assertEqual(self.create(board='Foreign').status_code, 404)
        self.assertEqual(self.create(title='x'*160, notes='y'*5000).status_code, 201)

    def test_transfer_preserves_identity_history_and_order(self):
        first = self.create().json['item']
        second = self.create('Remaining').json['item']
        target = self.create('Target', board='Destination').json['item']
        path = f"/api/tools/kanban/items/{first['id']}/transfer"
        payload = {'board_id': self.boards['Destination'], 'column_id': self.columns['Destination'],
                   'before_id': target['id'], 'revision': first['revision']}
        result = self.client.post(path, json=payload, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        moved = result.json['item']
        self.assertEqual(moved['created_at'], first['created_at'])
        self.assertEqual(moved['id'], first['id'])
        self.assertEqual(moved['revision'], 1)
        self.assertEqual([h['action'] for h in moved['history']], ['transferred', 'created'])
        self.assertEqual([i['id'] for i in self.snapshot('Destination')['items']], [first['id'], target['id']])
        self.assertEqual(self.snapshot('Source')['items'][0]['id'], second['id'])
        self.assertEqual(self.snapshot('Source')['items'][0]['position'], 0)
        self.assertEqual(self.client.post(path, json=payload, headers=self.headers).status_code, 409)

    def test_invalid_transfers_roll_back_and_do_not_leak_foreign_items(self):
        item = self.create().json['item']
        path = f"/api/tools/kanban/items/{item['id']}/transfer"
        valid = {'board_id': self.boards['Destination'], 'column_id': self.columns['Destination'], 'revision': 0}
        for payload, status in [(None, 400), ({**valid, 'revision': True}, 400),
                                ({**valid, 'board_id': self.boards['Foreign'], 'column_id': self.columns['Foreign']}, 404),
                                ({**valid, 'column_id': self.columns['Foreign']}, 400),
                                ({**valid, 'before_id': item['id']}, 400)]:
            self.assertEqual(self.client.post(path, json=payload, headers=self.headers).status_code, status)
            self.assertEqual(self.detail(item['id']), item)
        with self.client.session_transaction() as session:
            session['user_id'] = 2
        self.assertEqual(self.client.post(path, json=valid).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/tools/kanban/items/{item['id']}",
                                           json={'revision': 0}).status_code, 404)
        self.assertEqual(self.detail(item['id']), item)

    def test_same_board_transfer_and_noop_keep_existing_move_contract(self):
        item = self.create().json['item']
        column = self.snapshot('Source')['columns'][1]['id']
        path = f"/api/tools/kanban/items/{item['id']}/transfer"
        payload = {'board_id': self.boards['Source'], 'column_id': column, 'revision': 0}
        moved = self.client.post(path, json=payload, headers=self.headers)
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json['item']['column_id'], column)
        self.assertEqual(moved.json['item']['revision'], 1)
        payload['revision'] = 1
        self.assertEqual(self.client.post(path, json=payload, headers=self.headers).json['item'], moved.json['item'])
        legacy = self.client.post(f"/api/tools/kanban/items/{item['id']}/move",
                                  json={'column_id': self.columns['Source']}, headers=self.headers)
        self.assertEqual(legacy.status_code, 200)
        self.assertTrue(legacy.json['ok'])

    def test_delete_requires_current_revision_and_normalizes_order(self):
        first = self.create().json['item']
        second = self.create('Keep').json['item']
        path = f"/api/tools/kanban/items/{first['id']}"
        for payload, status in [(None, 400), ({'revision': True}, 400), ({'revision': 1}, 409)]:
            self.assertEqual(self.client.delete(path, json=payload, headers=self.headers).status_code, status)
        self.assertEqual(self.client.delete(path, json={'revision': 0}, headers=self.headers).status_code, 204)
        self.assertEqual(self.client.get(path, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.delete(path, json={'revision': 0}, headers=self.headers).status_code, 404)
        remaining = self.snapshot('Source')['items']
        self.assertEqual([(i['id'], i['position']) for i in remaining], [(second['id'], 0)])
        with self.app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM kanban_item_history WHERE item_id=?', (first['id'],)).fetchone()[0], 0)

    def test_column_order_preserves_cards_and_rejects_stale_or_foreign_orders(self):
        item = self.create().json['item']
        original = [c['id'] for c in self.snapshot('Source')['columns']]
        desired = original[::-1]
        path = f"/api/tools/kanban/boards/{self.boards['Source']}/columns/reorder"
        payload = {'column_ids': desired, 'expected_order': original}
        result = self.client.post(path, json=payload, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual([c['id'] for c in result.json['columns']], desired)
        self.assertEqual(self.detail(item['id']), item)
        self.assertEqual(self.client.post(path, json=payload, headers=self.headers).status_code, 409)
        for order in [[], [desired[0]]*3, desired+[999], [True]+desired[1:],
                      [self.columns['Foreign']]+desired[1:]]:
            self.assertEqual(self.client.post(path, json={'column_ids': order, 'expected_order': desired},
                                             headers=self.headers).status_code, 400)
        self.assertEqual([c['id'] for c in self.snapshot('Source')['columns']], desired)
        with self.client.session_transaction() as session:
            session['user_id'] = 2
        self.assertEqual(self.client.post(path, json=payload).status_code, 404)

    def test_cancellation_is_reversible_preserves_history_and_checks_revision(self):
        item = self.create().json['item']
        self.assertIsNone(item['cancelled_at'])
        path = f"/api/tools/kanban/items/{item['id']}/cancel"
        self.assertEqual(self.client.post(path, json={'revision': True}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post(path, json={'revision': 0, 'cancelled': 'true'}, headers=self.headers).status_code, 400)
        result = self.client.post(path, json={'revision': 0}, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        cancelled = result.json['item']
        self.assertTrue(cancelled['cancelled_at'])
        self.assertEqual(cancelled['column_id'], item['column_id'])
        self.assertEqual(cancelled['notes'], item['notes'])
        self.assertEqual(cancelled['history'][0]['action'], 'cancelled')
        self.assertEqual(self.client.post(path, json={'revision': 0, 'cancelled': False}, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.post(path, json={'revision': 1}, headers=self.headers).json['item'], cancelled)
        restored = self.client.post(path, json={'revision': 1, 'cancelled': False}, headers=self.headers).json['item']
        self.assertIsNone(restored['cancelled_at'])
        self.assertEqual([h['action'] for h in restored['history']], ['restored', 'cancelled', 'created'])
        with self.client.session_transaction() as session:
            session['user_id'] = 2
        self.assertEqual(self.client.post(path, json={'revision': 2}).status_code, 404)

    def test_readonly_wrong_service_revoked_and_anonymous_cannot_mutate(self):
        item = self.create().json['item']
        with self.app.app_context():
            db().execute("UPDATE dashboard_api_keys SET revoked_at='2026-01-01' WHERE name='dash_writer'")
            db().commit()
        with self.client.session_transaction() as session:
            session['user_id'] = 1
        operations = [('POST', f"/api/tools/kanban/boards/{self.boards['Source']}/items"),
                      ('POST', f"/api/tools/kanban/boards/{self.boards['Source']}/columns/reorder"),
                      ('POST', f"/api/tools/kanban/items/{item['id']}/transfer"),
                      ('POST', f"/api/tools/kanban/items/{item['id']}/cancel"),
                      ('DELETE', f"/api/tools/kanban/items/{item['id']}")]
        for token in ['dash_reader', 'dash_other_service', 'dash_writer', 'invalid']:
            for method, path in operations:
                self.assertEqual(self.client.open(path, method=method, json={},
                                 headers={'Authorization': 'Bearer '+token}).status_code, 401)
        with self.client.session_transaction() as session:
            session.clear()
        for method, path in operations:
            self.assertEqual(self.client.open(path, method=method, json={}).status_code, 401)
