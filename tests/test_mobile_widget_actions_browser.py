"""Real mobile header geometry and action/navigation regressions."""
import os
import secrets
import unittest
from browser_auth import auth_form


@unittest.skipUnless(os.environ.get('WORKSPACE_TEST_BASE_URL'), 'Requires disposable browser app')
class MobileWidgetActionsBrowserTests(unittest.TestCase):
    def test_kanban_actions_share_one_row_and_keep_working(self):
        from playwright.sync_api import sync_playwright, expect
        from pathlib import Path
        base = os.environ['WORKSPACE_TEST_BASE_URL']
        self.assertEqual(base, 'http://127.0.0.1:8020')
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(viewport={'width': 360, 'height': 800}, has_touch=True, service_workers='block')
            self.assertEqual(context.request.post(base + '/register', form={**auth_form(context.request, base),
                'username': 'header-' + secrets.token_hex(5), 'password': secrets.token_urlsafe(32)}, max_redirects=0).status, 302)
            created = context.request.post(base + '/tools/kanban', form={'name': 'Mobile board'}, max_redirects=0)
            self.assertEqual(created.status, 302)
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + created.headers['location'])
            back = page.get_by_role('button', name='← Boards', exact=True)
            new = page.get_by_role('button', name='+ New board', exact=True)
            more = page.locator('.kanban-column-tools > details > summary')
            for width in (320, 360, 375, 719, 720):
                with self.subTest(width=width):
                    page.set_viewport_size({'width': width, 'height': 800})
                    expect(back).to_be_visible()
                    boxes = [control.bounding_box() for control in (back, new, more)]
                    self.assertLessEqual(max(box['y'] for box in boxes) - min(box['y'] for box in boxes), 1)
                    for left, right in zip(boxes, boxes[1:]):
                        self.assertLessEqual(left['x'] + left['width'], right['x'])
                    for box in boxes:
                        self.assertGreaterEqual(box['height'], 44)
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
            page.set_viewport_size({'width': 360, 'height': 800})
            if os.environ.get('MOBILE_HEADER_ARTIFACTS'):
                directory = Path(os.environ['MOBILE_HEADER_ARTIFACTS'])
                directory.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(directory / 'kanban-360.png'), full_page=True)
            more.tap()
            page.get_by_role('button', name='Manage columns', exact=True).tap()
            expect(page.locator('#column-manager')).to_be_visible()
            page.keyboard.press('Escape')
            new.tap()
            expect(page.locator('#new-kanban')).to_be_visible()
            page.keyboard.press('Escape')
            back.tap()
            expect(page.get_by_role('searchbox', name='Find boards')).to_be_focused()
            expect(back).to_be_hidden()
            page.locator('.workspace-library').get_by_role('button', name='Mobile board', exact=True).tap()
            expect(back).to_be_visible()
            # Larger text can wrap when needed, without clipping or overlap.
            page.add_style_tag(content='body{font-size:28px!important}')
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 360)
            for width in (768, 1440):
                page.set_viewport_size({'width': width, 'height': 1000})
                expect(back).to_be_hidden()
                expect(new).to_be_visible()
                expect(more).to_be_visible()
            self.assertEqual(errors, [])
            browser.close()
