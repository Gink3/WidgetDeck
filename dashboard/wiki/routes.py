import os
import io

from PIL import Image, UnidentifiedImageError
from pathlib import Path

from flask import current_app, Blueprint, jsonify, render_template, request, send_from_directory, send_file, redirect
from werkzeug.utils import secure_filename

from dashboard.activity import recent_activity
from . import models


wiki = Blueprint("wiki", __name__, url_prefix="/tools/wiki")
ALLOWED_IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024


def raster_mime(source):
    try:
        with Image.open(source) as image:
            image.verify()
            return {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif",
                    "WEBP": "image/webp", "AVIF": "image/avif"}.get(image.format)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None


def body(): return request.get_json(silent=True) or {}
def fail(message, code=400): return jsonify(error=str(message)), code


def page_payload(page):
    if not page:
        return None
    page["links"] = models.links(page["slug"])
    return page


@wiki.get("")
@wiki.get("/")
def index():
    if not request.args and current_app.config.get("LAUNCHER_ENABLED"):
        from dashboard.launcher import recent
        previous=recent(1,'wiki')
        if previous:return redirect(previous[0]['url'])
    return render_template("wiki/index.html")


@wiki.get("/new")
def new_page(): return render_template("wiki/index.html")


@wiki.get("/<slug>")
def editor(slug):
    existing = models.get(slug)
    if existing and existing["slug"] != slug: return redirect("/tools/wiki/" + existing["slug"])
    return render_template("wiki/editor.html", page_slug=slug)


@wiki.get("/api/pages")
def pages_list(): return jsonify(pages=models.list_pages(request.args.get("q", ""), request.args.get("category", ""), request.args.get("review", ""), request.args.get("trash") == "1"))


@wiki.get("/api/activity")
def activity_list(): return jsonify(activity=recent_activity(area="wiki", limit=request.args.get("limit", 12)))


@wiki.post("/api/pages")
def pages_create(): return jsonify(page=models.create(body().get("title", "Untitled page"), body().get("content", ""), body().get("slug"))), 201


@wiki.post("/api/import-url")
def pages_import_url():
    import http.client
    from .web_import import import_page
    data = body()
    url = data.get('url') if isinstance(data, dict) else None
    if not isinstance(url, str) or not url.strip() or len(url) > 4096:
        return fail('Enter a web page URL.')
    try:
        page, warnings = import_page(url.strip())
        return jsonify(page=page, warnings=warnings), 201
    except (ValueError, OSError, http.client.HTTPException) as error:
        return fail(f'Could not import page: {error}')


@wiki.get("/api/pages/<slug>")
def pages_get(slug):
    page = models.get(slug)
    return jsonify(page=page_payload(page)) if page else fail("Wiki page not found.", 404)


@wiki.put("/api/pages/<slug>")
def pages_update(slug):
    data = body()
    if not isinstance(data, dict):
        return fail("A page update is required.")
    try:
        page = models.update(slug, data)
    except ValueError as error:
        return fail(error)
    return jsonify(page=page_payload(page)) if page else fail("Wiki page not found.", 404)


@wiki.delete("/api/pages/<slug>")
def pages_delete(slug): return ("", 204) if models.delete(slug) else fail("Wiki page not found.", 404)


@wiki.post('/api/import-html')
def pages_import_html():
    from .web_import import import_html, MAX_HTML, MAX_IMAGE
    from pathlib import PurePosixPath
    import http.client
    if request.content_length and request.content_length > 64 * 1024 * 1024:
        return fail('The HTML and assets must total less than 64 MB.', 413)
    uploaded = request.files.get('html')
    if not uploaded or not uploaded.filename or Path(uploaded.filename).suffix.lower() not in {'.html', '.htm'}:
        return fail('Choose a saved .html or .htm page.')
    raw = uploaded.read(MAX_HTML + 1)
    assets, total = {}, len(raw)
    files = request.files.getlist('assets')
    if len(files) > 100:
        return fail('Supply at most 100 companion image files.')
    for asset in files:
        if not asset.filename:
            return fail('Each companion image needs a filename.')
        name = asset.filename.replace('\\', '/')
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or not name or str(path) in assets:
            return fail('Use unique relative paths for companion images.')
        content = asset.read(MAX_IMAGE + 1)
        total += len(content)
        if len(content) > MAX_IMAGE or total > 64 * 1024 * 1024:
            return fail('Each image must be under 12 MB; total assets must be under 64 MB.', 413)
        assets[str(path)] = content
    try:
        page, warnings = import_html(raw, str(request.form.get('source_url') or '').strip(), assets)
    except (ValueError, OSError, http.client.HTTPException) as error:
        return fail(f'Could not import saved page: {error}')
    return jsonify(page=page_payload(page), warnings=warnings), 201


