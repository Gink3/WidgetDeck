from browser_auth import auth_form
"""Kanban workflows in Chromium; optionally run on disposable local-dev accounts."""
import os
import secrets
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlparse

from test_dashboard_tools import test_app
from werkzeug.serving import make_server


class KanbanBrowserTests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.base = os.environ.get('KANBAN_TEST_BASE_URL')
        if self.base:
            assert self.base == 'http://127.0.0.1:8020', 'Live tests are development-only'
        else:
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            app = test_app(directory.name)
            server = make_server('127.0.0.1', 0, app, threaded=True)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.shutdown)
            self.base = f'http://127.0.0.1:{server.server_port}'
        pw = sync_playwright().start()
        self.addCleanup(pw.stop)
        browser = pw.chromium.launch()
        self.addCleanup(browser.close)
        self.context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(7000)
        self.http = self.context.request
        if os.environ.get('KANBAN_TEST_BASE_URL'):
            result = self.http.post(self.base+'/register', form={**auth_form(self.http,self.base),'username': 'kanban-test-'+secrets.token_hex(5),
                                    'password': secrets.token_urlsafe(30)}, max_redirects=0)
            self.assertEqual(result.status, 302)
        self.boards = []
        for name in ['Source', 'Destination']:
            result = self.http.post(self.base+'/tools/kanban', form={'name': name}, max_redirects=0)
            self.assertEqual(result.status, 302)
            ident = int(parse_qs(urlparse(result.headers['location']).query)['board'][0])
            snapshot = self.http.get(self.base+f'/api/tools/kanban/boards/{ident}').json()['board']
            self.boards.append(snapshot)
        source = self.boards[0]
        result = self.http.post(self.base+f"/api/tools/kanban/boards/{source['id']}/items",
                               data={'title': 'Transfer me', 'notes': 'Original notes', 'column_id': source['columns'][0]['id']})
        self.assertEqual(result.status, 201)
        self.item = result.json()['item']
        self.page.goto(self.base+f"/tools/kanban?board={source['id']}")
        self.page.get_by_role('button', name='Transfer me').click()
        self.page.locator('#item-title').wait_for(state='visible')

    def destination(self):
        self.page.get_by_label('Destination board', exact=True).select_option(str(self.boards[1]['id']))
        self.page.wait_for_function("!document.querySelector('#transfer-column').disabled")

    def test_transfer_through_panel_persists_identity_and_history(self):
        self.destination()
        self.page.get_by_role('button', name='Move item', exact=True).click()
        self.page.wait_for_function("document.querySelector('#kanban-detail').hidden")
        self.assertEqual(self.page.locator(f"[data-item='{self.item['id']}']").count(), 0)
        item = self.http.get(self.base+f"/api/tools/kanban/items/{self.item['id']}").json()['item']
        self.assertEqual(item['board_id'], self.boards[1]['id'])
        self.assertEqual(item['notes'], 'Original notes')
        self.assertEqual(item['created_at'], self.item['created_at'])
        self.assertEqual(item['history'][0]['action'], 'transferred')
        self.page.reload()
        self.assertEqual(self.page.locator(f"[data-item='{self.item['id']}']").count(), 0)
        self.page.goto(self.base+f"/tools/kanban?board={self.boards[1]['id']}")
        self.page.get_by_role('button', name='Transfer me').click()
        self.page.locator('#item-history-section > summary').click()
        self.page.locator('#item-history strong').filter(has_text='Board changed').first.wait_for()
        self.page.locator('#item-history summary').filter(has_text='Board changed').click()
        self.assertIn('Source', self.page.locator('#item-history').inner_text())
        self.assertIn('Destination', self.page.locator('#item-history').inner_text())

    def test_unsaved_changes_and_conflicts_retain_card_and_draft(self):
        self.destination()
        self.page.locator('#item-notes').fill('Unsaved draft')
        self.page.get_by_role('button', name='Move item', exact=True).click()
        self.assertIn('Save the item', self.page.locator('#detail-status').inner_text())
        self.assertEqual(self.page.locator('#item-notes').input_value(), 'Unsaved draft')
        self.page.locator('#item-notes').fill('Original notes')
        result = self.http.patch(self.base+f"/api/tools/kanban/items/{self.item['id']}",
                                data={'title': 'Changed elsewhere', 'notes': 'Original notes',
                                      'column_id': self.item['column_id'], 'revision': self.item['revision']})
        self.assertEqual(result.status, 200)
        self.page.get_by_role('button', name='Move item', exact=True).click()
        self.page.get_by_text('This item changed in another window.', exact=False).wait_for()
        self.assertEqual(self.page.locator(f"[data-item='{self.item['id']}']").count(), 1)
        self.assertEqual(self.page.locator('#item-notes').input_value(), 'Original notes')

    def test_column_reorder_mode_keyboard_and_drag_persist_cards(self):
        original = [str(c['id']) for c in self.boards[0]['columns']]
        self.page.locator('.kanban-column-tools .workspace-more summary').click()
        self.page.get_by_role('button', name='Reorder columns', exact=True).click()
        self.page.get_by_role('button', name='Move To do column right', exact=True).click()
        self.page.wait_for_function("document.querySelector('#kanban-status').textContent === 'Column order saved.'")
        self.assertEqual(self.page.locator('.kanban-column').evaluate_all('(els)=>els.map(el=>el.dataset.column)'),
                         [original[1], original[0], original[2]])
        self.page.locator(f'[data-column="{original[2]}"]').drag_to(
            self.page.locator(f'[data-column="{original[1]}"]'), target_position={'x': 5, 'y': 20})
        self.page.wait_for_function('(id)=>document.querySelector(".kanban-column").dataset.column === id', arg=original[2])
        self.page.get_by_role('button', name='Finish reordering', exact=True).click()
        self.page.reload()
        self.assertEqual(self.page.locator('.kanban-column').evaluate_all('(els)=>els.map(el=>el.dataset.column)'),
                         [original[2], original[1], original[0]])
        self.assertEqual(self.page.locator(f'[data-column="{original[0]}"] [data-item="{self.item["id"]}"]').count(), 1)

    def test_board_columns_fit_desktop_and_mobile_scroll_stays_inside_board(self):
        self.page.get_by_role('button', name='Close item details', exact=True).click()
        for width in [1440, 1100, 800, 375]:
            self.page.set_viewport_size({'width': width, 'height': 1000})
            sizes = self.page.evaluate('''() => {
              const board = document.querySelector('.kanban-board');
              return {page: document.documentElement.scrollWidth, viewport: innerWidth,
                board: board.clientWidth, content: board.scrollWidth,
                cards: [...board.querySelectorAll('.kanban-card')].map(card => ({
                  width: card.getBoundingClientRect().width,
                  column: card.closest('.kanban-column').getBoundingClientRect().width}))};
            }''')
            self.assertLessEqual(sizes['page'], sizes['viewport']+1)
            if width >= 800:
                self.assertLessEqual(sizes['content'], sizes['board']+1)
            for card in sizes['cards']:
                self.assertLessEqual(card['width'], card['column'])

    def test_cancel_restore_and_confirmed_deletion(self):
        self.page.get_by_role('button', name='Cancel item', exact=True).click()
        self.page.get_by_role('button', name='Restore item', exact=True).wait_for()
        card = self.page.locator(f'[data-item="{self.item["id"]}"]')
        self.assertIn('is-cancelled', card.get_attribute('class'))
        self.page.reload()
        self.page.get_by_role('button', name='Transfer me').click()
        self.page.get_by_role('button', name='Restore item', exact=True).click()
        self.page.get_by_role('button', name='Cancel item', exact=True).wait_for()
        self.assertNotIn('is-cancelled', card.get_attribute('class'))
        self.page.once('dialog', lambda dialog: dialog.dismiss())
        self.page.get_by_role('button', name='Delete item…', exact=True).click()
        self.assertEqual(card.count(), 1)
        self.page.once('dialog', lambda dialog: dialog.accept())
        self.page.get_by_role('button', name='Delete item…', exact=True).click()
        card.wait_for(state='detached')
        self.assertEqual(self.http.get(self.base+f"/api/tools/kanban/items/{self.item['id']}").status, 404)

    def test_search_by_number_and_title_includes_cancelled_done_and_preserves_order(self):
        source = self.boards[0]
        self.http.post(self.base+f"/api/tools/kanban/boards/{source['id']}/items",
                       data={'title': 'Another task', 'column_id': source['columns'][0]['id']})
        self.http.patch(self.base+f"/api/tools/kanban/items/{self.item['id']}",
                        data={'title': self.item['title'], 'notes': self.item['notes'],
                              'column_id': source['columns'][2]['id'], 'revision': 0})
        self.http.post(self.base+f"/api/tools/kanban/items/{self.item['id']}/cancel", data={'revision': 1})
        self.page.reload()
        before = self.http.get(self.base+f"/api/tools/kanban/boards/{source['id']}").json()['board']['items']
        search = self.page.get_by_label('Search this board', exact=True)
        for query in [f"#{self.item['id']}", 'tRaNsFeR']:
            search.fill(query)
            self.assertEqual(self.page.locator('.kanban-card:visible').count(), 1)
            self.assertIn('Cancelled', self.page.locator('.kanban-card:visible').inner_text())
            self.assertEqual(self.page.locator('.kanban-card:visible').get_attribute('draggable'), 'false')
        search.fill('nothing matches this')
        self.assertEqual(self.page.locator('.kanban-card:visible').count(), 0)
        self.page.get_by_role('button', name='Clear search', exact=True).click()
        self.assertEqual(self.page.locator('.kanban-card:visible').count(), 2)
        after = self.http.get(self.base+f"/api/tools/kanban/boards/{source['id']}").json()['board']['items']
        self.assertEqual(after, before)

    def test_manage_columns_preserves_cards_and_themed_controls(self):
        self.page.locator('.kanban-column-tools .workspace-more summary').click()
        self.page.get_by_role('button',name='Manage columns',exact=True).click()
        self.page.get_by_label('New column name',exact=True).fill('Review')
        with self.page.expect_navigation():
            self.page.get_by_role('button',name='Add column',exact=True).click()
        board=self.http.get(self.base+f"/api/tools/kanban/boards/{self.boards[0]['id']}").json()['board']
        review=board['columns'][-1]
        self.assertEqual(review['name'],'Review')
        self.http.post(self.base+f"/api/tools/kanban/items/{self.item['id']}/move",data={'column_id':review['id'],'revision':self.item['revision']})
        self.page.reload()
        self.page.locator('.kanban-column-tools .workspace-more summary').click()
        self.page.get_by_role('button',name='Manage columns',exact=True).click()
        self.page.get_by_label('Column to remove',exact=True).select_option(str(review['id']))
        self.page.get_by_role('button',name='Remove column',exact=True).click()
        self.page.get_by_text('Choose a destination for all cards before removing a nonempty column.',exact=True).wait_for()
        self.page.get_by_label('Move remaining cards to',exact=True).select_option(str(board['columns'][0]['id']))
        with self.page.expect_navigation():
            self.page.get_by_role('button',name='Remove column',exact=True).click()
        after=self.http.get(self.base+f"/api/tools/kanban/items/{self.item['id']}").json()['item']
        self.assertEqual(after['column_id'],board['columns'][0]['id']);self.assertEqual(after['notes'],'Original notes')
        color=self.page.locator('#manage-columns').evaluate('(e)=>getComputedStyle(e).backgroundColor')
        self.assertNotIn(color,['rgb(255, 255, 255)','rgb(239, 239, 239)'])

    def test_comments_are_plain_text_and_preserve_unsaved_notes(self):
        self.page.locator('#item-notes').fill('Draft notes preserved')
        comments = self.page.locator('#item-comments-section')
        self.assertFalse(comments.evaluate('(el) => el.open'))
        self.page.set_viewport_size({'width':375,'height':900})
        mobile = self.page.evaluate('''() => ({page: document.documentElement.scrollWidth, viewport: innerWidth,
          width: document.querySelector('.kanban-detail').getBoundingClientRect().width})''')
        self.assertLessEqual(mobile['page'], mobile['viewport']+1)
        self.assertLessEqual(mobile['width'], mobile['viewport'])
        comments.locator('summary').focus()
        self.page.keyboard.press('Enter')
        self.assertTrue(comments.evaluate('(el) => el.open'))
        marker='<img src=x onerror="window.__commentAudit=1">'
        self.page.get_by_label('New comment',exact=True).fill(marker)
        self.page.get_by_role('button',name='Add comment',exact=True).click()
        self.page.get_by_text('Comment added.',exact=True).wait_for()
        self.assertEqual(self.page.locator('#item-notes').input_value(),'Draft notes preserved')
        self.assertEqual(self.page.locator('#item-comments img').count(),0)
        self.assertFalse(self.page.evaluate('Boolean(window.__commentAudit)'))
        self.assertEqual(self.page.locator('#item-comments p').inner_text(),marker)
        self.page.get_by_role('button',name='Save changes',exact=True).click()
        self.page.wait_for_function("document.querySelector('#save-item').disabled")
        self.page.get_by_role('button',name='Close item details',exact=True).click()
        self.page.reload()
        self.page.locator(f"[data-item='{self.item['id']}'] .kanban-open").click()
        self.page.locator('#item-comments-section > summary').click()
        self.page.locator('#item-comments p').wait_for()
        self.assertEqual(self.page.locator('#item-comments p').inner_text(),marker)

    def test_issue_links_open_the_target_and_cycles_are_rejected(self):
        dest=self.boards[1]
        target=self.http.post(self.base+f"/api/tools/kanban/boards/{dest['id']}/items",data={'title':'Prerequisite','column_id':dest['columns'][0]['id']}).json()['item']
        self.page.locator('#item-links-section > summary').click()
        self.page.get_by_label('Other item number',exact=True).fill(str(target['id']))
        self.page.get_by_role('button',name='Add link',exact=True).click()
        self.page.get_by_text('Links saved.',exact=True).wait_for()
        link=self.page.locator('#item-links a');self.assertIn('Depends on',link.inner_text())
        link.click()
        self.page.wait_for_function("!document.querySelector('#item-edit-form').hidden")
        self.assertEqual(self.page.locator('#item-title').input_value(),'Prerequisite')
        self.page.locator('#item-links-section > summary').click()
        self.page.get_by_label('Other item number',exact=True).fill(str(self.item['id']))
        self.page.get_by_role('button',name='Add link',exact=True).click()
        self.page.get_by_text('Dependencies cannot form a cycle.',exact=True).wait_for()

    def test_column_manager_respects_unsaved_comment_drafts(self):
        self.page.locator('#item-comments-section > summary').click()
        self.page.get_by_label('New comment',exact=True).fill('Unsaved comment')
        self.page.once('dialog',lambda dialog:dialog.dismiss())
        self.page.locator('.kanban-column-tools .workspace-more summary').click()
        self.page.get_by_role('button',name='Manage columns',exact=True).click()
        self.assertFalse(self.page.locator('#column-manager').evaluate('(el)=>el.open'))
        self.assertEqual(self.page.get_by_label('New comment',exact=True).input_value(),'Unsaved comment')
        self.page.once('dialog',lambda dialog:dialog.accept())
        self.page.locator('.kanban-column-tools .workspace-more summary').click()
        self.page.get_by_role('button',name='Manage columns',exact=True).click()
        self.assertTrue(self.page.locator('#column-manager').evaluate('(el)=>el.open'))
        self.assertEqual(self.page.get_by_label('New comment',exact=True).input_value(),'')


    def test_efforts_create_assign_filter_clear_and_cross_board_links(self):
        self.page.get_by_role('button', name='Close item details', exact=True).click()
        self.page.locator('.kanban-column-tools .workspace-more summary').click()
        self.page.get_by_role('button', name='Manage efforts', exact=True).click()
        self.page.get_by_label('New effort name', exact=True).fill('MCP and wiki RAG')
        with self.page.expect_navigation():
            self.page.get_by_role('button', name='Create effort', exact=True).click()
        self.page.get_by_role('button', name='Transfer me').click()
        self.page.locator('#item-metadata-section > summary').click()
        self.page.get_by_label('MCP and wiki RAG', exact=True).check()
        self.page.get_by_text('Efforts saved.', exact=True).wait_for()
        self.assertEqual(self.page.locator('.effort-badge').inner_text(), 'MCP and wiki RAG')
        self.page.get_by_role('button', name='Close item details', exact=True).click()
        self.page.get_by_label('Effort', exact=True).select_option(label='Untagged')
        self.assertFalse(self.page.locator(f'[data-item="{self.item["id"]}"]').is_visible())
        self.page.get_by_role('button', name='Clear effort filter', exact=True).click()
        self.assertTrue(self.page.locator(f'[data-item="{self.item["id"]}"]').is_visible())
        self.page.get_by_label('Effort', exact=True).select_option(label='MCP and wiki RAG')
        self.page.locator('#effort-related summary').click()
        self.page.locator('#effort-related-items a').wait_for()
        self.assertIn('Transfer me',self.page.locator('#effort-related-items').inner_text())
        self.assertTrue(self.page.locator('[data-reorder="up"]').is_disabled())
        self.page.reload()
        self.assertEqual(self.page.get_by_label('Effort', exact=True).locator('option:checked').inner_text(),'MCP and wiki RAG')
        self.page.set_viewport_size({'width':375,'height':900})
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),376)

    def test_effort_manager_rename_remove_and_draft_protection(self):
        effort=self.http.post(self.base+'/api/tools/kanban/efforts',data={'name':'Old effort'}).json()['effort']
        self.http.put(self.base+f'/api/tools/kanban/items/{self.item["id"]}/efforts',data={'effort_ids':[effort['id']],'revision':0})
        self.page.reload()
        self.page.get_by_role('button',name='Transfer me').click()
        self.page.locator('#item-metadata-section > summary').click()
        self.page.locator('#item-notes').fill('Keep this draft')
        self.page.get_by_label('Old effort',exact=True).click()
        self.page.get_by_text('Save your item edits before changing efforts.',exact=True).wait_for()
        self.assertTrue(self.page.get_by_label('Old effort',exact=True).is_checked())
        self.assertEqual(self.page.locator('#item-notes').input_value(),'Keep this draft')
        self.page.locator('#item-notes').fill('Original notes')
        self.page.get_by_role('button',name='Close item details',exact=True).click()
        self.page.locator('.kanban-column-tools .workspace-more summary').click()
        self.page.get_by_role('button',name='Manage efforts',exact=True).click()
        self.page.get_by_label('Existing effort',exact=True).select_option(str(effort['id']))
        self.page.get_by_label('Effort name',exact=True).fill('Renamed effort')
        with self.page.expect_navigation():self.page.get_by_role('button',name='Rename effort',exact=True).click()
        self.assertEqual(self.page.locator('.effort-badge').inner_text(),'Renamed effort')
        self.page.locator('.kanban-column-tools .workspace-more summary').click()
        self.page.get_by_role('button',name='Manage efforts',exact=True).click()
        self.page.get_by_label('Existing effort',exact=True).select_option(str(effort['id']))
        self.page.once('dialog',lambda dialog:dialog.accept())
        with self.page.expect_navigation():self.page.get_by_role('button',name='Remove effort…',exact=True).click()
        self.assertEqual(self.page.locator('.effort-badge').count(),0)
        self.assertEqual(self.page.locator('.kanban-card').count(),1)

    def test_column_add_dialog_cancels_and_creates_in_selected_column(self):
        from playwright.sync_api import expect
        page=self.page
        page.get_by_role('button',name='Close item details',exact=True).click()
        page.get_by_role('button',name='Add item to In Progress',exact=True).click()
        dialog=page.get_by_role('dialog',name='Add item to In Progress',exact=True)
        expect(dialog).to_be_visible()
        dialog.get_by_role('button',name='Cancel',exact=True).click()
        expect(dialog).not_to_be_visible()
        page.get_by_role('button',name='Add item to In Progress',exact=True).click()
        dialog.get_by_role('textbox',name='Item title',exact=True).fill('Created through dialog')
        dialog.get_by_role('textbox',name='Notes',exact=True).fill('Dialog notes')
        with page.expect_navigation():dialog.get_by_role('button',name='Add item',exact=True).click()
        column=page.locator(f'[data-column="{self.boards[0]["columns"][1]["id"]}"]')
        expect(column.get_by_role('button',name='Created through dialog',exact=False)).to_be_visible()
        page.reload()
        expect(column.get_by_role('button',name='Created through dialog',exact=False)).to_be_visible()
        page.set_viewport_size({'width':375,'height':900})
        page.get_by_role('button',name='Add item to To do',exact=True).click()
        expect(page.get_by_role('dialog',name='Add item to To do',exact=True)).to_be_visible()
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),375)
