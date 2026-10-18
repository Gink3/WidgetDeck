import json
import sqlite3

from dashboard.database import db, timestamp
from .common_models import _owner_id, _owned

def init_database(app):
    with sqlite3.connect(app.config["FOUR_AD_DATABASE"]) as connection:
        connection.executescript("""        CREATE TABLE IF NOT EXISTS kanban_boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS kanban_columns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, board_id INTEGER NOT NULL, name TEXT NOT NULL, position INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS kanban_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, board_id INTEGER NOT NULL, column_id INTEGER NOT NULL, title TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS kanban_boards_owner ON kanban_boards(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS kanban_columns_board ON kanban_columns(board_id, position);
        CREATE INDEX IF NOT EXISTS kanban_items_board ON kanban_items(board_id, column_id, position);

""")

        connection.execute("BEGIN IMMEDIATE")

        item_columns = {row[1] for row in connection.execute("PRAGMA table_info(kanban_items)")}

        if "updated_at" not in item_columns:
            connection.execute("ALTER TABLE kanban_items ADD COLUMN updated_at TEXT")
            connection.execute("UPDATE kanban_items SET updated_at=created_at")

        if "revision" not in item_columns:
            connection.execute("ALTER TABLE kanban_items ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")

        if "cancelled_at" not in item_columns:
            connection.execute("ALTER TABLE kanban_items ADD COLUMN cancelled_at TEXT")

        connection.execute("""CREATE TABLE IF NOT EXISTS kanban_item_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, action TEXT NOT NULL, changes TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        )""")

        connection.execute("CREATE INDEX IF NOT EXISTS kanban_history_item ON kanban_item_history(item_id,id DESC)")

        connection.execute("""CREATE TABLE IF NOT EXISTS kanban_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,item_id INTEGER NOT NULL,user_id INTEGER NOT NULL,
            body TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0)""")

        connection.execute("CREATE INDEX IF NOT EXISTS kanban_comments_item ON kanban_comments(item_id,id)")

        connection.execute("""CREATE TABLE IF NOT EXISTS kanban_links (
            item_id INTEGER NOT NULL,target_id INTEGER NOT NULL,kind TEXT NOT NULL,
            PRIMARY KEY(item_id,target_id,kind))""")

        connection.execute("CREATE INDEX IF NOT EXISTS kanban_links_target ON kanban_links(target_id)")



def kanban_boards():
    return db().execute("SELECT * FROM kanban_boards WHERE user_id=? ORDER BY created_at DESC", (_owner_id(),)).fetchall()



def kanban_board(board_id):
    return _owned("kanban_boards", board_id)



def kanban_board_snapshot(board_id):
    """Read one owned board in a consistent snapshot, in visual board order."""
    connection = db()
    with connection:
        connection.execute("BEGIN")
        board = kanban_board(board_id)
        if board is None:
            return None
        columns = [dict(row) for row in connection.execute(
            "SELECT id,board_id,name,position FROM kanban_columns WHERE board_id=? ORDER BY position,id", (board_id,))]
        items = [dict(row) for row in connection.execute("""SELECT i.*, c.name AS column_name
            FROM kanban_items i JOIN kanban_columns c ON c.id=i.column_id AND c.board_id=i.board_id
            WHERE i.board_id=? ORDER BY c.position,c.id,i.position,i.id""", (board_id,))]
        return {"id": board["id"], "name": board["name"], "created_at": board["created_at"],
                "columns": columns, "items": items}



def create_kanban(name, columns):
    connection = db()
    cur = connection.execute("INSERT INTO kanban_boards(user_id,name,created_at) VALUES(?,?,?)", (_owner_id(), name, timestamp()))
    for position, column in enumerate(columns):
        connection.execute("INSERT INTO kanban_columns(board_id,name,position) VALUES(?,?,?)", (cur.lastrowid, column, position))
    connection.commit()
    return cur.lastrowid



def kanban_columns(board_id):
    return db().execute("SELECT * FROM kanban_columns WHERE board_id=? ORDER BY position", (board_id,)).fetchall()



def kanban_items(board_id):
    return db().execute("SELECT * FROM kanban_items WHERE board_id=? ORDER BY position,id", (board_id,)).fetchall()



class ItemConflict(ValueError):
    pass



