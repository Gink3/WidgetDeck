import tempfile,unittest
from unittest.mock import patch
from test_dashboard_tools import test_app
from dashboard.campaign_tools import kanban_models as models
from dashboard.database import db

class KanbanCompletionTests(unittest.TestCase):
    def test_completion_clock_survives_edits_resets_on_reopen_and_migrates_history(self):
        with tempfile.TemporaryDirectory() as directory:
            app=test_app(directory);client=app.test_client();client.post('/tools/kanban',data={'name':'Clock'})
            board=client.get('/api/tools/kanban/boards/1').json['board'];todo,doing,done=[c['id'] for c in board['columns']]
            item=client.post('/api/tools/kanban/boards/1/items',json={'title':'Complete','column_id':done}).json['item'];self.assertTrue(item['completed_at'])
            url='/api/tools/kanban/items/'+str(item['id'])
            item=client.post(url+'/move',json={'column_id':todo,'revision':item['revision']}).json['item'];self.assertIsNone(item['completed_at'])
            with patch.object(models,'timestamp',return_value='2026-01-01T00:00:00+00:00'):
                item=client.post(url+'/move',json={'column_id':done,'revision':item['revision']}).json['item']
            self.assertEqual(item['completed_at'],'2026-01-01T00:00:00+00:00')
            item=client.patch(url,json={'title':'Edited later','notes':'Retained','column_id':done,'revision':item['revision']}).json['item']
            self.assertEqual(item['completed_at'],'2026-01-01T00:00:00+00:00')
            # Upgrade a database from before completion timestamps existed.
            with app.app_context():
                db().execute('ALTER TABLE kanban_items DROP COLUMN completed_at');db().commit()
            models.init_database(app);models.init_database(app)
            restored=client.get(url).json['item'];self.assertEqual(restored['completed_at'],'2026-01-01T00:00:00+00:00');self.assertEqual(restored['notes'],'Retained')
            self.assertEqual(len(client.get('/api/tools/kanban/boards/1').json['board']['items']),1)
