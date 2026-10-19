#!/usr/bin/env python3
"""Screen Git blobs without importing application code or printing their contents."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def blobs(repo, staged=False):
    args = ('ls-files', '--stage', '-z') if staged else ('ls-tree', '-r', '-z', 'HEAD')
    for entry in git(repo, *args).split(b'\0'):
        if not entry:
            continue
        header, path = entry.split(b'\t', 1)
        mode, oid, stage = header.split() if staged else (header.split()[0], header.split()[2], b'0')
        if stage != b'0' or mode not in (b'100644', b'100755'):
            yield path.decode(), None  # refuse conflicts, submodules and symlinks
        else:
            yield path.decode(), git(repo, 'cat-file', 'blob', oid.decode())


def reasons(path, data, fingerprints):
    parts = PurePosixPath(path).parts
    if data is None:
        return ['unsupported Git entry']
    issues = []
    if any(p in {'.agents', '.aws', '.codex', '.sources', '.widget-sources', '.build', '.venv', 'node_modules',
                 '__pycache__', 'instance', 'content-packs', 'private-artifacts'}
           or p == '.env' or p.startswith('.env.') or p == 'widget-migration-backups'
           or p.endswith(('.widget-migration-pending', '.generations')) for p in parts):
        issues.append('private or generated path')
    if path.startswith('static/mindmaps/') or path.endswith(('.pyc', '.sqlite', '.sqlite-wal', '.eml')):
        issues.append('runtime or generated artifact')
    if hashlib.sha256(data).hexdigest() in fingerprints:
        issues.append('restricted fingerprint')
    patterns = (
        rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        rb'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,}|AKIA[A-Z0-9]{16})\b',
        rb'(?i)(?:DASHBOARD_KANBAN_API_KEY|DASHBOARD_API_KEY)\s*=\s*[\"\']?[A-Za-z0-9_-]{24,}',
        rb'/(?:home|Users)/[^\s\"\']+/(?:\.env[^\s\"\']*|\.aws/[^\s\"\']*)',
    )
    if any(re.search(pattern, data) for pattern in patterns):
        issues.append('secret or private credential reference')
    return issues


def load_fingerprints(filename=None, required=False):
    value = Path(filename).read_text() if filename else os.environ.get('WIDGETDECK_RESTRICTED_SHA256', '[]')
    hashes = json.loads(value)
    if not isinstance(hashes, list) or any(not isinstance(h, str) or not re.fullmatch('[0-9a-f]{64}', h) for h in hashes):
        raise ValueError('Fingerprint input must be a JSON array of SHA-256 strings.')
    if required and not hashes:
        raise ValueError('Restricted fingerprint input is required; configure it outside Git.')
    return set(hashes)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--staged', action='store_true')
    parser.add_argument('--fingerprints', type=Path)
    parser.add_argument('--require-fingerprints', action='store_true')
    args = parser.parse_args(argv)
    try:
        fingerprints = load_fingerprints(args.fingerprints, args.require_fingerprints)
        failures = [(path, issue) for path, data in blobs(args.repo, args.staged)
                    for issue in reasons(path, data, fingerprints)]
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('Screening could not run: ' + type(error).__name__)
        return 2
    for path, issue in failures:
        print(json.dumps({'path': path, 'reason': issue}))
    print(f'Screening: {len(failures)} finding(s). Exact fingerprints do not clear transformed content or history.')
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
