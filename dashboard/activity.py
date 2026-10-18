"""Small, account-scoped activity feed shared by Dashboard tools."""

from difflib import SequenceMatcher
import uuid

from dashboard.auth import current_user_id
from dashboard.database import db, timestamp


def init_database(app):
    with __import__("sqlite3").connect(app.config["FOUR_AD_DATABASE"]) as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS activity_events (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, area TEXT NOT NULL,
            resource_id TEXT, resource_name TEXT NOT NULL,
            action TEXT NOT NULL DEFAULT 'edited', added_lines INTEGER NOT NULL DEFAULT 0,
            removed_lines INTEGER NOT NULL DEFAULT 0, occurred_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS activity_events_user_area_time
            ON activity_events(user_id, area, occurred_at DESC);
        """)
        connection.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(activity_events)")}
        if "count_unit" not in columns:
            connection.execute("ALTER TABLE activity_events ADD COLUMN count_unit TEXT NOT NULL DEFAULT 'lines'")
        connection.execute("""CREATE TABLE IF NOT EXISTS activity_edit_sessions (
            user_id INTEGER NOT NULL, area TEXT NOT NULL, resource_id TEXT NOT NULL,
            session_key TEXT NOT NULL, event_id TEXT NOT NULL, baseline TEXT NOT NULL,
            PRIMARY KEY(user_id,area,resource_id,session_key)
        )""")


def _owner_id():
    user_id = current_user_id()
    if not user_id:
        raise PermissionError("Sign in is required.")
    return user_id


def line_changes(before, after):
    """Return git-diff-style added and removed logical line counts."""
    old_lines = str(before or "").splitlines()
    new_lines = str(after or "").splitlines()
    added = removed = 0
    for tag, old_start, old_end, new_start, new_end in SequenceMatcher(None, old_lines, new_lines).get_opcodes():
        if tag in {"replace", "delete"}:
            removed += old_end - old_start
        if tag in {"replace", "insert"}:
            added += new_end - new_start
    return added, removed


def record_session_edit(area, resource_id, resource_name, before, after, session_key):
    """Update one net-change event per editing visit, inside the caller's transaction."""
    connection = db()
    key = (_owner_id(), area, str(resource_id), session_key)
    saved = connection.execute("""SELECT event_id,baseline FROM activity_edit_sessions
        WHERE user_id=? AND area=? AND resource_id=? AND session_key=?""", key).fetchone()
    if saved:
        event_id, baseline = saved["event_id"], saved["baseline"]
    else:
        event_id, baseline = str(uuid.uuid4()), before
        connection.execute("""INSERT INTO activity_edit_sessions(user_id,area,resource_id,session_key,event_id,baseline)
            VALUES(?,?,?,?,?,?)""", (*key, event_id, baseline))
    added, removed = line_changes(baseline, after)
    if not added and not removed:
        connection.execute("DELETE FROM activity_events WHERE id=? AND user_id=?", (event_id, key[0]))
        return
    connection.execute("""INSERT INTO activity_events(
        id,user_id,area,resource_id,resource_name,action,added_lines,removed_lines,occurred_at,count_unit)
        VALUES(?,?,?,?,?,'edited',?,?,?,'lines')
        ON CONFLICT(id) DO UPDATE SET resource_name=excluded.resource_name,
        added_lines=excluded.added_lines,removed_lines=excluded.removed_lines,occurred_at=excluded.occurred_at,count_unit=excluded.count_unit""",
        (event_id, key[0], area, str(resource_id), str(resource_name)[:200], added, removed, timestamp()))


def record_edit(area, resource_id, resource_name, before, after, action="edited"):
    added, removed = line_changes(before, after)
    if not added and not removed:
        return None
    event = {"id": str(uuid.uuid4()), "user_id": _owner_id(), "area": str(area),
             "resource_id": str(resource_id or ""), "resource_name": str(resource_name or "Untitled")[:200],
             "action": str(action or "edited"), "added_lines": added, "removed_lines": removed,
             "occurred_at": timestamp(), "count_unit": "lines"}
    db().execute("""INSERT INTO activity_events(
        id,user_id,area,resource_id,resource_name,action,added_lines,removed_lines,occurred_at,count_unit
    ) VALUES(:id,:user_id,:area,:resource_id,:resource_name,:action,:added_lines,:removed_lines,:occurred_at,:count_unit)""", event)
    db().commit()
    return event


def rename_resource(area, resource_id, resource_name):
    """Keep prior activity entries useful after an automatically named page is titled."""
    db().execute(
        "UPDATE activity_events SET resource_name=? WHERE user_id=? AND area=? AND resource_id=?",
        (str(resource_name or "Untitled")[:200], _owner_id(), str(area), str(resource_id or "")),
    )
    db().commit()


def recent_activity(area=None, limit=12):
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 12
    query = """SELECT id,area,resource_id,resource_name,action,added_lines,removed_lines,occurred_at,count_unit
        FROM activity_events WHERE user_id=?"""
    values = [_owner_id()]
    if area:
        query += " AND area=?"
        values.append(str(area))
    query += " ORDER BY occurred_at DESC, rowid DESC LIMIT ?"
    values.append(limit)
    return [dict(row) for row in db().execute(query, values)]
