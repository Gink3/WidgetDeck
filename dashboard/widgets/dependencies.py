"""Widget-level compatibility resolution; Python packages are resolved by pip."""
from packaging.specifiers import SpecifierSet

from .manifest import API_VERSION, WidgetError
from .sources import select


def dependency_order(manifests):
    """Validate an exact selection and return deterministic dependency-first order."""
    manifests = list(manifests)
    by_id = {manifest.id: manifest for manifest in manifests}
    if len(by_id) != len(manifests):
        raise WidgetError('Multiple providers or versions selected for one logical widget.')
    for manifest in manifests:
        if API_VERSION not in manifest.core_api:
            raise WidgetError(f'{manifest.identity}: incompatible core API {API_VERSION}.')
        for ident, constraint in manifest.dependencies.items():
            if ident not in by_id:
                raise WidgetError(f'{manifest.identity}: dependency {ident} must be explicitly selected.')
            dependency = by_id[ident]
            if not constraint.contains(dependency.version, prereleases=True):
                raise WidgetError(f'{manifest.identity}: {ident} {dependency.version} does not satisfy {constraint}.')
    ordered, visiting, complete = [], set(), set()
    def visit(ident):
        if ident in visiting:
            raise WidgetError(f'Widget dependency cycle at {ident}.')
        if ident in complete:
            return
        visiting.add(ident)
        for dependency in sorted(by_id[ident].dependencies):
            visit(dependency)
        visiting.remove(ident)
        complete.add(ident)
        ordered.append(by_id[ident])
    for ident in sorted(by_id):
        visit(ident)
    return ordered


def resolve(candidates, selections, *, bindings=None):
    """Resolve compatible versions without adding providers or importing code.

    Prefer newer stable versions, but backtrack when another selected widget needs
    an older compatible version. Provider/source choices are never backtracked.
    """
    candidates = list(candidates)
    select(candidates, selections, bindings=bindings)  # Validate sources and root choices.
    options = {}
    for ident, selection in selections.items():
        constraint = SpecifierSet(selection.version)
        options[ident] = sorted((c for c in candidates
            if c.manifest.id == ident and c.manifest.provider == selection.provider
            and constraint.contains(c.manifest.version, prereleases=bool(constraint.prereleases))
            and API_VERSION in c.manifest.core_api),
            key=lambda c: c.manifest.version, reverse=True)
    identities = sorted(options)
    chosen = {}
    last_error = None
    def compatible():
        for candidate in chosen.values():
            for ident, constraint in candidate.manifest.dependencies.items():
                if ident not in options:
                    return False
                if ident in chosen and not constraint.contains(chosen[ident].manifest.version, prereleases=True):
                    return False
        return True
    def search(index):
        nonlocal last_error
        if index == len(identities):
            try:
                ordered = dependency_order(c.manifest for c in chosen.values())
            except WidgetError as error:
                last_error = error
                return None
            return [chosen[m.id] for m in ordered]
        ident = identities[index]
        for candidate in options[ident]:
            chosen[ident] = candidate
            if compatible():
                result = search(index + 1)
                if result is not None:
                    return result
            chosen.pop(ident)
        return None
    result = search(0)
    if result is None:
        detail = f' {last_error}' if last_error else ' Check dependency ranges and explicitly selected dependencies.'
        raise WidgetError('No compatible acyclic widget selection.' + detail)
    return result
