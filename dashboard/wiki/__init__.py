from .models import init_database
from .routes import wiki


def init_wiki(app):
    import os
    app.config.setdefault('WIKI_BACKUP_MAX_BYTES', int(os.environ.get('WIKI_BACKUP_MAX_GB', '20')) * 1024**3)
    app.config.setdefault('WIKI_OCR_MAX_PAGES', int(os.environ.get('WIKI_OCR_MAX_PAGES', '50')))
    app.config.setdefault('WIKI_OCR_LANGUAGE', os.environ.get('WIKI_OCR_LANGUAGE', 'eng'))
    app.config.setdefault('WIKI_WORKER_DISABLED', os.environ.get('WIKI_WORKER_DISABLED') == '1')
    import fcntl
    from pathlib import Path
    with (Path(app.instance_path) / 'wiki-schema.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        init_database(app)
    app.register_blueprint(wiki)

    from .worker import start_worker
    start_worker(app)
