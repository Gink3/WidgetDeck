import tempfile
import unittest
from test_dashboard_tools import test_app

class ColumnLifecycleTests(unittest.TestCase):
    def test_add_remove_migrates_cards_preserves_history_and_checks_topology_and_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            client=test_app(directory).test_client()
            client.post('/tools/kanban',data={'name':'Board'})
            board=client.get('/api/tools/kanban/boards/1').json['board'];order=[c['id'] for c in board['columns']]
            root='/api/tools/kanban/boards/1/columns'
            response=client.post(root,json={'name':'Review','expected_order':order});self.assertEqual(response.status_code,201)
            new=response.json['columns'][-1]['id'];current=order+[new]
            self.assertEqual(client.post(root,json={'name':'Stale','expected_order':order}).status_code,409)
            item=client.post('/api/tools/kanban/boards/1/items',json={'title':'Preserve','notes':'original','column_id':new}).json['item']
            self.assertEqual(client.delete(root+f'/{new}',json={'expected_order':current}).status_code,400)
            self.assertEqual(client.delete(root+f'/{new}',json={'expected_order':current,'destination_id':order[0]},headers={'X-Test-User':'2'}).status_code,404)
            self.assertEqual(client.delete(root+f'/{new}',json={'expected_order':current,'destination_id':order[0]}).status_code,200)
            after=client.get('/api/tools/kanban/items/'+str(item['id'])).json['item']
            self.assertEqual(after['notes'],'original');self.assertEqual(after['column_id'],order[0]);self.assertEqual(after['revision'],1)
            self.assertEqual(after['history'][0]['action'],'moved')
            self.assertEqual(client.patch('/api/tools/kanban/items/'+str(item['id']),json={'title':'stale','notes':'','column_id':order[0],'revision':0}).status_code,409)
            for ident in order[:-1]:
                self.assertEqual(client.delete(root+f'/{ident}',json={'expected_order':order,'destination_id':order[-1]}).status_code,200);order=order[1:]
            self.assertEqual(client.delete(root+f'/{order[0]}',json={'expected_order':order}).status_code,400)
