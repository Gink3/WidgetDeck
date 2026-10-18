"""Account-owned effort tags preserve existing card contracts and upgrade data."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from flask import g, jsonify
from test_dashboard_tools import test_app
from dashboard.database import db
from dashboard.auth import current_user
from dashboard.campaign_tools import kanban_models as models


class EffortTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.app = test_app(temp.name)
        self.real_auth = False
        @self.app.before_request
        def real_auth():
            if self.real_auth:
                g.pop('dashboard_user',None)
                if not current_user():return jsonify(error='Sign in is required.'),401
        self.client = self.app.test_client()
        self.client.post('/tools/kanban', data={'name': 'First'})
        self.board = self.client.get('/api/tools/kanban/boards').json['boards'][0]['id']
        self.columns = self.client.get(f'/api/tools/kanban/boards/{self.board}').json['board']['columns']
        self.item = self.client.post(f'/api/tools/kanban/boards/{self.board}/items', json={
            'title':'Existing card', 'notes':'Preserve me', 'column_id':self.columns[0]['id']}).json['item']

    def effort(self, name='Modularization', headers=None):
        response=self.client.post('/api/tools/kanban/efforts',json={'name':name},headers=headers)
        self.assertEqual(response.status_code,201)
        return response.json['effort']

    def assign(self, ids, revision=0, headers=None):
        return self.client.put(f"/api/tools/kanban/items/{self.item['id']}/efforts",json={
            'effort_ids':ids,'revision':revision},headers=headers)

    def detail(self):return self.client.get(f"/api/tools/kanban/items/{self.item['id']}").json['item']

    def test_multiple_assignments_noop_legacy_update_and_transfer(self):
        a,b=self.effort(),self.effort('MCP and wiki RAG')
        changed=self.assign([a['id'],b['id']]).json['item']
        self.assertEqual(changed['revision'],1)
        self.assertEqual(len(changed['efforts']),2)
        self.assertEqual(self.assign([b['id'],a['id']],1).json['item']['revision'],1)
        legacy=self.client.patch(f"/api/tools/kanban/items/{changed['id']}",json={
            'title':'Updated legacy caller','notes':changed['notes'],'column_id':changed['column_id'],'revision':1}).json['item']
        self.assertEqual(len(legacy['efforts']),2)
        self.client.post('/tools/kanban',data={'name':'Second'})
        boards=self.client.get('/api/tools/kanban/boards').json['boards']; destination=next(b['id'] for b in boards if b['name']=='Second')
        column=self.client.get(f'/api/tools/kanban/boards/{destination}').json['board']['columns'][0]['id']
        moved=self.client.post(f"/api/tools/kanban/items/{changed['id']}/transfer",json={
            'board_id':destination,'column_id':column,'revision':legacy['revision']}).json['item']
        self.assertEqual(moved['efforts'],legacy['efforts']);self.assertEqual(moved['notes'],'Preserve me')
        related=self.client.get(f"/api/tools/kanban/efforts/{a['id']}/items").json['items']
        self.assertEqual(related[0]['board_id'],destination)
        snapshot=self.client.get(f'/api/tools/kanban/boards/{destination}').json['board']
        self.assertEqual(snapshot['items'][0]['efforts'],moved['efforts'])

    def test_rename_remove_revision_history_and_cards_survive(self):
        effort=self.effort();self.assign([effort['id']])
        path=f"/api/tools/kanban/efforts/{effort['id']}"
        self.assertEqual(self.client.patch(path,json={'name':'New name','revision':7}).status_code,409)
        renamed=self.client.patch(path,json={'name':'New name','revision':0}).json['effort']
        self.assertEqual(renamed['revision'],1)
        changed=self.detail();self.assertEqual(changed['revision'],2);self.assertEqual(changed['efforts'][0]['name'],'New name')
        self.assertEqual(self.assign([],1).status_code,409)
        self.assertEqual(self.client.delete(path,json={'revision':0}).status_code,409)
        self.assertEqual(self.client.delete(path,json={'revision':1}).status_code,204)
        kept=self.detail();self.assertEqual(kept['efforts'],[]);self.assertEqual(kept['revision'],3)
        self.assertEqual(kept['title'],self.item['title']);self.assertEqual(kept['notes'],self.item['notes'])
        self.assertEqual(len(kept['history']),4)

    def test_account_isolation_validation_and_atomic_create(self):
        own=self.effort();foreign=self.effort('Private',{'X-Test-User':'2'})
        self.assertEqual(len(self.client.get('/api/tools/kanban/efforts').json['efforts']),1)
        self.assertEqual(self.client.get(f"/api/tools/kanban/efforts/{foreign['id']}/items").status_code,404)
        self.assertEqual(self.client.delete(f"/api/tools/kanban/efforts/{own['id']}",json={'revision':0},headers={'X-Test-User':'2'}).status_code,404)
        self.assertEqual(self.assign([own['id']],headers={'X-Test-User':'2'}).status_code,404)
        for ids in ([foreign['id']], [own['id'],own['id']], [True], 'bad', [own['id']]*21):
            self.assertEqual(self.assign(ids).status_code,400)
        self.assertEqual(self.detail()['revision'],0)
        result=self.client.post(f'/api/tools/kanban/boards/{self.board}/items',json={
            'title':'Must roll back','column_id':self.columns[0]['id'],'effort_ids':[foreign['id']]})
        self.assertEqual(result.status_code,400)
        self.assertEqual(len(self.client.get(f'/api/tools/kanban/boards/{self.board}').json['board']['items']),1)
        for name in (' MODULARIZATION ', '', 'x'*81, 'bad\nname'):
            self.assertEqual(self.client.post('/api/tools/kanban/efforts',json={'name':name}).status_code,400)

    def test_creation_assignment_and_permanent_card_delete_cleanup(self):
        e=self.effort()
        created=self.client.post(f'/api/tools/kanban/boards/{self.board}/items',json={
            'title':'Assigned on create','column_id':self.columns[0]['id'],'effort_ids':[e['id']]}).json['item']
        self.assertEqual(created['efforts'][0]['id'],e['id'])
        self.client.delete(f"/api/tools/kanban/items/{created['id']}",json={'revision':0})
        self.assertEqual(self.client.get(f"/api/tools/kanban/efforts/{e['id']}/items").json['items'],[])
        with self.app.app_context():self.assertEqual(db().execute('SELECT count(*) FROM kanban_item_efforts').fetchone()[0],0)

    def test_idempotent_upgrade_preserves_existing_rows_and_assignments(self):
        e=self.effort();self.assign([e['id']]);before=self.detail()
        models.init_database(self.app);models.init_database(self.app)
        self.assertEqual(self.detail(),before)
        self.assertIn('Untagged',self.client.get(f'/tools/kanban?board={self.board}').text)

    def test_personal_read_only_wrong_service_and_revoked_keys(self):
        self.real_auth = True
        import hashlib,json
        with self.app.app_context(),db():
            for token,permission,revoked in [('dash_read',{'kanban':'read'},None),('dash_write',{'kanban':'write'},None),
                                             ('dash_wiki',{'wiki':'write'},None),('dash_revoked',{'kanban':'write'},'now')]:
                db().execute('INSERT INTO dashboard_api_keys(user_id,name,token_hash,prefix,permissions,created_at,revoked_at) VALUES(?,?,?,?,?,?,?)',
                    (1,'Fixture',hashlib.sha256(token.encode()).hexdigest(),'fixture',json.dumps(permission),'now',revoked))
        for token in ('dash_read','dash_wiki','dash_revoked'):
            result=self.client.post('/api/tools/kanban/efforts',headers={'Authorization':'Bearer '+token},json={'name':'Denied'})
            self.assertEqual(result.status_code,401)
        self.assertEqual(self.client.get('/api/tools/kanban/efforts',headers={'Authorization':'Bearer dash_read'}).status_code,200)
        self.assertEqual(self.client.post('/api/tools/kanban/efforts',headers={'Authorization':'Bearer dash_write'},json={'name':'Allowed'}).status_code,201)


    def test_upgrade_from_pre_effort_database_preserves_old_card_content(self):
        before=self.detail()
        with self.app.app_context(),db():
            db().execute('DROP TABLE kanban_item_efforts')
            db().execute('DROP TABLE kanban_efforts')
        models.init_database(self.app)
        self.assertEqual(self.detail(),before)
