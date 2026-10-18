"""Real application boundaries on isolated data; known gaps track Dashboard cards."""
import ast
import base64
import io
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from flask import request,send_from_directory
from PIL import Image
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]


def isolated_application(instance):
    name = 'security_fixture_'+secrets.token_hex(6)
    module = types.ModuleType(name)
    module.__file__ = str(ROOT/'app.py')
    sys.modules[name] = module
    tree = ast.parse((ROOT/'app.py').read_text())
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='app' for target in node.targets):
            node.value.keywords.append(ast.keyword(arg='instance_path',value=ast.Constant(instance)))
            break
    with patch.dict(os.environ,{'DASHBOARD_SECRET_KEY':secrets.token_hex(32),'DASHBOARD_ADMIN_USERNAME':'',
                               'DASHBOARD_ADMIN_PASSWORD':'','WIKI_WORKER_DISABLED':'1'}):
        exec(compile(ast.fix_missing_locations(tree),str(ROOT/'app.py'),'exec'),module.__dict__)
    module.app.config['TESTING'] = True
    if os.environ.get('AUDIT_FRONTEND_BUILD'):
        @module.app.before_request
        def public_built_assets():
            if request.path.startswith('/static/mindmaps/'):
                return send_from_directory(os.environ['AUDIT_FRONTEND_BUILD'],request.path[len('/static/mindmaps/'):])
    return name,module.app

def auth_post(client, path, data, **kwargs):
    client.get(path)
    with client.session_transaction() as cookie:
        token = cookie['auth_csrf_token']
    return client.post(path, data={**data, 'csrf_token': token}, **kwargs)


class SecurityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        name,self.app = isolated_application(self.directory.name)
        self.addCleanup(lambda:sys.modules.pop(name,None))
        self.alice,self.bob = self.app.test_client(),self.app.test_client()
        for client,username in [(self.alice,'audit-alice'),(self.bob,'audit-bob')]:
            self.assertEqual(auth_post(client,'/register',data={'username':username,'password':'isolated-audit-passphrase'}).status_code,302)

    def test_anonymous_tampered_cookie_invalid_bearer_and_login_injection_fail_closed(self):
        client = self.app.test_client()
        for path in ['/api/settings','/api/account/keys','/api/tools/kanban/boards','/tools/wiki/api/pages',
                     '/tools/mindmaps/api/maps','/four-ad/api/guild','/api/tools/flashcards/decks','/api/tools/chapter-painter/schemes']:
            self.assertEqual(client.get(path).status_code,401,path)
        client.set_cookie('dashboard_session','eyJ1c2VyX2lkIjoxfQ.fake.invalid')
        self.assertEqual(client.get('/api/settings').status_code,401)
        self.assertEqual(self.alice.get('/api/settings',headers={'Authorization':'Bearer invalid'}).status_code,401)
        self.assertEqual(auth_post(client,'/login',data={'username':"audit-alice' OR '1'='1' --",'password':'wrong'}).status_code,401)
        for path in ['/instance/dashboard.sqlite','/static/../instance/dashboard.sqlite','/.env']:
            self.assertEqual(self.alice.get(path).status_code,404)

    def test_real_sessions_scope_kanban_wiki_and_mindmaps_to_their_owner(self):
        result = self.alice.post('/tools/kanban',data={'name':'Alice private board'})
        board = self.alice.get('/api/tools/kanban/boards').json['boards'][0]
        self.assertEqual(self.bob.get('/api/tools/kanban/boards').json['boards'],[])
        self.assertEqual(self.bob.get(f"/api/tools/kanban/boards/{board['id']}").status_code,404)
        column = self.alice.get(f"/api/tools/kanban/boards/{board['id']}").json['board']['columns'][0]['id']
        self.assertEqual(self.bob.post(f"/api/tools/kanban/boards/{board['id']}/items",json={'column_id':column,'title':'forbidden'}).status_code,404)
        page = self.alice.post('/tools/wiki/api/pages',json={'title':'Alice private wiki','content':'Isolated fixture content'}).json['page']
        self.assertEqual(self.bob.get('/tools/wiki/api/pages/'+page['slug']).status_code,404)
        self.assertEqual(self.bob.put('/tools/wiki/api/pages/'+page['slug'],json={'content':'forbidden'}).status_code,404)
        self.assertEqual(self.bob.get('/tools/wiki/api/pages').json['pages'],[])
        mindmap = self.alice.post('/tools/mindmaps/api/maps',json={'title':'Alice private map','nodes':[],'edges':[]})
        self.assertEqual(mindmap.status_code,201)
        ident = mindmap.json['map']['id']
        self.assertEqual(self.bob.get('/tools/mindmaps/api/maps/'+ident).status_code,404)
        self.assertEqual(self.bob.put('/tools/mindmaps/api/maps/'+ident,json={'title':'forbidden'}).status_code,404)
        self.assertEqual(self.bob.delete('/tools/mindmaps/api/maps/'+ident).status_code,404)

    def test_api_key_management_csrf_and_readonly_key_permissions(self):
        self.assertEqual(self.alice.post('/api/account/keys',json={'name':'Missing CSRF','permissions':{'kanban':'read'}}).status_code,403)
        csrf = self.alice.get('/api/account/keys').json['csrf_token']
        result = self.alice.post('/api/account/keys',json={'name':'Audit reader','permissions':{'kanban':'read'}},headers={'X-CSRF-Token':csrf})
        self.assertEqual(result.status_code,201)
        headers = {'Authorization':'Bearer '+result.json['token']}
        self.assertEqual(self.alice.get('/api/tools/kanban/boards',headers=headers).status_code,200)
        self.assertEqual(self.alice.post('/api/tools/kanban/boards/1/items',json={},headers=headers).status_code,401)
        self.assertEqual(self.alice.get('/tools/wiki/api/pages',headers=headers).status_code,401)
        self.assertEqual(self.alice.get('/api/account/keys',headers=headers).status_code,401)

    def test_known_44_cross_origin_login_is_rejected(self):
        # Reproduces #44 until compatible login CSRF protection is implemented.
        client = self.app.test_client()
        response = auth_post(client,'/login',data={'username':'audit-alice','password':'isolated-audit-passphrase'},
                               headers={'Origin':'https://attacker.invalid'})
        self.assertIn(response.status_code,(400,403))


    def test_svg_does_not_fetch_loopback_and_rejects_external_xml_entities(self):
        from dashboard.image_converter import _convert
        output=io.BytesIO();Image.new('RGB',(4,4),'blue').save(output,format='PNG');image=output.getvalue();hits=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path);self.send_response(200);self.send_header('Content-Type','image/png');self.end_headers();self.wfile.write(image)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><image href="http://127.0.0.1:{server.server_port}/fixture.png" width="4" height="4"/></svg>'.encode()
            _convert(svg,'png')
            self.assertEqual(hits,[])
            good=b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><image href="data:image/png;base64,'+base64.b64encode(image)+b'" width="4" height="4"/></svg>'
            with Image.open(io.BytesIO(_convert(good,'png'))) as result:
                self.assertIsNotNone(result.getbbox())
            with self.assertRaises(ValueError):
                _convert(b'<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///audit-fixture">]><svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><text>&xxe;</text></svg>','png')
        finally:server.shutdown();server.server_close()

    @unittest.skipUnless(os.environ.get('AUDIT_FRONTEND_BUILD'),'Requires built frontend and Chromium')
    def test_wiki_preview_strips_active_html_and_javascript_urls(self):
        from playwright.sync_api import sync_playwright
        content='# Security preview\n\n<script>window.__auditXss=1</script><img src="/not-an-image" onerror="window.__auditXss=2">\n\n[bad](javascript:window.__auditXss=3)'
        page = self.alice.post('/tools/wiki/api/pages',json={'title':'Security page','content':content}).json['page']
        server=make_server('127.0.0.1',0,self.app,threaded=True)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch()
                context=browser.new_context()
                base=f'http://127.0.0.1:{server.server_port}'
                context.add_cookies([{'name':'dashboard_session','value':self.alice.get_cookie('dashboard_session').value,'url':base}])
                view=context.new_page();view.goto(base+'/tools/wiki/'+page['slug'])
                view.get_by_role('heading',name='Security preview',exact=True).wait_for()
                view.wait_for_timeout(100)
                self.assertTrue(view.evaluate('typeof window.__auditXss === "undefined"'))
                self.assertEqual(view.locator('[onerror],[onload],a[href^="javascript:"]').count(),0)
                context.close();browser.close()
        finally:server.shutdown();server.server_close()


class ImageArtifactTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('DASHBOARD_TEST_IMAGE'),'Requires rebuilt development image')
    def test_image_does_not_include_private_runtime_database_or_signing_key(self):
        image=os.environ['DASHBOARD_TEST_IMAGE']
        command=['docker','run','--rm','--network','none','--entrypoint','python',image,'-c',
                 'from pathlib import Path; assert not Path("/app/instance/dashboard.sqlite").exists(); assert not Path("/app/instance/.dashboard_secret").exists()']
        result=subprocess.run(command,capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,'Private runtime state is present in the image, or image check failed.')
