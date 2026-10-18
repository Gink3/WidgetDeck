"""Versioned registration contract for bundled and separately installed widgets."""
from dataclasses import dataclass, field
from importlib import import_module
import re

from .manifest import API_VERSION, Manifest, WidgetError, read_manifest


@dataclass
class Contributions:
    navigation: list = field(default_factory=list)
    services: dict = field(default_factory=dict)
    settings: list = field(default_factory=list)
    search: dict = field(default_factory=dict)
    activity: dict = field(default_factory=dict)
    resolvers: dict = field(default_factory=dict)


class Context:
    """A trusted widget's contribution interface; this is not a code sandbox."""
    def __init__(self, manifest, contributions, capabilities=(), *, storage=None):
        self.manifest = manifest
        self.storage = storage
        self.contributions = contributions
        self.capabilities = frozenset(capabilities)
        if self.capabilities - set(manifest.capabilities):
            raise WidgetError(f'{manifest.identity}: enabled undeclared capabilities.')

    def mail(self):
        from dashboard.mail import MailError, WidgetMail
        if 'mail' not in self.capabilities:
            raise MailError('This widget has not been granted the mail capability.')
        return WidgetMail(self.manifest.identity)

    def navigation(self, category, label, endpoint, *, icon='', description='',
                   action_label=None, action_url=None, position=0):
        category = self.manifest.default_category or category
        if any(link['id'] == self.manifest.id for link in self.contributions.navigation):
            raise WidgetError(f'Duplicate navigation ID: {self.manifest.id}.')
        if not all(isinstance(x, str) and x for x in (category, label, endpoint)):
            raise WidgetError('Navigation requires category, label and endpoint.')
        if type(position) is not int:
            raise WidgetError('Navigation position must be an integer.')
        self.contributions.navigation.append(dict(id=self.manifest.id, category=category,
            label=label, endpoint=endpoint, icon=icon, description=description,
            action_label=action_label, action_url=action_url, position=position))

    def api_service(self, ident, label, prefix):
        if not isinstance(ident, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', ident):
            raise WidgetError('Invalid API service ID.')
        if not isinstance(label, str) or not label:
            raise WidgetError('API services require a label.')
        if not isinstance(prefix, str) or not prefix.startswith('/') or not prefix.endswith('/') or any(c in prefix for c in '?#!<>'):
            raise WidgetError('API prefixes must be literal absolute paths ending in /.')
        for old, service in self.contributions.services.items():
            if old == ident or prefix.startswith(service['prefix']) or service['prefix'].startswith(prefix):
                raise WidgetError(f'Conflicting API service: {ident}.')
        self.contributions.services[ident] = dict(label=label, prefix=prefix)

    def settings(self, template, update=None):
        if not isinstance(template, str) or not template or template.startswith('/') or '..' in template.split('/'):
            raise WidgetError('Settings must use a package-relative template.')
        if update is not None and not callable(update):
            raise WidgetError('Settings update hook must be callable.')
        self.contributions.settings.append(dict(widget=self.manifest.id, template=template, update=update))

    def search(self, name, provider):
        if not callable(provider) or name in self.contributions.search:
            raise WidgetError(f'Invalid or duplicate search provider: {name}.')
        self.contributions.search[name] = provider

    def resolve(self, resolver):
        if not callable(resolver) or self.manifest.id in self.contributions.resolvers:
            raise WidgetError(f'Invalid or duplicate resolver: {self.manifest.id}.')
        self.contributions.resolvers[self.manifest.id] = resolver

    def activity(self, area, label):
        if not isinstance(area, str) or not area or not isinstance(label, str) or not label or area in self.contributions.activity:
            raise WidgetError(f'Invalid or duplicate activity area: {area}.')
        self.contributions.activity[area] = label


def register(app, manifests, *, capabilities=None):
    """Register a preselected dependency-ordered sequence after metadata validation.

    Source selection and dependency resolution are separate from execution. Flask
    applications cannot roll back arbitrary plugin initialization; discard an app
    whose registration fails instead of serving it or retrying its registration.
    """
    if 'dashboard_widgets' in app.extensions:
        raise WidgetError('Widgets have already been registered on this application.')
    manifests = list(manifests)
    seen = set()
    grants = capabilities or {}
    for manifest in manifests:
        if not isinstance(manifest, Manifest):
            raise WidgetError('Registration requires validated Manifest objects.')
        if manifest.id in seen:
            raise WidgetError(f'Multiple providers selected for {manifest.id}.')
        if API_VERSION not in manifest.core_api:
            raise WidgetError(f'{manifest.identity}: incompatible core API {API_VERSION}.')
        if set(grants.get(manifest.id, ())) - set(manifest.capabilities):
            raise WidgetError(f'{manifest.identity}: enabled undeclared capabilities.')
        seen.add(manifest.id)
    if set(grants) - seen:
        raise WidgetError('Capability grants reference an unselected widget.')
    from .dependencies import dependency_order
    manifests = dependency_order(manifests)
    from .storage import prepare
    storage = prepare(app, manifests)
    core_routes = tuple(str(rule) for rule in app.url_map.iter_rules())
    state = dict(manifests=tuple(manifests), contributions=Contributions(), ready=False, storage=storage)
    app.extensions['dashboard_widgets'] = state
    try:
        for manifest in manifests:
            context = Context(manifest, state['contributions'], grants.get(manifest.id, ()),
                              storage=storage[manifest.id])
            module, path = manifest.entry_point.split(':')
            factory = import_module(module)
            for part in path.split('.'):
                factory = getattr(factory, part)
            if not callable(factory):
                raise WidgetError(f'{manifest.identity}: entry point is not callable.')
            factory(app, context)
        claims = {}
        for rule in app.url_map.iter_rules():
            for method in rule.methods - {'OPTIONS'}:
                shape = re.sub(r'<(?:(?:[^:<>]+):)?[^<>]+>', '<parameter>', str(rule))
                key = (shape, method)
                if key in claims and claims[key] != rule.endpoint:
                    raise WidgetError(f'Conflicting route: {method} {rule}.')
                claims[key] = rule.endpoint
        for service in state['contributions'].services.values():
            if any(route.startswith(service['prefix']) for route in core_routes):
                raise WidgetError('An API service prefix overlaps a core route.')
        state['ready'] = True
    except Exception as error:
        raise WidgetError(f'{manifest.identity}: registration failed; discard this application.') from error
    return state
