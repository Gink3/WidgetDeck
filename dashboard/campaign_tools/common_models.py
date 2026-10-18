from dashboard.auth import current_user_id
from dashboard.database import db


def _owner_id():
    owner_id = current_user_id()
    if not owner_id:
        raise RuntimeError("A signed-in user is required.")
    return owner_id



def _owned(table, object_id):
    return db().execute(f"SELECT * FROM {table} WHERE id=? AND user_id=?", (object_id, _owner_id())).fetchone()
