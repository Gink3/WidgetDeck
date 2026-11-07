"""Word-length changes and surrender use the real persisted game/statistics."""
import os,secrets,unittest
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'),'Requires disposable app')
class TodoWordleBrowserTests(unittest.TestCase):
    def test_length_change_starts_game_and_only_counts_submitted_guesses(self):
        from playwright.sync_api import sync_playwright,expect
        base=os.environ['WORKSPACE_TEST_BASE_URL']
        with sync_playwright() as pw:
            browser=pw.chromium.launch();context=browser.new_context(viewport={'width':360,'height':800},service_workers='block')
            self.assertEqual(context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'word-length-'+secrets.token_hex(4),'password':secrets.token_urlsafe(32)},max_redirects=0).status,302)
            page=context.new_page();dialogs=[];page.on('dialog',lambda d:(dialogs.append(d.message),d.dismiss()))
            page.goto(base+'/tools/wordle');page.locator('#wordle-new').click()
            expect(page.locator('#wordle-status')).to_contain_text('0 of 6 guesses used')
            first=context.request.get(base+'/api/tools/wordle/game').json()['game']
            page.locator('#wordle-settings>summary').click();page.locator('#wordle-length').select_option('6')
            expect(page.locator('#wordle-guess')).to_have_attribute('maxlength','6')
            second=context.request.get(base+'/api/tools/wordle/game').json();self.assertNotEqual(first['id'],second['game']['id']);self.assertEqual(second['stats']['played'],0)
            # The curated answer pool excludes this valid guess, so it cannot win.
            page.locator('#wordle-settings>summary').click();page.locator('#wordle-play').focus();page.keyboard.type('abacus');page.keyboard.press('Enter')
            expect(page.locator('#wordle-status')).to_contain_text('1 of 6 guesses used')
            page.locator('#wordle-settings>summary').click();page.locator('#wordle-length').select_option('7')
            expect(page.locator('#wordle-guess')).to_have_attribute('maxlength','7')
            latest=context.request.get(base+'/api/tools/wordle/game').json();self.assertEqual(latest['game']['guesses'],[]);self.assertEqual(latest['stats']['played'],1);self.assertEqual(latest['stats']['wins'],0)
            self.assertEqual(dialogs,[])
            page.reload();expect(page.locator('#wordle-guess')).to_have_attribute('maxlength','7')
            page.locator('.wordle-controls>.workspace-more').last.locator('summary').click()
            page.get_by_role('button',name='Give up',exact=True).click()
            expect(page.locator('#wordle-status')).to_contain_text('The word was')
            state=context.request.get(base+'/api/tools/wordle/game').json()
            self.assertEqual(state['game']['status'],'lost');self.assertEqual(len(state['game']['answer']),7)
            self.assertEqual(state['stats']['played'],2)
            page.reload();expect(page.locator('#wordle-status')).to_contain_text('The word was')
            browser.close()
