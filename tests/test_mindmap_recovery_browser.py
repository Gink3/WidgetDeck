"""New and interrupted graph recovery is explicit and never replays autosave."""
import os
import secrets
import unittest
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'),'Requires disposable browser app')
class MindMapRecoveryBrowserTests(unittest.TestCase):
    def test_new_and_failed_save_recovery_requires_explicit_publish(self):
        from playwright.sync_api import sync_playwright,expect
        base=os.environ['WORKSPACE_TEST_BASE_URL'];self.assertEqual(base,'http://127.0.0.1:8020')
        with sync_playwright() as pw:
            browser=pw.chromium.launch();context=browser.new_context(viewport={'width':390,'height':844})
            self.assertEqual(context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'map-recovery-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/tools/mindmaps/new');page.get_by_label('Map name',exact=True).fill('Recover new graph')
            page.get_by_role('button',name='Add node',exact=True).click()
            page.evaluate("dispatchEvent(new Event('pagehide'))")
            page.once('dialog',lambda dialog:dialog.accept());page.reload()
            expect(page.get_by_label('Map name',exact=True)).to_have_value('Untitled mind map')
            recovery=page.locator('[data-draft-group=mind-map]');recovery.locator(':scope>summary').click()
            recovery.get_by_role('button',name='Restore draft',exact=True).click()
            expect(page.get_by_label('Map name',exact=True)).to_have_value('Recover new graph')
            expect(page.locator('.react-flow__node')).to_have_count(2)
            self.assertEqual(context.request.get(base+'/tools/mindmaps/api/maps').json()['maps'],[])
            page.get_by_role('button',name='Save new map',exact=True).click()
            expect(page.locator('.save-status')).to_have_text('Saved')
            page.wait_for_function("!location.pathname.endsWith('/new')")
            page.route('**/tools/mindmaps/api/maps/*',lambda route:route.abort() if route.request.method=='PUT' else route.continue_())
            page.get_by_label('Map name',exact=True).fill('Recover failed graph edits')
            expect(page.locator('.save-status')).to_have_text('Offline')
            page.once('dialog',lambda dialog:dialog.accept());page.reload()
            expect(page.get_by_label('Map name',exact=True)).to_have_value('Recover new graph')
            writes=[];page.on('request',lambda request:writes.append(request.method) if request.method in ('POST','PUT') and '/tools/mindmaps/api/maps' in request.url else None)
            recovery=page.locator('[data-draft-group=mind-map]');recovery.locator(':scope>summary').click()
            recovery.get_by_role('button',name='Restore draft',exact=True).click()
            expect(page.get_by_label('Map name',exact=True)).to_have_value('Recover failed graph edits')
            page.wait_for_timeout(1000);self.assertEqual(writes,[])
            page.unroute('**/tools/mindmaps/api/maps/*')
            page.get_by_role('button',name='Save recovered changes',exact=True).click()
            expect(page.locator('.save-status')).to_have_text('Saved')
            self.assertEqual(writes,['PUT'])
            self.assertEqual(context.request.get(base+'/tools/mindmaps/api/maps').json()['maps'][0]['name'],'Recover failed graph edits')
            self.assertEqual(page.evaluate("Object.keys(localStorage).filter(key=>key.startsWith('widgetdeck.draft.v1.')).length"),0)
            self.assertEqual(errors,[]);browser.close()
