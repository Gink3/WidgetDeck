"""Phone navigation uses an accessible left hamburger and retains fallbacks."""
import os,secrets,unittest
from pathlib import Path
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'),'Requires disposable app')
class MobileHamburgerBrowserTests(unittest.TestCase):
    def test_left_hamburger_navigation_keyboard_breakpoints_and_no_js(self):
        from playwright.sync_api import sync_playwright,expect
        base=os.environ['WORKSPACE_TEST_BASE_URL']
        with sync_playwright() as pw:
            browser=pw.chromium.launch();context=browser.new_context(viewport={'width':375,'height':850},service_workers='block')
            response=context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'hamburger-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0);self.assertEqual(response.status,302)
            page=context.new_page();page.goto(base+'/');toggle=page.get_by_role('button',name='Menu',exact=True);nav=page.locator('#main-navigation')
            for width in (320,375,720):
                page.set_viewport_size({'width':width,'height':850});expect(toggle).to_be_visible();expect(nav).to_be_hidden()
                a=toggle.bounding_box();b=page.locator('.header-identity').bounding_box();self.assertLessEqual(a['x']+a['width'],b['x']);self.assertGreaterEqual(a['width'],44);self.assertGreaterEqual(a['height'],44)
                expect(toggle.locator('svg')).to_be_visible();self.assertEqual(toggle.inner_text(),'')
                toggle.click();expect(nav).to_be_visible();expect(toggle).to_have_attribute('aria-expanded','true')
                page.keyboard.press('Escape');expect(nav).to_be_hidden();expect(toggle).to_be_focused()
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
            if os.environ.get('MOBILE_HEADER_ARTIFACTS'):page.screenshot(path=str(Path(os.environ['MOBILE_HEADER_ARTIFACTS'])/'hamburger-left-720.png'),full_page=True)
            toggle.click();page.locator('#global-search-open').click();expect(page.locator('#global-search-dialog')).to_be_visible();page.keyboard.press('Escape')
            page.get_by_role('link',name='Settings',exact=True).click();expect(page).to_have_url(base+'/settings')
            for width in (820,1440):
                page.set_viewport_size({'width':width,'height':900});expect(toggle).to_be_hidden();expect(nav).to_be_visible()
            fallback=browser.new_context(java_script_enabled=False,storage_state=context.storage_state(),viewport={'width':320,'height':850});plain=fallback.new_page();plain.goto(base+'/');expect(plain.locator('#main-navigation')).to_be_visible();expect(plain.locator('#mobile-nav-toggle')).to_be_hidden()
            browser.close()
