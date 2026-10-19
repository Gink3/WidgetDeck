# Explicit source management

The runtime never downloads or installs packages. Run management commands from a
trusted checkout with Python 3.12+, Git supporting archive `--mtime`, venv and the core requirements installed.
Package builds execute trusted package build code; review sources before building.
The manager must have the same widget API version as the selected core.

A management profile is separate from the existing runtime profile format:

```json
{
  "schema_version": 1,
  "name": "example",
  "core": {"repository": "../WidgetDeck", "ref": "v1.0.0"},
  "widgets": [{
    "id": "example", "provider": "example", "repository": "../example-widget",
    "subdirectory": ".", "ref": "v1.0.0", "version": ">=1,<2",
    "capabilities": []
  }],
  "content_packs": []
}
```

Repositories can be clean local checkouts or credential-free HTTPS/SSH Git URLs.
Local paths are relative to the profile. Use Git's credential helper or SSH agent
for private acquisition; keep secrets outside profile URLs and lock files.
Explicit branches, tags and commit IDs are supported. Production should select
reviewed stable tags; development can select branch heads. Each widget/content
selection can use its own repository, ref and subdirectory. Common
`widgets_repository` and `widgets_ref` defaults are optional. Default package
subdirectories are `widgets/<id>` and `content-packs/<id>`; use explicit paths
for other layouts. Packages need static project name/version metadata and
`widget.json` or `pack.json`. Content loader compatibility remains the selected
widget's responsibility.

```sh
python -m dashboard.widgets lock --profile management.json --output source-lock.json
python -m dashboard.widgets sync --lock source-lock.json --destination .build/sources
python -m dashboard.widgets build --lock source-lock.json --sources .build/sources --destination .build/candidate
```

Locking checks selected identities, versions, capabilities and widget dependencies
without importing package hooks. It records exact commits and archive hashes;
failed acquisition or validation leaves the previous lock intact. Symlinks and
submodules in selected source archives are rejected. Synchronization verifies the
locked archives and installs only selected packages into a new generation.

Build resolves Python dependencies with pip, records exact wheel versions and
SHA-256 hashes, installs offline with `--require-hashes`, runs pip consistency and
runtime metadata checks, and publishes a candidate pointer only after success.
Wheel artifacts and requirements.lock remain with that candidate. Rebuilding from
source can resolve newer transitive dependencies; retain the reviewed wheelhouse,
hash lock, platform/Python record and source lock for exact artifact reuse. Package
authors must include required frontend assets in wheels or declare their build
steps; this command does not infer an npm toolchain. The private composition's
Docker workflow supports its additional frontend build steps.

Add `--editable` to build for local development. Selected widget checkouts and
core must be clean and at the locked HEAD; editable widget installs refer to those
original checkout paths. Later edits are intentionally live. Content remains an
installed wheel. A production build uses only copied locked sources and installed
wheels. Neither mode deploys or migrates data. Run the generated `candidate/run`
launcher with your normal external configuration and storage environment. Its
default bind is loopback port 8000; Gunicorn arguments can override that default.

Sources and candidates are symlink pointers into sibling `*.generations`
directories. Prior generations remain available after success and failures leave
the previous pointer intact. Keep generations at their original absolute path
(virtual environments embed it). Remove an old generation only after confirming
no pointer, running process or retained release uses it. These private generated
files belong outside Git and the public Docker context. Keep startup using the
selected built candidate; acquisition is always an explicit operator action.

Existing list, validate, migrate and recover-migration commands and runtime
profiles retain their formats and behavior.
