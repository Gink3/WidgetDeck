import tempfile
import unittest
from test_dashboard_tools import test_app

class LinkTests(unittest.TestCase):
    def test_cross_board_links_cycles_revisions_and_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            client=test_app(directory).test_client();ids=[]
            for name in ['One','Two','Three']:
                client.post('/tools/kanban',data={'name':name})
                board=client.get('/api/tools/kanban/boards').json['boards'][0]
                column=client.get('/api/tools/kanban/boards/'+str(board['id'])).json['board']['columns'][0]['id']
                ids.append(client.post(f"/api/tools/kanban/boards/{board['id']}/items",json={'title':name,'column_id':column}).json['item']['id'])
            def link(source,target,rev=0,kind='depends_on',headers=None):
                return client.put(f'/api/tools/kanban/items/{source}/links',json={'links':[{'target_id':target,'kind':kind}],'revision':rev},headers=headers)
            a,b,c=ids
            self.assertEqual(link(a,b,headers={'X-Test-User':'2'}).status_code,404)
            self.assertEqual(link(a,a).status_code,400)
            self.assertEqual(link(a,9999).status_code,400)
            self.assertEqual(link(a,b).status_code,200)
            self.assertEqual(link(a,c).status_code,409)
            self.assertEqual(link(b,c).status_code,200)
            self.assertEqual(link(c,a).status_code,400)
            self.assertEqual(link(c,a,kind='related').status_code,200)
            detail=client.get(f'/api/tools/kanban/items/{b}').json['item']
            self.assertEqual(detail['dependents'][0]['target_id'],a)
            self.assertEqual(detail['links'][0]['target_id'],c)
            self.assertEqual(client.delete(f'/api/tools/kanban/items/{b}',json={'revision':1}).status_code,204)
            self.assertEqual(client.get(f'/api/tools/kanban/items/{a}').json['item']['links'],[])
