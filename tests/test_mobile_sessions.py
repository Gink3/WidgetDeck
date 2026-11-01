"""Cookie persistence, absolute expiry and logout replay against real auth routes."""
import tempfile
import time
import unittest
from test_security_boundaries import isolated_application, auth_post
from dashboard.database import db


class MobileSessionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        _, self.app = isolated_application(directory.name)
        self.client = self.app.test_client()
        self.assertEqual(auth_post(self.client, '/register', {
            'username': 'mobile', 'password': 'test-only-password'}).status_code, 302)
        self.client.post('/logout')

    def login(self, **extra):
        return auth_post(self.client, '/login', {
            'username': 'mobile', 'password': 'test-only-password', **extra})

    def test_remember_is_opt_in_and_returns_to_deep_link(self):
        response = self.login(next='/tools/kanban?board=7')
        self.assertEqual(response.location, '/tools/kanban?board=7')
        self.assertNotIn('Expires=', response.headers['Set-Cookie'])
        self.client.post('/logout')
        response = self.login(remember='1')
        self.assertIn('Expires=', response.headers['Set-Cookie'])
        status = self.client.get('/api/session')
        self.assertTrue(status.json['permanent'])
        self.assertAlmostEqual(status.json['expires_at'] - time.time(), 30 * 86400, delta=10)
        self.assertEqual(status.headers['Cache-Control'], 'private, no-store')
        self.assertNotIn('Set-Cookie', status.headers)
        # Simulate cold launch with the browser cookie in a new client.
        relaunched = self.app.test_client()
        relaunched.set_cookie('dashboard_session', self.client.get_cookie('dashboard_session').value)
        self.assertEqual(relaunched.get('/api/session').status_code, 200)

    def test_logout_revokes_a_copied_cookie(self):
        self.login(remember='1')
        copy = self.app.test_client()
        copy.set_cookie('dashboard_session', self.client.get_cookie('dashboard_session').value)
        self.client.post('/logout')
        self.assertEqual(copy.get('/api/session').status_code, 401)

    def test_absolute_expiry_cannot_be_extended_by_cookie_refresh(self):
        self.login(remember='1')
        with self.app.app_context():
            db().execute('UPDATE dashboard_browser_sessions SET expires_at=?', (time.time()-1,))
            db().commit()
        self.assertEqual(self.client.get('/api/session').status_code, 401)
        self.assertEqual(self.client.get('/api/settings').status_code, 401)
        response = self.client.get('/tools/kanban?board=7')
        self.assertIn('/login?next=', response.location)
        self.assertIn('board%3D7', response.location)

    def test_legacy_sessions_continue_to_work(self):
        with self.app.app_context():
            user = db().execute('SELECT id FROM dashboard_users WHERE username="mobile"').fetchone()['id']
        with self.client.session_transaction() as cookie:
            cookie.clear()
            cookie['user_id'] = user
        self.assertEqual(self.client.get('/api/session').status_code, 200)
        self.assertIsNone(self.client.get('/api/session').json['expires_at'])

    def test_external_redirects_are_rejected_and_failed_login_retains_next(self):
        for destination in ['//example.com', '/\\example.com', '/\n/example.com']:
            response = self.login(next=destination)
            self.assertEqual(response.location, '/')
            self.client.post('/logout')
        response = auth_post(self.client, '/login', {
            'username': 'mobile', 'password': 'wrong', 'next': '/tools/wiki/'})
        self.assertEqual(response.status_code, 401)
        self.assertIn(b'value="/tools/wiki/"', response.data)

