# Widget API version 1.4

Widgets are trusted executable server code. Capabilities describe enabled core
services; they do not sandbox Python or prevent direct access to server resources.

## Declarative manifest

Each package owns a `widget.json` file. Read it with
`dashboard.widgets.read_manifest`; reading metadata never imports widget code.

```json
{
  "schema_version": 1,
  "id": "example",
  "provider": "dashboard",
  "name": "Example",
  "version": "1.0.0",
  "core_api": ">=1.1,<2",
  "default_category": "Tools",
  "entry_point": "example_widget:register",
  "dependencies": {},
  "capabilities": []
}
```

Logical IDs and provider names are lowercase hyphenated identifiers. Identity is
`provider/id`; display names need not be unique. Versions are MAJOR.MINOR.PATCH,
optionally followed by Python prerelease/postrelease/development suffixes. Version
ranges use Python packaging specifiers. Unknown schema fields, duplicate JSON
keys, invalid/self dependencies and duplicate capabilities fail validation.

## Registration

```python
def register(app, context):
    app.register_blueprint(example)
    context.navigation("Tools", "Example", "example.index",
                       icon="◇", description="An original example utility.")
    context.api_service("example", "Example", "/api/tools/example/")
```

The core validates all selected metadata before importing entry points. Initializers
own additive/idempotent feature migrations and package templates/static assets.
Keep old routes/endpoints when converting existing utilities. Do not register
routes already owned by another widget or core, or overlapping API service prefixes.

Optional context methods:

- `settings(template, update=None)`: package-relative Jinja template and optional
  update callback accepting submitted payload and existing settings.
- `search(name, provider)`: unique provider name and request-scoped callable.
- `resolve(resolver)`: callable accepting resource ID and kind; it must enforce
  account ownership and return a launcher destination or None.
- `activity(area, label)`: unique activity area and display label.
- `mail()`: capability-controlled enqueue and owner-scoped delivery status; see
  [the mail service contract](mail-service.md). Requires a declared and explicitly
  granted `mail` capability and a signed-in user. Sending is disabled by default.

`context.manifest` exposes validated metadata. `context.capabilities` contains
only explicitly granted capabilities declared by the widget. Unselected widgets
must not be imported. Disabling preserves data/preferences. A registration failure
invalidates that app instance; discard it instead of attempting partial recovery.
The registration library stores state in `app.extensions['dashboard_widgets']`;
core consumes its navigation, service, settings, search, resolver and activity contributions.

## Compatibility

Core API version is independent of Dashboard and widget package versions. Source
selection, version locks and dependency ordering precede execution. The framework
preserves the legacy database helpers through `dashboard.four_ad.models` while
new widgets use `context.storage`. Provider replacement requires explicit
storage compatibility/migration; matching a display name never implies data reuse.

## Provider and source selection

`Candidate.local(repository, subdirectory)` reads `widget.json` from a local
package without executing it. `installed_candidates()` discovers the
`dashboard.widgets` entry point group; each distribution must include exactly
one `widget.json`, with matching entry point ID/value and package version.
Discovery never calls entry-point `load()` or imports the package.

`select(candidates, {logical_id: Selection(provider, version_range)})` selects the
highest compatible version of the explicitly chosen provider. Stable versions
are the default; prereleases require a range explicitly allowing them. A missing
provider never falls back to a same-named widget from another source. Duplicate
identity/version candidates and conflicting identity-to-source bindings fail.
Pass prior lock bindings through `bindings=` to reject source relocation without
an explicit migration. Source identity includes repository and package subdirectory.

Git sources accept credential-free HTTPS or SSH; use Git's credential/SSH tooling
instead of embedding tokens. Local subdirectories cannot traverse outside their
repository, including through symlinks. Merely discovering or selecting a
candidate does not install it or execute its entry point.

## Dependency ordering and independent releases

`resolve(candidates, selections, bindings=prior_bindings)` finds a compatible
combination of widget versions and returns dependency-first candidates. It prefers
newer allowed releases and can choose an older dependency/dependent when required.
It never adds an unselected dependency or changes its provider/source. Unresolvable
constraints and cycles fail before execution. `register()` independently validates
and orders an exact manifest selection before importing any factory.

