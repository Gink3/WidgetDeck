import logging
import tempfile
import threading
import unittest
from werkzeug.serving import make_server
from test_security_boundaries import isolated_application, auth_post


class WordleMobileTests(unittest.TestCase):
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

    def test_all_lengths_fit_short_portrait_and_landscape_without_changing_saved_games(self):
        from playwright.sync_api import sync_playwright, expect
        client = self.app.test_client()
        auth_post(client, '/register', {'username': 'wordle-mobile', 'password': 'test-only-password'})
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for length in (5, 6, 7):
                current = client.get('/api/tools/wordle/game').json
                payload = {'hard_mode': True, 'word_length': length}
                if current['game'] and current['game']['status'] == 'active':
                    payload.update(reset=True, revision=current['game']['revision'])
                created = client.post('/api/tools/wordle/games', json=payload,
                                      headers={'X-CSRF-Token': current['csrf_token']})
                self.assertEqual(created.status_code, 201)
                saved = created.json['game']
                context = browser.new_context(viewport={'width': 320, 'height': 568}, has_touch=True, is_mobile=True)
                context.add_cookies([{'name': 'dashboard_session',
                                     'value': client.get_cookie('dashboard_session').value, 'url': self.base}])
                page = context.new_page()
                page.goto(self.base + '/tools/wordle')
                expect(page.locator('#wordle-status')).to_contain_text('0 of 6 guesses used')
                for letter in 'CR':
                    page.locator('#wordle-keyboard').get_by_role('button', name=letter, exact=True).click()
                for width, height in ((320, 568), (390, 844), (844, 390), (1440, 900)):
                    page.set_viewport_size({'width': width, 'height': height})
                    expect(page.locator('html')).to_have_css('--mobile-viewport-height', str(height)+'px')
                    page.evaluate('scrollTo(0,0)')
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                    for selector in ('#wordle-grid', '#wordle-keyboard'):
                        box = page.locator(selector).bounding_box()
                        self.assertGreaterEqual(box['y'], 0)
                        self.assertLessEqual(box['y'] + box['height'], height, (length, width, height, selector, box))
                    self.assertEqual(page.locator('.wordle-row.current').inner_text().replace('\n', ''), 'CR')
                    for button in page.locator('#wordle-keyboard button').all():
                        self.assertGreaterEqual(button.bounding_box()['height'], 44)
                page.locator('#wordle-settings > summary').click()
                expect(page.get_by_label('Hard Mode', exact=True)).to_be_checked()
                page.locator('#wordle-settings > summary').click()
                page.get_by_text('Statistics and rules', exact=True).click()
                expect(page.locator('#wordle-stats')).to_be_visible()
                page.reload()
                expect(page.locator('#wordle-status')).to_contain_text('0 of 6 guesses used')
                self.assertEqual(client.get('/api/tools/wordle/game').json['game'], saved)
                context.close()
            browser.close()
