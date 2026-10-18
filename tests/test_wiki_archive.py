import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from test_dashboard_tools import test_app


class WikiArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = test_app(self.directory.name)
        self.client = self.app.test_client()

    def create(self, title='Archive', content=''):
        return self.client.post('/tools/wiki/api/pages',json={'title':title,'content':content}).json['page']

    def upload(self, slug, data=b'%PDF-1.7\narchived scan', name='scan.pdf', owner=1):
        return self.client.post(f'/tools/wiki/api/pages/{slug}/attachments', data={'document':(io.BytesIO(data),name)},headers={'X-Test-User':str(owner)})

    def test_attachment_original_bytes_checksum_download_and_owner_scope(self):
        page = self.create()
        payload = b'%PDF-1.7\narchived scan'
        result = self.upload(page['slug'],payload)
        self.assertEqual(result.status_code,201,result.json)
        attachment = result.json['attachments'][0]
        self.assertEqual(attachment['sha256'],hashlib.sha256(payload).hexdigest())
        self.assertEqual(attachment['byte_size'],len(payload))
        url = '/tools/wiki/api/attachments/' + attachment['id']
        response = self.client.get(url)
        self.addCleanup(response.close)
        self.assertEqual(response.data,payload)
        self.assertIn('attachment;',response.headers['Content-Disposition'])
        self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
        self.assertEqual(self.client.get(url,headers={'X-Test-User':'2'}).status_code,404)
        self.assertEqual(self.upload(page['slug'],owner=2).status_code,404)
        self.assertEqual(self.client.get('/tools/wiki/api/pages/' + page['slug'] + '/attachments',headers={'X-Test-User':'2'}).status_code,404)
        self.client.delete('/tools/wiki/api/pages/' + page['slug'])
        self.assertEqual(self.client.get(url).status_code,404)
        self.client.post('/tools/wiki/api/trash/' + page['slug'] + '/restore')
        restored = self.client.get(url)
        self.addCleanup(restored.close)
        self.assertEqual(restored.data,payload)

    def test_upload_validation(self):
        page = self.create()
        self.assertEqual(self.upload(page['slug'],b'<script/>','bad.html').status_code,400)
        self.assertEqual(self.upload(page['slug'],b'','empty.pdf').status_code,400)
        with patch('dashboard.wiki.routes.MAX_ATTACHMENT_BYTES',8):
            self.assertEqual(self.upload(page['slug']).status_code,400)
        self.assertEqual(self.upload(page['slug'],b'phone scan','capture.heic').status_code,201)

    def test_backup_includes_attachments_and_topic_settings_and_validates_integrity(self):
        page = self.create()
        item = self.upload(page['slug']).json['attachments'][0]
        self.client.put('/tools/wiki/api/pages/' + page['slug'],json={'content':'[scan](/tools/wiki/api/attachments/' + item['id'] + ')','metadata':{'topic':{'enabled':True,'category':'Books','property':'Status','value':'Reading'}}})
        response = self.client.get('/tools/wiki/api/backup')
        self.addCleanup(response.close)
        backup = response.data
        result = self.client.post('/tools/wiki/api/backup',data={'backup':(io.BytesIO(backup),'backup.zip')},headers={'X-Test-User':'2'})
        self.assertEqual(result.status_code,200,result.json)
        imported = self.client.get('/tools/wiki/api/pages/archive',headers={'X-Test-User':'2'}).json['page']
        items = self.client.get('/tools/wiki/api/pages/archive/attachments',headers={'X-Test-User':'2'}).json['attachments']
        self.assertNotEqual(items[0]['id'],item['id'])
        self.assertIn(items[0]['id'],imported['content'])
        self.assertEqual(imported['metadata']['topic']['value'],'Reading')
        self.assertEqual(items[0]['sha256'],item['sha256'])
        corrupt = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(backup)) as src, zipfile.ZipFile(corrupt,'w') as dst:
            for name in src.namelist(): dst.writestr(name,b'corrupt' if name.startswith('attachments/') else src.read(name))
        result = self.client.post('/tools/wiki/api/backup',data={'backup':(io.BytesIO(corrupt.getvalue()),'backup.zip')})
        self.assertEqual(result.status_code,400)
        self.assertIn('checksum',result.json['error'])
        self.assertEqual(len(self.client.get('/tools/wiki/api/pages').json['pages']),1)

    def test_deleted_and_missing_links_are_distinct_and_visits_do_not_create_pages(self):
        target = self.create('Old name')
        renamed = self.client.put('/tools/wiki/api/pages/' + target['slug'],json={'title':'New name'}).json['page']
        article = self.create('Referring','[[Old name]] [[new-name]] [[Missing]]')
        self.client.delete('/tools/wiki/api/pages/' + renamed['slug'])
        links = self.client.get('/tools/wiki/api/pages/' + article['slug']).json['page']['links']
        self.assertEqual(links['deleted'],[{'title':'New name','slug':'new-name'}])
        self.assertEqual(links['missing'],['missing'])
        self.assertEqual(self.client.get('/tools/wiki/api/resolve/old-name').json['state'],'deleted')
        self.assertEqual(self.client.get('/tools/wiki/api/resolve/old-name',headers={'X-Test-User':'2'}).json['state'],'missing')
        self.assertEqual(self.client.get('/tools/wiki/never-created').status_code,200)
        self.assertEqual(self.client.get('/tools/wiki/api/pages/never-created').status_code,404)
        self.assertEqual(self.client.get('/tools/wiki/api/pages?review=deleted-links').json['pages'][0]['id'],article['id'])
        self.client.post('/tools/wiki/api/trash/new-name/restore')
        links = self.client.get('/tools/wiki/api/pages/' + article['slug']).json['page']['links']
        self.assertEqual(links['deleted'],[])
        self.assertEqual(links['outgoing'][0]['slug'],'new-name')

    def test_topic_validation_and_private_index(self):
        page = self.create()
        response = self.client.put('/tools/wiki/api/pages/' + page['slug'],json={'metadata':{'topic':{'enabled':True,'sort':'sql'}}})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.client.get('/tools/wiki/api/index',headers={'X-Test-User':'2'}).json['pages'],[])