The profile controls prerelease opt-in. Once explicitly selected, prereleases
must still satisfy their dependents' version bounds. Disabling a required widget
fails validation; it does not delete records or automatically disable dependents.

Each widget's manifest/package version changes independently of core and other
widgets. Use per-widget tags such as `example/v1.0.0`; the distribution version
must match its manifest. Core API compatibility is a separate range. Development
can follow a branch but locks must still record its exact commit. Stable releases
must contain the tested merged commits; rebuilding from a moving branch at startup
is unsupported.


## Runtime profiles and testing

The default `profiles/compatibility.json` enables the five bundled core utilities.
Private installations use the explicit Dashboard-Personal profile so
upgrades do not silently remove features. `profiles/public.json` selects exactly
Wiki, Mind Maps, Kanban, Wordle and Image Converter. Set `DASHBOARD_WIDGET_PROFILE`
to an explicit JSON profile path to choose a different composition. Startup reads
and validates metadata but never clones repositories or installs packages.

Inspect profiles without executing widget code:

```bash
.venv/bin/python -m dashboard.widgets list --profile profiles/public.json
.venv/bin/python -m dashboard.widgets validate --profile profiles/compatibility.json
```

A profile contains schema_version 1, a name, explicit `widgets` selections and an
optional `sources` list. Each selection declares provider, version range and
optional capabilities. Sources declare kind, repository and optional subdirectory;
relative local paths resolve against the profile file. External code must already
be importable in the application's environment. Installed distributions can be
selected explicitly. Git acquisition and artifact locking/building are separate
management work; runtime rejects unsynchronized Git sources rather than fetching.

Core uses only selected navigation, permission services, settings panels, search
providers and resource resolvers. The activity API additionally returns registered
area labels. Existing keys/preferences/history remain stored when widgets are
disabled. The existing combined campaign initializer and model/route imports remain
compatible; Kanban can initialize without Frostgrave or Death Tracker.

For two development profiles on the same browser host, give the preview its own
instance directory and `DASHBOARD_SESSION_COOKIE_NAME`. The default cookie name is
unchanged. Production stays on its existing version until explicitly deployed.

**Publication boundary:** the public runtime profile is a testing composition,
not yet a sanitized source distribution or image. Private source/assets, extraction,
frontend package separation, screening and Git history cleanup remain outstanding.
Do not publish this intermediate repository/image.

## Default and personal utility categories

API 1.1 adds `default_category` (1–64 visible characters) to declarative widget
metadata. Every shipped bundled/private widget declares it. The manifest default
takes precedence over the category passed to `context.navigation`; the existing
positional navigation signature remains supported. Existing manifests without the
field keep their navigation category, so older widgets continue to load unchanged.
New manifests using this field declare `core_api: ">=1.1,<2"`. Core API and individual
widget package release versions remain separate.

Users manage categories in Settings. Core stores custom groups and per-logical-ID
assignments in additive, account-scoped SQLite tables. Launcher tiles, category
filters and the Utilities menu resolve the same effective grouping. An assignment
never changes global widget metadata, routes, permissions or resource ownership.
Deleting a personal category or choosing the widget default clears only the affected
assignments. Disabled widget assignments survive and apply when re-enabled.

`GET /api/launcher/categories` returns available categories, active utility defaults
and effective assignments, plus the launcher CSRF token. `POST` creates a category
with `{ "name": "My work" }`; `DELETE /api/launcher/categories/<id>` removes an owned
custom category. `PUT /api/launcher/categories/utilities/<logical-id>` accepts
`{ "category": "My work" }` or null to reset. These endpoints require a signed-in
browser session; writes require `X-CSRF-Token`. Bearer keys cannot manage preferences.
Names are limited to 64 characters, duplicates are case-insensitive, and each user
may create up to 50 custom categories. Existing settings and content are preserved.

