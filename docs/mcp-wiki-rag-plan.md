# MCP and Wiki RAG effort

Tracking effort: **MCP and Wiki RAG**. The executable card manifest is
[plans/mcp-wiki-rag.json](../plans/mcp-wiki-rag.json). It contains one parent,
eleven implementation milestones in To do and seven deferred stories in Backlog.
Each story includes scope/acceptance notes and explicit dependency keys.

The shared wiki retrieval service serves both the HTTP/MCP API and the optional
Ask the wiki UI. The MCP adapter calls supported HTTP APIs, not the database.
An agent can synthesize an answer using its own model and retrieved evidence;
Dashboard-generated answers use an independently configured provider.

## Delivery order

1. Contracts and evaluation baseline; additive API foundations.
2. Independently versioned read-only stdio MCP adapter, then narrow Kanban writes.
3. Durable indexing lifecycle, ranked keyword passages and source links.
4. Configurable embeddings/hybrid retrieval and coding-agent acceptance.
5. Optional grounded answer service and accessible wiki UI.
6. Reproducible packaging, private configuration, worker deployment and rollout.

Index only current non-deleted pages and successfully extracted attachments at
first. Inbox, historical revisions and other widgets require explicit later opt-in.
Keep ordinary wiki search and editing available with AI disabled or unavailable.

Treat the index as rebuildable derived state. Persist source hashes/revisions,
owner identity, extraction/chunking/model versions and index generations. Use durable
idempotent jobs and source eligibility checks, including delete, restore and import.
Recheck access and freshness before returning excerpts or cached/generated answers.
Preserve source IDs and exact excerpts; never invent attachment page locators.
Validate citations against retrieved sources, while evaluating factual support
separately. Retrieved document instructions are untrusted content.

Default to local-first indexing, optional AI dependencies and explicit hosted
provider configuration. Local embeddings do not prevent source passages reaching
a cloud coding-agent provider. Keep keys, model settings and production deployment
configuration in the private composition repository. Preserve existing supported
URLs, configuration, caller formats, accounts, data and backups through additive
changes. Measure retrieval and generation independently using sanitized fixtures.

Deferred stories cover remote HTTPS MCP authorization, optional widget tool
registration, reranking, OCR/provenance, revision search, inbox search and selected
cross-widget retrieval. These remain in the same effort's Backlog.

## Create cards and finish native effort assignment

The synchronizer is read-only unless `--apply` is supplied:

```bash
python3 tools/sync_effort_plan.py \
  --base-url https://widgetdeck.example \
  --env-file /path/to/private.env
```

Use a personal API key with Kanban write access to apply. The environment file is
parsed as data, never sourced; tokens and response bodies are not printed. Supply
`DASHBOARD_KANBAN_API_KEY` (legacy environment-file key name
`DASHBOARD_API_KEY` is also recognized). Run one synchronizer at a time.

```bash
python3 tools/sync_effort_plan.py \
  --base-url https://widgetdeck.example \
  --env-file /path/to/private.env --apply
```

On an older server, the script creates normal cards with the effort name and stable
plan markers in their notes, relates the parent to all stories and adds dependency
links. It discovers native effort support from the board snapshot rather than
misinterpreting authentication failures on unknown routes. It reports native
assignment as pending; it does not deploy or bypass authentication.

After deploying #118, rerun the same command to create/reuse the native effort and
add it to the same cards. Existing tags, titles, notes, statuses and unrelated links
are retained. Cards transferred to other owned boards are found by their markers.
Keep the plan markers in notes. Duplicate markers stop the run for reconciliation.
After a timeout, inspect or rerun explicitly; writes are not automatically retried.
This handles sequential reruns, not concurrent idempotent creation on old servers.

## Current tracking snapshot

Created on the existing Dashboard board on 2026-10-18:
parent #120; implementation #121–131 in To do; deferred #132–138 in Backlog.
All nineteen have effort-labelled notes and verified parent/dependency links.
Native production effort assignment is pending deployment of #118; the snapshot
is evidence, not hardcoded IDs used by the synchronizer. Production deployment
remains a manual user step. Dashboard archival is also being handled manually by
the user; all new implementation belongs in WidgetDeck.

## Implementation verification and remaining handoff

Kanban effort support is implemented in `f493426`; the plan/synchronizer is in
`270ef39`. The application regression suite passed 222 tests with 19 skips,
including upgrade, ownership and browser cases. The built image also passed
an authenticated, disposable container check without external network access.
Eight plan synchronizer integration checks passed, including all nineteen cards
and sequential reruns. Existing preview containers and production were retained.

During handoff, the retired Dashboard working copy's Python environment and
credential file became unavailable. Earlier credential screening found no matches;
the final repeat scan could not run against the removed credential baseline.
The live #118 completion-note/status update requires the relocated private
credential-file path. Native effort assignment still requires deployment followed
by an explicit synchronizer apply. No credentials should be restored into tracked
files or committed to either repository.