def reorder_kanban_columns(board_id, column_ids, expected_order):
    connection = db()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        if not kanban_board(board_id):
            return None
        current = [row["id"] for row in connection.execute(
            "SELECT id FROM kanban_columns WHERE board_id=? ORDER BY position,id", (board_id,))]
        if len(column_ids) != len(current) or set(column_ids) != set(current):
            raise ValueError("Supply every column from this board exactly once.")
        if current != expected_order:
            raise ItemConflict("The columns changed in another window. Refresh the board and try again.")
        connection.executemany("UPDATE kanban_columns SET position=? WHERE id=? AND board_id=?",
                               [(position, ident, board_id) for position, ident in enumerate(column_ids)])
    return [dict(row) for row in kanban_columns(board_id)]



def kanban_item(item_id):
    row = db().execute("""SELECT i.* FROM kanban_items i JOIN kanban_boards b ON b.id=i.board_id
        WHERE i.id=? AND b.user_id=?""", (item_id, _owner_id())).fetchone()
    return dict(row) if row else None



def kanban_item_detail(item_id):
    item = kanban_item(item_id)
    if item is None:
        return None
    item["links"] = kanban_links(item_id)
    item["dependents"] = kanban_links(item_id, reverse=True)
    item["comments"] = kanban_comments(item_id)
    item["history"] = [
        {**dict(row), "changes": json.loads(row["changes"])}
        for row in db().execute("""SELECT h.id,h.action,h.changes,h.occurred_at,u.username AS actor
            FROM kanban_item_history h LEFT JOIN dashboard_users u ON u.id=h.user_id
            WHERE h.item_id=? ORDER BY h.id DESC""", (item_id,))
    ]
    return item



def _item_history(item_id, action, changes):
    db().execute("""INSERT INTO kanban_item_history(item_id,user_id,action,changes,occurred_at)
        VALUES(?,?,?,?,?)""", (item_id, _owner_id(), action, json.dumps(changes), timestamp()))



def add_kanban_item(board_id, column_id, title, notes):
    connection = db()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        if not kanban_board(board_id):
            return None
        if not connection.execute("SELECT 1 FROM kanban_columns WHERE id=? AND board_id=?", (column_id, board_id)).fetchone():
            raise ValueError("Choose a column from this board.")
        position = connection.execute("SELECT COALESCE(MAX(position),-1)+1 FROM kanban_items WHERE column_id=?", (column_id,)).fetchone()[0]
        now = timestamp()
        cursor = connection.execute("""INSERT INTO kanban_items(board_id,column_id,title,notes,position,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)""", (board_id, column_id, title, notes, position, now, now))
        _item_history(cursor.lastrowid, "created", {})
    return cursor.lastrowid



def _place_item(item, column_id, before_id=None):
    """Normalize both columns and insert before a specific card (or at the end)."""
    connection = db()
    column = connection.execute("SELECT * FROM kanban_columns WHERE id=? AND board_id=?", (column_id, item["board_id"])).fetchone()
    if column is None:
        raise ValueError("Choose a column from this board.")
    target = [row["id"] for row in connection.execute(
        "SELECT id FROM kanban_items WHERE column_id=? AND id<>? ORDER BY position,id", (column_id, item["id"]))]
    if before_id is not None and before_id not in target:
        raise ValueError("The destination item has moved. Refresh the board and try again.")
    position = target.index(before_id) if before_id is not None else len(target)
    target.insert(position, item["id"])
    changes = {}
    if item["column_id"] != column_id:
        old_column = connection.execute("SELECT name FROM kanban_columns WHERE id=?", (item["column_id"],)).fetchone()
        changes["status"] = {"before": old_column["name"], "after": column["name"]}
        remaining = [row["id"] for row in connection.execute(
            "SELECT id FROM kanban_items WHERE column_id=? AND id<>? ORDER BY position,id", (item["column_id"], item["id"]))]
        connection.executemany("UPDATE kanban_items SET position=? WHERE id=?", [(index, ident) for index, ident in enumerate(remaining)])
    elif item["position"] != position:
        changes["position"] = {"before": item["position"] + 1, "after": position + 1}
    connection.execute("UPDATE kanban_items SET column_id=? WHERE id=?", (column_id, item["id"]))
    connection.executemany("UPDATE kanban_items SET position=? WHERE id=?", [(index, ident) for index, ident in enumerate(target)])
    return changes



def _check_revision(item, revision):
    if revision is not None and item["revision"] != revision:
        raise ItemConflict("This item changed in another window. Reopen it to load the latest version; your draft is still here.")



def move_kanban_item(item_id, column_id, before_id=None, revision=None):
    connection = db()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        item = kanban_item(item_id)
        if item is None:
            return None
        _check_revision(item, revision)
        changes = _place_item(item, column_id, before_id)
        if changes:
            connection.execute("UPDATE kanban_items SET updated_at=?,revision=revision+1 WHERE id=?", (timestamp(), item_id))
            _item_history(item_id, "moved" if "status" in changes else "reordered", changes)
    return kanban_item_detail(item_id)



