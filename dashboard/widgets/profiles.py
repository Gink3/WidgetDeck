"""Explicit runtime profiles; source acquisition never happens at startup."""
import json
from pathlib import Path
from . import register
from .bundled import ROOT, candidates as bundled_candidates
from .dependencies import resolve
from .manifest import WidgetError, _unique_object
from .sources import Candidate, Selection, Source, installed_candidates


def read_profile(path):
    path = Path(path)
    try:
        if path.stat().st_size > 1024 * 1024:
            raise WidgetError('Profile exceeds 1 MiB.')
        data = json.loads(path.read_text(), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise WidgetError(f'Cannot read profile: {path.name}.') from error
    if not isinstance(data, dict) or set(data) - {'schema_version', 'name', 'sources', 'widgets'}:
        raise WidgetError('Unsupported profile fields.')
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise WidgetError('Profile schema_version must be 1.')
    if not isinstance(data.get('name'), str) or not data['name']:
        raise WidgetError('Profile name is required.')
    if not isinstance(data.get('widgets'), dict) or not isinstance(data.get('sources', []), list):
        raise WidgetError('Profile widgets must be an object and sources a list.')
    selections, capabilities = {}, {}
    for ident, config in data['widgets'].items():
        if not isinstance(config, dict) or set(config) - {'provider', 'version', 'capabilities'}:
            raise WidgetError(f'{ident}: invalid selection fields.')
        selections[ident] = Selection(config.get('provider'), config.get('version', '>=0'))
        grants = config.get('capabilities', [])
        if not isinstance(grants, list) or any(not isinstance(g, str) for g in grants) or len(set(grants)) != len(grants):
            raise WidgetError(f'{ident}: capabilities must be a unique string list.')
        capabilities[ident] = grants
    sources = []
    for config in data.get('sources', []):
        if not isinstance(config, dict) or set(config) - {'kind', 'repository', 'subdirectory'}:
            raise WidgetError('Invalid runtime source fields.')
        kind, repository = config.get('kind'), config.get('repository')
        if kind == 'local' and isinstance(repository, str) and not Path(repository).is_absolute():
            repository = str(path.parent / repository)
        sources.append(Source(kind, repository, config.get('subdirectory', '.')))
    return data, selections, capabilities, sources


def resolve_profile(path):
    data, selections, capabilities, sources = read_profile(path)
    available = bundled_candidates()
    for source in sources:
        if source.kind == 'local':
            available.append(Candidate.local(source.repository, source.subdirectory))
        elif source.kind == 'installed':
            available.extend(c for c in installed_candidates() if c.source == source)
        else:
            raise WidgetError('Git sources must be synchronized and installed before runtime startup.')
    selected = resolve(available, selections)
    for candidate in selected:
        if set(capabilities.get(candidate.manifest.id, ())) - set(candidate.manifest.capabilities):
            raise WidgetError(f'{candidate.manifest.identity}: enabled undeclared capabilities.')
    return data, selected, capabilities


def register_profile(app, path=None):
    path = Path(path) if path else ROOT / 'profiles' / 'compatibility.json'
    profile, selected, capabilities = resolve_profile(path)
    state = register(app, [c.manifest for c in selected], capabilities=capabilities)
    state['profile'], state['candidates'] = profile['name'], tuple(selected)
    return state
