"""Explicit source acquisition and isolated candidate builds; never used at startup."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib

from packaging.specifiers import SpecifierSet
from packaging.utils import parse_wheel_filename
from packaging.version import Version

from .dependencies import dependency_order
from .manifest import API_VERSION, Manifest, WidgetError, _unique_object, slug
from .sources import Source


def _run(*args, cwd=None, env=None):
    clean = {k: v for k, v in os.environ.items() if not k.startswith(('DASHBOARD_', 'WIKI_', 'FOUR_AD_'))}
    clean.update(env or {})
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=clean,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        # Build tools may print private material; never reflect their output.
        raise WidgetError('Management subprocess failed: ' + str(args[0]).split('/')[-1])
    return result.stdout


def _git(repo, *args):
    return _run('git', '-C', repo, *args)


def _json(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=_unique_object)


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _lock_hash(lock):
    return _sha(json.dumps(lock, sort_keys=True).encode())


def _repository(value, base, cache, *, ref=None):
    if not isinstance(value, str) or not value or value.startswith('-') or any(ord(c) < 32 for c in value):
        raise WidgetError('Repository must be a local checkout or credential-free Git URL.')
    local = (base / value).expanduser().resolve()
    if local.exists():
        if _git(local, 'rev-parse', '--is-bare-repository').strip() != b'false':
            raise WidgetError('Local sources must be clean working checkouts.')
        if _git(local, 'status', '--porcelain').strip():
            raise WidgetError('Commit or stash source changes before management operations.')
        return local, str(local)
    Source('git', value)
    cached = cache / _sha(value.encode())
    if cached.is_symlink():
        raise WidgetError('Source cache cannot be a symbolic link.')
    if not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        _run('git', 'init', '--bare', cached)
    if ref is not None:
        _git(cached, 'fetch', '--no-tags', '--no-recurse-submodules', '--', value, ref)
    return cached, value


def _ref(value):
    if not isinstance(value, str) or not value or value.startswith('-') or any(ord(c) < 33 for c in value):
        raise WidgetError('An explicit safe branch, tag or commit is required.')
    return value


def _subdirectory(value):
    if not isinstance(value, str) or not value or ':' in value or '\\' in value:
        raise WidgetError('Invalid package subdirectory.')
    directory = PurePosixPath(value)
    if directory.is_absolute() or '..' in directory.parts:
        raise WidgetError('Package subdirectory must stay inside its repository.')
    return str(PurePosixPath(value))


def _object(commit, subdirectory, filename=None):
    suffix = '' if subdirectory == '.' else subdirectory
    if filename:
        suffix = '/'.join(filter(None, (suffix, filename)))
    return commit + (':' + suffix if suffix else '')


def _archive(repo, revision, subdirectory='.'):
    tree = _object(revision, subdirectory)
    # Reject unacquired submodules as well as links: source locks must be complete.
    for row in _git(repo, 'ls-tree', '-r', '-z', tree).split(b'\0'):
        if row and row.split(b' ', 1)[0] not in (b'100644', b'100755'):
            raise WidgetError('Source archives cannot contain links or submodules.')
    return _git(repo, 'archive', '--format=tar', tree)


def _extract(data, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as bundle:
        for member in bundle.getmembers():
            if not (member.isfile() or member.isdir()):
                raise WidgetError('Unsupported source archive entry.')
        bundle.extractall(destination, filter='data')


def lock(profile, output, cache):
    """Resolve all sources before atomically replacing the lock; imports no hooks."""
    profile, cache = Path(profile).resolve(), Path(cache).resolve()
    config = _json(profile)
    if config.get('schema_version') != 1 or not isinstance(config.get('widgets'), list):
        raise WidgetError('Management profile requires schema_version 1, core and widgets.')
    result = dict(manager_schema_version=1, name=config.get('name', profile.stem),
                  core=None, widgets=[], content_packs=[])

    def source(selection, *, core=False, content=False):
        reference = _ref(selection.get('ref', config.get('widgets_ref')))
        repository = selection.get('repository', config.get('widgets_repository'))
        repo, origin = _repository(repository, profile.parent, cache, ref=reference)
        # Remote fetch need not create a named branch/tag in the cache.
        if not Path(origin).exists():
            revision = _git(repo, 'rev-parse', 'FETCH_HEAD^{commit}').decode().strip()
        else:
            revision = _git(repo, 'rev-parse', '--verify', '--end-of-options', reference + '^{commit}').decode().strip()
        directory = '.' if core else _subdirectory(selection.get('subdirectory',
                    ('content-packs/' if content else 'widgets/') + selection['id']))
        item = dict(repository=origin, ref=reference, revision=revision, subdirectory=directory,
                    archive_sha256=_sha(_archive(repo, revision, directory)))
        if core:
            api_source = _git(repo, 'show', revision + ':dashboard/widgets/manifest.py').decode()
            match = re.search(r"^API_VERSION = Version\(['\"]([^'\"]+)['\"]\)", api_source, re.M)
            if not match or Version(match[1]) != API_VERSION:
                raise WidgetError('Run the manager from the selected core API version.')
            runtime = json.loads(_git(repo, 'show', revision + ':profiles/public.json'))
            manifests = []
            for ident in runtime['widgets']:
                path = f'dashboard/widgets/bundled_manifests/{ident}/widget.json'
                manifests.append(Manifest.from_dict(json.loads(_git(repo, 'show', revision + ':' + path))))
            return item, runtime, manifests
        metadata_name = 'pack.json' if content else 'widget.json'
        metadata = json.loads(_git(repo, 'show', _object(revision, directory, metadata_name)))
        project = tomllib.loads(_git(repo, 'show', _object(revision, directory, 'pyproject.toml')).decode())['project']
        if metadata['id'] != selection['id'] or metadata['provider'] != selection['provider']:
            raise WidgetError('Source metadata does not match selected package identity.')
        if metadata['version'] != project['version']:
            raise WidgetError('Package and manifest versions differ.')
        requested = selection.get('version', '>=0')
        constraint = SpecifierSet(requested if requested[:1] in '<>=!~' else '==' + requested)
        if Version(metadata['version']) not in constraint:
            raise WidgetError('Selected package version does not satisfy the profile.')
        grants = selection.get('capabilities', [])
        if not isinstance(grants, list) or len(set(grants)) != len(grants) or set(grants) - set(metadata.get('capabilities', [])):
            raise WidgetError('Invalid selected capabilities.')
        item.update(id=metadata['id'], provider=metadata['provider'], version=metadata['version'],
                    distribution=project['name'], capabilities=grants, metadata=metadata)
        return item

    result['core'], runtime, manifests = source(config['core'], core=True)
    for key in ('widgets', 'content_packs'):
        seen = set()
        for selection in config.get(key, []):
            slug(selection['id'], 'package ID')
            slug(selection['provider'], 'package provider')
            if selection['id'] in seen:
                raise WidgetError('Package IDs must be unique within each selection kind.')
            seen.add(selection['id'])
            item = source(selection, content=key == 'content_packs')
            result[key].append(item)
            if key == 'widgets':
                manifests = [m for m in manifests if m.id != item['id']]
                manifests.append(Manifest.from_dict(item['metadata']))
                runtime['widgets'][item['id']] = dict(provider=item['provider'], version='==' + item['version'], capabilities=item['capabilities'])
    dependency_order(manifests)
    result['runtime'] = runtime
    _write(output, result)
    return result


def _generation(destination):
    destination = Path(destination).absolute()
    generations = destination.parent / (destination.name + '.generations')
    if destination.exists() or destination.is_symlink():
        if not destination.is_symlink() or not destination.resolve().is_relative_to(generations.resolve()):
            raise WidgetError('Destination is not a manager-owned candidate pointer.')
    generations.mkdir(parents=True, exist_ok=True)
    generation = generations / secrets.token_hex(12)
    generation.mkdir(mode=0o700)
    return destination, generation


def _publish(destination, generation):
    temporary = destination.with_name(destination.name + '.next-' + secrets.token_hex(6))
    try:
        temporary.symlink_to(generation.relative_to(destination.parent), target_is_directory=True)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise WidgetError('Synchronized sources cannot contain symbolic links.')
        if path.is_file() and path != root / 'synchronized.json':
            digest.update(path.relative_to(root).as_posix().encode() + b'\0')
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def sync(lock_path, destination, cache):
    locked = _json(lock_path)
    if locked.get('manager_schema_version') != 1:
        raise WidgetError('Unsupported source lock.')
    destination, generation = _generation(destination)
    try:
        for key, items in (('core', [locked['core']]), ('widgets', locked['widgets']), ('content_packs', locked['content_packs'])):
            for item in items:
                repo, _ = _repository(item['repository'], Path.cwd(), Path(cache).resolve(), ref=item['revision'])
                data = _archive(repo, item['revision'], item['subdirectory'])
                if _sha(data) != item['archive_sha256']:
                    raise WidgetError('Source archive differs from the reviewed lock.')
                path = generation / key if key == 'core' else generation / key / item['id']
                _extract(data, path)
        _write(generation / 'source-lock.json', locked)
        _write(generation / 'synchronized.json', dict(lock_sha256=_lock_hash(locked), source_sha256=_digest(generation)))
        _publish(destination, generation)
        return dict(directory=str(destination), revision=locked['core']['revision'])
    except BaseException:
        shutil.rmtree(generation)
        raise


def build(lock_path, sources, destination, *, editable=False):
    """Resolve with pip, seal hashes, install offline, then atomically publish."""
    locked, sources = _json(lock_path), Path(sources).resolve()
    synchronized = _json(sources / 'synchronized.json')
    if synchronized['lock_sha256'] != _lock_hash(locked) or synchronized['source_sha256'] != _digest(sources):
        raise WidgetError('Synchronized sources or lock changed; synchronize before building.')
    destination, generation = _generation(destination)
    try:
        shutil.copytree(sources, generation / 'sources')
        if _digest(generation / 'sources') != synchronized['source_sha256']:
            raise WidgetError('Source changed while copying; candidate unchanged.')
        core = generation / 'sources/core'
        python = generation / 'venv/bin/python'
        _run(sys.executable, '-m', 'venv', generation / 'venv')
        wheelhouse = generation / 'wheelhouse'
        wheelhouse.mkdir()
        packages = [generation / 'sources' / key / p['id'] for key in ('widgets', 'content_packs') for p in locked[key]]
        _run(python, '-m', 'pip', 'wheel', '--wheel-dir', wheelhouse, '-r', core / 'requirements.txt',
             'setuptools', 'wheel', *packages)
        artifacts, requirements, distributions = [], [], set()
        for wheel in sorted(wheelhouse.glob('*.whl')):
            name, version, _, _ = parse_wheel_filename(wheel.name)
            if name in distributions:
                raise WidgetError('Wheel resolution produced conflicting versions.')
            distributions.add(name)
            sha = _sha(wheel.read_bytes())
            artifacts.append(dict(file=wheel.name, sha256=sha, distribution=name, version=str(version)))
            requirements.append(f'{name}=={version} --hash=sha256:{sha}')
        (generation / 'requirements.lock').write_text('\n'.join(requirements) + '\n')
        _write(generation / 'artifacts.json', artifacts)
        _run(python, '-m', 'pip', 'install', '--no-index', '--find-links', wheelhouse,
             '--require-hashes', '-r', generation / 'requirements.lock')
        runtime = json.loads(json.dumps(locked['runtime']))
        for item in locked['widgets']:
            if editable:
                repository = Path(item['repository'])
                if not repository.is_dir():
                    raise WidgetError('Editable builds require explicit local Git sources.')
                _repository(str(repository), Path.cwd(), generation / 'unused')
                if _git(repository, 'rev-parse', 'HEAD').decode().strip() != item['revision']:
                    raise WidgetError('Editable source HEAD differs from the reviewed lock.')
                package = repository / item['subdirectory']
                _run(python, '-m', 'pip', 'install', '--no-deps', '--no-build-isolation', '-e', package)
                runtime['sources'].append(dict(kind='local', repository=str(repository), subdirectory=item['subdirectory']))
            else:
                runtime['sources'].append(dict(kind='installed', repository=item['distribution']))
        if editable:
            original = Path(locked['core']['repository'])
            _repository(str(original), Path.cwd(), generation / 'unused')
            if _git(original, 'rev-parse', 'HEAD').decode().strip() != locked['core']['revision']:
                raise WidgetError('Editable core HEAD differs from the reviewed lock.')
            core = original
        _write(generation / 'runtime-profile.json', runtime)
        _write(generation / 'content-profile.json', dict(schema_version=1, packs=[dict(kind='installed',
            distribution=p['distribution'], id=p['id'], provider=p['provider'], version='==' + p['version']) for p in locked['content_packs']]))
        _run(python, '-m', 'pip', 'check')
        _run(python, '-m', 'dashboard.widgets', 'validate', '--profile', generation / 'runtime-profile.json',
             cwd=core, env={'PYTHONPATH': str(core), 'PYTHONDONTWRITEBYTECODE': '1'})
        _write(generation / 'build.json', dict(schema_version=1, editable=editable,
            python=sys.version, platform=platform.platform(), source_lock_sha256=_lock_hash(locked), artifacts=artifacts))
        _write(generation / 'source-lock.json', locked)
        command = [str(python), '-m', 'gunicorn', '--chdir', str(core), '--bind', '127.0.0.1:8000', 'app:app']
        script = '#!/bin/sh\nset -eu\nexport DASHBOARD_WIDGET_PROFILE=' + shlex.quote(str(generation / 'runtime-profile.json'))
        script += '\nexport FOUR_AD_CONTENT_PROFILE=' + shlex.quote(str(generation / 'content-profile.json'))
        script += '\nexec ' + shlex.join(command) + ' "$@"\n'
        (generation / 'run').write_text(script)
        (generation / 'run').chmod(0o700)
        _publish(destination, generation)
        return dict(directory=str(destination), editable=editable, artifacts=len(artifacts), launcher=str(destination / 'run'))
    except BaseException:
        shutil.rmtree(generation)
        raise