def update_kanban_item(item_id, title, notes, column_id, revision):
    connection = db()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        item = kanban_item(item_id)
        if item is None:
            return None
        _check_revision(item, revision)
        changes = {field: {"before": item[field], "after": value}
                   for field, value in (("title", title), ("notes", notes)) if item[field] != value}
        if column_id != item["column_id"]:
            changes.update(_place_item(item, column_id))
        if changes:
            connection.execute("UPDATE kanban_items SET title=?,notes=?,updated_at=?,revision=revision+1 WHERE id=?",
                               (title, notes, timestamp(), item_id))
            _item_history(item_id, "updated", changes)
    return kanban_item_detail(item_id)



def transfer_kanban_item(item_id, board_id, column_id, revision, before_id=None):
    """Transfer a card atomically, retaining its ID, timestamps and history."""
    connection = db()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        item = kanban_item(item_id)
        destination = kanban_board(board_id)
        if item is None or destination is None:
            return None
        _check_revision(item, revision)
        source = kanban_board(item["board_id"])
        changes = _place_item({**item, "board_id": board_id}, column_id, before_id)
        if item["board_id"] != board_id:
            changes["board"] = {"before": {"id": source["id"], "name": source["name"]},
                                "after": {"id": board_id, "name": destination["name"]}}
        if changes:
            connection.execute("UPDATE kanban_items SET board_id=?,updated_at=?,revision=revision+1 WHERE id=?",
                               (board_id, timestamp(), item_id))
            _item_history(item_id, "transferred" if "board" in changes else "moved", changes)
    return kanban_item_detail(item_id)



def delete_kanban_item(item_id, revision):
    connection = db()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        item = kanban_item(item_id)
        if item is None:
            return False
        _check_revision(item, revision)
        connection.execute("DELETE FROM kanban_item_history WHERE item_id=?", (item_id,))
        connection.execute("DELETE FROM kanban_comments WHERE item_id=?", (item_id,))
        connection.execute("DELETE FROM kanban_links WHERE item_id=? OR target_id=?", (item_id,item_id))
        connection.execute("DELETE FROM kanban_items WHERE id=?", (item_id,))
        remaining = connection.execute("SELECT id FROM kanban_items WHERE column_id=? ORDER BY position,id",
                                       (item["column_id"],)).fetchall()
        connection.executemany("UPDATE kanban_items SET position=? WHERE id=?",
                               [(index, row["id"]) for index, row in enumerate(remaining)])
    return True



def cancel_kanban_item(item_id, cancelled, revision):
    connection = db()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        item = kanban_item(item_id)
        if item is None:
            return None
        _check_revision(item, revision)
        if bool(item["cancelled_at"]) != cancelled:
            now = timestamp()
            connection.execute("UPDATE kanban_items SET cancelled_at=?,updated_at=?,revision=revision+1 WHERE id=?",
                               (now if cancelled else None, now, item_id))
            _item_history(item_id, "cancelled" if cancelled else "restored",
                          {"cancelled": {"before": bool(item["cancelled_at"]), "after": cancelled}})
    return kanban_item_detail(item_id)



def manage_kanban_column(board_id, expected_order, name=None, column_id=None, destination_id=None):
    connection = db()
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        if not kanban_board(board_id): return None
        columns = [dict(row) for row in kanban_columns(board_id)]
        order = [row['id'] for row in columns]
        if order != expected_order: raise ItemConflict('Columns changed. Refresh the board and try again.')
        if column_id is None:
            if not isinstance(name,str) or not name.strip() or len(name.strip())>80:
                raise ValueError('Use a column name of 1–80 characters.')
            if len(order)>=20: raise ValueError('A board can have at most twenty columns.')
            connection.execute('INSERT INTO kanban_columns(board_id,name,position) VALUES(?,?,?)',(board_id,name.strip(),len(order)))
        else:
            if column_id not in order: raise ValueError('Column not found in this board.')
            if len(order)<=1: raise ValueError('Keep at least one column.')
            if destination_id is not None and (destination_id not in order or destination_id==column_id):
                raise ValueError('Choose a different destination in this board.')
            cards = [dict(row) for row in connection.execute('SELECT * FROM kanban_items WHERE column_id=? ORDER BY position,id',(column_id,))]
            if cards and destination_id is None: raise ValueError('Choose a destination for all cards before removing a nonempty column.')
            for item in cards:
                changes=_place_item(item,destination_id)
                connection.execute('UPDATE kanban_items SET updated_at=?,revision=revision+1 WHERE id=?',(timestamp(),item['id']))
                _item_history(item['id'],'moved',changes)
            connection.execute('DELETE FROM kanban_columns WHERE id=? AND board_id=?',(column_id,board_id))
            connection.executemany('UPDATE kanban_columns SET position=? WHERE id=?',[(index,ident) for index,ident in enumerate(i for i in order if i!=column_id)])
    return [dict(row) for row in kanban_columns(board_id)]



