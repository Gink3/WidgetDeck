import logging
import secrets
import tempfile
import threading
import unittest
from flask import jsonify
from werkzeug.serving import make_server
from test_security_boundaries import isolated_application, auth_post


class RuntimeBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        cls.directory = tempfile.TemporaryDirectory()
        _, cls.app = isolated_application(cls.directory.name)
        cls.latch = threading.Event()
        cls.probe_calls = []
        cls.probe_status = {}

        @cls.app.post('/api/pwa-test/<case>')
        def probe(case):
            cls.probe_calls.append(case)
            if case == 'slow':
                cls.latch.wait(10)
            return jsonify(case=case), cls.probe_status.get(case, 200)

        cls.server = make_server('127.0.0.1', 0, cls.app, threaded=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.latch.set()
        cls.server.shutdown()
        cls.server.server_close()
        cls.directory.cleanup()

    def setUp(self):
        self.client = self.app.test_client()
        self.username = 'runtime-' + secrets.token_hex(4)
        self.password = 'test-only-password'
        auth_post(self.client, '/register', {'username': self.username, 'password': self.password})
        self.client.post('/tools/kanban', data={'name': 'Private runtime board'})
        self.board = self.client.get('/api/tools/kanban/boards').json['boards'][0]['id']
        board = self.client.get('/api/tools/kanban/boards/' + str(self.board)).json['board']
        self.column = board['columns'][0]['id']
        self.item = self.client.post(f'/api/tools/kanban/boards/{self.board}/items', json={
            'title': 'Private runtime card', 'column_id': self.column, 'notes': 'Original'}).json['item']

    def context(self, browser):
        context = browser.new_context(viewport={'width': 390, 'height': 844})
        context.add_cookies([{'name': 'dashboard_session',
                             'value': self.client.get_cookie('dashboard_session').value, 'url': self.base}])
        return context

    def test_save_observer_keeps_responses_and_preserves_unresolved_failure(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = self.context(browser)
            page = context.new_page()
            page.goto(self.base + f'/tools/kanban?board={self.board}')
            page.wait_for_function('window.WidgetDeckRuntime?.state.reachable === true')
            expect(page.locator('#pwa-connection')).not_to_be_visible()
            endpoint = '/api/tools/kanban/items/' + str(self.item['id'])
            def change(title, revision):
                return page.evaluate('''async data => {
                  const response = await fetch(data.url, {method:'PATCH',headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({title:data.title,revision:data.revision,notes:'Original',column_id:data.column})});
                  return {status:response.status, body:await response.json()};
                }''', {'url': endpoint, 'title': title, 'revision': revision, 'column': self.column})
            result = change('Saved title', 0)
            self.assertEqual(result['status'], 200)
            self.assertEqual(result['body']['item']['title'], 'Saved title')
            expect(page.locator('#pwa-save-feedback')).to_have_attribute('data-state', 'saved')
            self.assertEqual(change('Stale title', 0)['status'], 409)
            expect(page.locator('#pwa-save-feedback')).to_have_attribute('data-state', 'failed')
            page.evaluate("fetch('/api/pwa-test/unrelated', {method:'POST'}).then(r=>r.json())")
            expect(page.locator('#pwa-save-feedback')).to_have_attribute('data-state', 'failed')
            self.assertEqual(change('Recovered title', 1)['status'], 200)
            expect(page.locator('#pwa-save-feedback')).to_have_attribute('data-state', 'saved')
            self.assertEqual(self.client.get(endpoint).json['item']['title'], 'Recovered title')
            context.close()
            browser.close()

    def test_concurrent_saves_and_job_acceptance_are_not_false_success(self):
        from playwright.sync_api import sync_playwright, expect
        self.latch.clear()
        self.probe_status.update(failed=409, accepted=202)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                context = self.context(browser)
                page = context.new_page()
                page.goto(self.base + '/')
                page.evaluate("window.slowSave=fetch('/api/pwa-test/slow',{method:'POST'}); void 0")
                expect(page.locator('#pwa-save-feedback')).to_have_attribute('data-state', 'saving')
                page.evaluate("fetch('/api/pwa-test/failed',{method:'POST'}).then(r=>r.json())")
                self.latch.set()
                page.evaluate('window.slowSave.then(r=>r.json())')
                expect(page.locator('#pwa-save-feedback')).to_have_attribute('data-state', 'failed')
                self.probe_status['failed'] = 200
                page.evaluate("fetch('/api/pwa-test/failed',{method:'POST'}).then(r=>r.json())")
                page.evaluate("fetch('/api/pwa-test/accepted',{method:'POST'}).then(r=>r.json())")
                expect(page.locator('#pwa-save-feedback')).to_have_attribute('data-state', 'accepted')
                context.close()
                browser.close()
        finally:
            self.latch.set()

    def test_transient_requests_do_not_claim_saved_but_still_check_sessions(self):
        from playwright.sync_api import sync_playwright, expect
        self.probe_status['transient-write'] = 409
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                context = self.context(browser)
                page = context.new_page()
                page.goto(self.base + '/')
                page.wait_for_function('window.WidgetDeckRuntime?.state.reachable === true')
                def compute():
                    return page.evaluate("fetch('/api/pwa-test/transient', {method:'POST', widgetdeckOperation:'transient'}).then(async r=>({status:r.status,body:await r.json()}))")
                result = compute()
                self.assertEqual(result, {'status':200, 'body':{'case':'transient'}})
                expect(page.locator('#pwa-save-feedback')).to_be_hidden()
                page.evaluate("fetch('/api/pwa-test/transient-write', {method:'POST'}).then(r=>r.json())")
                expect(page.locator('#pwa-save-feedback')).to_have_attribute('data-state', 'failed')
                self.probe_status['transient'] = 503
                self.assertEqual(compute()['status'], 503)
                expect(page.locator('#pwa-save-feedback')).to_have_attribute('data-state', 'failed')
                self.probe_status['transient'] = 401
                self.assertEqual(compute()['status'], 401)
                expect(page.locator('#pwa-session-status')).to_contain_text('Your session expired')
                self.assertTrue(page.evaluate('window.WidgetDeckRuntime.state.reachable'))
                context.close()
                browser.close()
        finally:
            self.probe_status.pop('transient', None)
            self.probe_status.pop('transient-write', None)

    def test_expiry_recovery_and_account_change_keep_edits_private(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = self.context(browser)
            page = context.new_page()
            page.goto(self.base + f'/tools/kanban?board={self.board}&item={self.item["id"]}')
            notes = page.locator('#item-notes')
            expect(notes).to_be_visible()
            notes.fill('Private unsaved draft')
            page.evaluate("document.querySelector('#new-kanban').showModal()")
            self.client.post('/logout')
            self.assertEqual(page.evaluate("fetch('/api/session').then(r=>r.status)"), 401)
            expect(page.locator('#pwa-session-status')).to_contain_text('Your session expired')
            expect(notes).not_to_be_visible()
            self.assertEqual(notes.input_value(), 'Private unsaved draft')
            expect(page.get_by_role('link', name='Sign in in a new tab', exact=True)).to_be_visible()
            expect(page.get_by_role('link', name='Sign in in a new tab', exact=True)).to_be_focused()
            self.assertFalse(page.locator('#new-kanban').evaluate('el=>el.open'))
            expect(page.get_by_role('link', name='Open the current account', exact=True)).not_to_be_visible()
            auth_post(self.client, '/login', {'username': self.username, 'password': self.password})
            context.add_cookies([{'name': 'dashboard_session',
                                 'value': self.client.get_cookie('dashboard_session').value, 'url': self.base}])
            page.evaluate('window.WidgetDeckRuntime.checkSession()')
            expect(notes).to_be_visible()
            expect(notes).to_have_value('Private unsaved draft')
            other = self.app.test_client()
            auth_post(other, '/register', {'username': 'other-' + secrets.token_hex(4), 'password': self.password})
            context.add_cookies([{'name': 'dashboard_session',
                                 'value': other.get_cookie('dashboard_session').value, 'url': self.base}])
            page.evaluate('window.WidgetDeckRuntime.checkSession()')
            expect(page.locator('#pwa-session-status')).to_contain_text('different account')
            expect(notes).not_to_be_visible()
            expect(page.get_by_role('link', name='Open the current account', exact=True)).to_be_visible()
            self.assertEqual(self.client.get('/api/tools/kanban/items/' + str(self.item['id'])).json['item']['notes'], 'Original')
            context.close()
            browser.close()
