import tempfile
import unittest
from test_dashboard_tools import test_app

class CommentTests(unittest.TestCase):
    def test_comments_are_private_revision_safe_and_survive_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            client=test_app(directory).test_client()
            client.post('/tools/kanban',data={'name':'One'});client.post('/tools/kanban',data={'name':'Two'})
            board=client.get('/api/tools/kanban/boards/1').json['board']
            item=client.post('/api/tools/kanban/boards/1/items',json={'title':'Task','notes':'Original','column_id':board['columns'][0]['id']}).json['item']
            root='/api/tools/kanban/items/'+str(item['id']);comments=root+'/comments'
            self.assertEqual(client.post(comments,json={'body':'  '}).status_code,400)
            response=client.post(comments,json={'body':'<script>fixture</script>\nplain text'});self.assertEqual(response.status_code,201)
            comment=response.json['item']['comments'][0]
            for method in ('get','post'):
                self.assertEqual(getattr(client,method)(comments,json={'body':'foreign'},headers={'X-Test-User':'2'}).status_code,404)
            path=comments+'/'+str(comment['id'])
            self.assertEqual(client.patch(path,json={'body':'Edited','revision':0}).status_code,200)
            self.assertEqual(client.patch(path,json={'body':'Stale','revision':0}).status_code,409)
            dest=client.get('/api/tools/kanban/boards/2').json['board']
            moved=client.post(root+'/transfer',json={'board_id':2,'column_id':dest['columns'][0]['id'],'revision':item['revision']}).json['item']
            self.assertEqual(moved['comments'][0]['body'],'Edited');self.assertEqual(moved['notes'],'Original')
            self.assertEqual(client.delete(path,json={'revision':0}).status_code,409)
            self.assertEqual(client.delete(path,json={'revision':1}).status_code,200)
            self.assertEqual(client.get(comments).json['comments'],[])
