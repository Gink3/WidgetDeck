"""Recovery survives interruption without submitting, crossing owners or hiding conflicts."""
import logging
import tempfile
import threading
import unittest
from urllib.parse import urlencode
from werkzeug.serving import make_server
from test_security_boundaries import isolated_application


class DraftRecoveryBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        cls.directory = tempfile.TemporaryDirectory()
        _, cls.app = isolated_application(cls.directory.name)
        cls.server = make_server('127.0.0.1',0,cls.app,threaded=True)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.base = 'http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.directory.cleanup()

    def editor(self,page,owner='A',revision=1,ack=None):
        page.goto(self.base+'/login'+('?'+urlencode({'_draft_ack':ack}) if ack else ''))
        page.set_content('<body data-owner="'+owner+'"><main><label>Draft<textarea id="text"></textarea></label></main><form class="logout" onsubmit="event.preventDefault()"><button>Sign out</button></form></body>')
        page.add_script_tag(url=self.base+'/static/drafts.js')
        page.evaluate('''revision=>{
          window.revision=revision;window.baseline='';
          window.recovery=WidgetDeckDrafts.create({id:'fixture',resource:'one',host:document.querySelector('main'),
            read:()=>({text:document.querySelector('#text').value}),base:()=>({revision:window.revision}),
            restore:value=>{document.querySelector('#text').value=value.text;},
            dirty:()=>document.querySelector('#text').value!==window.baseline,
            validate:value=>typeof value?.text==='string'});
          document.querySelector('#text').addEventListener('input',()=>recovery.changed());
        }''',revision)

    def test_relaunch_restore_changed_base_and_independent_tabs(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            browser=pw.chromium.launch(); context=browser.new_context(); page=context.new_page()
            self.editor(page); page.locator('#text').fill('Recovery text\nUnicode café')
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
            self.editor(page); expect(page.locator('.draft-recovery')).to_be_visible()
            expect(page.locator('#text')).to_have_value('')
            page.locator('.draft-recovery>summary').click(); page.get_by_role('button',name='Restore draft',exact=True).click()
            expect(page.locator('#text')).to_have_value('Recovery text\nUnicode café')
            # No autosave or fetch path exists in the helper. A second tab has
            # a separate slot, keeping both versions available for comparison.
            other=context.new_page();self.editor(other)
            other.locator('#text').fill('Other tab edit');other.evaluate('recovery.capture()')
            self.assertEqual(page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('widgetdeck.draft.v1.A.')).length"),3)
            page.evaluate("window.baseline=document.querySelector('#text').value;recovery.clear()")
            self.assertEqual(page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('widgetdeck.draft.v1.A.')).length"),1)
            self.editor(page,revision=2);page.locator('.draft-recovery>summary').click()
            expect(page.get_by_role('button',name='Restore draft',exact=True)).to_be_disabled()
            self.assertIn('Other tab edit',page.get_by_label('Recovered draft to compare').input_value())
            expect(page.locator('#text')).to_have_value('')
            browser.close()

    def test_expiry_retention_owner_isolation_and_logout_only_clears_drafts(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page();self.editor(page)
            page.evaluate("localStorage.setItem('persistent-game-save','keep')")
            page.locator('#text').fill('Before expiry')
            page.evaluate("dispatchEvent(new Event('widgetdeck:session-expired'))")
            page.locator('#text').fill('After expiry');page.evaluate('recovery.capture()')
            self.editor(page,owner='B');expect(page.locator('.draft-recovery')).to_be_hidden()
            page.locator('#text').fill('B draft');page.evaluate('recovery.capture()')
            self.editor(page,owner='A');page.locator('.draft-recovery>summary').click()
            page.get_by_role('button',name='Restore draft',exact=True).click()
            expect(page.locator('#text')).to_have_value('Before expiry')
            page.get_by_role('button',name='Sign out',exact=True).click()
            self.assertEqual(page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('widgetdeck.draft.v1.A.')).length"),0)
            self.assertEqual(page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('widgetdeck.draft.v1.B.')).length"),1)
            self.assertEqual(page.evaluate("localStorage.getItem('persistent-game-save')"),'keep')
            browser.close()

    def test_expired_copy_pruning_limits_and_quota_failure_preserve_existing_bytes(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page();self.editor(page)
            page.locator('#text').fill('Original');page.evaluate('recovery.capture()')
            page.evaluate("()=>{const key=Object.keys(localStorage).find(k=>k.startsWith('widgetdeck.draft.v1.A.')),r=JSON.parse(localStorage.getItem(key));r.savedAt=Date.now()-8*86400000;localStorage.setItem(key,JSON.stringify(r));}")
            page.evaluate("window.baseline=document.querySelector('#text').value")
            self.editor(page);expect(page.locator('.draft-recovery')).to_be_hidden()
            page.locator('#text').fill('Keep this copy');page.evaluate('recovery.capture()')
            before=page.evaluate("Object.fromEntries(Object.entries(localStorage))")
            page.evaluate("Object.defineProperty(Storage.prototype,'setItem',{configurable:true,value(){throw new DOMException('Full','QuotaExceededError')}})")
            page.locator('#text').fill('New in-memory edits');page.evaluate('recovery.capture()')
            expect(page.locator('.draft-recovery')).to_contain_text('Browser storage is full or unavailable')
            self.assertEqual(page.evaluate('Object.fromEntries(Object.entries(localStorage))'),before)
            expect(page.locator('#text')).to_have_value('New in-memory edits')
            browser.close()

    def test_size_and_record_limits_retain_prior_and_damaged_copies(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page();self.editor(page)
            page.locator('#text').fill('Previous draft');page.evaluate('recovery.capture()')
            before=page.evaluate('Object.fromEntries(Object.entries(localStorage))')
            page.evaluate("document.querySelector('#text').value='x'.repeat(270000);recovery.capture()")
            expect(page.locator('.draft-recovery')).to_contain_text('exceeds the recovery limit')
            self.assertEqual(page.evaluate('Object.fromEntries(Object.entries(localStorage))'),before)
            page.evaluate("for(let i=0;i<19;i++)localStorage.setItem('widgetdeck.draft.v1.A.damaged-'+i,'retain malformed bytes')")
            before=page.evaluate('Object.fromEntries(Object.entries(localStorage))')
            page.evaluate('''()=>{recovery.dispose({preserve:false});document.querySelector('#text').value='Another resource';
              recovery=WidgetDeckDrafts.create({id:'fixture',resource:'two',host:document.querySelector('main'),read:()=>({text:document.querySelector('#text').value}),base:()=>null,restore:()=>{},dirty:()=>true});recovery.capture();}''')
            expect(page.locator('.draft-recovery')).to_contain_text('Draft recovery storage is full')
            self.assertEqual(page.evaluate('Object.fromEntries(Object.entries(localStorage))'),before)
            browser.close()

    def test_native_ack_keeps_edits_made_after_the_submitted_snapshot(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            browser=pw.chromium.launch();page=browser.new_page();self.editor(page)
            page.locator('#text').fill('Submitted snapshot');page.evaluate('recovery.capture()')
            nonce=page.evaluate('recovery.receipt()')
            page.locator('#text').fill('Newer edit while the form was submitting');page.evaluate('recovery.capture()')
            self.editor(page,ack=nonce)
            page.locator('.draft-recovery>summary').click();page.get_by_role('button',name='Restore draft',exact=True).click()
            expect(page.locator('#text')).to_have_value('Newer edit while the form was submitting')
            nonce=page.evaluate('recovery.receipt()')
            self.editor(page,ack=nonce)
            expect(page.locator('.draft-recovery')).to_be_hidden()
            self.assertEqual(page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('widgetdeck.draft.v1.')).length"),0)
            browser.close()
