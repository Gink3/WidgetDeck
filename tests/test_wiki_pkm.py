import io
import json
import tempfile
import unittest
import zipfile
from PIL import Image
from test_dashboard_tools import test_app


class WikiPKMTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = test_app(self.directory.name)
        self.client = self.app.test_client()

    def create(self, title='Original', content='First version'):
        r = self.client.post('/tools/wiki/api/pages', json=dict(title=title, content=content))
        self.assertEqual(r.status_code, 201)
        return r.json['page']

    def update(self, page, **changes):
        r = self.client.put('/tools/wiki/api/pages/' + page['slug'], json={'revision': page['revision'], **changes})
        self.assertEqual(r.status_code, 200, r.json)
        return r.json['page']

    def test_rename_keeps_links_and_rejects_stale_updates(self):
        original = self.create()
        referring = self.create('Referring', '[[Original]] and [[original]]')
        renamed = self.update(original, title='New title', aliases=['Alternate'])
        for alias in ['Original', 'original', 'Alternate']:
            self.assertEqual(self.client.get('/tools/wiki/api/pages/' + alias).json['page']['id'], original['id'])
        self.assertEqual(self.client.get('/tools/wiki/original').status_code, 302)
        self.assertEqual(self.client.get('/tools/wiki/api/pages/' + referring['slug']).json['page']['links']['outgoing'][0]['slug'], renamed['slug'])
        stale = self.client.put('/tools/wiki/api/pages/' + renamed['slug'], json={'revision':0,'content':'overwrite'})
        self.assertEqual(stale.status_code, 400)
        self.assertEqual(self.client.get('/tools/wiki/api/pages/' + renamed['slug']).json['page']['content'], 'First version')

    def test_history_restore_and_trash_are_owner_scoped(self):
        page = self.create()
        page = self.update(page, content='Second version', metadata={'categories':['Research']})
        history = self.client.get('/tools/wiki/api/revisions/' + page['slug']).json['revisions']
        self.assertEqual(history[0]['snapshot']['content'], 'First version')
        self.assertEqual(self.client.get('/tools/wiki/api/revisions/' + page['slug'], headers={'X-Test-User':'2'}).json['revisions'], [])
        restored = self.client.post(f"/tools/wiki/api/revisions/{page['slug']}/{history[0]['id']}/restore", json={'revision':page['revision']})
        self.assertEqual(restored.status_code, 200, restored.json)
        self.assertEqual(restored.json['page']['content'], 'First version')
        self.client.delete('/tools/wiki/api/pages/' + page['slug'])
        self.assertEqual(self.client.get('/tools/wiki/api/pages/' + page['slug']).status_code, 404)
        self.assertEqual(len(self.client.get('/tools/wiki/api/pages?trash=1').json['pages']), 1)
        self.assertEqual(self.client.post('/tools/wiki/api/trash/' + page['slug'] + '/restore', headers={'X-Test-User':'2'}).status_code, 404)
        self.assertEqual(self.client.post('/tools/wiki/api/trash/' + page['slug'] + '/restore').status_code, 200)

    def test_search_categories_and_review(self):
        page = self.create(content='Some text with a useful needle')
        self.update(page, aliases=['Reference'], metadata={'categories':['Research'], 'status':'inbox', 'reviewed_at':'2020-01-01T00:00:00+00:00', 'properties':{'Status':'Reading'}})
        for suffix in ['q=needle', 'q=Reference', 'category=Research', 'review=inbox', 'review=unfinished', 'review=unconnected', 'review=stale']:
            self.assertEqual(len(self.client.get('/tools/wiki/api/pages?' + suffix).json['pages']), 1, suffix)
        self.assertEqual(self.client.get('/tools/wiki/api/pages?category=Other').json['pages'], [])
        self.create('Broken', '[[Missing target]]')
        self.assertEqual(self.client.get('/tools/wiki/api/pages?review=missing').json['pages'][0]['title'], 'Broken')

    def test_macros_backup_roundtrip_with_images_and_links(self):
        self.client.put('/tools/wiki/api/macros/meeting', json={'content':'## Agenda\n\n## Notes'})
        self.assertEqual(self.client.get('/tools/wiki/api/macros', headers={'X-Test-User':'2'}).json['macros'], [])
        raster = io.BytesIO()
        Image.new('RGB',(2,2),'blue').save(raster,format='PNG')
        raster.seek(0)
        uploaded = self.client.post('/tools/wiki/api/images', data={'image':(raster,'test.png','image/png')}).json['image']
        self.client.put('/tools/wiki/api/macros/picture', json={'content':'![image](' + uploaded['url'] + ')'})
        target = self.create('Target')
        page = self.create('Article', '[[Target]]\n![image](' + uploaded['url'] + ')')
        page = self.update(page, metadata={'sources':[{'id':'book','title':'A book','locator':'p. 12'}], 'properties':{'Author':'Someone'}})
        backup = self.client.get('/tools/wiki/api/backup')
        self.addCleanup(backup.close)
        with zipfile.ZipFile(io.BytesIO(backup.data)) as archive:
            self.assertIn('pages/article.md', archive.namelist())
        r = self.client.post('/tools/wiki/api/backup', data={'backup':(io.BytesIO(backup.data),'wiki.zip')})
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(r.json['imported'], 2)
        copy = self.client.get('/tools/wiki/api/pages/article-2').json['page']
        self.assertIn('[[target-2]]', copy['content'])
        self.assertNotIn(uploaded['url'], copy['content'])
        self.assertEqual(copy['metadata']['properties'], {'Author':'Someone'})
        self.assertTrue(self.client.get('/tools/wiki/api/revisions/article-2').json['revisions'])
        r = self.client.post('/tools/wiki/api/backup', data={'backup':(io.BytesIO(backup.data),'wiki.zip')}, headers={'X-Test-User':'2'})
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(len(self.client.get('/tools/wiki/api/pages', headers={'X-Test-User':'2'}).json['pages']), 2)
        macros = self.client.get('/tools/wiki/api/macros', headers={'X-Test-User':'2'}).json['macros']
        self.assertNotIn(uploaded['url'], next(m['content'] for m in macros if m['name'] == 'picture'))

    def test_invalid_backup_does_not_partially_import(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('wiki.json', json.dumps({'version':1,'pages':[{'id':'1','slug':'test','title':'Test','content':'Text','metadata':{}}], 'images':[{'id':'bad','filename':'bad','mime_type':'text/html'}]}))
            archive.writestr('images/bad', '<script>bad</script>')
        response = self.client.post('/tools/wiki/api/backup', data={'backup':(io.BytesIO(data.getvalue()),'bad.zip')})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/tools/wiki/api/pages').json['pages'], [])

    def test_multiple_untitled_pages_can_be_named(self):
        for title in ['One','Two']:
            page = self.create('Untitled page')
            self.update(page, title=title)

    def test_duplicate_titles_can_be_renamed_without_stealing_aliases(self):
        original = self.create('Same name')
        duplicate = self.create('Same name')
        renamed = self.update(duplicate, title='Distinct name')
        self.assertEqual(self.client.get('/tools/wiki/api/pages/' + original['slug']).json['page']['id'], original['id'])
        self.assertEqual(self.client.get('/tools/wiki/api/pages/' + duplicate['slug']).json['page']['id'], renamed['id'])

    def test_metadata_validation_and_alias_collision_are_atomic(self):
        original = self.create('Original')
        other = self.create('Other')
        response = self.client.put('/tools/wiki/api/pages/' + other['slug'], json={'content':'must not save','aliases':['Original']})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/tools/wiki/api/pages/' + other['slug']).json['page']['content'], 'First version')
        for metadata in [{'categories':'wrong'}, {'sources':[{'id':'same','title':'A'},{'id':'same','title':'B'}]}, {'properties':{'Number':1}}, {'reviewed_at':'invalid'}]:
            response = self.client.put('/tools/wiki/api/pages/' + original['slug'], json={'metadata':metadata})
            self.assertEqual(response.status_code, 400, metadata)

    def test_migration_preserves_legacy_pages_and_is_repeatable(self):
        import sqlite3
        from flask import Flask
        from dashboard.wiki.models import init_database
        with tempfile.TemporaryDirectory() as folder:
            path = folder + '/legacy.sqlite'
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE wiki_pages(id TEXT PRIMARY KEY,user_id INTEGER,title TEXT,slug TEXT,content TEXT,created_at TEXT,updated_at TEXT)')
                conn.execute("INSERT INTO wiki_pages VALUES('old',1,'Legacy','legacy','Keep me','2020','2020')")
            app = Flask(__name__)
            app.config['FOUR_AD_DATABASE'] = path
            init_database(app)
            init_database(app)
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute('SELECT content,metadata,deleted_at,revision FROM wiki_pages').fetchone(), ('Keep me','{}',None,0))
