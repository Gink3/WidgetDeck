"""Streaming, owner-scoped archives with verified restore and v1 compatibility."""
import hashlib
import json
import tempfile
import uuid
import zipfile
from pathlib import Path
from flask import current_app
from . import models

CHUNK = 1024 * 1024


def digest_stream(source, destination=None):
    digest = hashlib.sha256()
    while chunk := source.read(CHUNK):
        digest.update(chunk)
        if destination is not None: destination.write(chunk)
    return digest.hexdigest()


def export_archive():
    # TemporaryFile spools to disk, so binary attachments never accumulate in RAM.
    output = tempfile.TemporaryFile()
    owner = models.owner_id()
    connection = models.db()
    try:
        # Consistent SQLite snapshot across pages, revisions and file metadata.
        connection.execute('BEGIN')
        pages = [models.decode(r) for r in connection.execute('SELECT * FROM wiki_pages WHERE user_id=?', (owner,))]
        records = {name:[dict(r) for r in connection.execute(f'SELECT * FROM wiki_{name} WHERE user_id=?', (owner,))] for name in ('images','revisions','macros','attachments','inbox')}
        connection.commit()
        manifest = dict(version=2, pages=pages, **records)
        checksums = {}
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,allowZip64=True) as archive:
            def write(name, data):
                data = data.encode('utf-8')
                archive.writestr(name,data)
                checksums[name] = hashlib.sha256(data).hexdigest()
            write('wiki.json',json.dumps(manifest,ensure_ascii=False))
            for page in pages: write(f'pages/{page["slug"]}.md',page['content'])
            for kind, folder in [('images',models.image_folder()),('attachments',models.attachment_folder())]:
                for item in records[kind]:
                    name = f'{kind}/{item["id"]}'
                    with (folder/item['stored_name']).open('rb') as source, archive.open(name,'w',force_zip64=True) as destination:
                        checksums[name] = digest_stream(source,destination)
            write('checksums.json',json.dumps(checksums))
        output.seek(0)
        return output
    except Exception:
        connection.rollback()
        output.close()
        raise


