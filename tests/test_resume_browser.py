"""Foreground GET/apply races never replace dirty, navigated or newer editor state."""
import os
import secrets
import unittest
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'),'Requires disposable browser app')
class ResumeBrowserTests(unittest.TestCase):
    def start(self,pw):
        base=os.environ['WORKSPACE_TEST_BASE_URL'];self.assertEqual(base,'http://127.0.0.1:8020')
        browser=pw.chromium.launch();context=browser.new_context(service_workers='block')
        self.assertEqual(context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'resume-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
        board=context.request.post(base+'/tools/kanban',form={'name':'Resume source'},max_redirects=0).headers['location'].split('board=')[1]
        column=context.request.get(base+'/api/tools/kanban/boards/'+board).json()['board']['columns'][0]['id']
        item=context.request.post(base+'/api/tools/kanban/boards/'+board+'/items',data={'title':'Initial','column_id':column}).json()['item']
        page=context.new_page();page.goto(base+'/');page.wait_for_function('WidgetDeckRuntime.state.verified')
        page.evaluate('''item=>{
          const host=document.createElement('section'),output=document.createElement('p');host.id='resume-fixture';output.id='resume-output';output.textContent='Initial';host.append(output);document.querySelector('main').append(host);
          window.currentId=item.id;window.currentVersion=0;window.userDirty=false;window.loadCount=0;window.applyCount=0;
          window.endpoint='/api/tools/kanban/items/'+item.id;
          window.registration=WidgetDeckRuntime.registerResume({id:'fixture',host,minAge:0,
            isDirty:()=>window.userDirty,identity:()=>window.currentId,version:()=>window.currentVersion,
            load:async({signal})=>{window.loadCount++;if(window.failLoad)throw new Error('Independent failed read');const response=await fetch(window.endpoint,{signal,cache:'no-store'});if(!response.ok)throw new Error('Read failed');return (await response.json()).item;},
            apply:item=>{window.applyCount++;document.querySelector('#resume-output').textContent=item.title;}
          });
        }''',item)
        return base,browser,context,page,item

    def test_clean_refresh_dirty_notice_and_explicit_retry_do_not_write(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base,browser,context,page,item=self.start(pw)
            changed=context.request.patch(base+'/api/tools/kanban/items/'+str(item['id']),data={'revision':0,'title':'Remote change','notes':item['notes'],'column_id':item['column_id']})
            self.assertEqual(changed.status,200)
            page.evaluate("dispatchEvent(new CustomEvent('widgetdeck:resume',{detail:{recovered:false}}))")
            expect(page.locator('#resume-output')).to_have_text('Remote change');self.assertEqual(page.evaluate('window.loadCount'),1)
            changed=context.request.patch(base+'/api/tools/kanban/items/'+str(item['id']),data={'revision':1,'title':'Latest saved data','notes':item['notes'],'column_id':item['column_id']})
            self.assertEqual(changed.status,200)
            page.evaluate("window.userDirty=true;for(let i=0;i<3;i++)dispatchEvent(new CustomEvent('widgetdeck:resume',{detail:{recovered:true}}))")
            expect(page.locator('.resume-refresh')).to_contain_text('Keep your unsaved edits')
            self.assertEqual(page.evaluate('window.loadCount'),1);expect(page.locator('#resume-output')).to_have_text('Remote change')
            page.evaluate('window.userDirty=false');page.get_by_role('button',name='Refresh saved data',exact=True).click()
            expect(page.locator('#resume-output')).to_have_text('Latest saved data');self.assertEqual(page.evaluate('window.loadCount'),2)
            self.assertEqual(context.request.get(base+'/api/tools/kanban/items/'+str(item['id'])).json()['item']['revision'],2)
            browser.close()

    def test_pending_resume_reads_coalesce_and_discard_dirty_identity_or_version_races(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base,browser,context,page,item=self.start(pw);pending=[]
            page.route('**/api/tools/kanban/items/*',lambda route:pending.append(route))
            for count,change in enumerate(['window.userDirty=true','window.currentId="different"','window.currentVersion=1'],1):
                with page.expect_request(lambda request:'/api/tools/kanban/items/' in request.url):
                    page.evaluate('''id=>{window.userDirty=false;window.currentId=id;window.currentVersion=0;registration.refresh(true);void 0;}''',item['id'])
                page.wait_for_function('window.loadCount === '+str(count))
                page.evaluate('registration.refresh(true);registration.refresh(true);void 0')
                self.assertEqual(page.evaluate('window.loadCount'),count)
                page.evaluate(change);pending.pop(0).continue_()
                expect(page.locator('.resume-refresh')).to_contain_text('Newer edits or navigation were kept')
                self.assertEqual(page.evaluate('window.applyCount'),0);expect(page.locator('#resume-output')).to_have_text('Initial')
            browser.close()

    def test_failed_reads_retry_and_account_change_cancels_pending_apply(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base,browser,context,page,item=self.start(pw)
            page.evaluate('window.failLoad=true;registration.refresh(true);void 0')
            expect(page.locator('.resume-refresh')).to_contain_text('Could not refresh')
            page.evaluate('window.failLoad=false;registration.refresh(true);void 0')
            page.wait_for_function('window.applyCount===1')
            pending=[];page.route('**/api/tools/kanban/items/*',lambda route:pending.append(route))
            with page.expect_request(lambda request:'/api/tools/kanban/items/' in request.url):
                page.evaluate('registration.refresh(true);void 0')
            page.evaluate("dispatchEvent(new Event('widgetdeck:account-changed'));document.querySelector('#resume-output').textContent='Keep current work'")
            if pending:pending[0].abort()
            expect(page.locator('#resume-output')).to_have_text('Keep current work');self.assertEqual(page.evaluate('window.applyCount'),1)
            browser.close()

    def test_explicit_refresh_does_not_repeat_a_synchronous_resume_apply(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base,browser,context,page,item=self.start(pw)
            page.evaluate('''()=>{
              window.applyCount=0;window.userDirty=true;
              window.registration=WidgetDeckRuntime.registerResume({id:'fixture',host:document.querySelector('#resume-fixture'),minAge:0,
                load:()=>null,apply:()=>window.applyCount++,isDirty:()=>window.userDirty});
              dispatchEvent(new CustomEvent('widgetdeck:resume'));window.userDirty=false;
            }''')
            page.get_by_role('button',name='Refresh saved data',exact=True).click()
            page.wait_for_function('window.applyCount>0')
            page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            self.assertEqual(page.evaluate('window.applyCount'),1);browser.close()
