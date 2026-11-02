"""Optional optimistic revisions preserve old clients and pre-revision map files."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask,g,request
from dashboard.auth import init_auth
from dashboard.mindmaps import init_mindmaps
from dashboard.mindmaps import models


class MindMapRevisionTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.app=Flask(__name__,instance_path=self.directory.name);self.app.config['TESTING']=True
        init_auth(self.app);init_mindmaps(self.app)
        @self.app.before_request
        def owner():g.dashboard_user={'id':int(request.headers.get('X-Test-User','1')),'username':'Fixture'}
        self.client=self.app.test_client()
        self.payload={'name':'Existing graph','nodes':[{'id':'original-node','title':'Keep me','description':'Private description','x':10,'y':20,'metadata':{'url':'https://example.invalid/'}}],'edges':[]}
        response=self.client.post('/tools/mindmaps/api/maps',json=self.payload);self.assertEqual(response.status_code,201)
        self.original=response.json['map'];self.url='/tools/mindmaps/api/maps/'+self.original['id']

    def test_stale_revision_rejects_and_legacy_requests_remain_compatible(self):
        first=self.client.put(self.url,json={**self.payload,'name':'First editor','revision':0})
        self.assertEqual(first.status_code,200);self.assertEqual(first.json['map']['revision'],1)
        second=self.client.put(self.url,json={**self.payload,'name':'Stale editor','revision':0})
        self.assertEqual(second.status_code,409)
        current=self.client.get(self.url).json['map'];self.assertEqual(current['name'],'First editor');self.assertEqual(current['nodes'],first.json['map']['nodes'])
        legacy=self.client.put(self.url,json={**self.payload,'name':'Compatible legacy edit'})
        self.assertEqual(legacy.status_code,200);self.assertEqual(legacy.json['map']['revision'],2)
        self.assertEqual(self.client.put(self.url,json={**self.payload,'revision':True}).status_code,400)
        self.assertEqual(self.client.put(self.url,json={**self.payload,'revision':2},headers={'X-Test-User':'2'}).status_code,404)

    def test_old_database_migrates_idempotently_without_changing_graph(self):
        with sqlite3.connect(self.app.config['FOUR_AD_DATABASE']) as connection:
            connection.execute('ALTER TABLE mind_maps DROP COLUMN revision')
        models.init_database(self.app);models.init_database(self.app)
        migrated=self.client.get(self.url).json['map']
        self.assertEqual(migrated,self.original)

    def test_graph_write_failure_rolls_back_metadata_and_revision(self):
        with patch.object(models,'_replace_graph',side_effect=RuntimeError('Independent write failure')):
            with self.assertRaises(RuntimeError):self.client.put(self.url,json={**self.payload,'name':'Must roll back','revision':0})
        self.assertEqual(self.client.get(self.url).json['map'],self.original)

    def test_supported_thousand_node_chain_roundtrips_and_cycle_is_rejected(self):
        nodes=[{'id':'chain-'+str(index),'title':'Node '+str(index),'x':index*2,'y':index*2} for index in range(1000)]
        edges=[{'id':'link-'+str(index),'source_id':nodes[index-1]['id'],'target_id':nodes[index]['id'],'kind':'hierarchy','directed':True} for index in range(1,1000)]
        created=self.client.post('/tools/mindmaps/api/maps',json={'name':'Deep supported map','nodes':nodes,'edges':edges})
        self.assertEqual(created.status_code,201);url='/tools/mindmaps/api/maps/'+created.json['map']['id'];self.assertEqual(len(self.client.get(url).json['map']['nodes']),1000)
        cyclic=[*edges,{'id':'cycle-link','source_id':nodes[-1]['id'],'target_id':nodes[0]['id'],'kind':'hierarchy','directed':True}]
        self.assertEqual(self.client.put(url,json={'nodes':nodes,'edges':cyclic}).status_code,400)
        self.assertEqual(len(self.client.get(url).json['map']['edges']),999)