def validate_archive(archive):
    infos = archive.infolist()
    if len({i.filename for i in infos}) != len(infos): raise ValueError('Duplicate archive entries.')
    limit = int(current_app.config.get('WIKI_BACKUP_MAX_BYTES',20*1024**3))
    if sum(i.file_size for i in infos)>limit: raise ValueError(f'Expanded backup exceeds the configured {limit//1024**3} GB limit.')
    if archive.getinfo('wiki.json').file_size>128*1024**2: raise ValueError('Backup metadata exceeds 128 MB.')
    data = json.loads(archive.read('wiki.json'))
    if not isinstance(data,dict) or data.get('version') not in (1,2): raise ValueError('Unsupported backup version.')
    if data['version']==2:
        if archive.getinfo('checksums.json').file_size>32*1024**2: raise ValueError('Checksum manifest is too large.')
        checksums=json.loads(archive.read('checksums.json'))
        if not isinstance(checksums,dict) or set(checksums)!={i.filename for i in infos if i.filename!='checksums.json'}: raise ValueError('Incomplete checksum manifest.')
        for name, expected in checksums.items():
            with archive.open(name) as source:
                if digest_stream(source)!=expected: raise ValueError('Backup checksum does not match: '+name)
    for key in ('pages','images','attachments','macros','revisions','inbox'):
        records=data.setdefault(key,[])
        if not isinstance(records,list) or not all(isinstance(r,dict) for r in records): raise ValueError('Invalid '+key+' records.')
    pages=data['pages']
    for page in pages:
        if not all(isinstance(page.get(k),str) for k in ('id','slug','title','content')): raise ValueError('Invalid page record.')
        models.normalize_metadata(page.get('metadata',{}))
        if not isinstance(page.get('aliases',[]),list) or not all(isinstance(a,str) for a in page.get('aliases',[])): raise ValueError('Invalid aliases.')
    page_ids={p['id'] for p in pages}
    if len(page_ids)!=len(pages): raise ValueError('Duplicate page IDs.')
    for note in data['inbox']:
        if not all(isinstance(note.get(k), str) for k in ('id', 'content', 'created_at', 'updated_at', 'page_ids')): raise ValueError('Invalid inbox note.')
        ids = json.loads(note['page_ids'])
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids): raise ValueError('Invalid inbox page links.')
        if note.get('processed_at') is not None and not isinstance(note['processed_at'], str): raise ValueError('Invalid processed date.')
    note_ids = {n['id'] for n in data['inbox']}
    if len(note_ids) != len(data['inbox']) or note_ids & page_ids: raise ValueError('Duplicate inbox IDs.')
    for kind in ('images','attachments'):
        ids=set()
        for item in data[kind]:
            if not all(isinstance(item.get(k),str) for k in ('id','filename')) or item['id'] in ids: raise ValueError('Invalid or duplicate file record.')
            ids.add(item['id'])
            if kind=='attachments' and item.get('page_id') not in page_ids | note_ids: raise ValueError('Attachment page is missing.')
            if kind=='images' and item.get('mime_type') not in ('image/png','image/jpeg','image/gif','image/webp','image/avif'): raise ValueError('Invalid image type in backup.')
            if kind=='images':
                tags = item.get('tags', '[]')
                models.normalize_image_tags(json.loads(tags) if isinstance(tags, str) else tags)
            with archive.open(kind+'/'+item['id']) as source:
                digest=digest_stream(source)
            if kind=='attachments' and digest!=item.get('sha256'): raise ValueError('Attachment checksum does not match: '+item['filename'])
    for macro in data['macros']:
        if not isinstance(macro.get('name'),str) or not models.re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',macro['name']): raise ValueError('Invalid macro name.')
        if not isinstance(macro.get('content'),str) or len(macro['content'])>100000: raise ValueError('Invalid macro template.')
    for revision in data['revisions']:
        if not all(isinstance(revision.get(k),str) for k in ('page_id','snapshot','created_at')): raise ValueError('Invalid revision.')
        snapshot=json.loads(revision['snapshot'])
        if not isinstance(snapshot,dict) or not all(isinstance(snapshot.get(k),str) for k in ('title','content')): raise ValueError('Invalid revision snapshot.')
        models.normalize_metadata(snapshot.get('metadata',{}))
    return data


def verify_archive(source):
    with zipfile.ZipFile(source) as archive:
        data=validate_archive(archive)
    return {'pages':len(data['pages']), 'attachments':len(data['attachments']), 'version':data['version']}


