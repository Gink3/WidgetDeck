"""Import public HTML articles and retain local copies of their images."""
import http.client
import ipaddress
import re
import socket
import ssl
import time
import uuid
from io import BytesIO
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from markdownify import markdownify
from PIL import Image
from readability import Document

from . import models

MAX_HTML = 4 * 1024 * 1024
MAX_IMAGE = 12 * 1024 * 1024
MAX_IMAGES = 20


def fetch(url, limit, deadline):
    """Resolve and pin public addresses, validating each redirect independently."""
    for _ in range(6):
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            raise ValueError('Use a public HTTP or HTTPS URL without credentials.')
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        addresses = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('Only public web addresses can be imported.')
        remaining = min(10, deadline - time.monotonic())
        if remaining <= 0:
            raise ValueError('Import timed out. Try a smaller page.')
        connection = http.client.HTTPConnection(parts.hostname, port, timeout=remaining)
        try:
            # Connect to the validated IP, never resolving the hostname a second time.
            connection.sock = socket.create_connection((addresses[0][4][0], port), timeout=remaining)
            if parts.scheme == 'https':
                connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=parts.hostname)
            path = urlunsplit(('', '', parts.path or '/', parts.query, ''))
            connection.request('GET', path, headers={'User-Agent': 'DashboardWikiImporter/1.0', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('The website returned an invalid redirect.')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f'The website returned HTTP {response.status}.')
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise ValueError('The website returned unsupported compressed content.')
            data = bytearray()
            while True:
                remaining = min(10, deadline - time.monotonic())
                if remaining <= 0:
                    raise ValueError('Import timed out.')
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read(min(65536, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > limit:
                    raise ValueError('The downloaded file is too large.')
            return bytes(data), response.getheader('Content-Type', ''), url
        finally:
            connection.close()
    raise ValueError('The website redirected too many times.')


def import_page(url):
    deadline = time.monotonic() + 90
    raw, mime, source = fetch(url, MAX_HTML, deadline)
    if mime.split(';')[0].lower() not in ('text/html', 'application/xhtml+xml'):
        raise ValueError('The URL must point to an HTML web page.')
    return import_html(raw, source, deadline=deadline)


def import_html(raw, source='', assets=None, deadline=None):
    """Convert saved HTML using supplied assets before bounded public downloads."""
    import base64
    import posixpath
    from urllib.parse import unquote
    if not raw or len(raw) > MAX_HTML:
        raise ValueError('Choose a nonempty HTML file smaller than 4 MB.')
    if source:
        parts = urlsplit(source)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            raise ValueError('Use a public HTTP or HTTPS source URL without credentials.')
    assets = assets or {}
    deadline = deadline or time.monotonic() + 90
    def asset_key(value):
        path = unquote(urlsplit(value).path).replace('\\', '/')
        return posixpath.normpath(path).lstrip('/')
    soup = BeautifulSoup(raw, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else 'Imported page'
    for tag in list(soup.select('script, style, noscript, iframe, nav, footer, header, aside, form, [hidden], [aria-hidden="true"]')):
        tag.decompose()
    noise = re.compile(r'(^|[\s_-])(ads?|advertisement|advertising|sponsored|cookie|newsletter|social-share|related-posts)([\s_-]|$)', re.I)
    for tag in list(soup.find_all(True)):
        if tag.attrs and noise.search(' '.join(tag.get('class', [])) + ' ' + tag.get('id', '')):
            tag.decompose()
    # Favor explicit article boundaries; use Readability for unstructured pages.
    article = soup.find('article') or soup.find('main')
    if article is None:
        article = BeautifulSoup(Document(str(soup)).summary(keep_all_images=True), 'html.parser')
    if len(article.get_text(strip=True)) < 20:
        raise ValueError('No readable article found. The page may require JavaScript or a login.')
    for link in article.find_all('a', href=True):
        target = urljoin(source, link['href'])
        if urlsplit(target).scheme in ('http', 'https', 'mailto'):
            link['href'] = target
        else:
            del link['href']
    warnings, copied, saved = [], {}, []
    try:
        images = list(article.find_all('img'))
        for index, tag in enumerate(images):
            reference = tag.get('data-src') or tag.get('data-original') or tag.get('src') or ''
            image_url = urljoin(source, reference)
            if index >= MAX_IMAGES or not image_url:
                warnings.append('Some images were omitted because the page exceeds the 20-image limit.')
                tag.decompose()
                continue
            try:
                if image_url not in copied:
                    local = assets.get(asset_key(reference))
                    if local is None:
                        local = assets.get(asset_key(image_url))
                    if local is not None:
                        data = local
                    elif reference.startswith('data:image/'):
                        prefix, encoded = reference.split(',', 1)
                        if not prefix.endswith(';base64') or len(encoded) > MAX_IMAGE * 4 // 3 + 4:
                            raise ValueError('Unsupported embedded image.')
                        data = base64.b64decode(encoded, validate=True)
                    else:
                        data, _, _ = fetch(image_url, MAX_IMAGE, deadline)
                    if len(data) > MAX_IMAGE:
                        raise ValueError('The image is too large.')
                    with Image.open(BytesIO(data)) as image:
                        image.verify()
                        fmt = image.format
                    types = {'PNG': ('.png', 'image/png'), 'JPEG': ('.jpg', 'image/jpeg'), 'GIF': ('.gif', 'image/gif'), 'WEBP': ('.webp', 'image/webp'), 'AVIF': ('.avif', 'image/avif')}
                    if fmt not in types:
                        raise ValueError('Unsupported image format.')
                    extension, image_mime = types[fmt]
                    name = uuid.uuid4().hex + extension
                    path = models.image_folder() / name
                    path.write_bytes(data)
                    saved.append((path, None))
                    record = models.save_image('imported-' + name, image_mime, len(data), name)
                    saved[-1] = (path, record['id'])
                    copied[image_url] = '/tools/wiki/api/images/' + record['id']
                tag['src'] = copied[image_url]
            except (ValueError, OSError, http.client.HTTPException):
                warnings.append('An image could not be copied and was omitted.')
                tag.decompose()
        content = markdownify(str(article), heading_style='ATX', bullets='-', keep_inline_images_in=['a', 'p', 'figure']).strip()
        if not content or len(content) > 990_000:
            raise ValueError('The extracted article is empty or too large for a wiki page.')
        if source:
            content += '\n\nSource: <' + source.replace('>', '%3E').replace('<', '%3C') + '>\n'
        page = models.create(title[:300], content)
        return page, list(dict.fromkeys(warnings))
    except Exception:
        for path, ident in saved:
            path.unlink(missing_ok=True)
            if ident:
                models.db().execute('DELETE FROM wiki_images WHERE id=? AND user_id=?', (ident, models.owner_id()))
        models.db().commit()
        raise
