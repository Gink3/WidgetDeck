"""Persistent provider claims and storage for trusted widgets.

The legacy layouts are compatibility exceptions, not permission to share storage
between new providers. This module does not sandbox executable widget code.
"""
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from dashboard.database import init_database
from .manifest import WidgetError, slug

# Preserve the pre-framework owners even when their widgets are disabled during
# the first upgrade. Names and table markers contain no optional widget content.
LEGACY = {
    'wiki': ('dashboard', 'wiki_pages'),
    'mind-maps': ('dashboard', 'mind_maps'),
    'kanban': ('dashboard', 'kanban_boards'),
    'wordle': ('dashboard', 'wordle_games'),
    'image-converter': ('dashboard', None),
    'four-against-darkness': ('personal', 'four_ad_records'),
    'zettelkasten': ('personal', 'zettels'),
    'flashcards': ('personal', 'flashcard_decks'),
    'paint-rack': ('personal', 'paint_rack_inventory'),
    'chapter-painter': ('personal', 'chapter_painter_schemes'),
    'notebook-cover-generator': ('personal', None),
    'grimdark-future': ('personal', None),
    'frontline-command': ('personal', None),
    'frostgrave': ('personal', 'frostgrave_parties'),
    'roguelike-death-tracker': ('personal', 'rdt_tables'),
    'menagerie': ('personal', None),
}


@dataclass(frozen=True)
class Storage:
    """Paths remain stable across versions; account scoping is the widget's job."""
    directory: Path
    database: Path
    legacy: bool = False

    @contextmanager
    def connect(self):
        """Commit on success, roll back on error, and always close the connection."""
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def _legacy(manifest):
    owner = LEGACY.get(manifest.id)
    if not owner or owner[0] != manifest.provider:
        return False
    if manifest.provider == 'dashboard':
        return manifest.entry_point == 'dashboard.widgets.bundled:register_widget'
    module = {'four-against-darkness': 'four_ad', 'roguelike-death-tracker': 'rdt',
              'notebook-cover-generator': 'notebook_covers'}.get(
        manifest.id, manifest.id.replace('-', '_'))
    return manifest.entry_point == f'dashboard_private_widgets.{module}:register'


def prepare(app, manifests):
    """Reserve all provider claims atomically, before importing any factory.

    Claims survive failed registration and disabling: an initializer may already
    have written data before failing. An operator must review migration rather
    than allowing another provider to claim that data on the next startup.
    """
    manifests = list(manifests)
    for manifest in manifests:
        slug(manifest.id, 'id')
        slug(manifest.provider, 'provider')
    init_database(app)
    database = Path(app.config['FOUR_AD_DATABASE']).resolve()
    root = database.parent / 'widget-storage'
    storage = {}
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('''CREATE TABLE IF NOT EXISTS widget_provider_bindings (
            widget_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
            version TEXT, storage_kind TEXT NOT NULL)''')
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        existing = {row[0]: row[1:] for row in connection.execute(
            'SELECT widget_id, provider, version, storage_kind FROM widget_provider_bindings')}
        for ident, (provider, marker) in LEGACY.items():
            if marker in tables and ident not in existing:
                connection.execute('INSERT INTO widget_provider_bindings VALUES(?,?,NULL,?)',
                                   (ident, provider, 'legacy'))
                existing[ident] = (provider, None, 'legacy')
        for manifest in manifests:
            previous = existing.get(manifest.id)
            kind = 'legacy' if _legacy(manifest) else 'isolated'
            if previous and (previous[0] != manifest.provider or previous[2] != kind):
                raise WidgetError(
                    f'{manifest.id}: stored provider {previous[0]} cannot be replaced by '
                    f'{manifest.provider}; a reviewed storage migration is required.')
            connection.execute('''INSERT INTO widget_provider_bindings VALUES(?,?,?,?)
                ON CONFLICT(widget_id) DO UPDATE SET version=excluded.version''',
                (manifest.id, manifest.provider, str(manifest.version), kind))
            directory = root / manifest.provider / manifest.id
            storage[manifest.id] = Storage(directory, database if kind == 'legacy'
                                           else directory / 'data.sqlite', kind == 'legacy')
    return storage
