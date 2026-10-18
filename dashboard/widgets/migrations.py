"""Reviewed offline storage migrations; runtime registration never calls hooks."""
from contextlib import closing
from datetime import datetime, timezone
import secrets
import hashlib
from importlib import import_module
import json
from pathlib import Path
import sqlite3

from packaging.version import InvalidVersion, Version
from dashboard.database import timestamp
from .manifest import API_VERSION, WidgetError, slug
from .storage import _legacy
from . import migration_files as files

TABLE = 'widget_provider_migrations'


def _connect_readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def _path(database, provider, widget, kind):
    slug(provider, 'stored provider')
    if kind == 'legacy':
        return database
    if kind != 'isolated':
        raise WidgetError('Unknown stored provider layout.')
    return database.parent / 'widget-storage' / provider / widget / 'data.sqlite'


def _managed_files(database, provider, widget):
    root = database.parent / 'widget-storage'
    directory = root / provider / widget
    for path in (root, root / provider, directory):
        if path.is_symlink():
            raise WidgetError('Migration storage cannot use symbolic links.')
    files = []
    if directory.exists():
        for path in directory.rglob('*'):
            if path.is_symlink():
                raise WidgetError('Migration storage cannot contain symbolic links.')
            if not path.is_file() and not path.is_dir():
                raise WidgetError('Migration storage contains an unsupported special file.')
            if path.is_file() and str(path.relative_to(directory)) not in {'data.sqlite', 'data.sqlite-wal',
                                                    'data.sqlite-shm', 'data.sqlite-journal'}:
                files.append(str(path.relative_to(directory)))
    return sorted(files)


