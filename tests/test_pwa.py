"""Public installation assets must never expose an authenticated workspace."""
import io
import json
import tempfile
import unittest
from PIL import Image
from test_security_boundaries import isolated_application


class PwaTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        _, self.app = isolated_application(directory.name)
        self.client = self.app.test_client()

    def test_manifest_has_root_identity_scope_and_real_icons(self):
        response = self.client.get('/static/branding/site.webmanifest')
        self.assertEqual(response.status_code, 200)
        manifest = json.loads(response.data)
        response.close()
        self.assertEqual(manifest['display'], 'standalone')
        for field in ('id', 'start_url', 'scope'):
            self.assertEqual(manifest[field], '/')
        for icon in manifest['icons']:
            response = self.client.get('/static/branding/' + icon['src'])
            self.assertEqual(response.status_code, 200)
            with Image.open(io.BytesIO(response.data)) as image:
                self.assertEqual('%sx%s' % image.size, icon['sizes'])
            response.close()

    def test_install_and_login_public_but_launch_and_deep_links_require_login(self):
        for path in ('/install', '/login'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'viewport-fit=cover', response.data)
            self.assertIn(b'name="apple-mobile-web-app-capable" content="yes"', response.data)
            self.assertIn(b'rel="apple-touch-icon"', response.data)
        response = self.client.get('/install')
        self.assertIn(b'Add to Home Screen', response.data)
        self.assertNotIn(b'API keys', response.data)
        for path in ('/', '/tools/kanban?board=7'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login?next=', response.location)
        self.assertEqual(self.client.get('/api/session').status_code, 401)
