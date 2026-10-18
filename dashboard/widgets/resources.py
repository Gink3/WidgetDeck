"""Serve package-owned templates/assets at existing Dashboard URLs."""
from pathlib import Path
from flask import send_from_directory
from jinja2 import ChoiceLoader, FileSystemLoader
from .manifest import WidgetError


def mount_resources(app, root):
    root = Path(root).resolve()
    mounted = app.extensions.setdefault('dashboard_widget_resource_roots', set())
    if root in mounted:
        return
    assets = app.extensions.setdefault('dashboard_widget_assets', {})
    static = root / 'static'
    proposed = {}
    for path in static.rglob('*') if static.is_dir() else ():
        if not path.is_file():
            continue
        relative = path.relative_to(static).as_posix()
        if relative in assets and assets[relative] != path:
            raise WidgetError(f'Duplicate widget asset: {relative}.')
        if app.static_folder and (Path(app.static_folder) / relative).is_file():
            raise WidgetError(f'Widget asset conflicts with core: {relative}.')
        proposed[relative] = path
    if 'dashboard_original_static' not in app.extensions:
        original = app.view_functions.get('static')
        app.extensions['dashboard_original_static'] = original
        def widget_static(filename, **kwargs):
            path = assets.get(filename)
            if path is not None:
                return send_from_directory(path.parent, path.name)
            return original(filename=filename, **kwargs)
        if original is not None:
            app.view_functions['static'] = widget_static
    assets.update(proposed)
    templates = root / 'templates'
    if templates.is_dir():
        app.jinja_loader = ChoiceLoader([app.jinja_loader, FileSystemLoader(templates)])
    mounted.add(root)
