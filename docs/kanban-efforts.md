# Kanban efforts

An effort is an account-owned project/initiative label, reusable across boards.
A card can have up to twenty efforts. Existing cards start untagged, and legacy
create/update/move/transfer requests continue working without effort fields.
Transfers retain associations. Effort names are normalized and unique per account;
renaming/removing an effort preserves cards, notes, comments, links and history.

Use More → Manage efforts to create, rename or remove an effort. In item details,
select efforts with checkboxes; changes save automatically after ordinary edits
are saved. Select an effort or Untagged above the board to filter across all status
columns. Clear effort filter restores the view; title search remains independent.
Filtered card reordering is disabled to prevent accidentally rearranging hidden
cards. Related items across boards provides direct links to the same effort's work.
The effort filter is preserved in the URL across reloads.

## Additive API

All endpoints use the existing Kanban authentication and account ownership rules.
Personal Kanban read keys can read; write keys can mutate. Existing legacy keys
retain their previous read-only endpoint allowlist. Bearer authentication never
falls back to browser sessions.

- GET `/api/tools/kanban/efforts`: `{efforts: [{id,name,revision}]}`.
- POST the same URL with `{name}`: 201 `{effort: ...}`.
- PATCH `/api/tools/kanban/efforts/<id>` with `{name,revision}`: `{effort: ...}`.
- DELETE the same URL with `{revision}`: 204, retaining assigned cards.
- PUT `/api/tools/kanban/items/<id>/efforts` with
  `{effort_ids: [1,2], revision: <current item revision>}` replaces assignments.
  Return `{item: ...}`. Empty array removes all assignments; identical sets are no-ops.
- GET `/api/tools/kanban/efforts/<id>/items` lists related cards across owned boards
  with board/status names. It does not expose other accounts' efforts or cards.
- Existing JSON item creation optionally accepts `effort_ids` atomically.
- Item details and board snapshot items add `efforts`; snapshots add the account's
  `efforts` collection. Existing fields and API version remain unchanged.

Missing/foreign resources return 404, invalid inputs 400, stale revisions 409.
Assignment changes increment the item revision and append history. Renaming or
removing an assigned effort also increments affected item revisions and records
history, preventing stale callers from silently overwriting concurrent edits.
Permanent card deletion cleans up its assignments. Effort deletion retains history
with the former effort name.

The automatic migration creates `kanban_efforts` and `kanban_item_efforts`; it
leaves all existing cards and other tables intact. Repeated initialization retains
assignments. Production needs this version deployed before native effort writes
are available; older servers can still receive normal cards with effort names in
notes and existing related-item links.
