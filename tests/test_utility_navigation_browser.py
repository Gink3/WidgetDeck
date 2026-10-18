import os
import secrets
import unittest
from browser_auth import auth_form


@unittest.skipUnless(os.environ.get('UTILITY_TEST_BASE_URL'),'Requires development deployment and Chromium')
class UtilityNavigationBrowserTests(unittest.TestCase):
    def test_search_categories_saved_order_and_mobile_menu(self):
        from playwright.sync_api import sync_playwright,expect
        base=os.environ['UTILITY_TEST_BASE_URL'];self.assertEqual(base,'http://127.0.0.1:8020')
        with sync_playwright() as pw:
            browser=pw.chromium.launch();context=browser.new_context(viewport={'width':375,'height':900})
            result=context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'menu-'+secrets.token_hex(5),'password':secrets.token_urlsafe(30)},max_redirects=0)
            self.assertEqual(result.status,302)
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/')
            page.evaluate("localStorage.setItem('dashboard.home.widget-order.v1',JSON.stringify(['frontline-command','wordle']))")
            page.reload()
            expect(page.locator('.card[data-category="Games"]').first).to_have_attribute('data-widget-id','frontline-command')
            page.locator('#utility-category').select_option('Data')
            expect(page.locator('.card:visible')).to_have_count(3)
            expect(page.get_by_role('combobox',name='Utilities',exact=True)).to_be_visible();expect(page.locator('#catalogue-filter-scope')).to_contain_text('Search, favourites and recent work include all categories')
            page.locator('#utility-search').fill('paint')
            expect(page.locator('.card:visible')).to_have_count(1)
            page.locator('#utility-search').fill('wiki');expect(page.locator('#home-search-results [role=option][data-utility=wiki]')).not_to_have_count(0)
            page.locator('#utility-search').fill('no-such-tool')
            expect(page.locator('#utility-results')).to_contain_text('No utilities found')
            page.get_by_text('Utilities',exact=True).click()
            page.locator('#utility-menu-search').fill('wiki')
            expect(page.locator('.utility-menu-group a:visible')).to_have_count(1)
            page.locator('.utility-menu-group a:visible').click()
            expect(page).to_have_url(base+'/tools/wiki/')
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),375)
            self.assertEqual(errors,[])
            context.close();browser.close()
