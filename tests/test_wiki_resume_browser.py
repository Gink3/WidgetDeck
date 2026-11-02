"""Actual Wiki read/editor/library refresh keeps modes, filters and dirty text."""
import os
import secrets
import unittest
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'),'Requires disposable browser app')
class WikiResumeBrowserTests(unittest.TestCase):
    def start(self,pw):
        base=os.environ['WORKSPACE_TEST_BASE_URL'];self.assertEqual(base,'http://127.0.0.1:8020')
        browser=pw.chromium.launch();context=browser.new_context(viewport={'width':390,'height':844},service_workers='block')
        self.assertEqual(context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'wiki-resume-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
        response=context.request.post(base+'/tools/wiki/api/pages',data={'title':'Foreground Article','content':'Original saved paragraph'});self.assertEqual(response.status,201)
        page=context.new_page();self.errors=[];page.on('pageerror',lambda error:self.errors.append(str(error)))
        return base,browser,context,page,response.json()['page']

    def test_reading_refresh_preserves_mode_and_dirty_editor_never_overwrites_remote_data(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base,browser,context,page,item=self.start(pw);endpoint=base+'/tools/wiki/api/pages/'+item['slug']
            page.goto(base+'/tools/wiki/'+item['slug']);expect(page.locator('.markdown-preview')).to_contain_text('Original saved paragraph')
            page.wait_for_function('WidgetDeckRuntime.state.verified')
            writes=[];page.on('request',lambda request:writes.append(request) if request.method=='PUT' and '/tools/wiki/api/pages/' in request.url else None)
            changed=context.request.put(endpoint,data={**item,'content':'Updated saved paragraph'});self.assertEqual(changed.status,200)
            page.evaluate("dispatchEvent(new CustomEvent('widgetdeck:resume',{detail:{recovered:true}}))")
            expect(page.locator('.markdown-preview')).to_contain_text('Updated saved paragraph')
            expect(page.locator('.wiki-toolbar').get_by_role('button',name='Read',exact=True)).to_have_class('selected');self.assertEqual(writes,[])
            page.get_by_role('button',name='Edit',exact=True).click()
            page.route('**/tools/wiki/api/pages/*',lambda route:route.abort() if route.request.method=='PUT' else route.continue_())
            editor=page.get_by_role('textbox',name='Article Markdown');editor.fill('Keep my dirty article text')
            expect(page.locator('.wiki-message')).to_be_visible()
            changed=context.request.put(endpoint,data={**changed.json()['page'],'content':'Newer server paragraph'});self.assertEqual(changed.status,200)
            page.evaluate("dispatchEvent(new CustomEvent('widgetdeck:resume',{detail:{recovered:true}}))")
            expect(page.locator('.resume-refresh')).to_contain_text('Keep your unsaved edits');expect(editor).to_have_value('Keep my dirty article text')
            self.assertEqual(context.request.get(endpoint).json()['page']['content'],'Newer server paragraph')
            self.assertEqual(len(writes),1);self.assertEqual(self.errors,[]);browser.close()

    def test_library_refresh_keeps_search_and_ignores_an_older_filter_response(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base,browser,context,page,item=self.start(pw);page.goto(base+'/tools/wiki?library=1')
            library=page.locator('.wiki-library');search=library.get_by_role('textbox',name='Search',exact=True)
            search.fill('Foreground');expect(page.locator('.wiki-page-card')).to_have_count(1)
            library.get_by_role('button',name='Filters',exact=True).click()
            response=context.request.post(base+'/tools/wiki/api/pages',data={'title':'Foreground second','content':'Saved later'});self.assertEqual(response.status,201)
            page.evaluate("dispatchEvent(new CustomEvent('widgetdeck:resume',{detail:{recovered:true}}))")
            expect(page.locator('.wiki-page-card')).to_have_count(2);expect(search).to_have_value('Foreground')
            expect(library.get_by_role('button',name='Filters',exact=True)).to_have_attribute('aria-expanded','true')
            response=context.request.post(base+'/tools/wiki/api/pages',data={'title':'Other target','content':'Another view'});self.assertEqual(response.status,201)
            pending=[]
            page.route('**/tools/wiki/api/pages?*',lambda route:pending.append(route) if 'q=Foreground' in route.request.url else route.continue_())
            with page.expect_request(lambda request:'/tools/wiki/api/pages?' in request.url and 'q=Foreground' in request.url):
                page.evaluate("dispatchEvent(new CustomEvent('widgetdeck:resume',{detail:{recovered:true}}))")
            search.fill('Other');expect(page.locator('.wiki-page-card')).to_have_count(1);expect(page.locator('.wiki-page-card')).to_contain_text('Other target')
            pending[0].continue_();expect(search).to_have_value('Other');expect(page.locator('.wiki-page-card')).to_contain_text('Other target')
            self.assertEqual(self.errors,[]);browser.close()
