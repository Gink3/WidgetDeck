"""Durable, additive managed-file copies for explicitly offline migrations."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3

from .manifest import WidgetError, slug


def pending(database):
    database = Path(database).resolve()
    return database.with_name(database.name + '.widget-migration-pending')


def require_recovered(database):
    path = pending(database)
    if path.exists() or path.is_symlink():
        raise WidgetError('Unfinished file migration; run recover-migration offline before starting widgets.')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def directory(proposed, side):
    database = Path(proposed['database'])
    provider = proposed['from_provider' if side == 'source' else 'to_provider']
    return database.parent / 'widget-storage' / provider / proposed['widget']


def fingerprints(proposed, side):
    root = directory(proposed, side)
    # SQLite shared-memory read marks are not persistent application data.
    return {name: digest(root / name) for name in proposed[side + '_files']
            if not (name.endswith('-shm') and sidecar(root / name))}


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sqlite_file(path):
    with path.open('rb') as stream:
        return stream.read(16) == b'SQLite format 3\0'


def sidecar(path):
    for suffix in ('-wal', '-shm', '-journal'):
        if path.name.endswith(suffix):
            main = path.with_name(path.name[:-len(suffix)])
            if main.is_file() and sqlite_file(main):
                return True
    return False


def snapshot(source, target):
    """SQLite backup includes committed WAL records; never copy its sidecars."""
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sqlite_file(source):
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(target)) as copied:
                original.backup(copied)
    else:
        shutil.copyfile(source, target)
    target.chmod(0o600)
    with target.open('rb') as stream:
        os.fsync(stream.fileno())
    sync_directory(target.parent)


def backup_files(proposed, destination):
    for side in ('source', 'target'):
        root = directory(proposed, side)
        for name in proposed[side + '_files']:
            source = root / name
            if not sidecar(source):
                snapshot(source, Path(destination) / source.relative_to(Path(proposed['database']).parent))


def stage(proposed):
    root = pending(proposed['database'])
    source, target = directory(proposed, 'source'), directory(proposed, 'target')
    entries = []
    new_directories = set()
    for name in proposed['source_files']:
        _relative(name)
        original = source / name
        if sidecar(original):
            continue
        staged = root / 'files' / name
        snapshot(original, staged)
        if not sqlite_file(original) and digest(staged) != proposed['source_file_hashes'][name]:
            raise WidgetError('Plan changed during staging; review a new dry-run plan.')
        destination = target / name
        if destination.exists():
            if not destination.is_file() or digest(destination) != digest(staged):
                raise WidgetError('Managed target file conflicts with source; no files overwritten.')
            continue
        for parent in (destination.parent, *destination.parents):
            if parent == target.parent:
                break
            if not parent.exists():
                new_directories.add(str(parent.relative_to(target)))
        entries.append(dict(path=name, sha256=digest(staged)))
    journal = dict(schema_version=1, plan_id=proposed['plan_id'],
        widget=proposed['widget'], target_provider=proposed['to_provider'],
        target_database=proposed['target_database'], entries=entries,
        new_directories=sorted(new_directories))
    temporary = root / 'journal.tmp'
    with temporary.open('x') as stream:
        json.dump(journal, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o600)
    temporary.replace(root / 'journal.json')
    for path in sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        sync_directory(path)
    sync_directory(root)
    return journal


def install(database, journal):
    root = pending(database)
    target = Path(database).resolve().parent / 'widget-storage' / journal['target_provider'] / journal['widget']
    for entry in journal['entries']:
        destination = target / entry['path']
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Atomic no-overwrite installation; stage remains available for recovery.
        os.link(root / 'files' / entry['path'], destination)
        for parent in destination.parents:
            sync_directory(parent)
            if parent == Path(database).resolve().parent:
                break


def _relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '\\' in value or not value or path.as_posix() != value or value == '.':
        raise WidgetError('Invalid migration recovery path; pending state retained.')
    return path


def recover(database, *, offline=False):
    if not offline:
        raise WidgetError('Stop the application and explicitly confirm offline recovery.')
    database = Path(database).resolve()
    root = pending(database)
    if root.is_symlink():
        raise WidgetError('Migration recovery cannot use symbolic links.')
    if not root.exists():
        return dict(recovered=False, committed=False)
    try:
        # Staging may have stopped before journal publication; live files have
        # not been touched in that case.
        journal_path = root / 'journal.json'
        committed = False
        if journal_path.exists():
            if any(path.is_symlink() for path in (root, *root.rglob('*'))):
                raise WidgetError('Migration recovery cannot use symbolic links.')
            journal = json.loads(journal_path.read_text())
            if journal['schema_version'] != 1:
                raise WidgetError('Unsupported migration recovery record.')
            slug(journal['target_provider'], 'recovery provider')
            slug(journal['widget'], 'recovery widget')
            target = database.parent / 'widget-storage' / journal['target_provider'] / journal['widget']
            target_database = Path(journal['target_database'])
            if target_database not in (database, target / 'data.sqlite'):
                raise WidgetError('Invalid migration recovery database.')
            for path in (target.parent.parent, target.parent, target, target_database):
                if path.is_symlink():
                    raise WidgetError('Migration recovery cannot use symbolic links.')
            for entry in journal['entries']:
                _relative(entry['path'])
                if entry['path'] == 'data.sqlite':
                    raise WidgetError('Invalid managed-file recovery entry.')
            # Opening both databases also triggers SQLite hot-journal recovery.
            for path in dict.fromkeys((target_database, database)):
                if path.exists():
                    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as connection:
                        connection.execute('SELECT name FROM sqlite_master').fetchall()
            with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True)) as connection:
                exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='widget_provider_migrations'").fetchone()
                committed = bool(exists and connection.execute(
                    'SELECT 1 FROM widget_provider_migrations WHERE id=?', (journal['plan_id'],)).fetchone())
            if committed and not target_database.exists():
                raise WidgetError('Committed target database is missing; pending state retained.')
            for entry in journal['entries']:
                destination = target / entry['path']
                for parent in (destination, *destination.parents):
                    if parent == target.parent:
                        break
                    if parent.is_symlink():
                        raise WidgetError('Migration recovery cannot use symbolic links.')
                if destination.exists():
                    if not destination.is_file() or digest(destination) != entry['sha256']:
                        raise WidgetError('Recovery file changed; pending state retained for manual review.')
                    if not committed:
                        destination.unlink()
                        sync_directory(destination.parent)
                elif committed:
                    staged = root / 'files' / entry['path']
                    if digest(staged) != entry['sha256']:
                        raise WidgetError('Recovery snapshot changed; pending state retained.')
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    os.link(staged, destination)
                    sync_directory(destination.parent)
            if not committed:
                for name in sorted(journal['new_directories'], key=lambda n: len(PurePosixPath(n).parts), reverse=True):
                    path = target if name == '.' else target / _relative(name)
                    for parent in (path, *path.parents):
                        if parent == target.parent:
                            break
                        if parent.is_symlink():
                            raise WidgetError('Migration recovery cannot use symbolic links.')
                    try:
                        path.rmdir()
                    except OSError:
                        pass  # Never delete other files or preexisting data.
        shutil.rmtree(root)
        sync_directory(root.parent)
        return dict(recovered=True, committed=committed)
    except WidgetError:
        raise
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        raise WidgetError('File recovery failed; keep application stopped and pending state intact.') from error
