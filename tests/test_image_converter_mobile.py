import io
import logging
import secrets
import tempfile
import threading
import unittest
from zipfile import ZipFile
from PIL import Image
from werkzeug.serving import make_server
from test_security_boundaries import isolated_application, auth_post


def image_bytes():
    output = io.BytesIO()
    Image.new('RGB', (8, 8), 'purple').save(output, format='PNG')
    return output.getvalue()


class ImageConverterMobileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        cls.directory = tempfile.TemporaryDirectory()
        _, cls.app = isolated_application(cls.directory.name)
        cls.server = make_server('127.0.0.1', 0, cls.app, threaded=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.directory.cleanup()

    def setUp(self):
        self.client = self.app.test_client()
        auth_post(self.client, '/register', {'username': 'convert-' + secrets.token_hex(4), 'password': 'test-only-password'})

    def context(self, browser, width=390, height=844):
        context = browser.new_context(viewport={'width': width, 'height': height}, has_touch=True, is_mobile=True)
        context.add_cookies([{'name': 'dashboard_session',
                             'value': self.client.get_cookie('dashboard_session').value, 'url': self.base}])
        return context

    def file(self, name='paint.png', content=None):
        return {'name': name, 'mimeType': 'image/png', 'buffer': image_bytes() if content is None else content}

    def test_original_post_still_returns_single_image_or_zip_and_json_errors_are_opt_in(self):
        path = '/tools/image-converter'
        for count in (1, 2):
            response = self.client.post(path, data={'format': 'jpeg', 'images': [(io.BytesIO(image_bytes()), 'paint.png') for _ in range(count)]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
            if count == 1:
                self.assertEqual(response.mimetype, 'image/jpeg')
                with Image.open(io.BytesIO(response.data)) as converted:
                    self.assertEqual(converted.size, (8, 8))
            else:
                with ZipFile(io.BytesIO(response.data)) as archive:
                    self.assertEqual(archive.namelist(), ['paint.jpg', 'paint-2.jpg'])
            response.close()
        response = self.client.post(path, data={'format': 'png'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.mimetype, 'text/html')
        response = self.client.post(path, data={'format': 'png', 'images': (io.BytesIO(b'invalid'), 'photo.heic')}, headers={'Accept': 'application/json'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('HEIC/HEIF', response.json['error'])

    def test_phone_previews_real_downloads_and_zip(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width, height in ((320, 720), (390, 844), (844, 390)):
                context = self.context(browser, width, height)
                page = context.new_page()
                page.goto(self.base + '/tools/image-converter')
                page.locator('input[type=file]').set_input_files(self.file())
                expect(page.locator('#converter-selection')).to_contain_text('1 image selected')
                expect(page.locator('#converter-files img')).to_have_count(1)
                page.locator('select[name=format]').select_option('jpeg')
                page.get_by_role('button', name='Convert images', exact=True).click()
                expect(page.locator('#converter-status')).to_contain_text('Conversion complete')
                with page.expect_download() as download:
                    page.get_by_role('link', name='Save file', exact=True).click()
                self.assertEqual(download.value.suggested_filename, 'paint.jpg')
                with Image.open(download.value.path()) as converted:
                    self.assertEqual(converted.size, (8, 8))
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
                page.locator('input[type=file]').set_input_files([self.file(), self.file()])
                page.get_by_role('button', name='Convert images', exact=True).click()
                expect(page.locator('#converter-result-name')).to_contain_text('converted-images.zip')
                with page.expect_download() as download:
                    page.get_by_role('link', name='Save file', exact=True).click()
                with ZipFile(download.value.path()) as archive:
                    self.assertEqual(archive.namelist(), ['paint.jpg', 'paint-2.jpg'])
                context.close()
            browser.close()

    def test_phone_errors_and_session_expiry_keep_selection(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = self.context(browser)
            page = context.new_page()
            page.goto(self.base + '/tools/image-converter')
            field = page.locator('input[type=file]')
            submit = page.get_by_role('button', name='Convert images', exact=True)
            field.set_input_files(self.file('photo.heic'))
            expect(page.locator('#converter-status')).to_contain_text('Export the photo as JPEG or PNG')
            expect(submit).to_be_disabled()
            field.set_input_files([self.file(str(n)+'.png') for n in range(31)])
            expect(page.locator('#converter-status')).to_contain_text('no more than 30')
            field.set_input_files(self.file('bad.png', b'invalid image'))
            submit.click()
            expect(page.locator('#converter-status')).to_contain_text('could not be converted')
            expect(page.locator('#converter-result')).not_to_be_visible()
            field.set_input_files(self.file())
            context.set_offline(True)
            submit.click()
            expect(page.locator('#converter-status')).to_contain_text('not been queued')
            context.set_offline(False)
            self.client.post('/logout')
            submit.click()
            expect(page.locator('#converter-login')).to_be_visible()
            self.assertEqual(field.evaluate('el => el.files.length'), 1)
            expect(submit).to_be_enabled()
            context.close()
            browser.close()
