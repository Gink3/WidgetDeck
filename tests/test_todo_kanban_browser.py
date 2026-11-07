"""Native item creation must not trigger an unsaved-navigation prompt."""
import os,secrets,unittest
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'),'Requires disposable app')
class TodoKanbanBrowserTests(unittest.TestCase):
    def test_native_creation_does_not_prompt_but_unsaved_drafts_do(self):
        from playwright.sync_api import sync_playwright,expect
        base=os.environ['WORKSPACE_TEST_BASE_URL']
        with sync_playwright() as pw:
            browser=pw.chromium.launch();context=browser.new_context(viewport={'width':375,'height':850},service_workers='block')
            self.assertEqual(context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'native-create-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
            board=context.request.post(base+'/tools/kanban',form={'name':'Native creation'},max_redirects=0)
            page=context.new_page();dialogs=[]
            page.on('dialog',lambda d:(dialogs.append(d.type),d.accept()))
            page.goto(base+board.headers['location'])
            page.get_by_role('button',name='Add item to To do',exact=True).click()
            form=page.locator('dialog[open] form');form.get_by_label('Item title',exact=True).fill('Created without prompt')
            form.get_by_label('Notes',exact=True).fill('Persist all notes')
            with page.expect_navigation():form.get_by_role('button',name='Add item',exact=True).click()
            expect(page.get_by_role('button',name='Created without prompt',exact=False)).to_be_visible()
            self.assertEqual(dialogs,[])
            page.get_by_role('button',name='Add item to To do',exact=True).click()
            page.locator('dialog[open] form').get_by_label('Item title',exact=True).fill('Unsaved draft')
            page.reload();self.assertIn('beforeunload',dialogs)
            browser.close()

    def test_older_done_is_hidden_recoverable_and_searchable(self):
        from datetime import datetime,timedelta,timezone
        from playwright.sync_api import sync_playwright,expect
        base=os.environ['WORKSPACE_TEST_BASE_URL']
        with sync_playwright() as pw:
            browser=pw.chromium.launch();context=browser.new_context(viewport={'width':375,'height':850},service_workers='block')
            self.assertEqual(context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'done-age-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
            created=context.request.post(base+'/tools/kanban',form={'name':'Ageing'},max_redirects=0)
            from urllib.parse import urlparse,parse_qs
            ident=parse_qs(urlparse(created.headers['location']).query)['board'][0]
            snapshot=context.request.get(base+'/api/tools/kanban/boards/'+ident).json()['board']
            item=context.request.post(base+'/api/tools/kanban/boards/'+ident+'/items',data={'title':'Old completion','column_id':snapshot['columns'][-1]['id']}).json()['item']
            self.assertTrue(item['completed_at'])
            page=context.new_page();page.goto(base+created.headers['location']);page.locator('#phone-kanban-column').select_option(str(item['column_id']))
            self.assertEqual(page.locator('.kanban-filters input[type=checkbox]').count(),0)
            card=page.locator('[data-item="'+str(item['id'])+'"]');expect(card).to_be_visible()
            page.clock.set_fixed_time(datetime.now(timezone.utc)+timedelta(days=8))
            page.locator('.kanban-filters>summary').click();page.locator('#kanban-search').fill('not found');page.locator('#kanban-search').fill('')
            expect(card).to_be_hidden();page.locator('.kanban-column-tools summary').click();page.locator('#show-older-done').click();expect(card).to_be_visible()
            page.locator('.kanban-column-tools summary').click();page.locator('#show-older-done').click();expect(card).to_be_hidden()
            page.locator('.kanban-filters>summary').click()
            page.locator('#kanban-search').fill('#'+str(item['id']));expect(card).to_be_visible()
            self.assertEqual(len(context.request.get(base+'/api/tools/kanban/boards/'+ident).json()['board']['items']),1)
            browser.close()

    def test_delete_board_requires_typed_name_and_keeps_other_boards(self):
        from playwright.sync_api import sync_playwright,expect
        base=os.environ['WORKSPACE_TEST_BASE_URL']
        with sync_playwright() as pw:
            browser=pw.chromium.launch();context=browser.new_context(viewport={'width':360,'height':800},service_workers='block')
            self.assertEqual(context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'board-delete-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
            context.request.post(base+'/tools/kanban',form={'name':'Keep this'},max_redirects=0)
            created=context.request.post(base+'/tools/kanban',form={'name':'Delete this'},max_redirects=0)
            page=context.new_page();dialogs=[];page.on('dialog',lambda d:(dialogs.append(d.message),d.accept()))
            page.goto(base+created.headers['location']);page.locator('.kanban-column-tools summary').click();page.locator('#delete-board-open').click()
            expect(page.locator('#delete-board-confirm')).to_be_disabled();page.locator('#delete-board-name').fill('delete this');expect(page.locator('#delete-board-confirm')).to_be_disabled()
            page.locator('#delete-board-name').fill('Delete this');page.locator('#delete-board-confirm').click()
            expect(page.locator('.workspace-library')).to_be_visible()
            expect(page.locator('.workspace-library')).to_contain_text('Keep this');expect(page.locator('.workspace-library')).not_to_contain_text('Delete this')
            self.assertEqual(dialogs,[]);self.assertEqual(len(context.request.get(base+'/api/tools/kanban/boards').json()['boards']),1)
            browser.close()
