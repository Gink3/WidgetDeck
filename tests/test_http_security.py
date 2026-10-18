import unittest
from unittest.mock import patch
from flask import Flask, session
from dashboard.http_security import configure_cookies, configure_headers

class HttpSecurityTests(unittest.TestCase):
    def test_cookie_flag_keeps_http_default_and_https_opt_in(self):
        for secure in ['0','1']:
            with self.subTest(secure=secure),patch.dict('os.environ',DASHBOARD_SESSION_COOKIE_SECURE=secure):
                app=Flask(__name__);app.secret_key='test-only';configure_cookies(app)
                @app.get('/')
                def index():session['user_id']=1;return 'ok'
                cookie=app.test_client().get('/').headers['Set-Cookie']
                self.assertEqual('Secure;' in cookie,secure=='1')
                self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Lax' if app.config.get('SESSION_COOKIE_SAMESITE') else 'Path=/',cookie)

    def test_headers_cover_errors_and_only_secure_hsts(self):
        app=Flask(__name__);configure_headers(app)
        for origin in ['http://localhost','https://localhost']:
            response=app.test_client().get('/missing',base_url=origin)
            self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
            self.assertEqual(response.headers['X-Frame-Options'],'SAMEORIGIN')
            self.assertIn('Content-Security-Policy-Report-Only',response.headers)
            self.assertNotIn('Content-Security-Policy',response.headers)
            self.assertEqual('Strict-Transport-Security' in response.headers,origin.startswith('https'))
            self.assertNotIn('includeSubDomains',response.headers.get('Strict-Transport-Security',''))
