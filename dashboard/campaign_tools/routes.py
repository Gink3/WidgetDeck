"""Legacy blueprint/function exports, with independently selectable route groups."""
from importlib import import_module
from flask import Blueprint
from .common_routes import named_values

METRICS = {"none", "average", "sum", "count"}
_EXPORTS = {'rdt': 'rdt', 'rdt_add_entry': 'rdt', 'kanban': 'kanban', 'kanban_add_item': 'kanban', 'kanban_create_item': 'kanban', 'kanban_reorder_columns': 'kanban', 'kanban_get_item': 'kanban', 'kanban_list_boards': 'kanban', 'kanban_read_board': 'kanban', 'kanban_update_item': 'kanban', 'kanban_move_item': 'kanban', 'kanban_transfer_item': 'kanban', 'kanban_delete_item': 'kanban', 'kanban_cancel_item': 'kanban', 'frostgrave': 'frostgrave', 'frostgrave_add_character': 'frostgrave', 'frostgrave_save_character': 'frostgrave', 'frostgrave_save_reference': 'frostgrave', 'kanban_manage_column': 'kanban', 'kanban_comments': 'kanban', 'kanban_update_links': 'kanban'}

from dashboard.legacy_widgets import available
__all__ = [name for name, group in _EXPORTS.items() if group == 'kanban' or available(group)] + ['campaign_tools', 'named_values', 'METRICS']


def blueprint_for(utilities=None):
    if utilities is None:
        from dashboard.legacy_widgets import available
        utilities = ['kanban'] + [name for name in ('rdt', 'frostgrave') if available(name)]
    utilities = tuple(utilities)
    if len(set(utilities)) != len(utilities) or set(utilities) - {'rdt', 'kanban', 'frostgrave'}:
        raise ValueError('Unknown or duplicate campaign utility.')
    blueprint = Blueprint('campaign_tools', __name__)
    for utility in utilities:
        group = import_module(f'.{utility}_routes', __package__).campaign_tools
        for callback in group.deferred_functions:
            blueprint.record(callback)
    return blueprint


def __getattr__(name):
    if name == 'campaign_tools':
        # Retain the original public blueprint for legacy direct registrations.
        blueprint = blueprint_for()
        globals()['campaign_tools'] = blueprint
        return blueprint
    if name not in _EXPORTS:
        raise AttributeError(name)
    return getattr(import_module(f'.{_EXPORTS[name]}_routes', __package__), name)


def __dir__():
    return sorted(set(globals()) | set(__all__))
