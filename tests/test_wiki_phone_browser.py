"""Phone reading width, deliberate modes, keyboard formatting and real PDF files."""
import io
import os
import re
from pathlib import Path
import secrets
import unittest
from PIL import Image
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'),'Requires disposable browser app')
class WikiPhoneBrowserTests(unittest.TestCase):
    def start(self,pw):
        base=os.environ['WORKSPACE_TEST_BASE_URL'];self.assertEqual(base,'http://127.0.0.1:8020')
        browser=pw.chromium.launch();context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,accept_downloads=True,service_workers='block')
        self.assertEqual(context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'wiki-phone-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
        self.assertEqual(context.request.post(base+'/tools/wiki/api/pages',data={'title':'Phone Target','content':'Linked article'}).status,201)
        table='| '+' | '.join('Column '+str(i) for i in range(8))+' |\n| '+' | '.join('---' for _ in range(8))+' |\n| '+' | '.join('Long-cell-'+str(i)+'-value'*8 for i in range(8))+' |'
        content='## Introduction\n\nPhone reading content.\n\n## Wide table\n\n'+table+'\n\n```\n'+('unbroken-code-'*80)+'\n```\n\n## Destination\n\nLast section.'
        response=context.request.post(base+'/tools/wiki/api/pages',data={'title':'Phone article','content':content,'metadata':{'properties':{'Campaign':'Frozen city','Status':'Reading'}}});self.assertEqual(response.status,201)
        item=response.json()['page'];updated=context.request.put(base+'/tools/wiki/api/pages/'+item['slug'],data={**item,'metadata':{**item['metadata'],'properties':{'Campaign':'Frozen city','Status':'Reading'}}});self.assertEqual(updated.status,200)
        page=context.new_page();self.errors=[];page.on('pageerror',lambda error:self.errors.append(str(error)))
        page.goto(base+'/tools/wiki/'+updated.json()['page']['slug']);page.wait_for_function('WidgetDeckRuntime.state.verified && document.querySelector(".wiki-toolbar")')
        return base,browser,context,page

    def test_phone_read_preview_wide_content_disclosures_and_desktop_split(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base,browser,context,page=self.start(pw)
            expect(page.get_by_role('button',name='Read',exact=True)).to_have_attribute('aria-pressed','true')
            self.assertNotEqual(page.evaluate('document.activeElement.tagName'),'TEXTAREA')
            expect(page.locator('.wiki-section-tree>details')).not_to_have_attribute('open','')
            expect(page.locator('.wiki-properties')).not_to_have_attribute('open','')
            self.assertGreater(page.locator('.markdown-preview').bounding_box()['width'],340)
            if os.environ.get('WIKI_PHONE_SCREENSHOT'):page.screenshot(path=os.environ['WIKI_PHONE_SCREENSHOT'])
            page.locator('.wiki-section-tree>details>summary').click();page.locator('.wiki-section-tree').get_by_role('link',name='Destination',exact=True).click()
            expect(page.locator('.wiki-section-tree>details')).not_to_have_attribute('open','')
            self.assertGreaterEqual(page.locator('#destination').bounding_box()['y'],page.locator('.wiki-toolbar').bounding_box()['y']+page.locator('.wiki-toolbar').bounding_box()['height']-1)
            region=page.get_by_role('region',name='Scrollable table',exact=True)
            region.scroll_into_view_if_needed()
            geometry=region.evaluate('e=>({content:e.scrollWidth,width:e.clientWidth})');self.assertGreater(geometry['content'],geometry['width'],geometry)
            region.evaluate('e=>e.scrollLeft=e.scrollWidth');self.assertGreater(region.evaluate('e=>e.scrollLeft'),0)
            position=region.evaluate('e=>e.scrollLeft')
            page.locator('.wiki-properties>summary').click();expect(page.locator('.wiki-properties')).to_contain_text('Frozen city')
            region.scroll_into_view_if_needed();self.assertAlmostEqual(region.evaluate('e=>e.scrollLeft'),position,delta=1)
            for width,height in [(320,568),(375,812),(719,900),(844,390),(900,700)]:
                page.set_viewport_size({'width':width,'height':height});self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                self.assertGreaterEqual(page.get_by_role('button',name='Save',exact=True).bounding_box()['height'],44)
            page.get_by_role('button',name='Preview',exact=True).click();expect(page.get_by_text('Preview of current edits',exact=True)).to_be_visible()
            expect(page.get_by_role('textbox',name='Article Markdown')).to_have_count(0)
            page.set_viewport_size({'width':1440,'height':1000})
            expect(page.get_by_role('button',name='Split',exact=True)).to_have_attribute('aria-pressed','true')
            expect(page.get_by_role('textbox',name='Article Markdown')).to_be_visible();expect(page.locator('.wiki-preview-pane')).to_be_visible()
            self.assertEqual(self.errors,[]);browser.close()

    def test_short_viewport_formatting_menus_and_link_suggestions_remain_reachable(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base,browser,context,page=self.start(pw)
            page.route('**/tools/wiki/api/pages/*',lambda route:route.fulfill(status=503,json={'error':'Independent unavailable save'}) if route.request.method=='PUT' else route.continue_())
            page.get_by_role('button',name='Edit',exact=True).click();editor=page.get_by_role('textbox',name='Article Markdown');editor.fill('bright')
            page.set_viewport_size({'width':390,'height':320});expect(page.locator('html')).to_have_css('--mobile-viewport-height','320px');editor.focus()
            page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            geometry=page.evaluate("({field:document.querySelector('textarea[aria-label=\"Article Markdown\"]').getBoundingClientRect().toJSON(),tools:document.querySelector('.wiki-format-toolbar').getBoundingClientRect().toJSON(),header:document.querySelector('.wiki-toolbar').getBoundingClientRect().toJSON()})")
            self.assertGreaterEqual(geometry['tools']['top'],geometry['header']['bottom']-1,geometry)
            self.assertGreaterEqual(geometry['field']['top'],geometry['tools']['bottom']-1,geometry);self.assertLessEqual(geometry['field']['bottom'],321,geometry)
            editor.evaluate('e=>e.setSelectionRange(0,6)');page.get_by_role('button',name='Bold',exact=True).click()
            expect(editor).to_have_value('**bright**');expect(editor).to_be_focused()
            page.get_by_role('button',name='Insert',exact=True).click();finder=page.get_by_role('textbox',name='Find an element, macro, or template');finder.fill('Page link')
            menu=page.locator('.wiki-insert-menu');self.assertGreaterEqual(menu.bounding_box()['y'],0);self.assertLessEqual(menu.bounding_box()['y']+menu.bounding_box()['height'],321)
            menu.get_by_role('button',name='Page link',exact=False).click();expect(editor).to_have_value(re.compile(r'.*\[\[.+\]\].*',re.S))
            editor.fill('[[Phone');expect(page.get_by_role('option',name='Phone Target',exact=True)).to_be_visible()
            page.get_by_role('option',name='Phone Target',exact=True).click();expect(editor).to_have_value('[[phone-target|Phone Target]]')
            if os.environ.get('WIKI_KEYBOARD_SCREENSHOT'):page.screenshot(path=os.environ['WIKI_KEYBOARD_SCREENSHOT'])
            page.get_by_role('button',name='Preview',exact=True).click();expect(page.locator('.wiki-preview-pane')).to_contain_text('Phone Target')
            page.get_by_role('button',name='Edit',exact=True).click();expect(editor).to_have_value('[[phone-target|Phone Target]]')
            page.set_viewport_size({'width':390,'height':400})
            page.evaluate("Object.defineProperty(visualViewport,'height',{configurable:true,value:300});Object.defineProperty(visualViewport,'offsetTop',{configurable:true,value:20});visualViewport.dispatchEvent(new Event('resize'))")
            page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))')
            geometry=page.evaluate("({field:document.querySelector('textarea[aria-label=\"Article Markdown\"]').getBoundingClientRect().toJSON(),tools:document.querySelector('.wiki-format-toolbar').getBoundingClientRect().toJSON(),header:document.querySelector('.wiki-toolbar').getBoundingClientRect().toJSON()})")
            self.assertGreaterEqual(geometry['header']['top'],20,geometry);self.assertGreaterEqual(geometry['field']['top'],geometry['tools']['bottom']-1,geometry);self.assertLessEqual(geometry['field']['bottom'],321,geometry)
            page.evaluate("delete visualViewport.height;delete visualViewport.offsetTop;visualViewport.dispatchEvent(new Event('resize'))")
            page.locator('.wiki-toolbar .workspace-more>summary').click();page.locator('.wiki-toolbar').get_by_role('button',name='Inbox',exact=True).click()
            expect(page.locator('#wiki-inbox')).to_be_visible();page.locator('#wiki-inbox>header').get_by_role('button',name='Close',exact=True).click()
            expect(editor).to_have_value('[[phone-target|Phone Target]]')
            self.assertEqual(self.errors,[]);browser.close()

    def test_upload_real_pdf_preview_pages_and_original_download_on_phone(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base,browser,context,page=self.start(pw)
            page.get_by_role('button',name='Edit',exact=True).click();page.locator('.wiki-toolbar .workspace-more>summary').click()
            page.get_by_role('button',name='Page settings',exact=True).click();settings=page.locator('#wiki-page-settings-dialog');settings.locator('.wiki-attachments>summary').click()
            raw=io.BytesIO();Image.new('RGB',(320,240),'white').save(raw,'PDF',save_all=True,append_images=[Image.new('RGB',(320,240),'purple')]);pdf=raw.getvalue()
            settings.get_by_label('Upload documents',exact=False).set_input_files({'name':'phone-reading.pdf','mimeType':'application/pdf','buffer':pdf})
            expect(settings.get_by_role('link',name='phone-reading.pdf',exact=True)).to_be_visible()
            # A controlled runner can advance the disabled document worker.
            # Other disposable servers may use their normal worker instead.
            processed=context.request.post(base+'/api/browser-fixture/process-wiki-document')
            if processed.status!=404:self.assertEqual(processed.status,200);self.assertTrue(processed.json()['processed'])
            settings.get_by_role('button',name='Preview document',exact=True).click();viewer=page.get_by_role('dialog',name='Document preview',exact=True)
            expect(viewer.get_by_text('Page 1 of 2',exact=True)).to_be_visible(timeout=30000)
            page.wait_for_function("document.querySelector('.wiki-pdf-page')?.naturalWidth>0")
            viewer.get_by_role('button',name='Next page',exact=True).click();expect(viewer.get_by_text('Page 2 of 2',exact=True)).to_be_visible()
            page.wait_for_function("document.querySelector('.wiki-pdf-page')?.complete && document.querySelector('.wiki-pdf-page').naturalWidth>0")
            page.set_viewport_size({'width':320,'height':320});expect(page.locator('html')).to_have_css('--mobile-viewport-height','320px')
            self.assertLessEqual(viewer.bounding_box()['height'],304)
            with page.expect_download() as download:viewer.get_by_role('link',name='Download original',exact=True).click()
            self.assertEqual(Path(download.value.path()).read_bytes(),pdf)
            viewer.get_by_role('button',name='Close preview',exact=True).click();expect(viewer).to_have_count(0)
            settings.get_by_role('button',name='Close',exact=True).click();expect(page.get_by_role('textbox',name='Article Markdown')).to_be_visible()
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),320);self.assertEqual(self.errors,[]);browser.close()
