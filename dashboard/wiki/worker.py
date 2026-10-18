"""Durable OCR/restore queues and scheduled backups, shared by gunicorn workers."""
import fcntl
import os
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import current_app, g
from . import models
from .backup import export_archive, verify_archive, import_archive


def backup_folder():
    folder=Path(current_app.instance_path)/'wiki_backups'/str(models.owner_id())
    folder.mkdir(parents=True,exist_ok=True)
    return folder


def settings():
    models.db().execute('INSERT OR IGNORE INTO wiki_backup_settings(user_id) VALUES(?)',(models.owner_id(),))
    models.db().commit()
    return dict(models.db().execute('SELECT * FROM wiki_backup_settings WHERE user_id=?',(models.owner_id(),)).fetchone())


def backup_files():
    return [{'name':p.name,'byte_size':p.stat().st_size,'created_at':datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat()} for p in sorted(backup_folder().glob('wiki-*.zip'),key=lambda p:p.stat().st_mtime_ns,reverse=True)]


def create_backup():
    config=settings()
    name='wiki-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.zip'
    temporary=backup_folder()/(name+'.partial')
    models.db().execute("UPDATE wiki_backup_settings SET last_attempt=?,error='' WHERE user_id=?",(models.timestamp(),models.owner_id()))
    models.db().commit()
    try:
        with export_archive() as source,temporary.open('wb') as destination: shutil.copyfileobj(source,destination,1024*1024)
        verify_archive(temporary)
        os.replace(temporary,backup_folder()/name)
        models.db().execute("UPDATE wiki_backup_settings SET last_success=?,error='',requested=0 WHERE user_id=?",(models.timestamp(),models.owner_id()))
        models.db().commit()
        # Prune only after a new complete archive has passed validation.
        for item in backup_files()[config['retain_count']:]: (backup_folder()/item['name']).unlink()
        return name
    except Exception as error:
        temporary.unlink(missing_ok=True)
        models.db().execute('UPDATE wiki_backup_settings SET error=?,requested=0 WHERE user_id=?',(str(error)[:500],models.owner_id()))
        models.db().commit()
        raise


def process_restore():
    row=models.db().execute("SELECT * FROM wiki_restore_jobs WHERE user_id=? AND state='queued' ORDER BY created_at LIMIT 1",(models.owner_id(),)).fetchone()
    if not row: return False
    models.db().execute("UPDATE wiki_restore_jobs SET state='running' WHERE id=?",(row['id'],))
    models.db().commit()
    path=Path(current_app.instance_path)/'wiki_restore_uploads'/row['filename']
    try:
        imported=import_archive(path)
        models.db().execute("UPDATE wiki_restore_jobs SET state='complete',imported=?,finished_at=? WHERE id=?",(imported,models.timestamp(),row['id']))
    except Exception as error:
        models.db().execute("UPDATE wiki_restore_jobs SET state='error',error=?,finished_at=? WHERE id=?",(str(error)[:500],models.timestamp(),row['id']))
    models.db().commit()
    path.unlink(missing_ok=True)
    return True


def tick(app):
    with app.app_context():
        lock=Path(app.instance_path)/'wiki-worker.lock'
        with lock.open('a') as handle:
            try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: return
            # A previous worker terminated while restoring. Do not retry blindly:
            # a transaction may have committed before its completion was recorded.
            models.db().execute("UPDATE wiki_restore_jobs SET state='error',error='Restore was interrupted. Check the library before importing again.' WHERE state='running'")
            models.db().commit()
            owners=[r[0] for r in models.db().execute('SELECT user_id FROM wiki_inbox UNION SELECT user_id FROM wiki_pages UNION SELECT user_id FROM wiki_macros UNION SELECT user_id FROM wiki_backup_settings UNION SELECT user_id FROM wiki_restore_jobs')]
            for owner in owners:
                g.dashboard_user={'id':owner}
                try:
                    config=settings()
                    now=datetime.now(timezone.utc)
                    due=not config['last_success'] or now-datetime.fromisoformat(config['last_success'])>=timedelta(hours=config['interval_hours'])
                    retry=not config['last_attempt'] or now-datetime.fromisoformat(config['last_attempt'])>=timedelta(minutes=15)
                    if config['requested'] or config['enabled'] and due and retry: create_backup()
                    process_restore()
                    from .documents import process_one
                    process_one()
                except Exception:
                    models.db().rollback()
                    app.logger.exception('Wiki background task failed for account %s',owner)


def start_worker(app):
    if app.testing or app.config.get('WIKI_WORKER_DISABLED'): return
    def loop():
        while True:
            try: tick(app)
            except Exception: app.logger.exception('Wiki worker failed')
            time.sleep(15)
    threading.Thread(target=loop,name='wiki-maintenance',daemon=True).start()
