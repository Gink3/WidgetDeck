"""Phone column navigation, focused editing and conservative board refresh."""
import os,secrets,unittest
from urllib.parse import urlparse,parse_qs
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'),'Requires disposable browser app')
class KanbanPhoneBrowserTests(unittest.TestCase):
    def test_columns_editing_comments_recovery_and_foreground_refresh(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base=os.environ['WORKSPACE_TEST_BASE_URL'];self.assertEqual(base,'http://127.0.0.1:8020')
            browser=pw.chromium.launch();context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,service_workers='block')
            self.assertEqual(context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'kanban-phone-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
            created=context.request.post(base+'/tools/kanban',form={'name':'Phone board'},max_redirects=0);self.assertEqual(created.status,302);board_id=parse_qs(urlparse(created.headers['location']).query)['board'][0]
            snapshot=context.request.get(base+'/api/tools/kanban/boards/'+board_id).json()['board'];cols=snapshot['columns']
            item=context.request.post(base+'/api/tools/kanban/boards/'+board_id+'/items',data={'title':'Phone task','notes':'Original notes','column_id':cols[0]['id']}).json()['item'];url=base+'/api/tools/kanban/items/'+str(item['id'])
            page=context.new_page();page.set_default_timeout(7000);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/tools/kanban?board='+board_id);page.wait_for_function('WidgetDeckRuntime.state.verified')
            expect(page.locator('.kanban-filters')).not_to_have_attribute('open','');expect(page.locator('.kanban-column:visible')).to_have_count(1)
            page.get_by_role('button',name='Next column',exact=True).tap();expect(page.locator('.kanban-column:visible')).to_have_attribute('data-column',str(cols[1]['id']))
            page.get_by_role('button',name='Previous column',exact=True).tap();page.get_by_role('button',name='Phone task',exact=False).tap()
            expect(page.locator('#close-detail')).to_be_focused();page.locator('#item-notes').fill('Phone edits')
            page.set_viewport_size({'width':390,'height':320});page.locator('#item-notes').focus()
            page.get_by_role('button',name='Save changes',exact=True).tap();expect(page.locator('#detail-status')).to_have_text('Changes saved.')
            page.locator('#item-column').select_option(str(cols[1]['id']));page.get_by_role('button',name='Save changes',exact=True).tap();expect(page.locator('#detail-status')).to_have_text('Changes saved.')
            page.set_viewport_size({'width':390,'height':844});page.locator('#item-comments-section>summary').tap();page.get_by_label('New comment',exact=True).fill('Phone comment');page.get_by_role('button',name='Add comment',exact=True).tap();expect(page.locator('#item-comments')).to_contain_text('Phone comment')
            page.locator('#item-history-section>summary').tap();expect(page.locator('#item-history')).to_contain_text('Notes changed')
            page.get_by_role('button',name='Close item details',exact=True).tap();expect(page.locator('.kanban-column:visible')).to_have_attribute('data-column',str(cols[1]['id']))
            # Dirty dialogs survive resume without GET/apply or duplicate writes.
            page.get_by_role('button',name='Add item to In Progress',exact=True).tap();dialog=page.locator('dialog[open]');dialog.get_by_label('Item title',exact=True).fill('Recover new phone task');dialog.get_by_label('Notes',exact=True).fill('Keep new task notes')
            page.evaluate("dispatchEvent(new CustomEvent('widgetdeck:resume',{detail:{recovered:true}}))");expect(page.locator('.resume-refresh')).to_contain_text('Keep your unsaved edits')
            page.evaluate("dispatchEvent(new Event('pagehide'))");page.once('dialog',lambda d:d.accept());page.reload();page.wait_for_function('WidgetDeckRuntime.state.verified')
            page.get_by_role('button',name='Add item to In Progress',exact=True).tap();dialog=page.locator('dialog[open]');recovery=dialog.locator('[data-draft-group=native-form]');recovery.locator(':scope>summary').tap();recovery.get_by_role('button',name='Restore draft',exact=True).tap();expect(dialog.get_by_label('Item title',exact=True)).to_have_value('Recover new phone task')
            dialog.get_by_role('button',name='Add item',exact=True).tap();page.wait_for_load_state('load');expect(page.get_by_role('button',name='Recover new phone task',exact=False)).to_be_visible();page.wait_for_function("Object.keys(localStorage).filter(k=>k.startsWith('widgetdeck.draft.v1.')).length===0")
            # A clean foreground event fetches fresh cards and retains the selected column.
            saved=context.request.get(url).json()['item'];self.assertEqual(saved['notes'],'Phone edits')
            self.assertEqual(context.request.patch(url,data={'title':'Changed elsewhere','notes':saved['notes'],'column_id':saved['column_id'],'revision':saved['revision']}).status,200)
            page.wait_for_function('WidgetDeckRuntime.state.verified')
            with page.expect_navigation():page.evaluate("dispatchEvent(new CustomEvent('widgetdeck:resume',{detail:{recovered:true}}))")
            expect(page.get_by_role('button',name='Changed elsewhere',exact=False)).to_be_visible();expect(page.locator('.kanban-column:visible')).to_have_count(1)
            page.set_viewport_size({'width':1440,'height':1000});expect(page.locator('.kanban-column:visible')).to_have_count(3)
            self.assertEqual(errors,[]);browser.close()
