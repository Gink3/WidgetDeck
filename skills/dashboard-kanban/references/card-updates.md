# Updating card notes and progress

The bundled `scripts/read_board.py` is read-only. For authorized updates, use an
HTTP client that loads the key from the appropriate private env file, sends
`Authorization: Bearer <key>`, refuses redirects and applies a timeout. Do not
put keys into shell commands, logs or example payloads. Use the same production
origin used to discover the card, and verify board membership before writing.

## Read before writing

`GET /api/tools/kanban/items/<item_id>` returns `{"item": {...}}` with the current
title, notes, column ID, board ID, revision and history. Discover destination
column IDs with `GET /api/tools/kanban/boards/<board_id>`; never infer them from
names or development IDs.

## Append notes

`PATCH /api/tools/kanban/items/<item_id>` requires all four fields:

```json
{
  "title": "the current unchanged title",
  "notes": "the current notes followed by the dated question or result",
  "column_id": 123,
  "revision": 4
}
```

Use freshly read values, not the example numbers. Titles must be 1–160 characters
and notes at most 5,000. Preserve the title and column when only updating notes.
If the appended section would exceed the limit, report the limit and use a concise
addition or request an agreed way to archive older notes; never truncate them.

## Move within the board

`POST /api/tools/kanban/items/<item_id>/move` accepts:

```json
{"column_id": 124, "revision": 5}
```

Optional `before_id` positions the item before another card; omit it to append.
Always supply the fresh revision even though the endpoint makes it optional.
This existing endpoint supports moves between columns within a board. Use the
separate `/transfer` endpoint below for cross-board transfers after deployment.

## Verification and conflict handling

After a successful write, GET the card again and verify the intended notes/column.
Use the returned revision for subsequent writes. On HTTP 409, re-read, preserve
new user content, and reconcile before retrying. After a timeout, re-read first to
check whether the write succeeded; do not blindly duplicate notes. Stop and report
repeated conflicts. HTTP 401/403 means authentication or permissions failed, and
404 means missing/inaccessible data or an unavailable route; do not work around
these responses with a different account or direct production database access.

## Create cards

`POST /api/tools/kanban/boards/<board_id>/items` accepts JSON:

```json
{"title": "Fix login throttling", "notes": "Acceptance criteria...", "column_id": 123}
```

Notes default to an empty string. Titles must be 1–160 characters, notes at most
5,000; invalid values are rejected without truncation. The column must belong to
the owned board. Success returns HTTP 201 with `{"item": {...}}`, including history
and revision, and a `Location` header pointing to the new card. Creation appends
to the column. After an ambiguous timeout, inspect the board before retrying;
this endpoint does not deduplicate repeated requests.

## Transfer cards between boards

`POST /api/tools/kanban/items/<item_id>/transfer` accepts JSON:

```json
{"board_id": 456, "column_id": 789, "revision": 4}
```

Both boards must belong to the caller. Optional `before_id` inserts before a card
in the destination column. Success returns `{"item": {...}}`. Transfers preserve
ID, title, notes, creation date and history, add a transfer history entry, increment
revision and normalize both column orders. Invalid destinations roll back the
whole operation. Same-board transfers are supported. The existing `/move` endpoint
continues to accept its original payload and only moves within a board.

## Delete cards

`DELETE /api/tools/kanban/items/<item_id>` requires a JSON body:

```json
{"revision": 4}
```

Success returns HTTP 204. Deletion permanently removes the card and its history;
use `/cancel` when history must be retained (existing Cancelled columns also remain supported).
Do not delete unless the user authorized deletion. A stale revision returns 409;
missing or inaccessible cards return 404. A repeated deletion returns 404.

All writes require a signed-in browser session or a personal key with Kanban
write permission. Read-only, revoked, wrong-service and legacy keys cannot write,
even if a valid browser session accompanies the bearer header. These additive
endpoints require the updated application to be deployed; old production builds
may reject requests. Do not substitute browser-only form endpoints or deploy
production automatically to work around an unavailable API.

## Reorder columns

`POST /api/tools/kanban/boards/<board_id>/columns/reorder` accepts JSON
`{"column_ids": [3, 1, 2], "expected_order": [1, 2, 3]}`. Supply every column
from the owned board exactly once and the order from the fresh board snapshot.
Success returns `{"columns": [...]}` in the new order. A changed prior order
returns 409; invalid/foreign column IDs return 400; inaccessible boards return 404.
The operation preserves card membership and history. Requires Kanban write access.

## Cancel or restore cards

`POST /api/tools/kanban/items/<item_id>/cancel` accepts
`{"revision": 4, "cancelled": true}`. Omit `cancelled` to cancel, or use `false`
to restore. Returns `{"item": {...}}`. Cancellation keeps the card in its column
with its ID, notes and history, sets nullable `cancelled_at`, and records an event.
Restoration clears the flag. Real state changes increment revision; repeated same
state requests with the current revision are no-ops. Stale revisions return 409;
missing/foreign cards return 404. Requires Kanban write access. Existing cards
receive a NULL flag through an automatic additive migration and remain active.

Existing-board columns: POST `/api/tools/kanban/boards/<id>/columns` with `name`
and `expected_order` (the current ordered column IDs). DELETE
`/api/tools/kanban/boards/<id>/columns/<column_id>` with `expected_order` and an
explicit `destination_id` for nonempty columns. Cards retain IDs, notes and history;
moved cards increment revision. The final column cannot be removed. Both endpoints
require Kanban write permission; stale topology returns 409.

Comments are independent of notes/card revisions. GET or POST
`/api/tools/kanban/items/<id>/comments` (`body`, 1–5000 characters); PATCH or DELETE
`/api/tools/kanban/items/<id>/comments/<comment_id>` requires the comment's integer
`revision`. PATCH also supplies `body`. Mutation replies include `item`; item detail
now adds `comments` with author/time/revision. Comments follow card transfers and
are removed with permanent card deletion. Rendering uses plain text.

PUT `/api/tools/kanban/items/<id>/links` replaces outgoing links atomically with
`revision` and `links: [{target_id: 123, kind: "depends_on"}]`. Kind can also be
`related`. Targets may be on other boards owned by the account. Self/foreign/missing
links, duplicates and dependency cycles are rejected. Detail adds `links` and
reverse `dependents`, including target title, board and status. Status is never
changed automatically. Transfer preserves links; permanent deletion removes them.
