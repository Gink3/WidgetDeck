"""Real browser checks on isolated accounts; these are not physical iPhone tests."""
import logging
import tempfile
import threading
import unittest
from werkzeug.serving import make_server
from test_security_boundaries import isolated_application, auth_post


class MobileShellBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        cls.directory = tempfile.TemporaryDirectory()
        _, cls.app = isolated_application(cls.directory.name)
        cls.server = make_server('127.0.0.1', 0, cls.app, threaded=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.directory.cleanup()

    def test_phone_forms_targets_and_enlarged_text(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in (320, 390, 844):
                context = browser.new_context(viewport={'width': width, 'height': 720},
                                              is_mobile=True, has_touch=True)
                page = context.new_page()
                page.goto(self.base + '/login')
                for selector in ('input[name=username]', 'input[name=password]', 'button[type=submit]', '.remember-login'):
                    target = page.locator(selector)
                    self.assertGreaterEqual(target.bounding_box()['height'], 44)
                self.assertEqual(page.locator('input[name=username]').evaluate('el => getComputedStyle(el).fontSize'), '16px')
                page.locator('input[name=username]').focus()
                self.assertEqual(page.locator('input[name=username]').evaluate('el => getComputedStyle(el).outlineStyle'), 'solid')
                # Text enlargement should reflow rather than force horizontal scrolling.
                page.add_style_tag(content='body{font-size:28px !important}')
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                self.assertNotIn('user-scalable=no', page.locator('meta[name=viewport]').get_attribute('content'))
                context.close()
            browser.close()

    def test_dialog_remains_usable_after_viewport_shrinks(self):
        from playwright.sync_api import sync_playwright, expect
        client = self.app.test_client()
        auth_post(client, '/register', {'username': 'mobile-dialog', 'password': 'test-only-password'})
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(viewport={'width': 390, 'height': 844})
            context.add_cookies([{'name': 'dashboard_session',
                                 'value': client.get_cookie('dashboard_session').value, 'url': self.base}])
            page = context.new_page()
            page.goto(self.base + '/tools/kanban')
            page.get_by_role('button', name='+ New board', exact=True).click()
            dialog = page.locator('#new-kanban')
            expect(dialog).to_be_visible()
            # Exercise a small available viewport; real iOS keyboard remains a device check.
            page.set_viewport_size({'width': 390, 'height': 320})
            expect(page.locator('html')).to_have_css('--mobile-viewport-height', '320px')
            self.assertLessEqual(dialog.bounding_box()['height'], 304)
            field = dialog.locator('input[name=name]')
            field.fill('Keyboard-sized viewport')
            dialog.get_by_role('button', name='Cancel', exact=True).click()
            expect(dialog).not_to_be_visible()
            context.close()
            browser.close()

    def test_kanban_small_action_targets_and_desktop_compatibility(self):
        from playwright.sync_api import sync_playwright
        client = self.app.test_client()
        auth_post(client, '/register', {'username': 'mobile-shell', 'password': 'test-only-password'})
        client.post('/tools/kanban', data={'name': 'Phone board'})
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in (320, 390, 1440):
                context = browser.new_context(viewport={'width': width, 'height': 900})
                context.add_cookies([{'name': 'dashboard_session',
                                     'value': client.get_cookie('dashboard_session').value, 'url': self.base}])
                page = context.new_page()
                page.goto(self.base + '/tools/kanban?board=1')
                if width <= 720:
                    page.locator('.new-card-button').first.wait_for(state='visible')
                    self.assertGreater(page.locator('.new-card-button').count(), 0)
                    for button in page.locator('.new-card-button').all():
                        box = button.bounding_box()
                        self.assertGreaterEqual(box['height'], 44)
                        self.assertGreaterEqual(box['width'], 44)
                else:
                    self.assertEqual(page.locator('.kanban-board').evaluate('el => getComputedStyle(el).display'), 'flex')
                context.close()
            browser.close()
