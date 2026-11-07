"""Board identity, two-row geometry and keyboard-safe compact filters."""
import os,secrets,unittest
from urllib.parse import urlparse,parse_qs
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'),'Requires disposable browser app')
class KanbanCompactControlsBrowserTests(unittest.TestCase):
    def test_compact_rows_filter_actions_and_labeled_board_at_all_sizes(self):
        from pathlib import Path
        from playwright.sync_api import sync_playwright,expect
        base=os.environ['WORKSPACE_TEST_BASE_URL']
        with sync_playwright() as pw:
            browser=pw.chromium.launch();context=browser.new_context(viewport={'width':1440,'height':1000},service_workers='block')
            self.assertEqual(context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'compact-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
            created=context.request.post(base+'/tools/kanban',form={'name':'Dashboard'},max_redirects=0)
            board_id=parse_qs(urlparse(created.headers['location']).query)['board'][0]
            board=context.request.get(base+'/api/tools/kanban/boards/'+board_id).json()['board']
            for title in ('Needle task','Other task'):self.assertEqual(context.request.post(base+'/api/tools/kanban/boards/'+board_id+'/items',data={'title':title,'column_id':board['columns'][0]['id']}).status,201)
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)));page.goto(base+created.headers['location'])
            expect(page.locator('#kanban-board-name')).to_have_text('Dashboard');expect(page.locator('#kanban-board-label')).to_have_text('Board')
            expect(page.locator('#kanban-board-name')).to_have_attribute('aria-describedby','kanban-board-label')
            columns=page.locator('.kanban-column:visible').first
            def compact(width):
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),width)
                self.assertLessEqual(columns.bounding_box()['y']-page.locator('main').bounding_box()['y'],120,(width,columns.bounding_box()))
            for width in (901,1050,1440,1920,2560,3669):
                page.set_viewport_size({'width':width,'height':1000})
                expect(page.locator('#kanban-search')).to_be_visible()
                a=page.locator('#kanban-search').bounding_box();b=page.locator('#effort-filter').bounding_box()
                self.assertAlmostEqual(a['y'],b['y'],delta=1);compact(width)
                page.locator('#kanban-search').fill('Needle');page.locator('#effort-filter').select_option('untagged')
                expect(page.get_by_role('button',name='Needle task',exact=False)).to_be_visible();expect(page.get_by_role('button',name='Other task',exact=False)).to_be_hidden();compact(width)
                page.locator('#clear-kanban-search').click();page.locator('#clear-effort-filter').click()
                if width==1440 and os.environ.get('MOBILE_HEADER_ARTIFACTS'):page.screenshot(path=str(Path(os.environ['MOBILE_HEADER_ARTIFACTS'])/'kanban-compact-1440.png'),full_page=True)
            for width in (320,360,375,719,720,820,900):
                page.set_viewport_size({'width':width,'height':850})
                expect(page.locator('.kanban-filters')).not_to_have_attribute('open','');compact(width)
                select=page.locator('#phone-kanban-column').bounding_box();summary=page.locator('.kanban-filters>summary').bounding_box();self.assertAlmostEqual(select['y'],summary['y'],delta=1)
                before=columns.bounding_box()['y'];page.locator('.kanban-filters>summary').click();expect(page.locator('#kanban-search')).to_be_visible()
                self.assertAlmostEqual(columns.bounding_box()['y'],before,delta=1)
                page.locator('#kanban-search').fill('Needle');page.locator('#effort-filter').select_option('untagged')
                expect(page.get_by_role('button',name='Other task',exact=False)).to_be_hidden()
                page.locator('#clear-kanban-search').click();page.locator('#clear-effort-filter').click();page.locator('#close-kanban-filters').click();expect(page.locator('.kanban-filters>summary')).to_be_focused()
                if width==375 and os.environ.get('MOBILE_HEADER_ARTIFACTS'):page.screenshot(path=str(Path(os.environ['MOBILE_HEADER_ARTIFACTS'])/'kanban-compact-375.png'),full_page=True)
            page.set_viewport_size({'width':375,'height':320});page.locator('.kanban-filters>summary').click()
            fields=page.locator('.kanban-filter-fields');expect(fields).to_be_visible()
            page.wait_for_function("document.querySelector('.kanban-filter-fields').getBoundingClientRect().bottom<=innerHeight")
            box=fields.bounding_box();self.assertGreaterEqual(box['y'],0);self.assertLessEqual(box['y']+box['height'],320)
            page.locator('#kanban-search').focus();page.keyboard.press('Escape');expect(fields).to_be_hidden();expect(page.locator('.kanban-filters>summary')).to_be_focused()
            # Large text and long board names can grow naturally without clipping.
            page.set_viewport_size({'width':360,'height':850});page.add_style_tag(content='body{font-size:28px!important}')
            page.locator('#kanban-board-name').evaluate("el=>el.textContent='A long board name for research and personal project planning'")
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),360)
            self.assertEqual(errors,[]);browser.close()
