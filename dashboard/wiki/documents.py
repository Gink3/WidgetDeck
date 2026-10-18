"""Local document extraction. Originals are never modified or sent off-machine."""
import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from flask import current_app
from PIL import Image, ImageOps
from . import models

TEXT_LIMIT = 2_000_000


def run(args, timeout=60):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=True, env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
        return result.stdout.decode('utf-8', errors='replace')
    except FileNotFoundError:
        raise ValueError(f'{args[0]} is not installed on this server. Rebuild the application image to enable document processing.')
    except subprocess.TimeoutExpired:
        raise ValueError('Document processing exceeded the time limit. Try a smaller document.')
    except subprocess.CalledProcessError:
        raise ValueError('Could not read this document. It may be damaged, encrypted, or unsupported.')


def image_preview(path, destination):
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
        image.thumbnail((2400, 2400))
        image.save(destination, 'PNG')


def extract(item):
    path = models.attachment_folder() / item['stored_name']
    extension = Path(item['filename']).suffix.lower()
    preview = models.attachment_folder() / (item['id'] + '.preview.png')
    status, note, preview_type = 'ready', '', ''
    text = ''
    page_count = 0
    if extension in ('.txt', '.md', '.csv', '.rtf'):
        text = path.read_bytes()[:TEXT_LIMIT].decode('utf-8', errors='replace')
        preview_type = 'text'
    elif extension in ('.docx', '.xlsx', '.pptx', '.odt', '.ods', '.odp'):
        with zipfile.ZipFile(path) as archive:
            # Read text XML only; never unpack paths or load active document content.
            names = [n for n in archive.namelist() if n in ('word/document.xml', 'xl/sharedStrings.xml', 'content.xml') or n.startswith(('ppt/slides/slide', 'xl/worksheets/sheet')) and n.endswith('.xml')]
            if sum(archive.getinfo(n).file_size for n in names) > 32*1024*1024: raise ValueError('Expanded document text exceeds 32 MB.')
            chunks=[]
            for name in names:
                root = ElementTree.fromstring(archive.read(name))
                chunks.append(' '.join(t for t in root.itertext() if t.strip()))
            text = '\n'.join(chunks)
        preview_type = 'text'
    elif extension == '.doc':
        text = run(['antiword', str(path)])
        preview_type = 'text'
    elif extension == '.pdf':
        preview_type = 'pdf'
        info = run(['pdfinfo', str(path)])
        import re
        match = re.search(r'^Pages:\s*(\d+)', info, re.M)
        count = int(match[1]) if match else 1
        page_count = count
        limit = int(current_app.config.get('WIKI_OCR_MAX_PAGES', 50))
        extracted = run(['pdftotext', '-layout', str(path), '-']).split('\f')
        chunks=[]
        with tempfile.TemporaryDirectory() as temporary:
            for index in range(min(count,limit)):
                part = extracted[index].strip() if index < len(extracted) else ''
                if len(part) < 30:
                    root = str(Path(temporary) / 'scan')
                    run(['pdftoppm', '-f', str(index+1), '-l', str(index+1), '-scale-to', '2200', '-singlefile', '-png', str(path), root])
                    try: part = run(['tesseract', root+'.png', 'stdout', '-l', current_app.config.get('WIKI_OCR_LANGUAGE','eng')])
                    except ValueError as error:
                        status, note = 'partial', str(error)
                chunks.append(f'Page {index+1}\n{part}')
        if count > limit:
            chunks.extend(extracted[limit:count])
            status, note = 'partial', f'OCR limited to the first {limit} pages; embedded text from later pages is included.'
        text = '\n\n'.join(chunks)
    elif extension in ('.png','.jpg','.jpeg','.gif','.webp','.avif','.heic','.heif','.tif','.tiff'):
        image_preview(path,preview)
        preview_type = 'image'
        page_count = 1
        try: text = run(['tesseract', str(preview), 'stdout', '-l', current_app.config.get('WIKI_OCR_LANGUAGE','eng')])
        except ValueError as error: status, note = 'partial', str(error)
        with Image.open(preview) as image: pass
        if extension in ('.tif','.tiff'):
            with Image.open(path) as image:
                if getattr(image,'n_frames',1)>1: status,note='partial','Preview and OCR cover the first image in this multi-page TIFF. Upload a PDF to index multiple pages.'
    else:
        status, note = 'unsupported', 'Original file is archived. Text extraction is not available for this format; use PDF or an OpenXML document for searchable text.'
    if len(text)>TEXT_LIMIT: status,note='partial','Extracted text was limited to two million characters.'
    return text[:TEXT_LIMIT], status, note, preview_type, page_count


def process_one():
    # Called under the process-wide file lock held by the worker.
    row = models.db().execute("SELECT a.* FROM wiki_attachments a LEFT JOIN wiki_pages p ON p.id=a.page_id AND p.user_id=a.user_id LEFT JOIN wiki_inbox n ON n.id=a.page_id AND n.user_id=a.user_id WHERE a.user_id=? AND a.processing_status IN ('pending','processing') AND ((p.id IS NOT NULL AND p.deleted_at IS NULL) OR n.id IS NOT NULL) ORDER BY a.created_at LIMIT 1", (models.owner_id(),)).fetchone()
    if not row: return False
    item = dict(row)
    models.db().execute("UPDATE wiki_attachments SET processing_status='processing' WHERE id=?", (item['id'],))
    models.db().commit()
    try: text,status,note,preview,pages = extract(item)
    except Exception as error: text,status,note,preview,pages='', 'error', str(error)[:500], '', 0
    models.db().execute('UPDATE wiki_attachments SET text_content=?,processing_status=?,processing_error=?,preview_type=?,preview_pages=? WHERE id=? AND user_id=?', (text,status,note,preview,pages,item['id'],models.owner_id()))
    models.db().commit()
    return True


def pdf_page_preview(item, number):
    if not 1 <= number <= max(1, item['preview_pages']): raise ValueError('PDF page number is out of range.')
    folder=models.attachment_folder()
    output=folder/(item['id']+f'.page-{number}.png')
    if not output.exists():
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            prefix=str(Path(temporary)/'page')
            run(['pdftoppm','-f',str(number),'-l',str(number),'-scale-to','2000','-singlefile','-png',str(folder/item['stored_name']),prefix])
            os.replace(prefix+'.png',output)
    return output
