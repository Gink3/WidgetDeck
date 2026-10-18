import io
import tempfile
import unittest
from test_dashboard_tools import test_app


class WikiInboxTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = test_app(self.directory.name)
        self.client = self.app.test_client()

    def capture(self, content='Remember this'):
        response = self.client.post('/tools/wiki/api/inbox', json={'content': content})
        self.assertEqual(response.status_code, 201)
        return response.json['note']

    def test_separate_notes_process_reopen_and_conflicts(self):
        note = self.capture()
        url = '/tools/wiki/api/inbox/' + note['id']
        self.assertEqual(self.client.get('/tools/wiki/api/pages').json['pages'], [])
        self.assertEqual(len(self.client.get('/tools/wiki/api/inbox').json['notes']), 1)
        updated = self.client.put(url, json={'revision': 0, 'processed': True})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.client.get('/tools/wiki/api/inbox').json['notes'], [])
        self.assertEqual(len(self.client.get('/tools/wiki/api/inbox?processed=1').json['notes']), 1)
        self.assertEqual(self.client.put(url, json={'revision': 0, 'content': 'stale'}).status_code, 409)
        self.assertEqual(self.client.put(url, json={'revision': 1, 'processed': False}).status_code, 200)
        self.assertEqual(len(self.client.get('/tools/wiki/api/inbox').json['notes']), 1)
        other = {'X-Test-User': '2'}
        self.assertEqual(self.client.get(url, headers=other).status_code, 404)
        self.assertEqual(self.client.put(url, headers=other, json={'revision': 2}).status_code, 404)
        self.assertEqual(self.client.get('/tools/wiki/api/inbox', headers=other).json['notes'], [])

    def test_files_page_copy_and_backup_restore(self):
        note = self.capture('')
        url = '/tools/wiki/api/inbox/' + note['id']
        upload = self.client.post(url + '/attachments', data={'document': (io.BytesIO(b'original file'), 'reminder.txt')})
        self.assertEqual(upload.status_code, 201, upload.json)
        item = upload.json['attachments'][0]
        self.assertEqual(len(self.client.get('/tools/wiki/api/inbox?q=reminder').json['notes']), 1)
        page = self.client.post('/tools/wiki/api/pages', json={'title': 'Research'}).json['page']
        attached = self.client.post(url + '/attach/' + item['id'], json={'page_slug': page['slug']})
        self.assertEqual(attached.status_code, 201, attached.json)
        self.assertNotEqual(attached.json['id'], item['id'])
        self.client.put(url, json={'revision': 0, 'page_slug': page['slug'], 'processed': True})
        self.assertEqual(self.client.get(url).json['note']['pages'][0]['id'], page['id'])
        download = self.client.get('/tools/wiki/api/attachments/' + item['id'])
        self.addCleanup(download.close)
        self.assertEqual(download.data, b'original file')
        other = {'X-Test-User': '2'}
        self.assertEqual(self.client.get('/tools/wiki/api/attachments/' + item['id'], headers=other).status_code, 404)
        backup = self.client.get('/tools/wiki/api/backup')
        self.addCleanup(backup.close)
        restored = self.client.post('/tools/wiki/api/backup', data={'backup': (io.BytesIO(backup.data), 'backup.zip')}, headers=other)
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual(self.client.get('/tools/wiki/api/inbox', headers=other).json['notes'], [])
        imported = self.client.get('/tools/wiki/api/inbox?processed=1', headers=other).json['notes'][0]
        self.assertNotEqual(imported['id'], note['id'])
        self.assertNotEqual(imported['pages'][0]['id'], page['id'])
        self.assertEqual(len(imported['attachments']), 1)
        result = self.client.get('/tools/wiki/api/attachments/' + imported['attachments'][0]['id'], headers=other)
        self.addCleanup(result.close)
        self.assertEqual(result.data, b'original file')

    def test_inbox_only_document_processing_and_backup(self):
        from flask import g
        from dashboard.wiki.documents import process_one
        note = self.capture('Document reminder')
        self.client.post('/tools/wiki/api/inbox/' + note['id'] + '/attachments', data={'document': (io.BytesIO(b'unique searchable document text'), 'notes.txt')})
        with self.app.test_request_context():
            g.dashboard_user = {'id': 1, 'username': 'Test'}
            self.assertTrue(process_one())
        self.assertEqual(len(self.client.get('/tools/wiki/api/inbox?q=unique searchable').json['notes']), 1)
        backup = self.client.get('/tools/wiki/api/backup')
        self.addCleanup(backup.close)
        result = self.client.post('/tools/wiki/api/backup', data={'backup': (io.BytesIO(backup.data), 'backup.zip')}, headers={'X-Test-User': '2'})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(len(self.client.get('/tools/wiki/api/inbox', headers={'X-Test-User': '2'}).json['notes']), 1)
