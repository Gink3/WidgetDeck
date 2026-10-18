import os
import secrets
import unittest
from browser_auth import auth_form

@unittest.skipUnless(os.environ.get('WORDLE_TEST_BASE_URL'),'Requires development deployment and Chromium')
class WordleBrowserTests(unittest.TestCase):
    def test_random_hard_game_validation_persistence_and_mobile_keyboard(self):
        from playwright.sync_api import sync_playwright
        base=os.environ['WORDLE_TEST_BASE_URL'];self.assertEqual(base,'http://127.0.0.1:8020')
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            context=browser.new_context(viewport={'width':375,'height':900})
            response=context.request.post(base+'/register',form={**auth_form(context.request,base),'username':'wordle-test-'+secrets.token_hex(5),'password':secrets.token_urlsafe(30)},max_redirects=0)
            self.assertEqual(response.status,302)
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/tools/wordle');page.get_by_text('Start a new game.',exact=True).wait_for()
            page.get_by_label('Hard mode for the next game',exact=True).check()
            page.get_by_role('button',name='New game',exact=True).click()
            page.get_by_text('0 of 6 guesses used · Hard mode.',exact=True).wait_for()
            page.get_by_label('Your guess',exact=True).fill('zzzzz')
            page.get_by_role('button',name='Submit guess',exact=True).click()
            page.get_by_text('Choose a word from the English five-letter dictionary.',exact=True).wait_for()
            page.get_by_label('Your guess',exact=True).fill('')
            for letter in 'CRANE':page.locator('#wordle-keyboard').get_by_role('button',name=letter,exact=True).click()
            page.get_by_role('button',name='Enter',exact=True).click()
            page.wait_for_function("document.querySelectorAll('#wordle-grid .correct, #wordle-grid .present, #wordle-grid .absent').length === 5")
            saved=context.request.get(base+'/api/tools/wordle/game').json()['game']
            self.assertEqual(saved['guesses'][0]['word'],'crane');self.assertTrue(saved['hard_mode'])
            page.reload()
            page.wait_for_function("document.querySelectorAll('#wordle-grid .correct, #wordle-grid .present, #wordle-grid .absent').length === 5")
            self.assertEqual(context.request.get(base+'/api/tools/wordle/game').json()['game'],saved)
            priority={'absent':1,'present':2,'correct':3};keys={}
            for guess in saved['guesses']:
                for letter,mark in zip(guess['word'],guess['marks']):
                    if priority[mark]>priority.get(keys.get(letter),0):keys[letter]=mark
            for letter,mark in keys.items():
                key=page.locator('#wordle-keyboard [data-letter="'+letter+'"]')
                self.assertEqual(key.get_attribute('class'),mark)
                if mark=='absent':
                    self.assertEqual(key.evaluate('(e)=>getComputedStyle(e).backgroundColor'),'rgb(25, 25, 29)')
                    self.assertEqual(key.evaluate('(e)=>getComputedStyle(e).color'),'rgb(170, 167, 178)')
            unused=page.locator('#wordle-keyboard [data-letter]:not([class]), #wordle-keyboard [data-letter][class=""]').first
            self.assertNotEqual(unused.evaluate('(e)=>getComputedStyle(e).backgroundColor'),'rgb(25, 25, 29)')
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),375)
            self.assertEqual(errors,[])
            page.goto(base+'/')
            menagerie=page.locator('[data-widget-id="menagerie"]')
            self.assertEqual(menagerie.get_attribute('href'),'https://menagerie.taylorkhomelab.com/')
            self.assertEqual(menagerie.get_attribute('target'),'_blank')
            context.route('https://menagerie.taylorkhomelab.com/**',lambda route:route.fulfill(status=200,content_type='text/html',body='Local link test'))
            with page.expect_popup() as popup:menagerie.click()
            popup.value.wait_for_load_state()
            self.assertTrue(popup.value.evaluate('window.opener === null'))
            context.close();browser.close()