@wiki.post("/api/images")
def images_upload():
    uploaded = request.files.get("image")
    if not uploaded or not uploaded.filename: return fail("Choose an image to upload.")
    filename = secure_filename(uploaded.filename); extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_IMAGES or not str(uploaded.mimetype or "").startswith("image/"): return fail("Use a PNG, JPEG, GIF, WebP, or AVIF image.")
    content = uploaded.read(MAX_IMAGE_BYTES + 1)
    if not content or len(content) > MAX_IMAGE_BYTES: return fail("Images must be smaller than 12 MB.")
    mime = raster_mime(io.BytesIO(content))
    if not mime: return fail("Use a valid PNG, JPEG, GIF, WebP, or AVIF image.")
    stored_name = f"{os.urandom(16).hex()}{extension}"
    (models.image_folder() / stored_name).write_bytes(content)
    image = models.save_image(filename, mime, len(content), stored_name)
    return jsonify(image={"id": image["id"], "filename": image["filename"], "url": f"/tools/wiki/api/images/{image['id']}"}), 201


@wiki.get("/api/images/<image_id>")
def images_get(image_id):
    image = models.get_image(image_id)
    if not image: return fail("Image not found.", 404)
    path = models.image_folder() / image["stored_name"]
    mime = raster_mime(path)
    response = send_from_directory(models.image_folder(), image["stored_name"],
                                   mimetype=mime or "application/octet-stream",
                                   as_attachment=not bool(mime), download_name=image["filename"])
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


@wiki.get('/api/images')
def images_list():
    response = jsonify(images=models.image_library(str(request.args.get('q') or '')))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@wiki.patch('/api/images/<image_id>/metadata')
def images_metadata(image_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or type(data.get('revision')) is not int:
        return fail('Supply image tags and their current revision.')
    try:
        image = models.update_image_tags(image_id, data.get('tags'), data['revision'])
    except models.ImageConflict as error:
        return fail(error, 409)
    except ValueError as error:
        return fail(error)
    return jsonify(image={k: image[k] for k in ('id', 'filename', 'tags', 'revision')}) if image else fail('Image not found.', 404)


@wiki.get('/api/revisions/<slug>')
def revisions_list(slug):
    return jsonify(revisions=models.revisions(slug))


@wiki.post('/api/revisions/<slug>/<revision_id>/restore')
def revision_restore(slug, revision_id):
    revision = next((r for r in models.revisions(slug) if r['id'] == revision_id), None)
    if not revision: return fail('Revision not found.', 404)
    try:
        page = models.update(slug, {**revision['snapshot'], 'revision': body().get('revision')})
        return jsonify(page=page_payload(page))
    except ValueError as error: return fail(error, 409)


@wiki.post('/api/trash/<slug>/restore')
def trash_restore(slug):
    page = models.get(slug, include_deleted=True)
    if not page: return fail('Page not found.', 404)
    models.db().execute('UPDATE wiki_pages SET deleted_at=NULL WHERE id=? AND user_id=?', (page['id'], models.owner_id()))
    models.db().commit()
    return jsonify(page=models.get(page['slug']))


@wiki.get('/api/macros')
def macros_list():
    return jsonify(macros=[dict(r) for r in models.db().execute('SELECT name,content FROM wiki_macros WHERE user_id=? ORDER BY name', (models.owner_id(),))])


@wiki.put('/api/macros/<name>')
def macro_save(name):
    if not models.re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', name): return fail('Use a lowercase macro name with letters, numbers, hyphens or underscores.')
    content = body().get('content')
    if not isinstance(content, str) or not content.strip() or len(content) > 100000: return fail('Provide a macro template under 100,000 characters.')
    models.db().execute('INSERT INTO wiki_macros VALUES(?,?,?) ON CONFLICT(user_id,name) DO UPDATE SET content=excluded.content', (models.owner_id(), name, content))
    models.db().commit()
    return jsonify(name=name, content=content)


@wiki.delete('/api/macros/<name>')
def macro_delete(name):
    models.db().execute('DELETE FROM wiki_macros WHERE user_id=? AND name=?', (models.owner_id(), name))
    models.db().commit()
    return '', 204


@wiki.get('/api/backup')
def backup_export():
    from .backup import export_archive
    return send_file(export_archive(), mimetype='application/zip', as_attachment=True, download_name='wiki-backup.zip')


@wiki.post('/api/backup')
def backup_import():
    import zipfile
    from .backup import import_archive
    uploaded = request.files.get('backup')
    if not uploaded: return fail('Choose a wiki backup ZIP.')
    try: return jsonify(imported=import_archive(uploaded))
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile) as error: return fail('Invalid backup: ' + str(error))


