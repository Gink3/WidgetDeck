import tempfile,unittest
from test_dashboard_tools import test_app
from dashboard.database import db

class KanbanBoardDeletionTests(unittest.TestCase):
    def test_exact_name_owner_and_atomic_related_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            app=test_app(directory);client=app.test_client()
            for name in ('Delete me','Keep me'):client.post('/tools/kanban',data={'name':name})
            boards=[client.get('/api/tools/kanban/boards/'+str(n)).json['board'] for n in (1,2)]
            items=[client.post('/api/tools/kanban/boards/'+str(board['id'])+'/items',json={'title':'Card','column_id':board['columns'][0]['id']}).json['item'] for board in boards]
            first,second=[i['id'] for i in items]
            with app.app_context():
                connection=db()
                connection.execute("INSERT INTO kanban_comments(item_id,user_id,body,created_at,updated_at) VALUES(?,1,'comment','now','now')",(first,))
                effort=connection.execute("INSERT INTO kanban_efforts(user_id,name,name_key) VALUES(1,'Shared','shared')").lastrowid
                connection.execute('INSERT INTO kanban_item_efforts(item_id,effort_id) VALUES(?,?)',(first,effort))
                connection.execute("INSERT INTO kanban_links(item_id,target_id,kind) VALUES(?,?,'related')",(second,first));connection.commit()
            url='/api/tools/kanban/boards/1'
            self.assertEqual(client.delete(url,json={'expected_name':'delete me'}).status_code,400)
            self.assertEqual(client.delete(url,json={'expected_name':'Delete me'},headers={'X-Test-User':'2'}).status_code,404)
            self.assertEqual(client.get(url).status_code,200)
            self.assertEqual(client.delete(url,json={'expected_name':'Delete me'}).status_code,200)
            self.assertEqual(client.get(url).status_code,404);self.assertEqual(client.delete(url,json={'expected_name':'Delete me'}).status_code,404)
            self.assertEqual(client.get('/api/tools/kanban/boards/2').status_code,200)
            with app.app_context():
                for table in ('kanban_items','kanban_columns'):
                    self.assertEqual(db().execute(f'SELECT COUNT(*) FROM {table} WHERE board_id=1').fetchone()[0],0)
                for table in ('kanban_comments','kanban_item_history','kanban_item_efforts'):
                    self.assertEqual(db().execute(f'SELECT COUNT(*) FROM {table} WHERE item_id=?',(first,)).fetchone()[0],0)
                self.assertEqual(db().execute('SELECT COUNT(*) FROM kanban_links').fetchone()[0],0)
                self.assertEqual(db().execute('SELECT COUNT(*) FROM kanban_efforts').fetchone()[0],1)
