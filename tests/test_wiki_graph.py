import tempfile
import unittest
from test_dashboard_tools import test_app


class WikiGraphTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = test_app(self.directory.name).test_client()

    def test_graph_counts_aliases_cycles_isolated_and_owner_scope(self):
        def create(title, content='', owner=1):
            return self.client.post('/tools/wiki/api/pages', json={'title': title, 'content': content}, headers={'X-Test-User': str(owner)}).json['page']
        a = create('Alpha')
        b = create('Beta', '[[Alpha]]')
        isolated = create('Isolated')
        deleted = create('Deleted')
        create('Private', '[[Alpha]]', 2)
        self.client.post('/tools/wiki/api/inbox', json={'content': '[[Alpha]]'})
        self.client.put('/tools/wiki/api/pages/beta', json={'aliases': ['Old beta']})
        self.client.put('/tools/wiki/api/pages/alpha', json={'content': '[[Beta]] [[Old beta]] [[beta|Again]] [[Alpha]] [[Missing]] [[Deleted]]'})
        self.client.delete('/tools/wiki/api/pages/deleted')
        graph = self.client.get('/tools/wiki/api/graph').json
        nodes = {n['id']: n for n in graph['nodes']}
        self.assertEqual(set(nodes), {a['id'], b['id'], isolated['id']})
        self.assertEqual((nodes[a['id']]['incoming'], nodes[a['id']]['outgoing']), (1, 1))
        self.assertEqual((nodes[b['id']]['incoming'], nodes[b['id']]['outgoing']), (1, 1))
        self.assertEqual((nodes[isolated['id']]['incoming'], nodes[isolated['id']]['outgoing']), (0, 0))
        self.assertEqual({(e['source'], e['target']) for e in graph['edges']}, {(a['id'], b['id']), (b['id'], a['id'])})
        self.assertNotIn('content', nodes[a['id']])
        other = self.client.get('/tools/wiki/api/graph', headers={'X-Test-User': '2'}).json
        self.assertEqual(len(other['nodes']), 1)
        self.assertEqual(other['edges'], [])