Personal category names merge case-insensitively with matching defaults introduced
by newly enabled widgets. The personal name and category ID remain manageable;
deleting that personal category restores the widget-defined labels and assignments.
A saved destination remains available while used, even if the widget that originally
defined the default category is temporarily disabled.

## Persistent provider claims and storage

Before importing factories, registration atomically records selected providers in
`widget_provider_bindings` in the existing configured database. Claims remain
when widgets are disabled, and after an initializer fails, because it may already
have written data. A provider change or a switch between legacy and isolated
storage fails before any factory runs. Version upgrades within the same provider
retain their paths; widget schema migrations must remain additive and repeatable.

On the first upgrade, existing legacy tables reserve their original providers even
when those widgets are disabled. The shipped implementations continue using their
existing shared database and file paths. No records or user preferences are moved
or deleted. `FOUR_AD_DATABASE` retains its existing precedence and override behavior.
The compatibility list contains only widget identities/table names, not private
implementations or content.

API 1.2 adds `context.storage`; widgets using it declare `core_api: ">=1.2,<2"`.
Existing manifests and entry points remain compatible. New widgets should use
`context.storage`, whose database is
`<configured database directory>/widget-storage/<provider>/<logical-id>/data.sqlite`.
`context.storage.directory` is the corresponding directory for widget-owned files;
create it before writing files. Paths do not contain a version, so upgrades retain
data. `context.storage.connect()` is a context manager that commits on success,
rolls back on failure, and always closes its SQLite connection:

```python
def register(app, context):
    with context.storage.connect() as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS notes '
                           '(user_id INTEGER NOT NULL, text TEXT NOT NULL)')
```

Widgets must enforce account ownership themselves. The shared `dashboard.database`
helper remains available for backward compatibility; new providers should use their
own storage. These are trusted-code contracts, not a sandbox against malicious code.

The explicit offline workflow below supports reviewed provider replacement.
File copying requires separate review and opt-in. Disabling and re-enabling the
same provider needs no migration.

## Reviewed offline SQLite migrations (API 1.3)

Migration hooks are optional declarative metadata. Widgets using this addition
require `core_api: ">=1.3,<2"`. Existing manifests and registration APIs remain
compatible. A replacement author must declare a compatible source identity and
version range, and implement an explicit transformation:

```json
"storage_migrations": {
  "original/example": {
    "from_version": ">=1,<2",
    "entry_point": "example_widget.migrations:from_original"
  }
}
```

The source logical ID must match the target. Reading manifests or registering
widgets never imports or executes migration hooks. Runtime provider replacement
continues to fail until the operator explicitly migrates the stored binding.

First generate a metadata-only plan using the target profile and exact recorded
source and selected target versions:

```sh
python -m dashboard.widgets migrate --profile target-profile.json \
  --widget example --database /path/to/instance/dashboard.sqlite \
  --from-provider original --from-version 1.0.0 --to-version 2.0.0
```

Review the selected package/locked code, declared compatibility, hook, paths and
plan ID. Stop all application processes/workers using the instance, then repeat
with `--reviewed --offline --plan-id PLAN_ID_FROM_DRY_RUN`. The offline flag is the
operator's explicit confirmation; the command does not stop running services or
prove they are quiescent. Do not run it against an active deployment. The plan ID
binds the reviewed manifest/versions/database, not a signature of executable code;
use the reviewed locked build for execution. Switch the runtime profile only after
successful migration, then validate the replacement and retain the backups.

The runner automatically backs up existing source, target and registry databases
under `widget-migration-backups/` in the configured database directory. Backup
files are mode 0600 inside a private migration directory; failures stop execution
before hook imports. Failed or interrupted migrations retain these backups.

The hook receives `(source_connection, target_connection)`. Source is a read-only
SQLite snapshot; target owns a transaction. Use `execute`/`executemany`; hooks must
not commit, roll back, attach databases or call `executescript` (its implicit commit
is blocked). Preserve record IDs, account ownership, reference relationships and
unrelated shared tables. The shared legacy target layout is supported through an
explicit compatible hook; no generic schema or ownership mapping is inferred.

