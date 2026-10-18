"""Kanban initialization and compatible independently installed campaign groups."""
from importlib import import_module


def init_campaign_tools(app, utilities=None):
    from .routes import blueprint_for
    from dashboard.legacy_widgets import available
    if utilities is None:
        utilities = ['kanban'] + [name for name in ('rdt', 'frostgrave') if available(name)]
    selected = tuple(utilities)
    blueprint = blueprint_for(selected)
    done = app.extensions.setdefault('campaign_utilities', set())
    pending = [name for name in selected if name not in done]
    if not pending:
        return
    blueprint = blueprint_for(pending)
    for utility in pending:
        import_module(f'.{utility}_models', __package__).init_database(app)
    if 'campaign_tools' not in app.blueprints:
        from flask import Blueprint
        app.register_blueprint(Blueprint('campaign_tools', __name__))
    state = blueprint.make_setup_state(app, {}, first_registration=True)
    for callback in blueprint.deferred_functions:
        callback(state)
    done.update(pending)


def __getattr__(name):
    if name == 'campaign_tools':
        from .routes import campaign_tools
        return campaign_tools
    raise AttributeError(name)
