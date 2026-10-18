import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from test_security_boundaries import isolated_application, auth_post
from dashboard.auth_security import consume_budget

class AuthSecurityTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        _,self.app=isolated_application(self.directory.name)
        self.client=self.app.test_client()

    def test_csrf_and_normal_auth_flow(self):
        for path in ['/login','/register']:
            self.assertEqual(self.client.post(path,data={}).status_code,403)
            self.assertEqual(self.client.post(path,data={'csrf_token':'invalid'}).status_code,403)
        self.assertEqual(auth_post(self.client,'/register',{'username':'tester','password':'test-only-password'}).status_code,302)
        self.client.post('/logout')
        self.assertEqual(auth_post(self.client,'/login',{'username':'tester','password':'test-only-password'}).status_code,302)

    def test_workers_share_atomic_budget_with_expiry_and_address_isolation(self):
        self.app.config.update(AUTH_RATE_LIMIT=3,AUTH_RATE_WINDOW=10)
        def attempt(_):
            with self.app.test_request_context('/login',environ_base={'REMOTE_ADDR':'192.0.2.1'}):
                return consume_budget('login',100)
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt,range(8))),3)
        _,worker=isolated_application(self.directory.name);worker.config.update(AUTH_RATE_LIMIT=3,AUTH_RATE_WINDOW=10)
        with worker.test_request_context('/login',environ_base={'REMOTE_ADDR':'192.0.2.1'}):
            self.assertFalse(consume_budget('login',105));self.assertTrue(consume_budget('login',111))
        with worker.test_request_context('/login',environ_base={'REMOTE_ADDR':'192.0.2.2'}):
            self.assertTrue(consume_budget('login',105))

    def test_throttled_login_is_generic_and_has_retry_header(self):
        self.app.config['AUTH_RATE_LIMIT']=1
        self.assertEqual(auth_post(self.client,'/login',{'username':'missing','password':'wrong'}).status_code,401)
        result=auth_post(self.client,'/login',{'username':'missing','password':'wrong'})
        self.assertEqual(result.status_code,429);self.assertIn('Retry-After',result.headers)