def import_archive(upload):
    owner=models.owner_id()
    connection=models.db()
    paths=[]
    try:
        with zipfile.ZipFile(upload) as archive:
            data=validate_archive(archive)
            # Stage binaries before taking the database write lock; every staged
            # file has a new random name, and failures remove all staged files.
            file_maps={'images':{},'attachments':{}}
            staged={}
            for kind,folder in [('images',models.image_folder()),('attachments',models.attachment_folder())]:
                for item in data[kind]:
                    ident=str(uuid.uuid4())
                    file_maps[kind][item['id']]=ident
                    path=folder/(ident+'.bin')
                    paths.append(path)
                    with archive.open(kind+'/'+item['id']) as source,path.open('wb') as destination:
                        digest_stream(source,destination)
                    staged[(kind,item['id'])]=path
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                mapping={}
                for page in data['pages']:
                    ident,slug=str(uuid.uuid4()),models.unique_slug(page['slug'])
                    mapping[page['id']]=(ident,slug)
                    connection.execute('INSERT INTO wiki_pages(id,user_id,title,slug,content,created_at,updated_at,metadata,deleted_at) VALUES(?,?,?,?,?,?,?,?,?)', (ident,owner,page['title'],slug,'',page.get('created_at') or models.timestamp(),page.get('updated_at') or models.timestamp(),'{}',page.get('deleted_at')))
                for note in data['inbox']:
                    mapping[note['id']] = (str(uuid.uuid4()), '')
                for note in data['inbox']:
                    connection.execute('INSERT INTO wiki_inbox(id,user_id,content,created_at,updated_at,processed_at,page_ids) VALUES(?,?,?,?,?,?,?)', (mapping[note['id']][0], owner, note['content'], note['created_at'], note['updated_at'], note.get('processed_at'), json.dumps([mapping[i][0] for i in json.loads(note['page_ids']) if i in mapping])))
                for item in data['images']:
                    path=staged[('images',item['id'])]
                    tags = item.get('tags', '[]')
                    tags = models.normalize_image_tags(json.loads(tags) if isinstance(tags, str) else tags)
                    connection.execute('INSERT INTO wiki_images(id,user_id,filename,stored_name,mime_type,byte_size,created_at,tags) VALUES(?,?,?,?,?,?,?,?)',(file_maps['images'][item['id']],owner,item['filename'],path.name,item['mime_type'],path.stat().st_size,item.get('created_at') or models.timestamp(),json.dumps(tags)))
                for item in data['attachments']:
                    path=staged[('attachments',item['id'])]
                    connection.execute('INSERT INTO wiki_attachments(id,user_id,page_id,filename,stored_name,mime_type,byte_size,sha256,created_at,text_content) VALUES(?,?,?,?,?,?,?,?,?,?)', (file_maps['attachments'][item['id']],owner,mapping[item['page_id']][0],item['filename'],path.name,'application/octet-stream',path.stat().st_size,item['sha256'],item.get('created_at') or models.timestamp(),str(item.get('text_content',''))[:2_000_000]))
                targets={}
                for page in data['pages']:
                    for alias in [page['title'],page['slug']]+page.get('aliases',[]): targets[alias.casefold()]=mapping[page['id']][1]
                def rewrite(content):
                    content=models.WIKI_LINK.sub(lambda m:'[['+targets.get(m[1].strip().casefold(),m[1].strip())+('|' + m[0].split('|',1)[1][:-2] if '|' in m[0] else '')+']]',content)
                    for kind, ids in file_maps.items():
                        for old,new in ids.items(): content=content.replace('/tools/wiki/api/'+kind+'/'+old,'/tools/wiki/api/'+kind+'/'+new)
                    return content
                def remap_metadata(value):
                    metadata = models.normalize_metadata(value)
                    if 'topic' in metadata:
                        metadata['topic']['page_ids'] = [mapping[i][0] for i in metadata['topic'].get('page_ids', []) if i in mapping]
                    return metadata
                for note in data['inbox']:
                    connection.execute('UPDATE wiki_inbox SET content=? WHERE id=?', (rewrite(note['content']), mapping[note['id']][0]))
                for page in data['pages']:
                    ident,slug=mapping[page['id']]
                    connection.execute('UPDATE wiki_pages SET content=?,metadata=? WHERE id=?',(rewrite(page['content']),json.dumps(remap_metadata(page.get('metadata',{}))),ident))
                    for alias in page.get('aliases',[]):
                        if not models.get(alias,True): connection.execute('INSERT OR IGNORE INTO wiki_aliases VALUES(?,?,?)',(owner,alias,ident))
                for revision in data['revisions']:
                    if revision['page_id'] not in mapping: continue
                    snap=json.loads(revision['snapshot'])
                    snap.update(id=mapping[revision['page_id']][0],slug=mapping[revision['page_id']][1],user_id=owner,content=rewrite(snap['content']))
                    snap['aliases']=models.get(snap['slug'],True)['aliases']
                    snap['metadata']=remap_metadata(snap.get('metadata',{}))
                    connection.execute('INSERT INTO wiki_revisions VALUES(?,?,?,?,?)',(str(uuid.uuid4()),owner,snap['id'],json.dumps(snap),revision['created_at']))
                for macro in data['macros']:
                    connection.execute('INSERT OR IGNORE INTO wiki_macros VALUES(?,?,?)',(owner,macro['name'],rewrite(macro['content'])))
        return len(data['pages'])
    except Exception:
        connection.rollback()
        for path in paths: path.unlink(missing_ok=True)
        raise
