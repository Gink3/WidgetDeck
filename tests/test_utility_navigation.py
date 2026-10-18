import sys
import tempfile
import unittest
from test_security_boundaries import isolated_application, auth_post
from dashboard.navigation import GROUPS


class UtilityNavigationTests(unittest.TestCase):
    def test_grouped_launcher_preserves_routes_and_widget_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            name,app=isolated_application(directory)
            try:
                client=app.test_client()
                auth_post(client,'/register',{'username':'menu-check','password':'isolated-menu-passphrase'})
                home=client.get('/').text
                self.assertIn('id="utility-search"',home)
                self.assertIn('id="utility-category"',home)
                ids=[]
                for category,utilities in GROUPS:
                    self.assertIn(category,home)
                    for ident,label,endpoint in utilities:
                        ids.append(ident)
                        self.assertIn('data-widget-id="'+ident+'"',home)
                        if not endpoint.startswith('https://'):
                            with app.test_request_context():
                                from flask import url_for
                                self.assertEqual(client.get(url_for(endpoint)).status_code,200)
                self.assertEqual(len(ids),len(set(ids)))
                self.assertIn('id="utility-menu-search"',client.get('/settings').text)
            finally:sys.modules.pop(name,None)