def plan(manifest, database, from_provider, from_version, to_version, *, copy_files=False):
    """Read metadata and existing bindings only; never import code or create files."""
    if API_VERSION not in manifest.core_api:
        raise WidgetError('Migration target is incompatible with this core API.')
    database = Path(database).resolve()
    slug(from_provider, 'source provider')
    try:
        source_version = Version(from_version)
    except (InvalidVersion, TypeError) as error:
        raise WidgetError('Supply the exact recorded source version.') from error
    if str(manifest.version) != to_version:
        raise WidgetError('Selected target version differs from the reviewed target version.')
    identity = f'{from_provider}/{manifest.id}'
    declaration = manifest.storage_migrations.get(identity)
    if declaration is None or source_version not in declaration.from_version:
        raise WidgetError('Target does not declare compatibility with this source/version.')
    seed = dict(database=str(database), source=identity, from_version=from_version,
                target_manifest=manifest.to_dict())
    if copy_files:
        seed['copy_files'] = True
    request_id = hashlib.sha256(json.dumps(seed, sort_keys=True).encode()).hexdigest()
    try:
        with closing(_connect_readonly(database)) as connection:
            connection.execute('BEGIN')
            row = connection.execute('SELECT provider,version,storage_kind FROM '
                'widget_provider_bindings WHERE widget_id=?', (manifest.id,)).fetchone()
            if not row:
                raise WidgetError('No stored source binding; start the original provider first.')
            kind = 'legacy' if _legacy(manifest) else 'isolated'
            if row == (manifest.provider, to_version, kind):
                exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()
                previous = connection.execute(f'SELECT plan_json FROM {TABLE} WHERE request_id=?', (request_id,)).fetchone() if exists else None
                if previous:
                    return {**json.loads(previous[0]), 'already_applied': True}
            if row[0] == manifest.provider and row[2] == kind:
                raise WidgetError('Version-only upgrades belong to the existing widget schema migration path.')
            if row[0] != from_provider or row[1] is None or row[1] != from_version:
                raise WidgetError('Stored source provider/version differs from the reviewed migration.')
            source = _path(database, from_provider, manifest.id, row[2])
            target = _path(database, manifest.provider, manifest.id, kind)
            result = dict(request_id=request_id, widget=manifest.id, from_provider=from_provider,
                from_version=row[1], from_kind=row[2], to_provider=manifest.provider,
                to_version=to_version, to_kind=kind, database=str(database),
                source_database=str(source), target_database=str(target),
                entry_point=declaration.entry_point, already_applied=False,
                source_files=_managed_files(database, from_provider, manifest.id),
                target_files=_managed_files(database, manifest.provider, manifest.id))
            identity = dict(request_id=request_id, from_kind=row[2],
                            source_database=str(source), target_database=str(target))
            if copy_files:
                result.update(copy_files=True,
                    source_file_hashes=files.fingerprints(result, 'source'),
                    target_file_hashes=files.fingerprints(result, 'target'))
                identity.update(source_files=result['source_file_hashes'], target_files=result['target_file_hashes'])
            result['plan_id'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            return result
    except (sqlite3.Error, OSError) as error:
        raise WidgetError('Cannot read stored migration bindings; no changes made.') from error


def _authorize(action, first, second, database, trigger):
    # Transaction boundaries belong to the runner, not the callback. This also
    # prevents executescript's implicit commit from escaping failure rollback.
    forbidden = {sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT,
                 sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}
    introspection = {'table_info', 'table_xinfo', 'index_info', 'index_xinfo',
                     'index_list', 'foreign_key_list', 'foreign_key_check'}
    if action in forbidden or (action == sqlite3.SQLITE_PRAGMA and first not in introspection):
        return sqlite3.SQLITE_DENY
    if database == 'registry' or first in {'widget_provider_bindings', TABLE}:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK



def _backup(proposed):
    root = Path(proposed['database']).parent
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + secrets.token_hex(4)
    destination = root / 'widget-migration-backups' / name
    destination.mkdir(parents=True, mode=0o700)
    for path in dict.fromkeys(Path(proposed[key]) for key in ('database', 'source_database', 'target_database')):
        if not path.exists():
            continue
        target = destination / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(_connect_readonly(path)) as source, closing(sqlite3.connect(target)) as copied, copied:
            source.backup(copied)
        target.chmod(0o600)
    if proposed.get('copy_files'):
        files.backup_files(proposed, destination)
    return str(destination)


def execute(manifest, database, from_provider, from_version, to_version, *,
            plan_id, offline=False, copy_files=False):
    """Apply a reviewed plan atomically; caller must stop the application first.

    Hooks receive (read_only_source_connection, transactional_target_connection).
    Managed files are copied unchanged only with explicit copy_files approval.
    Plugins remain trusted Python code; authorizers protect accidental SQL misuse.
    """
    if not offline:
        raise WidgetError('Stop the application and explicitly confirm offline operation.')
    files.require_recovered(database)
    proposed = plan(manifest, database, from_provider, from_version, to_version, copy_files=copy_files)
    if proposed['plan_id'] != plan_id:
        raise WidgetError('Plan changed; review a new dry-run plan before migration.')
    if proposed['already_applied']:
        return proposed
    if (proposed['source_files'] or proposed['target_files']) and not copy_files:
        raise WidgetError('File-bearing stores require file-aware migration support; no changes made.')
    pending = files.pending(database)
    if copy_files:
        try:
            pending.mkdir(mode=0o700)
            files.sync_directory(pending.parent)
        except OSError as error:
            raise WidgetError('Cannot reserve file migration; recover any unfinished operation first.') from error
    try:
        proposed['backup_directory'] = _backup(proposed)
    except (OSError, sqlite3.Error) as error:
        if copy_files:
            files.recover(database, offline=True)
        raise WidgetError('Cannot back up migration stores; provider binding unchanged.') from error
    try:
        journal = files.stage(proposed) if copy_files else None
        if copy_files and plan(manifest, database, from_provider, from_version, to_version,
                               copy_files=True)['plan_id'] != plan_id:
            raise WidgetError('Plan changed during staging; review a new dry-run plan.')
        result = _execute_sql(manifest, proposed, to_version, journal)
    except Exception as error:
        if copy_files:
            files.recover(database, offline=True)
        if isinstance(error, WidgetError):
            raise
        raise WidgetError('Migration staging failed; provider binding unchanged.') from error
    if copy_files:
        files.recover(database, offline=True)
    return result


def _execute_sql(manifest, proposed, to_version, journal=None):
    target_path = Path(proposed['target_database'])
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(target_path)) as target, target:
            schema = 'main'
            if target_path != Path(proposed['database']):
                target.execute('ATTACH DATABASE ? AS registry', (proposed['database'],))
                schema = 'registry'
                for name in ('main', 'registry'):
                    if target.execute(f'PRAGMA {name}.journal_mode').fetchone()[0] not in {'delete', 'truncate', 'persist'}:
                        raise WidgetError('Cross-database migration requires durable rollback journals; configuration left unchanged.')
            target.execute('PRAGMA foreign_keys=ON')
            target.execute('BEGIN IMMEDIATE')
            binding = target.execute(f'SELECT provider,version,storage_kind FROM {schema}.widget_provider_bindings WHERE widget_id=?', (manifest.id,)).fetchone()
            if binding != (proposed['from_provider'], proposed['from_version'], proposed['from_kind']):
                raise WidgetError('Source binding changed; review the migration again.')
            source_path = Path(proposed['source_database'])
            source = _connect_readonly(source_path) if source_path.exists() else sqlite3.connect(':memory:')
            try:
                source.row_factory = target.row_factory = sqlite3.Row
                source.execute('PRAGMA query_only=ON')
                source.execute('BEGIN')
                source.set_authorizer(_authorize)
                target.set_authorizer(_authorize)
                module, name = proposed['entry_point'].split(':')
                callback = import_module(module)
                for part in name.split('.'):
                    callback = getattr(callback, part)
                if not callable(callback):
                    raise WidgetError('Migration hook is not callable.')
                callback(source, target)
            finally:
                # Release the read snapshot before the attached registry commits.
                source.close()
                target.set_authorizer(None)
            target.execute(f'''CREATE TABLE IF NOT EXISTS {schema}.{TABLE} (
                id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, plan_json TEXT NOT NULL, completed_at TEXT NOT NULL)''')
            target.execute(f'UPDATE {schema}.widget_provider_bindings SET provider=?,version=?,storage_kind=? WHERE widget_id=?',
                (manifest.provider, to_version, proposed['to_kind'], manifest.id))
            target.execute(f'INSERT INTO {schema}.{TABLE} VALUES(?,?,?,?)',
                (proposed['plan_id'], proposed['request_id'], json.dumps(proposed, sort_keys=True), timestamp()))
            if journal is not None:
                files.install(proposed['database'], journal)
    except WidgetError:
        raise
    except Exception as error:
        raise WidgetError('Migration failed; SQLite data and provider binding rolled back.') from error
    return {**proposed, 'already_applied': True}
