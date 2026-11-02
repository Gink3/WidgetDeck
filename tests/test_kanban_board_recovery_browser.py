"""New-board drafts retain dynamic columns and clear only after native success."""
import os,secrets,unittest
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'),'Requires disposable browser app')
class KanbanBoardRecoveryBrowserTests(unittest.TestCase):
    def test_relaunch_owner_isolation_rejected_submit_and_success_receipt(self):
        from playwright.sync_api import sync_playwright,expect
        base=os.environ['WORKSPACE_TEST_BASE_URL'];self.assertEqual(base,'http://127.0.0.1:8020')
        with sync_playwright() as pw:
            browser=pw.chromium.launch();context=browser.new_context(viewport={'width':390,'height':844},service_workers='block')
            response=context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'board-draft-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0);self.assertEqual(response.status,302)
            cookies=context.cookies();page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));posts=[];page.on('request',lambda r:posts.append(r.url) if r.method=='POST' and '/tools/kanban' in r.url else None)
            def open_form():
                page.get_by_role('button',name='+ New board',exact=True).click();return page.locator('#new-kanban form')
            def restore():
                form=open_form();panel=form.locator('[data-draft-group=native-form]');panel.locator(':scope>summary').click();panel.get_by_role('button',name='Restore draft',exact=True).click();return form
            page.goto(base+'/tools/kanban');form=open_form();form.get_by_label('Board name').fill('Interrupted project')
            form.locator('[data-add-kanban-column]').click();form.locator('[data-add-kanban-column]').click();form.locator('.remove-field').last.click()
            names=['Ideas','Preparing','Review café','Finished']
            for i,name in enumerate(names):form.locator('[name=column_name]').nth(i).fill(name)
            page.evaluate("dispatchEvent(new Event('pagehide'))");page.once('dialog',lambda d:d.accept());page.reload();form=open_form();expect(form.get_by_label('Board name')).to_have_value('');expect(form.locator('[name=column_name]')).to_have_count(3)
            self.assertEqual(posts,[])
            # A different signed-in account in this browser cannot restore the draft.
            other=browser.new_context();self.assertEqual(other.request.post(base+'/register',form={**auth_form(other.request,base),'username':'other-board-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
            context.add_cookies(other.cookies());page.goto(base+'/tools/kanban');form=open_form();expect(form.locator('[data-draft-group=native-form]')).to_be_hidden();other.close()
            context.add_cookies(cookies);page.goto(base+'/tools/kanban');form=restore();expect(form.get_by_label('Board name')).to_have_value('Interrupted project');self.assertEqual(form.locator('[name=column_name]').evaluate_all('(fields)=>fields.map(f=>f.value)'),names)
            page.route('**/tools/kanban',lambda r:r.fulfill(status=503,body='Fixture rejected board creation') if r.request.method=='POST' else r.continue_())
            with page.expect_navigation():form.get_by_role('button',name='Create board',exact=True).click()
            page.unroute('**/tools/kanban');page.goto(base+'/tools/kanban');form=restore();expect(form.get_by_label('Board name')).to_have_value('Interrupted project')
            before=page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('widgetdeck.draft.v1.')).length")
            with page.expect_navigation():form.get_by_role('button',name='Create board',exact=True).click()
            expect(page.locator('#kanban-board-name')).to_have_text('Interrupted project');self.assertEqual(page.locator('.kanban-column > .campaign-section-heading > h2').all_text_contents(),names)
            # A receipt clears this editor and its restored slot; older independent copies remain.
            page.wait_for_function("count=>Object.keys(localStorage).filter(k=>k.startsWith('widgetdeck.draft.v1.')).length===count",arg=before-2)
            self.assertNotIn('_draft_ack',page.url);self.assertEqual(len(posts),2);self.assertEqual(errors,[]);browser.close()
