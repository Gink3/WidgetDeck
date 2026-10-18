"""Compatible exports for the independently initialized campaign utilities."""
from importlib import import_module
from dashboard.database import db, timestamp
from .common_models import _owner_id, _owned

_EXPORTS = {'rdt_tables': 'rdt', 'rdt_table': 'rdt', 'create_rdt': 'rdt', 'rdt_fields': 'rdt', 'rdt_entries': 'rdt', 'add_rdt_entry': 'rdt', 'kanban_boards': 'kanban', 'kanban_board': 'kanban', 'kanban_board_snapshot': 'kanban', 'create_kanban': 'kanban', 'kanban_columns': 'kanban', 'kanban_items': 'kanban', 'ItemConflict': 'kanban', 'reorder_kanban_columns': 'kanban', 'kanban_item': 'kanban', 'kanban_item_detail': 'kanban', '_item_history': 'kanban', 'add_kanban_item': 'kanban', '_place_item': 'kanban', '_check_revision': 'kanban', 'move_kanban_item': 'kanban', 'update_kanban_item': 'kanban', 'transfer_kanban_item': 'kanban', 'delete_kanban_item': 'kanban', 'cancel_kanban_item': 'kanban', 'frostgrave_parties': 'frostgrave', 'frostgrave_party': 'frostgrave', 'create_frostgrave_party': 'frostgrave', 'frostgrave_characters': 'frostgrave', 'add_frostgrave_character': 'frostgrave', 'frostgrave_character': 'frostgrave', 'save_frostgrave_character': 'frostgrave', 'save_frostgrave_reference': 'frostgrave', 'manage_kanban_column': 'kanban', 'kanban_comments': 'kanban', 'change_kanban_comment': 'kanban', 'kanban_links': 'kanban', 'update_kanban_links': 'kanban'}

from dashboard.legacy_widgets import available
__all__ = [name for name, group in _EXPORTS.items() if group == 'kanban' or available(group)] + ['init_database', 'db', 'timestamp']


def init_database(app):
    from dashboard.legacy_widgets import available
    for utility in ['kanban'] + [name for name in ('rdt', 'frostgrave') if available(name)]:
        import_module(f'.{utility}_models', __package__).init_database(app)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    return getattr(import_module(f'.{_EXPORTS[name]}_models', __package__), name)


def __dir__():
    return sorted(set(globals()) | set(__all__))
