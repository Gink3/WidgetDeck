"""Source-qualified widget selection, separate from importing executable code."""
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from .manifest import API_VERSION, Manifest, WidgetError, read_manifest, slug


@dataclass(frozen=True)
class Source:
    kind: str
    repository: str
    subdirectory: str = '.'

    def __post_init__(self):
        if not isinstance(self.kind, str) or self.kind not in {'local', 'git', 'installed'}:
            raise WidgetError('Source kind must be local, git or installed.')
        if not isinstance(self.repository, str) or not self.repository or any(ord(c) < 32 for c in self.repository):
            raise WidgetError('Source repository is required and cannot contain control characters.')
        if not isinstance(self.subdirectory, str):
            raise WidgetError('Source subdirectory must be relative.')
        directory = PurePosixPath(self.subdirectory)
        if directory.is_absolute() or '..' in directory.parts or '\\' in self.subdirectory:
            raise WidgetError('Source subdirectory must remain inside its repository.')
        object.__setattr__(self, 'subdirectory', str(directory))
        if self.kind == 'local':
            root = Path(self.repository).expanduser().resolve()
            package = (root / self.subdirectory).resolve()
            if not package.is_relative_to(root):
                raise WidgetError('Source subdirectory escapes its repository through a symlink.')
            object.__setattr__(self, 'repository', str(root))
        elif self.kind == 'git':
            try:
                parts = urlsplit(self.repository)
                if parts.scheme in {'https', 'ssh'}:
                    parts.port  # Validate malformed/out-of-range ports.
            except ValueError as error:
                raise WidgetError('Invalid Git source URL.') from error
            scp = re.fullmatch(r'[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+:[^\s]+', self.repository)
            if not scp and (parts.scheme not in {'https', 'ssh'} or not parts.hostname or parts.password
                            or (parts.scheme == 'https' and parts.username) or parts.query or parts.fragment):
                raise WidgetError('Git source must use credential-free HTTPS or SSH.')
        elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', self.repository):
            raise WidgetError('Installed sources require a distribution name.')

    def to_dict(self):
        return dict(kind=self.kind, repository=self.repository, subdirectory=self.subdirectory)


@dataclass(frozen=True)
class Candidate:
    manifest: Manifest
    source: Source

    @classmethod
    def local(cls, repository, subdirectory='.'):
        source = Source('local', str(repository), subdirectory)
        return cls(read_manifest(Path(source.repository) / source.subdirectory / 'widget.json'), source)


@dataclass(frozen=True)
class Selection:
    provider: str
    version: str = '>=0'

    def __post_init__(self):
        slug(self.provider, 'selected provider')
        try:
            if not isinstance(self.version, str) or not self.version:
                raise WidgetError('Selected version range must be nonempty.')
            SpecifierSet(self.version)
        except InvalidSpecifier as error:
            raise WidgetError('Invalid selected version range.') from error


def select(candidates, selections, *, bindings=None):
    """Select one explicitly configured provider/version per logical widget.

    Source bindings are immutable within a resolution. Matching display names,
    another provider, or an incompatible newest release never imply substitution.
    """
    if not isinstance(selections, dict):
        raise WidgetError('Selections must map logical IDs to Selection objects.')
    available = {}
    expected_bindings = bindings or {}
    source_bindings = {}
    for candidate in candidates:
        if not isinstance(candidate, Candidate):
            raise WidgetError('Expected validated widget candidates.')
        manifest = candidate.manifest
        identity = manifest.identity
        if identity in source_bindings and source_bindings[identity] != candidate.source:
            raise WidgetError(f'Conflicting source bindings for {identity}.')
        source_bindings[identity] = candidate.source
        key = (identity, manifest.version)
        if key in available:
            raise WidgetError(f'Duplicate candidate: {identity} {manifest.version}.')
        available[key] = candidate
    result = {}
    for ident, selection in selections.items():
        slug(ident, 'selected widget ID')
        if not isinstance(selection, Selection):
            raise WidgetError(f'{ident}: expected a Selection object.')
        identity = f'{selection.provider}/{ident}'
        constraint = SpecifierSet(selection.version)
        matches = [c for (key, version), c in available.items() if key == identity
                   and constraint.contains(version, prereleases=bool(constraint.prereleases))
                   and API_VERSION in c.manifest.core_api]
        if not matches:
            raise WidgetError(f'No compatible candidate for {identity} ({selection.version}).')
        chosen = max(matches, key=lambda c: c.manifest.version)
        if identity in expected_bindings and expected_bindings[identity] != chosen.source:
            raise WidgetError(f'Source binding changed for {identity}; explicit migration is required.')
        result[ident] = chosen
    return result


def installed_candidates():
    """Read metadata for dashboard.widgets entry points without importing them.

    Each distribution contains exactly one packaged widget.json. Installation is
    separate from discovery; only explicit selection permits code execution.
    """
    result = []
    for entry in entry_points(group='dashboard.widgets'):
        distribution = entry.dist
        files = [f for f in distribution.files or () if PurePosixPath(str(f)).name == 'widget.json']
        if len(files) != 1:
            raise WidgetError('Widget distributions must package exactly one widget.json.')
        manifest = read_manifest(distribution.locate_file(files[0]))
        if manifest.entry_point != entry.value or entry.name != manifest.id:
            raise WidgetError(f'{manifest.identity}: entry point metadata does not match manifest.')
        if str(manifest.version) != distribution.version:
            raise WidgetError(f'{manifest.identity}: distribution and manifest versions differ.')
        result.append(Candidate(manifest, Source('installed', distribution.name)))
    return result
