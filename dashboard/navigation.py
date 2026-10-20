"""One category map for the home launcher and searchable utility navigation."""
from flask import current_app, request, url_for

GROUPS = [('Games', [('wordle', 'Wordle', 'wordle.index')]), ('Knowledge', [('wiki', 'Wiki', 'wiki.index'), ('mind-maps', 'Mind Maps', 'mindmaps.index')]), ('Tools', [('kanban', 'Kanban', 'campaign_tools.kanban'), ('image-converter', 'Image Converter', 'image_converter.index')])]
METADATA = {'wordle': {'icon': '▦', 'description': 'Unlimited five, six, and seven-letter English puzzles with private statistics and hard mode.'}, 'wiki': {'icon': '▤', 'description': 'Write linked Markdown pages, keep notes together, and add images where they help.'}, 'mind-maps': {'icon': '⌘', 'description': 'Build private idea maps, plan projects, and connect the threads that matter.'}, 'kanban': {'icon': '▤', 'description': 'Move cards through a workflow designed around each individual project.'}, 'image-converter': {'icon': '▧', 'description': 'Convert AVIF, PNG, JPEG, and WebP images right in your browser workflow.'}}
ACTIONS = {'wordle': ('Play Wordle', '/tools/wordle'), 'wiki': ('New wiki page', '/tools/wiki/new'), 'mind-maps': ('New mind map', '/tools/mindmaps/new'), 'kanban': ('New board', '/tools/kanban?new=1'), 'image-converter': ('Convert an image', '/tools/image-converter')}


def utility_groups(personalized=True):
    state = current_app.extensions.get('dashboard_widgets')
    if state is None:
        entries = []
        for category, utilities in GROUPS:
            for position, (ident, label, endpoint) in enumerate(utilities):
                action = ACTIONS.get(ident, (None, None))
                entries.append(dict(id=ident, label=label, endpoint=endpoint, category=category,
                    position=position, action_label=action[0], action_url=action[1], **METADATA[ident]))
    else:
        entries = state['contributions'].navigation
    entries = [dict(entry, default_category=entry['category']) for entry in entries]
    if personalized:
        from dashboard.utility_categories import preferences
        custom, overrides = preferences()
        known = {entry['category'].casefold(): entry['category'] for entry in entries}
        for item in custom:
            known[item['name'].casefold()] = item['name']
        for name in overrides.values():
            known.setdefault(name.casefold(), name)
        for entry in entries:
            override = overrides.get(entry['id'])
            entry['category'] = known.get((override or entry['category']).casefold(), entry['category'])
    categories = [name for name, _ in GROUPS]
    groups = {}
    ordered = sorted(entries, key=lambda e: (categories.index(e['category']) if e['category'] in categories else len(categories),
                                            e['category'], e.get('position', 0), e['id']))
    for entry in ordered:
        endpoint = entry['endpoint']
        external = endpoint.startswith('https://')
        if not external and endpoint not in current_app.view_functions:
            continue
        url = endpoint if external else url_for(endpoint)
        link = {key: value for key, value in entry.items() if key not in {'endpoint', 'position'}}
        link.update(url=url, external=external, active=request.endpoint == endpoint,
                    action_label=entry.get('action_label') or 'Open ' + entry['label'],
                    action_url=entry.get('action_url') or url)
        groups.setdefault(entry['category'], []).append(link)
    return [dict(name=name, links=links) for name, links in groups.items()]


def init_navigation(app):
    @app.context_processor
    def utility_navigation():
        state = current_app.extensions.get('dashboard_widgets')
        templates = [item['template'] for item in state['contributions'].settings] if state is not None else []
        return {'utility_groups': utility_groups(), 'widget_settings': templates}
