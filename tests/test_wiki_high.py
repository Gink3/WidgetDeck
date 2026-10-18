import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from flask import g
from PIL import Image, ImageDraw, ImageFont
from test_dashboard_tools import test_app
from dashboard.wiki import models
from dashboard.wiki.backup import export_archive, import_archive, verify_archive
from dashboard.wiki.worker import create_backup, settings, backup_files, tick
from dashboard.wiki.documents import process_one


class WikiHighTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app=test_app(self.directory.name)
        self.client=self.app.test_client()

    def create(self,title='Archive',content=''):
        return self.client.post('/tools/wiki/api/pages',json={'title':title,'content':content}).json['page']

    def context(self):
        context=self.app.app_context()
        context.push()
        self.addCleanup(context.pop)
        g.dashboard_user={'id':1}

    def test_infobox_table_and_properties_share_values_in_both_directions(self):
        content=':::infobox\n### Book\n| Detail | Value |\n| --- | --- |\n| Author | First |\n| Status | Reading |\n:::\nText'
        page=self.create(content=content)
        self.assertEqual(page['metadata']['properties']['Author'],'First')
        meta=page['metadata'];meta['properties']['Author']='Second'
        page=self.client.put('/tools/wiki/api/pages/archive',json={'metadata':meta}).json['page']
        self.assertIn('| Author | Second |',page['content'])
        page=self.client.put('/tools/wiki/api/pages/archive',json={'content':page['content'].replace('| Status | Reading |','| Status | Finished |')}).json['page']
        self.assertEqual(page['metadata']['properties']['Status'],'Finished')
        del page['metadata']['properties']['Author']
        page=self.client.put('/tools/wiki/api/pages/archive',json={'metadata':page['metadata']}).json['page']
        self.assertNotIn('| Author |',page['content'])
        self.assertNotIn('Author',page['metadata']['properties'])
        self.assertEqual(len(self.client.get('/tools/wiki/api/pages?q=Finished').json['pages']),1)

    def test_autosave_preserves_blank_partial_duplicate_and_formatted_table_rows(self):
        page = self.create(content=':::infobox\n| Field | Value |\n| --- | --- |\n| Author | First |\n:::\nAfter')
        for row in ['|  |  |', '| Partial |', '| Author | Another |', '|    | typed |']:
            content = page['content'].replace('\n:::', '\n'+row+'\n:::')
            result = self.client.put('/tools/wiki/api/pages/archive', json={
                'content': content, 'metadata': page['metadata'], 'revision': page['revision']})
            self.assertEqual(result.status_code, 200)
            page = result.json['page']
            self.assertEqual(page['content'], content)
            # A second autosave must not canonicalize an unchanged draft either.
            result = self.client.put('/tools/wiki/api/pages/archive', json={
                'content': content, 'metadata': page['metadata'], 'revision': page['revision']})
            self.assertEqual(result.json['page']['content'], content)
        reloaded = self.client.get('/tools/wiki/api/pages/archive').json['page']
        self.assertEqual(reloaded['content'], page['content'])
        self.assertIn('| Field | Value |', reloaded['content'])
        self.assertEqual(reloaded['metadata']['properties']['Author'], 'Another')

    def test_backup_retention_verification_and_asynchronous_restore(self):
        self.create(content='Preserve me')
        self.context()
        settings()
        models.db().execute('UPDATE wiki_backup_settings SET retain_count=1 WHERE user_id=1');models.db().commit()
        first=create_backup();second=create_backup()
        self.assertEqual([b['name'] for b in backup_files()],[second])
        self.assertFalse((Path(self.directory.name)/'wiki_backups'/'1'/first).exists())
        archive=Path(self.directory.name)/'wiki_backups'/'1'/second
        self.assertEqual(verify_archive(archive)['pages'],1)
        response=self.client.post('/tools/wiki/api/restores',data={'backup':(io.BytesIO(archive.read_bytes()),'backup.zip')})
        self.assertEqual(response.status_code,202)
        tick(self.app)
        status=self.client.get('/tools/wiki/api/backups').json
        self.assertEqual(status['restores'][0]['state'],'complete',status)
        self.assertEqual(len(self.client.get('/tools/wiki/api/pages').json['pages']),2)
        self.assertEqual(self.client.get('/tools/wiki/api/backups/'+second,headers={'X-Test-User':'2'}).status_code,404)

    def test_streaming_restore_accepts_archive_over_old_100mb_limit(self):
        self.context()
        with tempfile.TemporaryFile() as source:
            digest=hashlib.sha256()
            with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as archive:
                with archive.open('attachments/file','w') as output:
                    chunk=b'0'*1024*1024
                    for _ in range(101): output.write(chunk);digest.update(chunk)
                archive.writestr('wiki.json',json.dumps({'version':1,'pages':[{'id':'page','slug':'large','title':'Large','content':''}],'images':[],'attachments':[{'id':'file','page_id':'page','filename':'large.pdf','sha256':digest.hexdigest(),'created_at':models.timestamp()}]}))
            source.seek(0)
            self.assertEqual(import_archive(source),1)
        self.assertEqual(models.attachments('large')[0]['byte_size'],101*1024*1024)

    def test_text_document_processing_and_private_search(self):
        page=self.create()
        response=self.client.post('/tools/wiki/api/pages/archive/attachments',data={'document':(io.BytesIO(b'Unique archive phrase nebula731'),'notes.txt')})
        ident=response.json['attachments'][0]['id']
        self.context();self.assertTrue(process_one())
        detail=self.client.get('/tools/wiki/api/attachments/'+ident+'/details').json['attachment']
        self.assertEqual(detail['processing_status'],'ready')
        self.assertIn('nebula731',detail['text_content'])
        results=self.client.get('/tools/wiki/api/pages?q=nebula731').json['pages']
        self.assertEqual(results[0]['document_matches'][0]['filename'],'notes.txt')
        self.assertEqual(self.client.get('/tools/wiki/api/pages?q=nebula731',headers={'X-Test-User':'2'}).json['pages'],[])
        self.assertEqual(self.client.get('/tools/wiki/api/attachments/'+ident+'/details',headers={'X-Test-User':'2'}).status_code,404)

    def test_real_scanned_pdf_ocr_and_image_preview(self):
        import shutil
        if not shutil.which('tesseract'): self.skipTest('Run in the application image for Tesseract integration.')
        self.create()
        image=Image.new('RGB',(1800,350),'white')
        ImageDraw.Draw(image).text((60,90),'ARCHIVE QUARTZ RECEIPT 48291',font=ImageFont.load_default(size=65),fill='black')
        for format,filename in [('PDF','scan.pdf'),('PNG','photo.png')]:
            output=io.BytesIO();image.save(output,format=format,**({'save_all':True,'append_images':[image]} if format=='PDF' else {}))
            result=self.client.post('/tools/wiki/api/pages/archive/attachments',data={'document':(io.BytesIO(output.getvalue()),filename)})
            ident=result.json['attachments'][-1]['id']
            with self.app.app_context():
                g.dashboard_user={'id':1};self.assertTrue(process_one())
            item=self.client.get('/tools/wiki/api/attachments/'+ident+'/details').json['attachment']
            self.assertEqual(item['processing_status'],'ready',item)
            self.assertIn('QUARTZ',item['text_content'])
            preview=self.client.get('/tools/wiki/api/attachments/'+ident+'/preview')
            self.addCleanup(preview.close)
            self.assertEqual(preview.status_code,200)
            self.assertIn(preview.mimetype,('image/png','application/pdf'))
            if format=='PDF':
                self.assertEqual(item['preview_pages'],2)
                raster=self.client.get('/tools/wiki/api/attachments/'+ident+'/preview?page=2')
                self.addCleanup(raster.close)
                self.assertEqual(raster.status_code,200)
                self.assertTrue(raster.data.startswith(b'\x89PNG'))
                self.assertEqual(self.client.get('/tools/wiki/api/attachments/'+ident+'/preview?page=3').status_code,400)
