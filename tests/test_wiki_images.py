"""Image catalog ownership, optimistic tags, legacy migration and archive contracts."""
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from PIL import Image
from test_dashboard_tools import test_app


class WikiImageLibraryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = test_app(self.directory.name)
        self.client = self.app.test_client()
        output = io.BytesIO()
        Image.new('RGB', (4, 4), 'blue').save(output, format='PNG')
        self.image = output.getvalue()

    def upload(self):
        return self.client.post('/tools/wiki/api/images', data={'image': (io.BytesIO(self.image), 'Article-photo.png', 'image/png')}).json['image']

    def test_search_tags_references_and_concurrent_owner_scoped_updates(self):
        image = self.upload()
        self.client.post('/tools/wiki/api/pages', json={'title': 'Illustrated page', 'content': f"![photo]({image['url']})"})
        result = self.client.get('/tools/wiki/api/images?q=article-PHOTO')
        self.assertEqual(result.status_code, 200)
        entry = result.json['images'][0]
        self.assertEqual(entry['pages'], [{'title': 'Illustrated page', 'slug': 'illustrated-page'}])
        path = f"/tools/wiki/api/images/{image['id']}/metadata"
        result = self.client.patch(path, json={'tags': [' Research ', 'café', 'Research'], 'revision': 0})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['image']['tags'], ['Research', 'café'])
        self.assertEqual(result.json['image']['revision'], 1)
        self.assertEqual(self.client.get('/tools/wiki/api/images?q=CAFÉ').json['images'][0]['id'], image['id'])
        self.assertEqual(self.client.patch(path, json={'tags': [], 'revision': 0}).status_code, 409)
        self.assertEqual(self.client.patch(path, json={'tags': [], 'revision': 1}, headers={'X-Test-User': '2'}).status_code, 404)
        self.assertEqual(self.client.get('/tools/wiki/api/images', headers={'X-Test-User': '2'}).json['images'], [])
        for tags in [None, 'wrong', [''], ['x'*41], ['tag']*21, [True]]:
            self.assertEqual(self.client.patch(path, json={'tags': tags, 'revision': 1}).status_code, 400)
        self.assertEqual(self.client.patch(path, json={'tags': [], 'revision': True}).status_code, 400)
        with self.client.get(image['url']) as response:
            self.assertEqual(response.data, self.image)

    def test_tags_and_image_references_round_trip_without_changing_old_urls(self):
        image = self.upload()
        self.client.patch(f"/tools/wiki/api/images/{image['id']}/metadata", json={'tags': ['reference'], 'revision': 0})
        self.client.post('/tools/wiki/api/pages', json={'title': 'Original', 'content': f"![photo]({image['url']})"})
        with self.client.get('/tools/wiki/api/backup') as response:
            archive = response.data
        result = self.client.post('/tools/wiki/api/backup', data={'backup': (io.BytesIO(archive), 'backup.zip')}, headers={'X-Test-User': '2'})
        self.assertEqual(result.status_code, 200)
        restored = self.client.get('/tools/wiki/api/images', headers={'X-Test-User': '2'}).json['images'][0]
        self.assertEqual(restored['tags'], ['reference'])
        self.assertNotEqual(restored['id'], image['id'])
        self.assertEqual(restored['pages'][0]['title'], 'Original')
        with self.client.get(image['url']) as response:
            self.assertEqual(response.data, self.image)

    def test_v1_archives_without_tags_still_import(self):
        output = io.BytesIO()
        data = {'version': 1, 'pages': [], 'images': [{'id': 'legacy-image', 'filename': 'old.png', 'mime_type': 'image/png'}]}
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('wiki.json', json.dumps(data))
            archive.writestr('images/legacy-image', self.image)
        result = self.client.post('/tools/wiki/api/backup', data={'backup': (io.BytesIO(output.getvalue()), 'old.zip')})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get('/tools/wiki/api/images').json['images'][0]['tags'], [])

    def test_legacy_image_schema_migrates_automatically_with_existing_files(self):
        directory = Path(self.directory.name)/'legacy'
        directory.mkdir()
        with sqlite3.connect(directory/'dashboard.sqlite') as connection:
            connection.execute('CREATE TABLE wiki_images(id TEXT PRIMARY KEY,user_id INTEGER,filename TEXT,stored_name TEXT,mime_type TEXT,byte_size INTEGER,created_at TEXT)')
            connection.execute('INSERT INTO wiki_images VALUES(?,?,?,?,?,?,?)', ('old-image', 1, 'old.png', 'old.png', 'image/png', len(self.image), '2026-01-01'))
        images = directory/'wiki_uploads'/'1'
        images.mkdir(parents=True)
        (images/'old.png').write_bytes(self.image)
        client = test_app(str(directory)).test_client()
        entry = client.get('/tools/wiki/api/images').json['images'][0]
        self.assertEqual((entry['id'], entry['tags'], entry['revision']), ('old-image', [], 0))
        with client.get('/tools/wiki/api/images/old-image') as response:
            self.assertEqual(response.data, self.image)

    def test_spoofed_upload_and_legacy_active_content_are_safe(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'
        response = self.client.post('/tools/wiki/api/images', data={'image': (io.BytesIO(svg), 'fake.png', 'image/svg+xml')})
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/tools/wiki/api/images', data={'image': (io.BytesIO(self.image), 'valid.png', 'image/svg+xml')})
        with self.client.get(response.json['image']['url']) as downloaded:
            self.assertEqual(downloaded.mimetype, 'image/png')
        image = self.upload()
        with sqlite3.connect(Path(self.directory.name)/'dashboard.sqlite') as connection:
            stored = connection.execute('SELECT stored_name FROM wiki_images WHERE id=?', (image['id'],)).fetchone()[0]
            connection.execute('UPDATE wiki_images SET mime_type=? WHERE id=?', ('image/svg+xml', image['id']))
        (Path(self.directory.name)/'wiki_uploads'/'1'/stored).write_bytes(svg)
        with self.client.get(image['url']) as downloaded:
            self.assertEqual(downloaded.data, svg)
            self.assertEqual(downloaded.mimetype, 'application/octet-stream')
            self.assertIn('attachment', downloaded.headers['Content-Disposition'])
            self.assertEqual(downloaded.headers['X-Content-Type-Options'], 'nosniff')
            self.assertIn('sandbox', downloaded.headers['Content-Security-Policy'])
