import io
import tempfile
import unittest
from test_dashboard_tools import test_app


class TopicSelectionTests(unittest.TestCase):
    def test_selected_pages_survive_save_and_backup_remapping(self):
        with tempfile.TemporaryDirectory() as directory:
            client = test_app(directory).test_client()
            target = client.post('/tools/wiki/api/pages', json={'title': 'Target'}).json['page']
            client.post('/tools/wiki/api/pages', json={'title': 'Topic'})
            saved = client.put('/tools/wiki/api/pages/topic', json={'metadata': {'topic': {'enabled': True, 'mode': 'selected', 'page_ids': [target['id']]}}})
            self.assertEqual(saved.json['page']['metadata']['topic']['page_ids'], [target['id']])
            self.assertEqual(client.put('/tools/wiki/api/pages/topic', json={'metadata': {'topic': {'page_ids': 'bad'}}}).status_code, 400)
            backup = client.get('/tools/wiki/api/backup')
            self.addCleanup(backup.close)
            imported = client.post('/tools/wiki/api/backup', data={'backup': (io.BytesIO(backup.data), 'backup.zip')})
            self.assertEqual(imported.status_code, 200, imported.json)
            copied = client.get('/tools/wiki/api/pages/target-2').json['page']
            topic = client.get('/tools/wiki/api/pages/topic-2').json['page']
            self.assertEqual(topic['metadata']['topic']['page_ids'], [copied['id']])
