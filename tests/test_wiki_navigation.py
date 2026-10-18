import tempfile
import unittest
from test_dashboard_tools import test_app


class WikiNavigationTests(unittest.TestCase):
    def test_navigation_is_owned_ordered_and_tracks_page_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            client = test_app(directory).test_client()
            page = client.post('/tools/wiki/api/pages', json={'title': 'First'}).json['page']
            client.post('/tools/wiki/api/pages', json={'title': 'Second'})
            self.assertEqual(client.get('/tools/wiki/api/navigation').json, {'pinned': [], 'recent': []})
            client.put('/tools/wiki/api/pages/first/navigation', json={'pinned': True})
            client.post('/tools/wiki/api/pages/first/navigation')
            client.post('/tools/wiki/api/pages/second/navigation')
            result = client.get('/tools/wiki/api/navigation').json
            self.assertEqual([p['title'] for p in result['recent']], ['Second', 'First'])
            self.assertEqual(result['pinned'][0]['id'], page['id'])
            self.assertEqual(client.get('/tools/wiki/api/navigation', headers={'X-Test-User': '2'}).json, {'pinned': [], 'recent': []})
            self.assertEqual(client.put('/tools/wiki/api/pages/first/navigation', json={'pinned': True}, headers={'X-Test-User': '2'}).status_code, 404)
            self.assertEqual(client.put('/tools/wiki/api/pages/first/navigation', json={'pinned': 'yes'}).status_code, 400)
            client.put('/tools/wiki/api/pages/first', json={'title': 'Renamed'})
            self.assertEqual(client.get('/tools/wiki/api/navigation').json['pinned'][0]['title'], 'Renamed')
            client.delete('/tools/wiki/api/pages/renamed')
            result = client.get('/tools/wiki/api/navigation').json
            self.assertEqual(result['pinned'], [])
            self.assertEqual(len(result['recent']), 1)
            client.post('/tools/wiki/api/trash/renamed/restore')
            self.assertEqual(len(client.get('/tools/wiki/api/navigation').json['pinned']), 1)
            client.put('/tools/wiki/api/pages/renamed/navigation', json={'pinned': False})
            self.assertEqual(client.get('/tools/wiki/api/navigation').json['pinned'], [])