def kanban_comments(item_id):
    if not kanban_item(item_id): return []
    return [dict(row) for row in db().execute("""SELECT c.*,u.username AS author FROM kanban_comments c
        LEFT JOIN dashboard_users u ON u.id=c.user_id WHERE c.item_id=? ORDER BY c.id""",(item_id,))]



def change_kanban_comment(item_id,body=None,comment_id=None,revision=None,delete=False):
    connection=db()
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        if not kanban_item(item_id):return None
        if not delete and (not isinstance(body,str) or not body.strip() or len(body)>5000):
            raise ValueError('Comments need 1–5000 characters.')
        if comment_id is None:
            connection.execute('INSERT INTO kanban_comments(item_id,user_id,body,created_at,updated_at) VALUES(?,?,?,?,?)',
                               (item_id,_owner_id(),body.strip(),timestamp(),timestamp()))
        else:
            comment=connection.execute('SELECT * FROM kanban_comments WHERE id=? AND item_id=? AND user_id=?',
                                       (comment_id,item_id,_owner_id())).fetchone()
            if not comment:return None
            if type(revision) is not int:raise ValueError('Supply the comment revision.')
            if comment['revision']!=revision:raise ItemConflict('Comment changed. Reopen the item before editing it.')
            if delete:connection.execute('DELETE FROM kanban_comments WHERE id=?',(comment_id,))
            else:connection.execute('UPDATE kanban_comments SET body=?,updated_at=?,revision=revision+1 WHERE id=?',
                                    (body.strip(),timestamp(),comment_id))
    return kanban_item_detail(item_id)



def kanban_links(item_id,reverse=False):
    if not kanban_item(item_id):return []
    source,target=('target_id','item_id') if reverse else ('item_id','target_id')
    # Column names are internal constants, never interpolated request input.
    return [dict(row) for row in db().execute(f"""SELECT i.id AS target_id,i.title,i.board_id,
        i.cancelled_at,c.name AS column_name,l.kind FROM kanban_links l
        JOIN kanban_items i ON i.id=l.{target} JOIN kanban_boards b ON b.id=i.board_id
        JOIN kanban_columns c ON c.id=i.column_id WHERE l.{source}=? AND b.user_id=?
        ORDER BY l.kind,i.id""",(item_id,_owner_id()))]



def update_kanban_links(item_id,links,revision):
    if type(revision) is not int or not isinstance(links,list) or len(links)>50:
        raise ValueError('Supply a revision and at most fifty links.')
    normalized=[]
    for link in links:
        if not isinstance(link,dict) or type(link.get('target_id')) is not int or link.get('kind') not in ('depends_on','related'):
            raise ValueError('Each link needs a target ID and depends_on or related kind.')
        pair=(link['target_id'],link['kind'])
        if pair in normalized:raise ValueError('Duplicate link.')
        normalized.append(pair)
    connection=db()
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        item=kanban_item(item_id)
        if not item:return None
        _check_revision(item,revision)
        before=[(l['target_id'],l['kind']) for l in kanban_links(item_id)]
        for target,kind in normalized:
            if target==item_id or not kanban_item(target):raise ValueError('Choose another item owned by this account.')
            if kind=='depends_on':
                cycle=connection.execute("""WITH RECURSIVE reachable(id) AS (
                    SELECT ? UNION SELECT l.target_id FROM kanban_links l JOIN reachable r ON l.item_id=r.id
                    WHERE l.kind='depends_on' AND l.item_id<>?) SELECT 1 FROM reachable WHERE id=?""",(target,item_id,item_id)).fetchone()
                if cycle:raise ValueError('Dependencies cannot form a cycle.')
        if set(before)!=set(normalized):
            connection.execute('DELETE FROM kanban_links WHERE item_id=?',(item_id,))
            connection.executemany('INSERT INTO kanban_links(item_id,target_id,kind) VALUES(?,?,?)',[(item_id,target,kind) for target,kind in normalized])
            connection.execute('UPDATE kanban_items SET updated_at=?,revision=revision+1 WHERE id=?',(timestamp(),item_id))
            _item_history(item_id,'updated',{'links':{'before':str(before),'after':str(normalized)}})
    return kanban_item_detail(item_id)
