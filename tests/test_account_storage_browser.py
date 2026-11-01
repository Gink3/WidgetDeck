"""Preserved legacy bytes, explicit owner recovery and serialized browser saves."""
import json
import logging
import secrets
import tempfile
import threading
import unittest
from werkzeug.serving import make_server
from test_security_boundaries import isolated_application, auth_post


class AccountStorageBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        cls.directory = tempfile.TemporaryDirectory()
        _, cls.app = isolated_application(cls.directory.name)
        cls.server = make_server('127.0.0.1', 0, cls.app, threaded=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.directory.cleanup()

    def setUp(self):
        self.clients = []
        for _ in range(2):
            client = self.app.test_client()
            auth_post(client, '/register', {'username':'storage-'+secrets.token_hex(4), 'password':'test-only-password'})
            self.clients.append(client)

    def sign_in(self, context, index):
        context.add_cookies([{'name':'dashboard_session','value':self.clients[index].get_cookie('dashboard_session').value,'url':self.base}])

    def open_store(self, page, records=None):
        page.goto(self.base+'/')
        page.wait_for_function('window.WidgetDeckStorage && window.WidgetDeckRuntime?.state.reachable === true')
        page.evaluate('''records => { window.store=WidgetDeckStorage.create({id:'test-saves',title:'Test',records:records.map(key=>({key,kind:'list',initial:[],validate:Array.isArray}))}); }''', records or ['old.items'])

    def test_explicit_recovery_merges_keeps_exact_backup_and_denies_other_account(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser=pw.chromium.launch(); context=browser.new_context(accept_downloads=True)
            self.sign_in(context,0); page=context.new_page(); self.open_store(page)
            original='[ {"id":"old", "name":"Private older save"}, {"id":"same","name":"Older version"} ]'
            page.evaluate("raw=>localStorage.setItem('old.items',raw)", original)
            self.open_store(page)
            expect(page.locator('[data-storage-group=test-saves]')).not_to_contain_text('Private older save')
            self.assertEqual(page.evaluate("store.read('old.items',[])"),[])
            self.assertTrue(page.evaluate("store.write('old.items',[{id:'same',name:'Current version'}])"))
            page.once('dialog',lambda dialog:dialog.accept())
            page.get_by_role('button',name='Recover my older saves').click()
            expect(page.locator('[data-storage-group=test-saves]')).to_contain_text('Recovery complete')
            expected=[{'id':'same','name':'Current version'},{'id':'old','name':'Private older save'}]
            self.assertEqual(page.evaluate("store.read('old.items',[])"),expected)
            self.assertEqual(page.evaluate("localStorage.getItem('old.items')"),original)
            with page.expect_download() as download:page.get_by_role('button',name='Download data backup').click()
            with open(download.value.path()) as file:backup=json.load(file)
            self.assertEqual(backup['older']['old.items'],original)
            self.sign_in(context,1); self.open_store(page)
            self.assertEqual(page.evaluate("store.read('old.items',[])"),[])
            self.assertFalse(page.evaluate('store.recover()'))
            self.assertIsNone(page.evaluate("localStorage.getItem(store.key('old.items'))"))
            expect(page.locator('[data-storage-group=test-saves]')).not_to_contain_text('Private older save')
            self.sign_in(context,0); self.open_store(page)
            self.assertEqual(page.evaluate("store.read('old.items',[])"),expected)
            context.close(); browser.close()

    def test_recovery_and_other_tab_update_share_lock_without_lost_records(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(); context=browser.new_context(); self.sign_in(context,0)
            first=context.new_page(); self.open_store(first)
            first.evaluate("localStorage.setItem('old.items',JSON.stringify([{id:'old'}]))")
            second=context.new_page(); self.open_store(second)
            first.evaluate('''() => {const native=fetch;window.release=null;window.fetch=async(...args)=>{if(args[0]==='/api/session')await new Promise(resolve=>window.release=resolve);return native(...args);};window.recovery=store.recover();void 0;}''')
            first.wait_for_function('window.release !== null')
            second.evaluate("window.update=store.update('old.items',items=>[...items,{id:'new'}]);void 0")
            first.evaluate('window.release()')
            self.assertTrue(first.evaluate('window.recovery'))
            self.assertTrue(second.evaluate('window.update'))
            self.assertEqual(first.evaluate("store.read('old.items',[])"),[{'id':'old'},{'id':'new'}])
            context.close(); browser.close()

    def test_partial_quota_failure_is_retryable_and_never_overwrites_damaged_records(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser=pw.chromium.launch(); context=browser.new_context(); self.sign_in(context,0)
            page=context.new_page(); self.open_store(page,['old.items','old.more'])
            page.evaluate("localStorage.setItem('old.items','[{\"id\":\"first\"}]');localStorage.setItem('old.more','[{\"id\":\"second\"}]')")
            page.evaluate('''() => {window.originalSet=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){if(key===store.key('old.more'))throw new DOMException('Full','QuotaExceededError');return originalSet.call(this,key,value);};}''')
            self.assertFalse(page.evaluate('store.recover()'))
            expect(page.locator('[data-storage-group=test-saves]')).to_contain_text('storage is full')
            self.assertEqual(page.evaluate("localStorage.getItem('old.more')"),'[{"id":"second"}]')
            self.assertEqual(page.evaluate("store.read('old.more',[])"),[{'id':'second'}])
            self.sign_in(context,1); self.open_store(page,['old.items','old.more'])
            self.assertFalse(page.evaluate('store.recover()'))
            self.sign_in(context,0); self.open_store(page,['old.items','old.more'])
            self.assertTrue(page.evaluate("store.update('old.items',items=>[...items,{id:'newer'}])"))
            self.assertTrue(page.evaluate('store.recover()'))
            self.assertEqual(page.evaluate("store.read('old.items',[])"),[{'id':'first'},{'id':'newer'}])
            self.assertEqual(page.evaluate("store.read('old.more',[])"),[{'id':'second'}])
            page.evaluate("localStorage.setItem(store.key('old.more'),'damaged private bytes')")
            self.assertEqual(page.evaluate("store.read('old.more',[])"),[])
            self.assertFalse(page.evaluate("store.write('old.more',[{id:'replacement'}])"))
            self.assertEqual(page.evaluate("localStorage.getItem(store.key('old.more'))"),'damaged private bytes')
            context.close(); browser.close()

    def test_backup_quota_failure_keeps_claimed_saves_readable_and_exportable(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(); context=browser.new_context(accept_downloads=True); self.sign_in(context,0)
            page=context.new_page(); self.open_store(page)
            original='[ {"id":"older","name":"Private original"} ]'
            page.evaluate("raw=>localStorage.setItem('old.items',raw)",original)
            page.evaluate("""() => {const native=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){if(key==='widgetdeck.legacy-backup.v1.test-saves')throw new DOMException('Full','QuotaExceededError');return native.call(this,key,value);};}""")
            self.assertFalse(page.evaluate('store.recover()'))
            self.assertEqual(page.evaluate("store.read('old.items',[])"),json.loads(original))
            self.assertFalse(page.evaluate("store.write('old.items',[])"))
            with page.expect_download() as download:page.get_by_role('button',name='Download data backup').click()
            with open(download.value.path()) as file:backup=json.load(file)
            self.assertEqual(backup['older']['old.items'],original)
            self.sign_in(context,1); self.open_store(page)
            self.assertFalse(page.evaluate('store.recover()'))
            self.assertEqual(page.evaluate("store.read('old.items',[])"),[])
            context.close(); browser.close()

    def test_expired_session_and_missing_locks_do_not_claim_legacy_data(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(); context=browser.new_context(); self.sign_in(context,0)
            page=context.new_page(); self.open_store(page)
            page.evaluate("localStorage.setItem('old.items','[{\"id\":\"kept\"}]')")
            self.clients[0].post('/logout')
            self.assertFalse(page.evaluate('store.recover()'))
            self.assertIsNone(page.evaluate("localStorage.getItem('widgetdeck.legacy-owner.v1.test-saves')"))
            self.sign_in(context,1); self.open_store(page)
            page.evaluate("Object.defineProperty(navigator,'locks',{configurable:true,value:undefined})")
            self.assertFalse(page.evaluate('store.recover()'))
            self.assertIsNone(page.evaluate("localStorage.getItem('widgetdeck.legacy-owner.v1.test-saves')"))
            self.assertTrue(page.evaluate("store.write('old.items',[{id:'new-only'}])"))
            self.assertEqual(page.evaluate("localStorage.getItem('old.items')"),'[{"id":"kept"}]')
            context.close(); browser.close()
