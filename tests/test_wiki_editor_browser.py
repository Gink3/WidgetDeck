from browser_auth import auth_form
"""Run with WIKI_FRONTEND_BUILD pointing to a built static/mindmaps directory."""
import os
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path

from flask import request, send_from_directory
from PIL import Image
from werkzeug.serving import make_server
from test_dashboard_tools import test_app


@unittest.skipUnless(os.environ.get('WIKI_FRONTEND_BUILD') or os.environ.get('WIKI_TEST_BASE_URL'), 'Requires built frontend and Playwright Chromium')
class WikiEditorBrowserTests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.content = '\n'.join(f'Line {i}: article content' for i in range(250))
        self.base = os.environ.get('WIKI_TEST_BASE_URL')
        if self.base:
            assert self.base == 'http://127.0.0.1:8020', 'Live tests are development-only'
        else:
            self.directory = tempfile.TemporaryDirectory()
            self.addCleanup(self.directory.cleanup)
            app = test_app(self.directory.name)

            @app.before_request
            def built_assets():
                if request.path.startswith('/static/mindmaps/'):
                    return send_from_directory(os.environ['WIKI_FRONTEND_BUILD'], request.path[len('/static/mindmaps/'):])

            self.client = app.test_client()
            self.client.post('/tools/wiki/api/pages', json={'title': 'Scroll test', 'content': self.content})
            self.server = make_server('127.0.0.1', 0, app, threaded=True)
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
            self.addCleanup(self.server.shutdown)
            self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch()
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page(viewport={'width': 1440, 'height': 1000})
        self.page.set_default_timeout(10000)
        if os.environ.get('WIKI_TEST_BASE_URL'):
            import secrets
            from types import SimpleNamespace
            result = self.page.request.post(self.base+'/register', form={**auth_form(self.page.request,self.base),
                'username': 'wiki-test-'+secrets.token_hex(5), 'password': secrets.token_urlsafe(30)}, max_redirects=0)
            self.assertEqual(result.status, 302)
            self.client = SimpleNamespace(post=lambda path, json: SimpleNamespace(
                json=self.page.request.post(self.base+path, data=json).json()))
            self.client.post('/tools/wiki/api/pages', json={'title': 'Scroll test', 'content': self.content})
        self.page.goto(self.base + '/tools/wiki/scroll-test?edit=1')
        self.editor = self.page.get_by_role('textbox', name='Article Markdown')
        self.editor.wait_for()

    def upload(self, captioned=False):
        data = BytesIO()
        Image.new('RGB', (4, 4)).save(data, format='PNG')
        if captioned:
            self.page.get_by_role('button', name='Insert', exact=True).click()
        with self.page.expect_file_chooser() as chooser:
            self.page.get_by_role('button', name='Captioned image' if captioned else 'Insert image', exact=not captioned).click()
        chooser.value.set_files({'name': 'sample.png', 'mimeType': 'image/png', 'buffer': data.getvalue()})

    def test_save_returns_to_library_in_every_editor_mode(self):
        from playwright.sync_api import expect
        if not os.environ.get('WIKI_TEST_BASE_URL'):
            from unittest.mock import patch
            # Reproduce the launcher redirect that used to reopen the editor.
            self.client.application.config['LAUNCHER_ENABLED'] = True
            recent = patch('dashboard.launcher.recent', return_value=[{'url': '/tools/wiki/scroll-test'}])
            recent.start()
            self.addCleanup(recent.stop)
        for mode in ('Edit', 'Split', 'Read'):
            with self.subTest(mode=mode):
                self.page.goto(self.base + '/tools/wiki/scroll-test?edit=1')
                editor = self.page.get_by_role('textbox', name='Article Markdown')
                content = 'Saved from ' + mode
                editor.fill(content)
                self.page.get_by_role('button', name=mode, exact=True).click()
                toolbar = self.page.locator('.wiki-toolbar')
                expect(toolbar.get_by_role('link', name='← Wiki', exact=True)).to_have_count(0)
                save = toolbar.get_by_role('button', name='Save', exact=True)
                expect(save).to_have_count(1)
                save.click()
                expect(self.page).to_have_url(self.base + '/tools/wiki?library=1')
                stored = self.page.request.get(self.base + '/tools/wiki/api/pages/scroll-test').json()['page']
                self.assertEqual(stored['content'], content)

    def test_library_entry_and_local_draft_return(self):
        from playwright.sync_api import expect
        self.page.route('**/api/pages/scroll-test', lambda route: route.fulfill(
            status=503, content_type='application/json', body='{"error":"Server unavailable"}')
            if route.request.method == 'PUT' else route.continue_())
        self.editor.fill('Draft preserved when returning to library')
        self.page.get_by_role('button', name='Wiki library', exact=True).click()
        expect(self.page).to_have_url(self.base + '/tools/wiki?library=1')
        self.page.goto(self.base + '/tools/wiki')
        expect(self.page.locator('#wiki-root')).to_have_attribute('data-page', 'library')
        self.page.goto(self.base + '/tools/wiki/scroll-test')
        expect(self.page.get_by_role('button', name='Read', exact=True)).to_have_class('selected')
        self.assertTrue(self.page.evaluate("Object.values(localStorage).some(value => value.includes('Draft preserved when returning to library'))"))

    def test_library_cards_and_shortcuts_open_reading_mode(self):
        from playwright.sync_api import expect
        self.page.goto(self.base + '/tools/wiki')
        card = self.page.locator('.wiki-page-card').filter(has=self.page.get_by_role('heading', name='Scroll test', exact=True))
        card.get_by_role('button', name='Pin Scroll test', exact=True).click()
        card.get_by_role('link', name='Scroll test', exact=True).click()
        expect(self.page.get_by_role('button', name='Read', exact=True)).to_have_class('selected')
        expect(self.page.get_by_role('textbox', name='Article Markdown')).to_have_count(0)
        self.page.get_by_role('button', name='Wiki library', exact=True).click()
        shortcuts = self.page.locator('.wiki-shortcut-pages')
        links = shortcuts.get_by_role('link', name='Scroll test', exact=True)
        expect(links).to_have_count(2)
        for href in links.evaluate_all('(links) => links.map(link => link.getAttribute("href"))'):
            self.assertNotIn('edit=1', href)
        links.first.click()
        expect(self.page.get_by_role('button', name='Read', exact=True)).to_have_class('selected')
        self.page.get_by_role('button', name='Edit', exact=True).click()
        expect(self.page.get_by_role('textbox', name='Article Markdown')).to_be_visible()

    def test_failed_save_keeps_editor_and_draft(self):
        from playwright.sync_api import expect
        self.page.route('**/api/pages/scroll-test', lambda route: route.fulfill(
            status=503, content_type='application/json', body='{"error":"Server unavailable"}')
            if route.request.method == 'PUT' else route.continue_())
        self.editor.fill('Keep this unsaved draft')
        self.page.locator('.wiki-toolbar').get_by_role('button', name='Save', exact=True).click()
        expect(self.page.get_by_role('alert')).to_contain_text('Server unavailable')
        expect(self.editor).to_have_value('Keep this unsaved draft')
        expect(self.page.locator('.wiki-toolbar').get_by_role('button', name='Save', exact=True)).to_be_enabled()
        self.assertIn('/tools/wiki/scroll-test', self.page.url)

    def test_infobox_rows_survive_pending_and_repeated_autosaves(self):
        content = ':::infobox\n| Field | Value |\n| --- | --- |\n| Author | First |\n:::\nAfter'
        pending = []
        self.page.route('**/api/pages/scroll-test', lambda route: pending.append(route)
                        if route.request.method == 'PUT' else route.continue_())
        self.editor.fill(content)
        self.page.wait_for_timeout(800)
        self.assertEqual(len(pending), 1)
        content = content.replace('\n:::', '\n|  |  |\n| Partial |\n:::')
        self.editor.fill(content)
        pending[0].continue_()
        self.page.unroute('**/api/pages/scroll-test')
        self.page.wait_for_function("""async (content) => {
          const response = await fetch('/tools/wiki/api/pages/scroll-test');
          return (await response.json()).page.content === content;
        }""", arg=content)
        self.assertEqual(self.editor.input_value(), content)
        self.page.goto(self.base+'/tools/wiki/scroll-test?edit=1')
        self.editor.wait_for()
        self.assertEqual(self.editor.input_value(), content)

    def test_table_format_and_autosave_preserve_caret_selection_and_viewport(self):
        content = self.content[:self.content.index('Line 25')] + '| A | B |\n| --- | --- |\n| Longer cell | xyz |\n' + self.content
        self.editor.fill(content)
        at = content.index('xyz') + 2
        self.editor.evaluate('(el, at) => { el.focus(); el.setSelectionRange(at, at); el.scrollTop = 350; }', at)
        top = self.editor.evaluate('el => el.scrollTop')
        self.page.get_by_role('button', name='Format table', exact=True).click()
        self.page.wait_for_timeout(100)
        state = self.editor.evaluate('el => ({value: el.value, at: el.selectionStart, end: el.selectionEnd, top: el.scrollTop})')
        self.assertEqual(state['at'], state['value'].index('xyz')+2)
        self.assertEqual(state['end'], state['at'])
        self.assertEqual(state['top'], top)
        self.editor.evaluate('el => { el.setSelectionRange(10, 25, "backward"); el.scrollTop = 350; }')
        self.page.wait_for_timeout(1000)
        state = self.editor.evaluate('el => ({at: el.selectionStart, end: el.selectionEnd, direction: el.selectionDirection, top: el.scrollTop})')
        self.assertEqual(state, {'at': 10, 'end': 25, 'direction': 'backward', 'top': 350})

    def test_saved_html_import_with_companion_folder_through_library(self):
        with tempfile.TemporaryDirectory() as folder:
            assets = Path(folder)/'story_files'
            assets.mkdir()
            Image.new('RGB', (4, 4), 'blue').save(assets/'photo.png')
            html = Path(folder)/'story.html'
            html.write_text('<html><title>Saved browser article</title><body><nav>Junk navigation</nav><article>'
                            '<h1>Saved browser article</h1><p>Readable article content kept completely offline.</p>'
                            '<img src="story_files/photo.png" alt="Offline photo"><script>alert(1)</script>'
                            '</article></body></html>')
            self.page.goto(self.base+'/tools/wiki?library=1')
            self.page.locator('.wiki-heading-actions .workspace-more summary').click()
            self.page.get_by_role('button', name='Import HTML', exact=True).click()
            self.page.get_by_label('Saved HTML file', exact=True).set_input_files(str(html))
            self.page.get_by_label('Companion images folder (optional)', exact=True).set_input_files(str(assets))
            self.page.get_by_role('button', name='Import saved page', exact=True).click()
            self.page.get_by_role('dialog', name='Import saved HTML').get_by_role('link', name='Saved browser article', exact=True).click()
            self.editor.wait_for()
            content = self.editor.input_value()
            self.assertIn('Readable article content', content)
            self.assertNotIn('Junk navigation', content)
            self.assertNotIn('alert(1)', content)
            url = content.split('![Offline photo](')[1].split(')')[0]
            self.assertEqual(self.page.request.get(self.base+url).status, 200)

    @unittest.skipUnless(os.environ.get('WIKI_TEST_BASE_URL'), 'Public URL check runs only against development')
    def test_public_url_import_through_library(self):
        self.page.goto(self.base+'/tools/wiki?library=1')
        self.page.locator('.wiki-heading-actions .workspace-more summary').click()
        self.page.get_by_role('button', name='Import URL', exact=True).click()
        self.page.get_by_label('Web page URL', exact=True).fill('https://example.com/')
        self.page.get_by_role('button', name='Import page', exact=True).click()
        self.page.get_by_role('dialog', name='Import web page').get_by_role('link', name='Example Domain', exact=True).wait_for(timeout=50000)
        self.page.get_by_role('dialog', name='Import web page').get_by_role('link', name='Example Domain', exact=True).click()
        self.page.get_by_role('button', name='Edit', exact=True).click()
        self.editor.wait_for()
        self.assertIn('Source: <https://example.com/>', self.editor.input_value())

    def test_image_library_tags_search_and_page_references_persist(self):
        output = BytesIO()
        Image.new('RGB', (4, 4), 'blue').save(output, format='PNG')
        response = self.page.request.post(self.base+'/tools/wiki/api/images', multipart={
            'image': {'name': 'catalog.png', 'mimeType': 'image/png', 'buffer': output.getvalue()}})
        self.assertEqual(response.status, 201)
        image = response.json()['image']
        self.client.post('/tools/wiki/api/pages', json={'title': 'Catalog reference', 'content': f"![photo]({image['url']})"})
        self.page.goto(self.base+'/tools/wiki?library=1')
        self.page.locator('.wiki-heading-actions .workspace-more summary').click()
        self.page.get_by_role('button', name='Image library', exact=True).click()
        dialog = self.page.get_by_role('dialog', name='Image library', exact=True)
        dialog.get_by_role('heading', name='catalog.png', exact=True).wait_for()
        self.assertEqual(dialog.get_by_role('link', name='Catalog reference', exact=True).count(), 1)
        dialog.get_by_label('Tags for catalog.png', exact=True).fill('reference, science')
        dialog.get_by_role('button', name='Save tags', exact=True).click()
        self.page.wait_for_function("""async () => {
          const r = await fetch('/tools/wiki/api/images?q=science');
          return (await r.json()).images.length === 1;
        }""")
        dialog.get_by_label('Search images', exact=True).fill('science')
        dialog.get_by_role('heading', name='catalog.png', exact=True).wait_for()
        dialog.get_by_role('button', name='Close image library', exact=True).click()
        self.page.reload()
        self.page.locator('.wiki-heading-actions .workspace-more summary').click()
        self.page.get_by_role('button', name='Image library', exact=True).click()
        self.assertEqual(dialog.get_by_label('Tags for catalog.png', exact=True).input_value(), 'reference, science')

    def test_image_insertion_preserves_scroll_and_caret(self):
        at = self.content.index('Line 20')
        self.editor.evaluate('(el, at) => { el.focus(); el.setSelectionRange(at, at); el.scrollTop = 300; }', at)
        before = self.editor.evaluate('el => el.scrollTop')
        self.upload()
        self.page.wait_for_function("""() => document.querySelector('textarea[aria-label="Article Markdown"]').value.includes('![sample.png]')""")
        self.page.wait_for_timeout(100)
        state = self.editor.evaluate('el => ({value: el.value, top: el.scrollTop, caret: el.selectionStart})')
        self.assertEqual(state['top'], before)
        self.assertTrue(state['value'].startswith(self.content[:at] + '![sample.png]('))
        self.assertEqual(state['caret'], state['value'].index(')', at) + 1)

    def test_upload_does_not_discard_edits_made_while_pending(self):
        pending = []
        self.page.route('**/api/images', lambda route: pending.append(route))
        self.editor.evaluate('el => { el.focus(); el.setSelectionRange(0, 0); }')
        self.upload()
        self.page.wait_for_timeout(100)
        self.assertEqual(len(pending), 1)
        self.editor.fill(self.content + '\nNew text during upload')
        pending[0].continue_()
        self.page.wait_for_function("""() => document.querySelector('textarea[aria-label="Article Markdown"]').value.includes('![sample.png]')""")
        self.assertIn('New text during upload', self.editor.input_value())
        self.assertIn('Line 249', self.editor.input_value())

    def test_captioned_image_picker_uploads_and_inserts_a_rendered_figure(self):
        at = self.content.index('Line 20')
        self.editor.evaluate('(el, at) => { el.focus(); el.setSelectionRange(at, at); el.scrollTop = 300; }', at)
        before = self.editor.evaluate('el => el.scrollTop')
        self.upload(captioned=True)
        self.page.wait_for_function("""() => document.querySelector('textarea[aria-label="Article Markdown"]').value.includes(':::figure right')""")
        value = self.editor.input_value()
        self.assertTrue(value.startswith(self.content[:at] + '\n\n:::figure right\n![sample.png](/tools/wiki/api/images/'))
        self.assertIn('\n\nCaption for this image.\n:::\n', value)
        self.assertNotIn('/path/to/image.jpg', value)
        self.assertEqual(self.editor.evaluate('el => el.scrollTop'), before)
        # Preview mode renders the existing right-aligned figure component.
        self.page.get_by_role('button', name='Read', exact=True).click()
        figure = self.page.locator('figure.wiki-figure')
        figure.wait_for(state='visible')
        self.assertEqual(figure.locator('figcaption').inner_text(), 'Caption for this image.')
        self.assertTrue(figure.locator('img').get_attribute('src').startswith('/tools/wiki/api/images/'))

    def test_cancel_captioned_picker_does_not_insert_a_placeholder(self):
        self.page.get_by_role('button', name='Insert', exact=True).click()
        with self.page.expect_file_chooser() as chooser:
            self.page.get_by_role('button', name='Captioned image').click()
        chooser.value.set_files([])
        self.assertEqual(self.editor.input_value(), self.content)
        # A subsequent normal image upload must still insert ordinary Markdown.
        self.upload()
        self.page.wait_for_function("""() => document.querySelector('textarea[aria-label="Article Markdown"]').value.includes('![sample.png]')""")
        self.assertNotIn(':::figure right', self.editor.input_value())

    def test_word_wrap_persists_across_pages_and_reload_without_changing_text(self):
        toggle = self.page.get_by_role('button', name='Word wrap', exact=True)
        self.assertEqual(toggle.get_attribute('aria-pressed'), 'true')
        self.assertEqual(self.editor.get_attribute('wrap'), 'soft')
        toggle.click()
        self.assertEqual(self.editor.get_attribute('wrap'), 'off')
        self.assertEqual(self.editor.input_value(), self.content)
        long_content = 'Long line ' + 'word ' * 300
        self.client.post('/tools/wiki/api/pages', json={'title': 'Second page', 'content': long_content})
        self.page.goto(self.base + '/tools/wiki/second-page?edit=1')
        self.editor.wait_for()
        self.assertEqual(self.editor.get_attribute('wrap'), 'off')
        self.assertTrue(self.editor.evaluate('el => el.scrollWidth > el.clientWidth'))
        self.page.reload()
        self.editor.wait_for()
        self.assertEqual(self.editor.get_attribute('wrap'), 'off')
        toggle.click()
        self.assertEqual(self.editor.get_attribute('wrap'), 'soft')
        self.assertTrue(self.editor.evaluate('el => el.scrollWidth <= el.clientWidth + 1'))
        self.assertEqual(self.editor.input_value(), long_content)
        self.page.reload()
        self.editor.wait_for()
        self.assertEqual(toggle.get_attribute('aria-pressed'), 'true')

    def test_word_wrap_still_toggles_when_storage_is_blocked(self):
        self.page.evaluate('() => { Storage.prototype.setItem = () => { throw new Error("Storage blocked"); }; }')
        toggle = self.page.get_by_role('button', name='Word wrap', exact=True)
        toggle.click()
        self.assertEqual(self.editor.get_attribute('wrap'), 'off')
        toggle.click()
        self.assertEqual(self.editor.get_attribute('wrap'), 'soft')
        self.assertEqual(self.editor.input_value(), self.content)

    def test_math_symbol_suggestions_accept_enter_and_escape(self):
        self.editor.fill('$')
        self.editor.press_sequentially('\\alp')
        suggestions = self.page.get_by_role('listbox', name='math suggestions')
        suggestions.wait_for(state='visible')
        self.assertIn('α', suggestions.inner_text())
        self.editor.press('Enter')
        self.assertEqual(self.editor.input_value(), '$\\alpha ')
        self.editor.press_sequentially('\\bet')
        suggestions.wait_for(state='visible')
        self.editor.press('Escape')
        suggestions.wait_for(state='hidden')
        self.assertEqual(self.editor.input_value(), '$\\alpha \\bet')

    def test_math_template_suggestions_accept_click_and_position_caret(self):
        self.editor.fill('$$\n')
        self.editor.press_sequentially('\\fr')
        self.page.get_by_role('option', name='\\frac — fraction', exact=True).click()
        self.assertEqual(self.editor.input_value(), '$$\n\\frac{}{}')
        self.assertEqual(self.editor.evaluate('el => el.selectionStart'), 9)
        self.editor.press_sequentially('1')
        self.assertEqual(self.editor.input_value(), '$$\n\\frac{1}{}')

    def test_table_tools_add_remove_and_undo_with_persisted_content(self):
        content='Before\n\n| Name | Value |\n| --- | --- |\n| Alpha | one |\n| Beta | two |\n\nAfter'
        self.editor.fill(content)
        def command(label,needle):
            self.editor.evaluate('(el,needle)=>{el.focus();const at=el.value.indexOf(needle);el.setSelectionRange(at,at)}',needle)
            self.page.get_by_role('button',name='Table tools',exact=True).click()
            self.page.get_by_role('button',name=label,exact=True).click()
        command('Insert row below','Alpha')
        self.assertEqual(len([line for line in self.editor.input_value().splitlines() if line.startswith('|')]),5)
        command('Insert column right','Alpha')
        self.assertIn('New column',self.editor.input_value())
        command('Delete column','New column')
        self.assertNotIn('New column',self.editor.input_value())
        command('Delete row','Beta')
        self.assertNotIn('Beta',self.editor.input_value())
        self.page.get_by_role('button',name='Undo',exact=True).click()
        self.assertIn('Beta',self.editor.input_value())
        expected=self.editor.input_value()
        self.assertTrue(expected.startswith('Before\n\n'));self.assertTrue(expected.endswith('\n\nAfter'))
        with self.page.expect_response(lambda r: r.request.method == 'PUT' and r.url.endswith('/api/pages/scroll-test')) as saved:
            self.editor.press('Control+s')
        self.assertEqual(saved.value.json()['page']['content'],expected)
        self.page.get_by_text('Saved to server',exact=True).first.wait_for()
        self.page.goto(self.base+'/tools/wiki/scroll-test?edit=1');self.editor.wait_for()
        self.assertEqual(self.editor.input_value(),expected)