@wiki.get('/api/index')
def page_index():
    return jsonify(pages=models.list_pages() + models.list_pages(trash=True))


@wiki.get('/api/resolve/<slug>')
def page_resolve(slug):
    page = models.get(slug, include_deleted=True)
    if not page: return jsonify(state='missing', slug=slug)
    if page['deleted_at']:
        return jsonify(state='deleted', page={key: page[key] for key in ('id', 'slug', 'title', 'deleted_at')})
    return jsonify(state='active', page=page_payload(page))


@wiki.get('/api/pages/<slug>/attachments')
def attachment_list(slug):
    items = models.attachments(slug)
    return jsonify(attachments=items) if items is not None else fail('Page not found.', 404)


ATTACHMENT_TYPES = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods', '.odp',
    '.txt', '.md', '.csv', '.rtf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif',
    '.heic', '.heif', '.tif', '.tiff'
}
MAX_ATTACHMENT_BYTES = 32 * 1024 * 1024


@wiki.post('/api/inbox/<note_id>/attachments')
@wiki.post('/api/pages/<slug>/attachments')
def attachment_upload(slug=None, note_id=None):
    import hashlib
    import uuid
    page = inbox_get_record(note_id) if note_id else models.get(slug)
    if not page: return fail('Destination not found.', 404)
    uploaded = request.files.get('document')
    if not uploaded or not uploaded.filename: return fail('Choose a document or scanned image.')
    filename = Path(uploaded.filename.replace('\\', '/')).name.strip()
    if not filename or len(filename) > 255 or any(ord(c) < 32 for c in filename): return fail('Use a filename under 256 characters without control characters.')
    if Path(filename).suffix.lower() not in ATTACHMENT_TYPES: return fail('Use a PDF, Office/OpenDocument file, text document, or scanned image.')
    content = uploaded.read(MAX_ATTACHMENT_BYTES + 1)
    if not content or len(content) > MAX_ATTACHMENT_BYTES: return fail('Each attachment must be nonempty and no larger than 32 MB.')
    ident = str(uuid.uuid4())
    stored_name = ident + '.bin'
    path = models.attachment_folder() / stored_name
    try:
        path.write_bytes(content)
        with models.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Recheck after upload so a concurrently trashed page cannot receive files.
            if not (inbox_get_record(note_id) if note_id else models.get(slug)):
                path.unlink(missing_ok=True)
                return fail('Page was moved to trash.', 409)
            connection.execute('INSERT INTO wiki_attachments(id,user_id,page_id,filename,stored_name,mime_type,byte_size,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (ident, models.owner_id(), page['id'], filename, stored_name, 'application/octet-stream', len(content), hashlib.sha256(content).hexdigest(), models.timestamp()))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return jsonify(attachments=inbox_payload(inbox_get_record(note_id))['attachments'] if note_id else models.attachments(slug)), 201


@wiki.get('/api/attachments/<ident>')
def attachment_download(ident):
    item = models.get_attachment(ident)
    if not item: return fail('Attachment not found. Restore its page from trash if it was deleted.', 404)
    response = send_from_directory(models.attachment_folder(), item['stored_name'], as_attachment=True, download_name=item['filename'], mimetype='application/octet-stream')
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@wiki.get('/api/attachments/<ident>/details')
def attachment_details(ident):
    item=models.get_attachment(ident)
    if not item: return fail('Attachment not found.',404)
    return jsonify(attachment={k:item[k] for k in ('id','filename','processing_status','processing_error','preview_type','preview_pages','text_content')})


@wiki.get('/api/attachments/<ident>/preview')
def attachment_preview(ident):
    item=models.get_attachment(ident)
    if not item: return fail('Attachment not found.',404)
    if item['preview_type']=='pdf' and request.args.get('page'):
        from .documents import pdf_page_preview
        try: path=pdf_page_preview(item,int(request.args['page']))
        except ValueError as error: return fail(error)
        response=send_file(path,mimetype='image/png')
    elif item['preview_type']=='pdf':
        response=send_from_directory(models.attachment_folder(),item['stored_name'],mimetype='application/pdf',download_name=item['filename'])
    elif item['preview_type']=='image':
        response=send_from_directory(models.attachment_folder(),ident+'.preview.png',mimetype='image/png')
    else: return fail('No visual preview is available. Use extracted text or download the original.',404)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='private, no-store'
    response.headers['Content-Security-Policy']="default-src 'none'; frame-ancestors 'self'; sandbox"
    return response


@wiki.post('/api/attachments/<ident>/process')
def attachment_process(ident):
    if not models.get_attachment(ident): return fail('Attachment not found.',404)
    models.db().execute("UPDATE wiki_attachments SET processing_status='pending',processing_error='' WHERE id=? AND user_id=?",(ident,models.owner_id()))
    models.db().commit()
    return jsonify(state='pending'),202


@wiki.get('/api/backups')
def backup_list():
    from .worker import settings,backup_files
    jobs=[dict(r) for r in models.db().execute('SELECT id,state,imported,error,created_at FROM wiki_restore_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 10',(models.owner_id(),))]
    return jsonify(settings=settings(),backups=backup_files(),restores=jobs)


@wiki.put('/api/backups/settings')
def backup_configure():
    from .worker import settings
    settings()
    value=body()
    try:
        enabled=value['enabled']
        hours=int(value['interval_hours'])
        retain=int(value['retain_count'])
        if not isinstance(enabled,bool) or hours not in (6,24,168) or not 1<=retain<=30: raise ValueError()
    except (KeyError,TypeError,ValueError): return fail('Choose a 6-hour, daily, or weekly schedule and keep 1–30 backups.')
    models.db().execute('UPDATE wiki_backup_settings SET enabled=?,interval_hours=?,retain_count=? WHERE user_id=?',(int(enabled),hours,retain,models.owner_id()))
    models.db().commit()
    return jsonify(settings=settings())


@wiki.post('/api/backups/run')
def backup_request():
    from .worker import settings
    settings()
    models.db().execute('UPDATE wiki_backup_settings SET requested=1 WHERE user_id=?',(models.owner_id(),))
    models.db().commit()
    return jsonify(state='queued'),202


@wiki.get('/api/backups/<name>')
def backup_download(name):
    from .worker import backup_folder
    if not models.re.fullmatch(r'wiki-\d{8}T\d{6}-[a-f0-9]{8}\.zip',name): return fail('Backup not found.',404)
    return send_from_directory(backup_folder(),name,as_attachment=True,mimetype='application/zip')


@wiki.post('/api/restores')
def restore_queue():
    import uuid
    from flask import current_app
    uploaded=request.files.get('backup')
    if not uploaded: return fail('Choose a wiki backup ZIP.')
    ident=str(uuid.uuid4())
    folder=Path(current_app.instance_path)/'wiki_restore_uploads'
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/(ident+'.zip')
    total=0
    try:
        with path.open('wb') as output:
            while chunk:=uploaded.stream.read(1024*1024):
                total+=len(chunk)
                if total>int(current_app.config.get('WIKI_BACKUP_MAX_BYTES',20*1024**3)): raise ValueError('Uploaded backup exceeds the configured size limit.')
                output.write(chunk)
        models.db().execute('INSERT INTO wiki_restore_jobs(id,user_id,filename,created_at) VALUES(?,?,?,?)',(ident,models.owner_id(),path.name,models.timestamp()))
        models.db().commit()
    except Exception as error:
        path.unlink(missing_ok=True)
        if isinstance(error,ValueError): return fail(error)
        raise
    return jsonify(id=ident,state='queued'),202


# Inbox captures are independent of article pages. Attachments use the capture's
# UUID as their container, sharing the existing processing/download pipeline.
def inbox_get_record(ident):
    row = models.db().execute('SELECT * FROM wiki_inbox WHERE id=? AND user_id=?', (ident, models.owner_id())).fetchone()
    return dict(row) if row else None


def inbox_payload(note):
    note = dict(note)
    ids = models.json.loads(note.pop('page_ids'))
    note['pages'] = [dict(r) for r in models.db().execute('SELECT id,title,slug,deleted_at FROM wiki_pages WHERE user_id=?', (models.owner_id(),)) if r['id'] in ids]
    note['attachments'] = [dict(r) for r in models.db().execute('SELECT id,filename,byte_size,processing_status,created_at FROM wiki_attachments WHERE user_id=? AND page_id=? ORDER BY created_at', (models.owner_id(), note['id']))]
    return note


@wiki.get('/api/inbox')
def inbox_list():
    query = request.args.get('q', '').casefold().strip()
    rows = models.db().execute('SELECT * FROM wiki_inbox WHERE user_id=?' + ('' if request.args.get('processed') == '1' else ' AND processed_at IS NULL') + ' ORDER BY created_at DESC', (models.owner_id(),))
    notes = [inbox_payload(r) for r in rows]
    if query:
        notes = [n for n in notes if query in n['content'].casefold() or any(query in (r['filename'] + ' ' + r['text_content']).casefold() for r in models.db().execute('SELECT filename,text_content FROM wiki_attachments WHERE user_id=? AND page_id=?', (models.owner_id(), n['id'])))]
    return jsonify(notes=notes, owner_id=models.owner_id())


@wiki.post('/api/inbox')
def inbox_create():
    content = body().get('content', '')
    if not isinstance(content, str) or len(content) > 1_000_000: return fail('Note must be text under one million characters.')
    ident, now = str(models.uuid.uuid4()), models.timestamp()
    models.db().execute('INSERT INTO wiki_inbox(id,user_id,content,created_at,updated_at) VALUES(?,?,?,?,?)', (ident, models.owner_id(), content, now, now))
    models.db().commit()
    return jsonify(note=inbox_payload(inbox_get_record(ident))), 201


@wiki.get('/api/inbox/<ident>')
def inbox_read(ident):
    note = inbox_get_record(ident)
    return jsonify(note=inbox_payload(note)) if note else fail('Note not found.', 404)


@wiki.put('/api/inbox/<ident>')
def inbox_update(ident):
    data = body()
    with models.db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        note = inbox_get_record(ident)
        if not note: return fail('Note not found.', 404)
        if data.get('revision') != note['revision']: return fail('This note changed in another tab. Reopen it before saving; copy your edits first.', 409)
        content = data.get('content', note['content'])
        if not isinstance(content, str) or len(content) > 1_000_000: return fail('Note must be text under one million characters.')
        if 'processed' in data and not isinstance(data['processed'], bool): return fail('Invalid processed state.')
        processed = (models.timestamp() if data['processed'] else None) if 'processed' in data else note['processed_at']
        ids = models.json.loads(note['page_ids'])
        if data.get('page_slug'):
            page = models.get(data['page_slug'])
            if not page: return fail('Page not found.', 404)
            ids = list(dict.fromkeys(ids + [page['id']]))
        connection.execute('UPDATE wiki_inbox SET content=?,processed_at=?,page_ids=?,updated_at=?,revision=revision+1 WHERE id=? AND user_id=?', (content, processed, models.json.dumps(ids), models.timestamp(), ident, models.owner_id()))
    return jsonify(note=inbox_payload(inbox_get_record(ident)))


@wiki.post('/api/inbox/<ident>/attach/<attachment_id>')
def inbox_attach(ident, attachment_id):
    import shutil
    note = inbox_get_record(ident)
    item = models.get_attachment(attachment_id)
    page = models.get(body().get('page_slug', ''))
    if not note or not item or item['page_id'] != ident or not page: return fail('Note, attachment, or page not found.', 404)
    new_id = str(models.uuid.uuid4())
    path = models.attachment_folder() / (new_id + '.bin')
    try:
        shutil.copyfile(models.attachment_folder() / item['stored_name'], path)
        with models.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if not models.get(page['slug']):
                path.unlink(missing_ok=True)
                return fail('Page was moved to trash.', 409)
            connection.execute('INSERT INTO wiki_attachments(id,user_id,page_id,filename,stored_name,mime_type,byte_size,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?)', (new_id, models.owner_id(), page['id'], item['filename'], path.name, item['mime_type'], item['byte_size'], item['sha256'], models.timestamp()))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return jsonify(id=new_id), 201


@wiki.get('/api/graph')
def page_graph():
    rows = [dict(r) for r in models.db().execute('SELECT id,title,slug,content FROM wiki_pages WHERE user_id=? AND deleted_at IS NULL ORDER BY title COLLATE NOCASE', (models.owner_id(),))]
    by_id = {r['id']: r for r in rows}
    by_slug = {r['slug']: r for r in rows}
    titles = {r['title'].casefold(): r['slug'] for r in rows}
    for alias in models.db().execute('SELECT alias,page_id FROM wiki_aliases WHERE user_id=?', (models.owner_id(),)):
        if alias['page_id'] in by_id:
            titles[alias['alias'].casefold()] = by_id[alias['page_id']]['slug']
    edges = []
    counts = {r['id']: {'incoming': 0, 'outgoing': 0} for r in rows}
    for row in rows:
        targets = set()
        for match in models.WIKI_LINK.finditer(row['content']):
            target = match.group(1).strip().rstrip('\\')
            slug = target if target in by_slug else titles.get(target.casefold(), models.slugify(target))
            if slug in by_slug and by_slug[slug]['id'] != row['id']:
                targets.add(by_slug[slug]['id'])
        for target in sorted(targets):
            edges.append({'id': row['id'] + ':' + target, 'source': row['id'], 'target': target})
            counts[row['id']]['outgoing'] += 1
            counts[target]['incoming'] += 1
    return jsonify(owner_id=models.owner_id(), nodes=[{k: r[k] for k in ('id', 'title', 'slug')} | counts[r['id']] for r in rows], edges=edges)


@wiki.get('/api/navigation')
def navigation_list():
    rows = [dict(r) for r in models.db().execute('SELECT p.id,p.title,p.slug,n.pinned,n.viewed_at FROM wiki_page_navigation n JOIN wiki_pages p ON p.id=n.page_id AND p.user_id=n.user_id WHERE n.user_id=? AND p.deleted_at IS NULL ORDER BY n.viewed_at DESC', (models.owner_id(),))]
    return jsonify(pinned=sorted([r for r in rows if r['pinned']], key=lambda p: p['title'].casefold())[:6], recent=[r for r in rows if r['viewed_at']][:6])


@wiki.route('/api/pages/<slug>/navigation', methods=['POST', 'PUT'])
def navigation_update(slug):
    page = models.get(slug)
    if not page: return fail('Page not found.', 404)
    owner = models.owner_id()
    if request.method == 'PUT' and not isinstance(body().get('pinned'), bool): return fail('Pinned must be true or false.')
    with models.db() as connection:
        connection.execute('INSERT OR IGNORE INTO wiki_page_navigation(user_id,page_id) VALUES(?,?)', (owner, page['id']))
        if request.method == 'POST':
            from datetime import datetime, timezone
            connection.execute('UPDATE wiki_page_navigation SET viewed_at=? WHERE user_id=? AND page_id=?', (datetime.now(timezone.utc).isoformat(timespec='microseconds'), owner, page['id']))
        else:
            connection.execute('UPDATE wiki_page_navigation SET pinned=? WHERE user_id=? AND page_id=?', (body()['pinned'], owner, page['id']))
    return jsonify(ok=True)
