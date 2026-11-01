"""Public installation assets must never expose an authenticated workspace."""
import io
import json
import logging
import tempfile
import threading
import unittest
from PIL import Image
from test_security_boundaries import isolated_application


class PwaTests(unittest.TestCase):
    def setUp(self):
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
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

    def test_offline_assets_are_public_generic_and_worker_has_root_scope(self):
        for path in ('/offline.html', '/offline.html?v=test'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Connect to the internet', response.data)
            self.assertNotIn('Set-Cookie', response.headers)
            response.close()
        response = self.client.get('/service-worker.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/javascript')
        self.assertEqual(response.headers['Service-Worker-Allowed'], '/')
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_installed_worker_never_caches_accounts_or_replays_writes(self):
        from playwright.sync_api import sync_playwright, expect
        from werkzeug.serving import make_server
        from test_security_boundaries import auth_post
        auth_post(self.client, '/register', {'username': 'offline-test', 'password': 'test-only-password'})
        self.client.post('/tools/kanban', data={'name': 'SECRET private board'})
        server = make_server('127.0.0.1', 0, self.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                context = browser.new_context()
                context.add_cookies([{'name': 'dashboard_session',
                                     'value': self.client.get_cookie('dashboard_session').value, 'url': base}])
                page = context.new_page()
                page.goto(base + '/tools/kanban?board=1')
                page.wait_for_function('navigator.serviceWorker.controller !== null')
                expect(page.locator('#kanban-board-name')).to_have_text('SECRET private board')
                page.evaluate("fetch('/api/session')")
                entries = page.evaluate('''async () => {
                  const keys = await caches.keys();
                  return (await Promise.all(keys.map(async key => {
                    const cache = await caches.open(key);
                    return (await cache.keys()).map(request => request.url);
                  }))).flat();
                }''')
                self.assertEqual(len(entries), 3)
                self.assertTrue(all('/offline.html?v=' in url or '/static/branding/dashboard-icon-' in url for url in entries))
                context.set_offline(True)
                expect(page.locator('#pwa-connection')).to_be_visible()
                self.assertTrue(page.evaluate("fetch('/api/tools/kanban/boards/1/items', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'must not replay'})}).then(()=>false,()=>true)"))
                page.goto(base + '/tools/kanban?board=1')
                expect(page.get_by_role('heading', name='You’re offline')).to_be_visible()
                self.assertNotIn('SECRET', page.locator('body').inner_text())
                context.set_offline(False)
                page.get_by_role('button', name='Try again').click()
                expect(page.locator('#kanban-board-name')).to_have_text('SECRET private board')
                board = context.request.get(base + '/api/tools/kanban/boards/1').json()['board']
                self.assertEqual(board['items'], [])
                page.get_by_role('button', name='Sign out', exact=True).click()
                expect(page).to_have_url(base + '/login')
                context.set_offline(True)
                page.goto(base + '/tools/kanban?board=1')
                self.assertNotIn('SECRET', page.locator('body').inner_text())
                context.close()
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
