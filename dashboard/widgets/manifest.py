"""Declarative widget metadata; reading a manifest never imports widget code."""
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from types import MappingProxyType

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

API_VERSION = Version('1.4.0')
SLUG = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z')
ENTRY_POINT = re.compile(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\Z')


class WidgetError(ValueError):
    """Invalid metadata, configuration, or registration of a selected widget."""


@dataclass(frozen=True)
class StorageMigration:
    from_version: SpecifierSet
    entry_point: str


def slug(value, field):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise WidgetError(f'{field} must be a lowercase hyphenated identifier.')
    return value


@dataclass(frozen=True)
class Manifest:
    id: str
    provider: str
    name: str
    version: Version
    core_api: SpecifierSet
    entry_point: str
    dependencies: object
    capabilities: tuple
    schema_version: int = 1
    default_category: str | None = None
    storage_migrations: object = field(default_factory=lambda: MappingProxyType({}))

    @property
    def identity(self):
        return f'{self.provider}/{self.id}'

    @classmethod
    def from_dict(cls, document):
        fields = {'schema_version', 'id', 'provider', 'name', 'version', 'core_api',
                  'entry_point', 'dependencies', 'capabilities', 'default_category', 'storage_migrations'}
        if not isinstance(document, dict) or set(document) - fields:
            raise WidgetError('Manifest must be an object containing only supported fields.')
        if type(document.get('schema_version')) is not int or document['schema_version'] != 1:
            raise WidgetError('Manifest schema_version must be 1.')
        ident = slug(document.get('id'), 'id')
        provider = slug(document.get('provider'), 'provider')
        name = document.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 160:
            raise WidgetError('name must contain 1–160 characters.')
        raw_version = document.get('version')
        if not isinstance(raw_version, str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:(?:a|b|rc)\d+|\.post\d+|\.dev\d+)?', raw_version):
            raise WidgetError('version must use MAJOR.MINOR.PATCH with an optional Python prerelease suffix.')
        try:
            version = Version(raw_version)
            raw_api = document.get('core_api')
            if not isinstance(raw_api, str) or not raw_api:
                raise WidgetError('core_api must declare a nonempty compatibility range.')
            core_api = SpecifierSet(raw_api)
        except (InvalidVersion, InvalidSpecifier) as error:
            raise WidgetError('Invalid version or core_api constraint.') from error
        entry = document.get('entry_point')
        if not isinstance(entry, str) or not ENTRY_POINT.fullmatch(entry):
            raise WidgetError('entry_point must use module:callable syntax.')
        dependencies = document.get('dependencies', {})
        if not isinstance(dependencies, dict):
            raise WidgetError('dependencies must map logical widget IDs to version ranges.')
        parsed = {}
        for dependency, constraint in dependencies.items():
            slug(dependency, 'dependency')
            if dependency == ident:
                raise WidgetError('A widget cannot depend on itself.')
            if not isinstance(constraint, str) or not constraint:
                raise WidgetError(f'{dependency}: dependency range must be nonempty.')
            try:
                parsed[dependency] = SpecifierSet(constraint)
            except InvalidSpecifier as error:
                raise WidgetError(f'{dependency}: invalid dependency range.') from error
        capabilities = document.get('capabilities', [])
        if not isinstance(capabilities, list) or len(set(str(c) for c in capabilities)) != len(capabilities):
            raise WidgetError('capabilities must be a list of unique identifiers.')
        for capability in capabilities:
            slug(capability, 'capability')
        category = document.get('default_category')
        if category is not None:
            from dashboard.utility_categories import category_name
            try:
                category = category_name(category)
            except ValueError as error:
                raise WidgetError('Invalid default_category: ' + str(error)) from error
        migrations = document.get('storage_migrations', {})
        if not isinstance(migrations, dict):
            raise WidgetError('storage_migrations must map source identities to migration declarations.')
        converted = {}
        for identity, migration in migrations.items():
            if not isinstance(identity, str) or identity.count('/') != 1:
                raise WidgetError('Migration source must use provider/widget identity.')
            source, widget = identity.split('/')
            slug(source, 'migration provider')
            if widget != ident:
                raise WidgetError('Migration source must have the same logical widget ID.')
            if not isinstance(migration, dict) or set(migration) != {'from_version', 'entry_point'}:
                raise WidgetError('Migration requires only from_version and entry_point.')
            constraint, hook = migration['from_version'], migration['entry_point']
            if not isinstance(constraint, str) or not constraint:
                raise WidgetError('Migration from_version must be a nonempty version range.')
            try:
                constraint = SpecifierSet(constraint)
            except InvalidSpecifier as error:
                raise WidgetError('Invalid migration source version range.') from error
            if not isinstance(hook, str) or not ENTRY_POINT.fullmatch(hook):
                raise WidgetError('Migration entry_point must use module:callable syntax.')
            converted[identity] = StorageMigration(constraint, hook)
        return cls(ident, provider, name.strip(), version, core_api, entry,
                   MappingProxyType(parsed), tuple(capabilities), default_category=category,
                   storage_migrations=MappingProxyType(converted))

    def to_dict(self):
        result = {'schema_version': self.schema_version, 'id': self.id, 'provider': self.provider,
                'name': self.name, 'version': str(self.version), 'core_api': str(self.core_api),
                'entry_point': self.entry_point,
                'dependencies': {k: str(v) for k, v in self.dependencies.items()},
                'capabilities': list(self.capabilities)}
        if self.default_category is not None:
            result['default_category'] = self.default_category
        if self.storage_migrations:
            result['storage_migrations'] = {identity: dict(from_version=str(migration.from_version),
                entry_point=migration.entry_point) for identity, migration in self.storage_migrations.items()}
        return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WidgetError(f'Duplicate manifest key: {key}.')
        result[key] = value
    return result


def read_manifest(path):
    path = Path(path)
    try:
        if path.stat().st_size > 1024 * 1024:
            raise WidgetError('Manifest exceeds 1 MiB.')
        document = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise WidgetError(f'Cannot read manifest: {path.name}.') from error
    return Manifest.from_dict(document)
