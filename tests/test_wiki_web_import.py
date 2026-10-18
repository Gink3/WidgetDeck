import tempfile
import time
import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image
from test_dashboard_tools import test_app
from dashboard.wiki.web_import import fetch

HTML = b'''<html><head><title>Example article</title></head><body>
<nav>Navigation junk</nav><article><h1>Useful heading</h1>
<p>This is the useful article with <strong>bold text</strong> and a <a href="/next">link</a>.</p>
<div class="advertisement">Buy our junk</div><ul><li>First point</li><li>Second point</li></ul>
<img data-src="/photo.png" alt="Article photo"><script>alert(1)</script>
</article><footer>Footer junk</footer></body></html>'''


class WebImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = test_app(self.directory.name).test_client()
        output = BytesIO()
        Image.new('RGB', (4, 4)).save(output, format='PNG')
        self.image = output.getvalue()

    def download(self, url, limit, deadline):
        if url.endswith('/photo.png'):
            return self.image, 'image/png', url
        return HTML, 'text/html; charset=utf-8', 'https://example.com/story'

    @patch('dashboard.wiki.web_import.fetch')
    def test_saved_html_uses_companion_images_offline_and_preserves_existing_pages(self, download):
        original = self.client.post('/tools/wiki/api/pages', json={'title': 'Example article', 'content': 'Keep me'}).json['page']
        raw = HTML.replace(b'/photo.png', b'story_files/photo.png')
        result = self.client.post('/tools/wiki/api/import-html', data={
            'html': (BytesIO(raw), 'story.html'),
            'assets': (BytesIO(self.image), 'story_files/photo.png'),
            'source_url': 'https://example.com/story'})
        self.assertEqual(result.status_code, 201)
        download.assert_not_called()
        page = result.json['page']
        self.assertNotEqual(page['slug'], original['slug'])
        self.assertIn('Source: <https://example.com/story>', page['content'])
        self.assertIn('![Article photo](/tools/wiki/api/images/', page['content'])
        self.assertNotIn('advertisement', page['content'])
        self.assertEqual(result.json['warnings'], [])
        self.assertEqual(self.client.get('/tools/wiki/api/pages/'+original['slug']).json['page']['content'], 'Keep me')
        image_url = page['content'].split('![Article photo](')[1].split(')')[0]
        with self.client.get(image_url) as response:
            self.assertEqual(response.data, self.image)
        self.assertEqual(self.client.get(image_url, headers={'X-Test-User': '2'}).status_code, 404)

    @patch('dashboard.wiki.web_import.fetch')
    def test_saved_html_fetches_missing_images_from_source_and_reports_offline_failures(self, download):
        download.side_effect = self.download
        result = self.client.post('/tools/wiki/api/import-html', data={
            'html': (BytesIO(HTML), 'story.html'), 'source_url': 'https://example.com/story'})
        self.assertEqual(result.status_code, 201)
        self.assertEqual(download.call_args.args[0], 'https://example.com/photo.png')
        download.side_effect = ValueError('Offline')
        result = self.client.post('/tools/wiki/api/import-html', data={'html': (BytesIO(HTML), 'story.html')})
        self.assertEqual(result.status_code, 201)
        self.assertTrue(result.json['warnings'])
        self.assertNotIn('![', result.json['page']['content'])

    def test_saved_html_rejects_traversal_and_non_http_source_urls(self):
        for source in ['file:///etc/passwd', 'javascript:alert(1)', 'https://user:password@example.com/']:
            self.assertEqual(self.client.post('/tools/wiki/api/import-html', data={
                'html': (BytesIO(HTML), 'story.html'), 'source_url': source}).status_code, 400)
        self.assertEqual(self.client.post('/tools/wiki/api/import-html', data={
            'html': (BytesIO(HTML), 'story.html'), 'assets': (BytesIO(self.image), '../photo.png')}).status_code, 400)
        self.assertEqual(self.client.post('/tools/wiki/api/import-html', data={}).status_code, 400)

    @patch('dashboard.wiki.web_import.fetch')
    def test_saved_html_embedded_raster_images_need_no_network(self, download):
        import base64
        raw = HTML.replace(b'/photo.png', b'data:image/png;base64,'+base64.b64encode(self.image))
        result = self.client.post('/tools/wiki/api/import-html', data={'html': (BytesIO(raw), 'story.html')})
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json['warnings'], [])
        download.assert_not_called()

    @patch('dashboard.wiki.web_import.fetch')
    def test_article_markdown_images_and_existing_page_are_preserved(self, download):
        download.side_effect = self.download
        original = self.client.post('/tools/wiki/api/pages', json={'title': 'Example article', 'content': 'Existing content'}).json['page']
        result = self.client.post('/tools/wiki/api/import-url', json={'url': 'https://example.com/story'})
        self.assertEqual(result.status_code, 201)
        page = result.json['page']
        self.assertNotEqual(page['slug'], original['slug'])
        content = page['content']
        for expected in ['# Useful heading', '**bold text**', '[link](https://example.com/next)', '- First point', '![Article photo](/tools/wiki/api/images/', 'Source: <https://example.com/story>']:
            self.assertIn(expected, content)
        for unwanted in ['Buy our junk', 'Navigation junk', 'Footer junk', 'alert(1)']:
            self.assertNotIn(unwanted, content)
        image_url = content.split('![Article photo](')[1].split(')')[0]
        with self.client.get(image_url) as response:
            self.assertEqual(response.data, self.image)
        self.assertEqual(self.client.get(image_url, headers={'X-Test-User': '2'}).status_code, 404)
        self.assertEqual(self.client.get('/tools/wiki/api/pages/' + original['slug']).json['page']['content'], 'Existing content')
        self.assertEqual(result.json['warnings'], [])

    @patch('dashboard.wiki.web_import.fetch')
    def test_failed_images_are_reported_without_remote_image_links(self, download):
        def failing(url, limit, deadline):
            if url.endswith('.png'):
                raise ValueError('Blocked image')
            return self.download(url, limit, deadline)
        download.side_effect = failing
        result = self.client.post('/tools/wiki/api/import-url', json={'url': 'https://example.com/story'})
        self.assertEqual(result.status_code, 201)
        self.assertTrue(result.json['warnings'])
        self.assertNotIn('![', result.json['page']['content'])

    def test_invalid_input_and_private_addresses(self):
        for payload in [{}, {'url': 1}, {'url': 'file:///etc/passwd'}, {'url': 'http://127.0.0.1/'}, {'url': 'http://[::1]/'}]:
            self.assertEqual(self.client.post('/tools/wiki/api/import-url', json=payload).status_code, 400)
        self.assertEqual(self.client.get('/tools/wiki/api/pages').json['pages'], [])

    @patch('dashboard.wiki.web_import.socket.getaddrinfo')
    def test_dns_resolving_to_private_network_is_rejected(self, resolve):
        resolve.return_value = [(2, 1, 6, '', ('192.168.1.1', 80))]
        with self.assertRaisesRegex(ValueError, 'public'):
            fetch('http://example.com', 1000, time.monotonic() + 10)

    @patch('dashboard.wiki.web_import.fetch')
    def test_non_html_is_rejected(self, download):
        download.return_value = (b'%PDF', 'application/pdf', 'https://example.com/file')
        self.assertEqual(self.client.post('/tools/wiki/api/import-url', json={'url': 'https://example.com/file'}).status_code, 400)

    @patch('dashboard.wiki.web_import.socket.create_connection')
    @patch('dashboard.wiki.web_import.http.client.HTTPConnection')
    @patch('dashboard.wiki.web_import.socket.getaddrinfo')
    def test_redirects_cannot_reach_private_network(self, resolve, connection, connect):
        resolve.side_effect = [[(2, 1, 6, '', ('93.184.216.34', 80))], [(2, 1, 6, '', ('127.0.0.1', 80))]]
        response = connection.return_value.getresponse.return_value
        response.status = 302
        response.getheader.return_value = 'http://localhost/private'
        with self.assertRaisesRegex(ValueError, 'public'):
            fetch('http://example.com/story', 1000, time.monotonic() + 10)
        connect.assert_called_once()
        self.assertEqual(connect.call_args.args[0], ('93.184.216.34', 80))
