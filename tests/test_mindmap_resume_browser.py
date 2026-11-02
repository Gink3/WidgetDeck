"""Actual map refresh, conflict retention and explicit retry after backgrounding."""
import os
import secrets
import unittest
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'),'Requires disposable browser app')
class MindMapResumeBrowserTests(unittest.TestCase):
    def start(self,pw):
        base=os.environ['WORKSPACE_TEST_BASE_URL'];self.assertEqual(base,'http://127.0.0.1:8020')
        browser=pw.chromium.launch();context=browser.new_context(viewport={'width':390,'height':844},service_workers='block')
        self.assertEqual(context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'map-resume-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
        response=context.request.post(base+'/tools/mindmaps/api/maps',data={'name':'Initial map'});self.assertEqual(response.status,201);item=response.json()['map']
        page=context.new_page();self.errors=[];page.on('pageerror',lambda error:self.errors.append(str(error)))
        page.goto(base+'/tools/mindmaps/'+item['id']);page.wait_for_function('WidgetDeckRuntime.state.verified && document.querySelector(".save-status")?.textContent==="Saved"')
        return base,browser,context,page,item

    def test_clean_resume_updates_without_writes_and_stale_save_retains_a_comparison_copy(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base,browser,context,page,item=self.start(pw);url=base+'/tools/mindmaps/api/maps/'+item['id']
            writes=[];page.on('request',lambda request:writes.append(request) if request.method=='PUT' and '/api/maps/' in request.url else None)
            changed=context.request.put(url,data={**item,'name':'Saved elsewhere'});self.assertEqual(changed.status,200)
            page.evaluate("dispatchEvent(new CustomEvent('widgetdeck:resume',{detail:{recovered:true}}))")
            expect(page.get_by_label('Map name',exact=True)).to_have_value('Saved elsewhere');self.assertEqual(writes,[])
            changed=context.request.put(url,data={**changed.json()['map'],'name':'Newer server version'});self.assertEqual(changed.status,200)
            page.get_by_label('Map name',exact=True).fill('Local conflicting version')
            expect(page.locator('.save-status')).to_have_text('Conflict')
            expect(page.get_by_role('link',name='Open saved version',exact=True)).to_be_visible()
            expect(page.get_by_label('Map name',exact=True)).to_have_value('Local conflicting version')
            page.get_by_label('Map name',exact=True).fill('Revised local conflicting version')
            page.wait_for_timeout(1000);self.assertEqual(len(writes),1)
            page.evaluate("dispatchEvent(new CustomEvent('widgetdeck:resume',{detail:{recovered:true}}))")
            expect(page.locator('.resume-refresh')).to_contain_text('Keep your unsaved edits')
            page.once('dialog',lambda dialog:dialog.accept());page.reload()
            expect(page.get_by_label('Map name',exact=True)).to_have_value('Newer server version')
            recovery=page.locator('[data-draft-group=mind-map]');recovery.locator(':scope>summary').click()
            expect(recovery.get_by_role('button',name='Restore draft',exact=True)).to_be_disabled()
            self.assertIn('Revised local conflicting version',recovery.get_by_label('Recovered draft to compare').input_value())
            self.assertEqual(context.request.get(url).json()['map']['revision'],2)
            self.assertEqual(self.errors,[]);browser.close()

    def test_background_save_waits_for_an_explicit_retry_after_owner_verification(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base,browser,context,page,item=self.start(pw);writes=[]
            page.on('request',lambda request:writes.append(request) if request.method=='PUT' and '/api/maps/' in request.url else None)
            page.get_by_label('Map name',exact=True).fill('Keep interrupted map edits')
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
            expect(page.locator('.save-status')).to_have_text('Offline');self.assertEqual(writes,[])
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))")
            page.wait_for_function('WidgetDeckRuntime.state.verified')
            page.wait_for_timeout(1000);self.assertEqual(writes,[])
            expect(page.get_by_label('Map name',exact=True)).to_have_value('Keep interrupted map edits')
            page.get_by_role('button',name='Retry save',exact=True).click();expect(page.locator('.save-status')).to_have_text('Saved')
            self.assertEqual(len(writes),1)
            saved=context.request.get(base+'/tools/mindmaps/api/maps/'+item['id']).json()['map']
            self.assertEqual(saved['name'],'Keep interrupted map edits');self.assertEqual(saved['revision'],1)
            self.assertEqual(self.errors,[]);browser.close()
