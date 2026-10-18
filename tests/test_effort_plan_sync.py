"""Plan synchronization is additive, restartable and works before tag deployment."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from test_dashboard_tools import test_app

spec=importlib.util.spec_from_file_location('effort_sync',Path(__file__).resolve().parents[1]/'tools/sync_effort_plan.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class Transport:
    def __init__(self,client,native=True):self.client=client;self.native=native;self.writes=0
    def request(self,method,path,payload=None):
        if not self.native and path.startswith('/api/tools/kanban/efforts'):raise module.ApiError(404)
        if method!='GET':self.writes+=1
        result=self.client.open(path,method=method,json=payload)
        if result.status_code>=400:raise module.ApiError(result.status_code)
        data=None if result.status_code==204 else result.json
        if not self.native and isinstance(data,dict) and 'board' in data:data['board'].pop('efforts',None)
        return data


class PlanSyncTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.client=test_app(temp.name).test_client()
        self.client.post('/tools/kanban',data={'name':'Dashboard','column_name':['Backlog','To do','In Progress','Done']})
        self.transport=Transport(self.client)
        self.plan={'schema_version':1,'plan_id':'fixture','effort':'MCP and Wiki RAG','board':'Dashboard','items':[
            {'key':'overview','title':'Overview','column':'To do','depends_on':[],'notes':'Coordinate'},
            {'key':'foundation','title':'Foundation','column':'To do','depends_on':[],'notes':'Build contracts'},
            {'key':'future','title':'Future','column':'Backlog','depends_on':['foundation'],'notes':'Future task'}]}

    def test_dry_run_and_idempotent_apply_preserve_existing_work(self):
        result=module.sync(self.transport,self.plan)
        self.assertEqual(result['to_create'],3);self.assertEqual(self.transport.writes,0)
        result=module.sync(self.transport,self.plan,True);self.assertIsNotNone(result['effort_id'])
        item_id=result['items']['foundation'];path=f'/api/tools/kanban/items/{item_id}'
        item=self.client.get(path).json['item']
        self.client.patch(path,json={'title':'User renamed','notes':item['notes']+'\nUser notes',
            'column_id':item['column_id'],'revision':item['revision']})
        extra=self.client.post('/api/tools/kanban/efforts',json={'name':'Other project'}).json['effort']
        item=self.client.get(path).json['item']
        self.client.put(path+'/efforts',json={'effort_ids':[result['effort_id'],extra['id']],'revision':item['revision']})
        before=self.client.get(path).json['item'];writes=self.transport.writes
        repeated=module.sync(self.transport,self.plan,True)
        self.assertEqual(repeated,result);self.assertEqual(self.transport.writes,writes)
        self.assertEqual(self.client.get(path).json['item'],before)
        overview=self.client.get(f"/api/tools/kanban/items/{result['items']['overview']}").json['item']
        self.assertEqual(len(overview['links']),2)

    def test_old_server_creates_group_links_and_deployment_finishes_native_tags(self):
        self.transport.native=False
        result=module.sync(self.transport,self.plan,True)
        self.assertTrue(result['native_effort_pending']);self.assertIsNone(result['effort_id'])
        self.transport.native=True
        upgraded=module.sync(self.transport,self.plan,True)
        self.assertFalse(upgraded['native_effort_pending']);self.assertEqual(upgraded['items'],result['items'])
        items=self.client.get('/api/tools/kanban/boards/1').json['board']['items']
        self.assertEqual(len(items),3)
        self.assertTrue(all(i['efforts'][0]['id']==upgraded['effort_id'] for i in items))

    def test_transferred_card_is_found_without_duplicate_or_status_change(self):
        result=module.sync(self.transport,self.plan,True);ident=result['items']['foundation']
        self.client.post('/tools/kanban',data={'name':'Other'})
        snapshot=self.client.get('/api/tools/kanban/boards/2').json['board']
        item=self.client.get(f'/api/tools/kanban/items/{ident}').json['item']
        self.client.post(f'/api/tools/kanban/items/{ident}/transfer',json={
            'board_id':2,'column_id':snapshot['columns'][0]['id'],'revision':item['revision']})
        repeated=module.sync(self.transport,self.plan,True)
        self.assertEqual(repeated['items'],result['items'])
        self.assertEqual(self.client.get(f'/api/tools/kanban/items/{ident}').json['item']['board_id'],2)

    def test_duplicate_markers_stop_before_any_writes(self):
        result=module.sync(self.transport,self.plan,True)
        item=self.client.get(f"/api/tools/kanban/items/{result['items']['foundation']}").json['item']
        self.client.post('/api/tools/kanban/boards/1/items',json={'title':'Duplicate','notes':item['notes'],'column_id':item['column_id']})
        count=self.transport.writes
        with self.assertRaises(ValueError):module.sync(self.transport,self.plan,True)
        self.assertEqual(self.transport.writes,count)

    def test_full_plan_has_unique_keys_and_valid_dependencies(self):
        import json
        plan=json.loads((Path(__file__).resolve().parents[1]/'plans/mcp-wiki-rag.json').read_text())
        module.validate_plan(plan)
        self.assertEqual(len(plan['items']),19)
        self.assertEqual(sum(r['column']=='Backlog' for r in plan['items']),7)


    def test_authentication_failure_never_falls_back_to_untagged_writes(self):
        transport=self.transport
        class Denied:
            def request(self,method,path,payload=None):
                if path=='/api/tools/kanban/efforts':raise module.ApiError(401)
                return transport.request(method,path,payload)
        with self.assertRaises(module.ApiError):module.sync(Denied(),self.plan,True)
        self.assertEqual(transport.writes,0)

    def test_cycle_is_rejected_before_discovery_or_mutation(self):
        self.plan['items'][1]['depends_on']=['future']
        with self.assertRaises(ValueError):module.sync(self.transport,self.plan,True)
        self.assertEqual(self.transport.writes,0)


    def test_entire_plan_can_be_grouped_natively_without_duplicates(self):
        import json
        plan=json.loads((Path(__file__).resolve().parents[1]/'plans/mcp-wiki-rag.json').read_text())
        result=module.sync(self.transport,plan,True)
        self.assertEqual(len(result['items']),19)
        related=self.client.get(f"/api/tools/kanban/efforts/{result['effort_id']}/items").json['items']
        self.assertEqual(len(related),19)
        overview=self.client.get(f"/api/tools/kanban/items/{result['items']['overview']}").json['item']
        self.assertEqual(len(overview['links']),18)
        writes=self.transport.writes
        self.assertEqual(module.sync(self.transport,plan,True),result)
        self.assertEqual(self.transport.writes,writes)