Target data, registry binding and the completed-plan ledger commit together. An
exception rolls back all SQLite changes, including a previously existing target's
rows. An exact repeat of a completed plan returns without rerunning the hook.
Changes to bindings or target metadata require a new reviewed plan. Source data
and core preferences remain stored; the runner never deletes the old namespace.

For separate target/registry files, both must use durable rollback journals
(DELETE/TRUNCATE/PERSIST). WAL, MEMORY and OFF are rejected without silently changing
configuration. This follows SQLite's [attached-database atomicity conditions](https://www.sqlite.org/lang_attach.html).
Single-database legacy targets retain SQLite's normal transaction semantics.

Without file-copy opt-in, non-database managed files reject execution before any
hook imports. Symlinks and special files are always rejected. Existing legacy
files outside the managed namespace remain in place; authors/operators must
review external file references. Hooks are trusted Python code: SQL authorizers
prevent accidental transaction/registry misuse, and do not sandbox arbitrary
code or external side effects.

### Managed files and interrupted migrations

Add `--copy-files` to both the dry run and reviewed execution to copy the source
provider's managed files into the target namespace without changing their names
or bytes. This opt-in is part of the reviewed plan, as are hashes of source and
target files. Changed content invalidates approval, including changes during
staging. The two-connection SQL hook API remains unchanged; file transformation,
renaming and migration of files outside `context.storage.directory` require a
separately reviewed operator procedure. No file mapping is inferred.

Existing identical target files and target-only files remain intact. A differing
file at the same target path stops execution without overwriting it. Nested
SQLite files are recognized by their header and copied with SQLite's backup API,
including committed WAL records; WAL/shared-memory/journal sidecars are not copied.
The main provider database is transformed by the declared SQL hook. Source stores
and preferences remain intact. Private automatic backups also include these
managed files and secondary SQLite snapshots.

File-aware execution reserves a private pending directory next to the registry
database, stages snapshots, and durably records recovery metadata before linking
any new target files. Links are atomic and never overwrite existing paths. The
staging and target directories must support hard links on the same filesystem;
unsupported links fail safely. Keep the application's filesystems on durable
storage with working fsync semantics. Do not modify recovery state or run recovery
concurrently with the migration. All application/worker processes must stay stopped.

An exception rolls back SQL and removes only this operation's new files. Process
exit or power interruption may leave pending state; widget initialization and
Personal preflight refuse it. Keep the app stopped and run:

```sh
python -m dashboard.widgets recover-migration \
  --database /path/to/instance/dashboard.sqlite --offline
```

Recovery first lets SQLite recover its journals, then uses the committed migration
ledger to retain/finish file installation or remove uncommitted copies. It never
deletes the old source namespace or preexisting target files. Recovery is repeatable;
after it succeeds, repeat the originally reviewed migration or start the selected
provider as appropriate. An exact completed-plan repeat does not rerun the hook.
Unexpected file edits or missing/corrupt recovery data stop recovery for manual
review; retain pending state and backups rather than clearing the startup guard.

Widgets can define non-text activity actions using the optional `actions` argument:

```python
record = context.activity('painting', 'Painting', actions={
    'painted': {'label': 'Painted', 'unit': 'miniature', 'plural': 'miniatures'},
})
# In the successful widget write transaction, under the signed-in account:
with db():
    save_painting()
    record('painted', scheme_id, 'Space marine', quantity=2)
```

`activity(area, label)` remains compatible. The returned recorder accepts only
registered actions and positive integer quantities (up to 1,000,000). `plural` is
optional. Events use the current account, and roll back with the widget's write;
the recorder never commits. The home feed displays the widget's action and unit
(e.g. “Painted 2 miniatures”) alongside existing wiki line changes. The additive
`actions` field on `/api/activity` describes registered actions. The existing
`added_lines` count carries the quantity when `count_unit` is not `lines` or
`words`. Wordle records each completed game once, including a reset after guesses;
empty abandoned games do not produce a played event.
