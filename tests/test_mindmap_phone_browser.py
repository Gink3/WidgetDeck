"""Phone touch actions operate on real saved graphs without keyboard shortcuts."""
import os,secrets,unittest,re
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'),'Requires disposable browser app')
class MindMapPhoneBrowserTests(unittest.TestCase):
    def test_touch_creation_copy_connection_drawer_and_saved_roundtrip(self):
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            base=os.environ['WORKSPACE_TEST_BASE_URL'];self.assertEqual(base,'http://127.0.0.1:8020')
            browser=pw.chromium.launch();context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,service_workers='block')
            self.assertEqual(context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'map-phone-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
            node=lambda id,title,x:{'id':id,'title':title,'x':x,'y':0,'width':180,'height':44,'type':'idea'}
            response=context.request.post(base+'/tools/mindmaps/api/maps',data={'name':'Touch map','nodes':[node('root-'+secrets.token_hex(4),'Root',0),node('other-'+secrets.token_hex(4),'Other',280)]});self.assertEqual(response.status,201);item=response.json()['map'];url=base+'/tools/mindmaps/api/maps/'+item['id']
            page=context.new_page();page.set_default_timeout(5000);errors=[];page.on('pageerror',lambda error:(errors.append(str(error))))
            page.goto(base+'/tools/mindmaps/'+item['id']);page.wait_for_function('WidgetDeckRuntime.state.verified && document.querySelector(".save-status")?.textContent==="Saved"',timeout=5000)
            expect(page.locator('.detail-panel')).not_to_be_visible();self.assertGreater(page.locator('.react-flow').bounding_box()['height'],500)
            page.get_by_text('Root',exact=True).tap();actions=page.get_by_label('Selection actions',exact=True)
            actions.get_by_role('button',name='Add child',exact=True).tap();expect(page.locator('.react-flow__node')).to_have_count(3)
            page.get_by_role('button',name='Details',exact=True).tap();panel=page.get_by_label('Map details',exact=True)
            panel.get_by_label('Title',exact=True).fill('Touch child');panel.get_by_label('Notes',exact=True).fill('Phone notes remain saved')
            page.set_viewport_size({'width':390,'height':360});panel.get_by_label('Notes',exact=True).focus();panel.get_by_role('button',name='Done',exact=True).tap();expect(panel).not_to_be_visible()
            expect(page.locator('.save-status')).to_be_visible();page.set_viewport_size({'width':390,'height':844})
            actions.get_by_role('button',name='Add sibling',exact=True).tap();expect(page.locator('.react-flow__node')).to_have_count(4)
            page.get_by_text('Root',exact=True).tap();actions.get_by_role('button',name='Collapse',exact=True).tap();expect(page.locator('.react-flow__node')).to_have_count(2)
            actions.get_by_role('button',name='Copy',exact=True).tap();actions.get_by_role('button',name='Paste',exact=True).tap()
            # Pasting includes hidden descendants and remaps node and edge IDs.
            expect(page.locator('.save-status')).to_have_text('Saved');saved=context.request.get(url).json()['map'];self.assertEqual(len(saved['nodes']),7);self.assertEqual(len(saved['edges']),4)
            page.get_by_text('Other',exact=True).tap();actions.get_by_role('button',name='Connect',exact=True).tap();page.get_by_label('Connection kind',exact=True).select_option('relation')
            with page.expect_response(lambda response:response.request.method=='PUT' and response.url==url):page.locator('.react-flow__node').filter(has_text='Root').first.tap()
            expect(page.locator('.mind-connect-prompt')).to_have_count(0)
            expect(page.locator('.save-status')).to_have_text('Saved');saved=context.request.get(url).json()['map'];self.assertEqual(len(saved['edges']),5);self.assertEqual(saved['edges'][-1]['kind'],'relation')
            page.locator('.editor-toolbar .workspace-more>summary').tap();page.get_by_role('button',name='Settings',exact=True).tap();expect(panel.locator('.settings-panel')).to_be_visible();panel.get_by_role('button',name='Done',exact=True).tap()
            # Fit and zoom controls are reachable native buttons; the graph survives reload.
            page.get_by_role('button',name=re.compile('^Fit view$',re.I)).tap();page.get_by_role('button',name=re.compile('^Zoom in$',re.I)).tap();page.get_by_role('button',name=re.compile('^Zoom out$',re.I)).tap()
            center="()=>{const element=document.querySelector('.react-flow'),rect=element.getBoundingClientRect(),matrix=new DOMMatrix(getComputedStyle(element.querySelector('.react-flow__viewport')).transform);return {x:(rect.width/2-matrix.e)/matrix.a,y:(rect.height/2-matrix.f)/matrix.a}}"
            for size in [{'width':320,'height':568},{'width':844,'height':390}]:
                before=page.evaluate(center);page.set_viewport_size(size);page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))');after=page.evaluate(center);self.assertAlmostEqual(before['x'],after['x'],delta=2);self.assertAlmostEqual(before['y'],after['y'],delta=2);self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),size['width']);expect(page.locator('.save-status')).to_be_visible()
            page.get_by_role('button',name=re.compile('^Fit view$',re.I)).tap();expect(page.locator('.react-flow__node:visible')).not_to_have_count(0);self.assertGreater(page.locator('.react-flow').bounding_box()['height'],230);page.screenshot(path='/artifacts/mind-phone-final.png');page.reload();expect(page.locator('.save-status')).to_have_text('Saved');self.assertEqual(len(context.request.get(url).json()['map']['nodes']),7)
            page.set_viewport_size({'width':1440,'height':1000});expect(page.locator('.detail-panel')).to_be_visible()
            page.get_by_role('button',name=re.compile('^Fit view$',re.I)).click()
            page.locator('.react-flow__node').filter(has_text='Root').first.click();page.locator('.react-flow__node').filter(has_text='Other').click(modifiers=['Control'])
            expect(page.locator('.react-flow__node.selected')).to_have_count(2)
            self.assertEqual(errors,[]);browser.close()
