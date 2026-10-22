"""The five bundled public utilities; private packages register their own hooks."""
from importlib import import_module
import json
from pathlib import Path
from .sources import Candidate

ROOT = Path(__file__).resolve().parents[2]


def candidates():
    return [Candidate.local(ROOT, str(path.parent.relative_to(ROOT)))
            for path in sorted((Path(__file__).parent / 'bundled_manifests').glob('*/widget.json'))]


def register_widget(app, context):
    entry = json.loads((Path(__file__).parent / 'catalogue.json').read_text())[context.manifest.id]
    if context.manifest.id == 'kanban':
        from dashboard.campaign_tools import init_campaign_tools
        init_campaign_tools(app, utilities=['kanban'])
    elif 'initializer' in entry:
        module, function = entry['initializer'].split(':')
        getattr(import_module(module), function)(app)
    context.navigation(**entry['navigation'])
    if 'service' in entry:
        context.api_service(**entry['service'])
    if 'search' in entry:
        from dashboard.launcher.search import PROVIDERS
        name = entry['search']
        context.search(name, lambda: PROVIDERS[name]())
        from dashboard.launcher import _legacy_resolve
        context.resolve(lambda resource, kind: _legacy_resolve(context.manifest.id, resource, kind))
    if context.manifest.id in {'wiki', 'kanban'}:
        context.activity(context.manifest.id, context.manifest.name)
    if context.manifest.id == 'wordle':
        app.extensions['wordle_activity'] = context.activity('wordle', 'Wordle', actions={
            'played': {'label': 'Played', 'unit': 'game', 'plural': 'games'},
        })
