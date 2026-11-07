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
