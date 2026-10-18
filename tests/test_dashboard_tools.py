"""Kanban persistence and wiki editing-session regressions on disposable data."""
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from flask import Flask, g, request

from dashboard import activity
from dashboard.auth import init_auth
from dashboard.campaign_tools import init_campaign_tools, models as kanban
from dashboard.database import db
from dashboard.wiki import init_wiki


def test_app(directory):
    app = Flask(__name__, root_path=str(Path(__file__).resolve().parents[1]), instance_path=directory)
    app.config.update(TESTING=True, TEMPLATES_AUTO_RELOAD=True)
    init_auth(app)
    activity.init_database(app)
    init_campaign_tools(app, utilities=["kanban"])
    init_wiki(app)
    for endpoint in ('home', 'settings', 'logout', 'frontline_command', 'grimdark_future', 'mindmaps.index', 'image_converter.index'):
        app.add_url_rule('/test/' + endpoint, endpoint, lambda: 'Test route')

    @app.before_request
    def test_user():
        owner = int(request.headers.get('X-Test-User', 1))
        g.dashboard_user = {'id': owner, 'username': 'Test' if owner == 1 else 'Other'}

    with app.app_context():
        db().executemany('INSERT INTO dashboard_users(id,username,password_hash,created_at) VALUES(?,?,?,?)',
                         [(1, 'Test', 'not-a-login', '2026-01-01T00:00:00+00:00'), (2, 'Other', 'not-a-login', '2026-01-01T00:00:00+00:00')])
        db().commit()
    return app


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = test_app(self.directory.name)
        self.client = self.app.test_client()

    def board(self, name='Test board', owner=1):
        response = self.client.post('/tools/kanban', data={'name': name, 'column_name': ['To do', 'In Progress', 'Done']}, headers={'X-Test-User': str(owner)})
        ident = int(parse_qs(urlparse(response.location).query)['board'][0])
        with self.app.app_context():
            columns = [row['id'] for row in db().execute('SELECT id FROM kanban_columns WHERE board_id=? ORDER BY position', (ident,))]
        return ident, columns

    def add(self, board, column, title):
        self.client.post(f'/tools/kanban/{board}/items', data={'column_id': column, 'title': title, 'notes': 'Original notes'})
        with self.app.app_context():
            return db().execute('SELECT MAX(id) FROM kanban_items').fetchone()[0]

    def order(self, column):
        with self.app.app_context():
            rows = db().execute('SELECT id,position FROM kanban_items WHERE column_id=? ORDER BY position,id', (column,)).fetchall()
        self.assertEqual([row['position'] for row in rows], list(range(len(rows))))
        return [row['id'] for row in rows]

    def detail(self, ident):
        return self.client.get(f'/api/tools/kanban/items/{ident}').get_json()['item']

    def test_reordering_and_cross_column_moves_persist(self):
        board, cols = self.board()
        first, second, third = [self.add(board, cols[0], name) for name in ['First', 'Second', 'Third']]
        response = self.client.post(f'/api/tools/kanban/items/{third}/move', json={'column_id': cols[0], 'before_id': first, 'revision': 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.order(cols[0]), [third, first, second])
        self.assertEqual(self.detail(third)['history'][0]['action'], 'reordered')
        self.client.post(f'/api/tools/kanban/items/{first}/move', json={'column_id': cols[1]})
        self.assertEqual(self.order(cols[0]), [third, second])
        self.assertEqual(self.order(cols[1]), [first])
        self.client.post(f'/api/tools/kanban/items/{second}/move', json={'column_id': cols[1], 'before_id': first})
        self.assertEqual(self.order(cols[1]), [second, first])
        self.assertEqual(self.detail(second)['history'][0]['changes']['status'], {'before': 'To do', 'after': 'In Progress'})
        fourth = self.add(board, cols[0], 'Fourth')
        self.assertEqual(self.order(cols[0]), [third, fourth])

    def test_edit_history_metadata_and_noop_save(self):
        board, cols = self.board()
        ident = self.add(board, cols[0], 'Before')
        original = self.detail(ident)
        payload = {'title': 'After', 'notes': 'Updated\nnotes', 'column_id': cols[1], 'revision': 0}
        response = self.client.patch(f'/api/tools/kanban/items/{ident}', json=payload)
        self.assertEqual(response.status_code, 200)
        item = response.get_json()['item']
        self.assertEqual(item['created_at'], original['created_at'])
        self.assertEqual(item['revision'], 1)
        self.assertTrue(item['updated_at'])
        self.assertEqual(item['history'][0]['actor'], 'Test')
        self.assertEqual(item['history'][0]['changes']['notes'], {'before': 'Original notes', 'after': 'Updated\nnotes'})
        self.assertEqual(self.order(cols[1]), [ident])
        payload['revision'] = 1
        self.client.patch(f'/api/tools/kanban/items/{ident}', json=payload)
        self.assertEqual(len(self.detail(ident)['history']), 2)

    def test_stale_edits_and_moves_are_rejected(self):
        board, cols = self.board()
        ident = self.add(board, cols[0], 'Keep me')
        payload = {'title': 'Current', 'notes': 'Current notes', 'column_id': cols[0], 'revision': 0}
        self.client.patch(f'/api/tools/kanban/items/{ident}', json=payload)
        payload['notes'] = 'Stale notes'
        self.assertEqual(self.client.patch(f'/api/tools/kanban/items/{ident}', json=payload).status_code, 409)
        self.assertEqual(self.client.post(f'/api/tools/kanban/items/{ident}/move', json={'column_id': cols[1], 'revision': 0}).status_code, 409)
        self.assertEqual(self.detail(ident)['notes'], 'Current notes')
        self.assertEqual(self.order(cols[0]), [ident])

    def test_foreign_items_columns_and_bad_requests_are_rejected(self):
        board, cols = self.board()
        _, foreign = self.board('Other board', 2)
        ident = self.add(board, cols[0], 'Private')
        url = f'/api/tools/kanban/items/{ident}'
        self.assertEqual(self.client.get(url, headers={'X-Test-User': '2'}).status_code, 404)
        self.assertEqual(self.client.post(url + '/move', json={'column_id': foreign[0]}).status_code, 400)
        self.assertEqual(self.client.post(url + '/move', json={'column_id': cols[0], 'before_id': 999}).status_code, 400)
        self.assertEqual(self.client.post(url + '/move', json=['bad']).status_code, 400)
        self.assertEqual(self.client.post(url + '/move', json={'column_id': True}).status_code, 400)
        payload = {'title': 'Hacked', 'notes': '', 'column_id': cols[0], 'revision': 0}
        self.assertEqual(self.client.patch(url, json=payload, headers={'X-Test-User': '2'}).status_code, 404)
        payload['title'] = ' '
        self.assertEqual(self.client.patch(url, json=payload).status_code, 400)
        self.assertEqual(self.detail(ident)['title'], 'Private')
        self.assertEqual(len(self.detail(ident)['history']), 1)

    def test_kanban_page_renders_detail_editor_and_disables_title_autocomplete(self):
        board, cols = self.board()
        self.add(board, cols[0], '<script>alert(1)</script>')
        response = self.client.get(f'/tools/kanban?board={board}')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="kanban-detail"', html)
        self.assertIn('name="title" autocomplete="off"', html)
        self.assertIn('Update history', html)
        self.assertNotIn('<script>alert(1)</script>', html)

    def create_page(self, content=''):
        return self.client.post('/tools/wiki/api/pages', json={'title': 'Session notes', 'content': content}).get_json()['page']

    def edit(self, page, session, content, **extra):
        response = self.client.put('/tools/wiki/api/pages/' + page['slug'], json={'content': content, 'edit_session': session, **extra})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()['page']

    def feed(self):
        return self.client.get('/tools/wiki/api/activity').get_json()['activity']

    def test_autosaves_share_one_net_change_event(self):
        page, session = self.create_page(), str(uuid.uuid4())
        for text in ['one', 'one two', 'one two three', 'one two three four']:
            page = self.edit(page, session, text)
        events = self.feed()
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]['added_lines'], events[0]['removed_lines'], events[0]['count_unit']), (1, 0, 'lines'))

    def test_session_autosaves_return_updated_wiki_links(self):
        page = self.create_page()
        target = self.client.post('/tools/wiki/api/pages', json={
            'title': 'Related article', 'content': f"[[{page['slug']}]]",
        }).get_json()['page']
        session = str(uuid.uuid4())
        page = self.edit(page, session, f"[[{target['slug']}]]")
        self.assertEqual(page['links'], {
            'incoming': [{'title': target['title'], 'slug': target['slug']}],
            'missing': [],
            'deleted': [],
            'outgoing': [{'title': target['title'], 'slug': target['slug']}],
        })
        page = self.edit(page, session, 'Link removed')
        self.assertEqual(page['links']['outgoing'], [])
        self.assertEqual(len(page['links']['incoming']), 1)
        events = [event for event in self.feed() if event['resource_id'] == page['id']]
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]['added_lines'], events[0]['removed_lines']), (1, 0))

    def test_editing_an_existing_line_counts_a_replacement(self):
        page = self.create_page('original text')
        self.edit(page, str(uuid.uuid4()), 'original text plus two words')
        edited = next(event for event in self.feed() if event['action'] == 'edited')
        self.assertEqual((edited['added_lines'], edited['removed_lines']), (1, 1))

    def test_separate_visits_have_separate_events_and_deletion_is_real(self):
        page = self.edit(self.create_page(), str(uuid.uuid4()), 'one\ntwo\nthree')
        self.edit(page, str(uuid.uuid4()), 'one\nthree')
        self.assertEqual(len(self.feed()), 2)
        self.assertEqual((self.feed()[0]['added_lines'], self.feed()[0]['removed_lines']), (0, 1))

    def test_new_lines_only_count_additions_across_autosaves(self):
        page, session = self.create_page('Original line'), str(uuid.uuid4())
        for content in ['Original line\nNew', 'Original line\nNew line\nAnother line']:
            page = self.edit(page, session, content)
        edited = [entry for entry in self.feed() if entry['action'] == 'edited']
        self.assertEqual(len(edited), 1)
        self.assertEqual((edited[0]['added_lines'], edited[0]['removed_lines']), (2, 0))

    def test_reverting_session_removes_net_zero_event(self):
        page, session = self.create_page(), str(uuid.uuid4())
        page = self.edit(page, session, 'temporary words')
        event_id = self.feed()[0]['id']
        page = self.edit(page, session, '')
        self.assertEqual(self.feed(), [])
        self.edit(page, session, 'final words')
        self.assertEqual(self.feed()[0]['id'], event_id)
        self.assertEqual(self.feed()[0]['added_lines'], 1)

    def test_renaming_keeps_the_same_session_and_noop_does_not_add_activity(self):
        page, session = self.create_page(), str(uuid.uuid4())
        page = self.edit(page, session, 'first')
        event_id = self.feed()[0]['id']
        page = self.edit(page, session, 'first second', title='Renamed notes')
        self.edit(page, session, 'first second')
        self.assertEqual(len(self.feed()), 1)
        self.assertEqual(self.feed()[0]['id'], event_id)
        self.assertEqual(self.feed()[0]['resource_name'], 'Renamed notes')
        self.assertEqual(self.feed()[0]['added_lines'], 1)
        self.assertEqual(self.client.get('/tools/wiki/api/activity', headers={'X-Test-User': '2'}).get_json()['activity'], [])

    def test_sessions_are_scoped_to_page_and_invalid_session_is_rejected(self):
        first, second, session = self.create_page(), self.create_page(), str(uuid.uuid4())
        self.edit(first, session, 'one')
        self.edit(second, session, 'two words')
        self.assertEqual(len(self.feed()), 2)
        response = self.client.put('/tools/wiki/api/pages/' + first['slug'], json={'edit_session': 'bad', 'content': 'lost'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/tools/wiki/api/pages/' + first['slug']).get_json()['page']['content'], 'one')

    def test_legacy_schema_migration_preserves_items_and_activity(self):
        filename = str(Path(self.directory.name) / 'legacy.sqlite')
        with sqlite3.connect(filename) as connection:
            connection.executescript("""
            CREATE TABLE kanban_items(id INTEGER PRIMARY KEY,board_id INTEGER,column_id INTEGER,title TEXT,notes TEXT,position INTEGER,created_at TEXT);
            INSERT INTO kanban_items VALUES(1,1,1,'Legacy title','Legacy notes',0,'2025-01-01');
            CREATE TABLE activity_events(id TEXT PRIMARY KEY,user_id INTEGER,area TEXT,resource_id TEXT,resource_name TEXT,action TEXT,added_lines INTEGER,removed_lines INTEGER,occurred_at TEXT);
            INSERT INTO activity_events VALUES('old',1,'wiki','page','Legacy page','edited',1,1,'2025-01-01');
            """)
        old_database = self.app.config['FOUR_AD_DATABASE']
        self.app.config['FOUR_AD_DATABASE'] = filename
        for _ in range(2):
            kanban.init_database(self.app)
            activity.init_database(self.app)
        self.app.config['FOUR_AD_DATABASE'] = old_database
        with sqlite3.connect(filename) as connection:
            self.assertEqual(connection.execute('SELECT title,notes,updated_at,revision FROM kanban_items').fetchone(), ('Legacy title', 'Legacy notes', '2025-01-01', 0))
            self.assertEqual(connection.execute('SELECT added_lines,removed_lines,count_unit FROM activity_events').fetchone(), (1, 1, 'lines'))


if __name__ == '__main__':
    unittest.main()
