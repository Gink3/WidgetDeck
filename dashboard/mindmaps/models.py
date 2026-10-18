import json
import math
import uuid

from flask import current_app

from dashboard.auth import current_user_id
from dashboard.database import db, timestamp


NODE_TYPES = {"topic", "idea", "question", "note", "reference", "task"}
EDGE_KINDS = {"hierarchy", "relation"}


def init_database(app):
    with __import__("sqlite3").connect(app.config["FOUR_AD_DATABASE"]) as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS mind_maps (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            viewport TEXT NOT NULL DEFAULT '{"x":0,"y":0,"zoom":1}', layout_mode TEXT NOT NULL DEFAULT 'freeform',
            settings TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS mind_maps_owner_updated ON mind_maps(user_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS mind_map_nodes (
            id TEXT PRIMARY KEY, map_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            x REAL NOT NULL, y REAL NOT NULL, width REAL NOT NULL DEFAULT 180, height REAL NOT NULL DEFAULT 44,
            type TEXT NOT NULL DEFAULT 'topic', collapsed INTEGER NOT NULL DEFAULT 0, metadata TEXT NOT NULL DEFAULT '{}',
            style_override TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(map_id) REFERENCES mind_maps(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS mind_map_nodes_map ON mind_map_nodes(map_id);
        CREATE TABLE IF NOT EXISTS mind_map_edges (
            id TEXT PRIMARY KEY, map_id TEXT NOT NULL, source_id TEXT NOT NULL, target_id TEXT NOT NULL,
            kind TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', directed INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(map_id) REFERENCES mind_maps(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS mind_map_edges_map ON mind_map_edges(map_id);
        CREATE TABLE IF NOT EXISTS mind_map_settings (user_id INTEGER PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL);
        """)


def owner_id():
    value = current_user_id()
    if not value:
        raise PermissionError("Sign in is required.")
    return value


def map_row(map_id):
    return db().execute("SELECT * FROM mind_maps WHERE id=? AND user_id=?", (map_id, owner_id())).fetchone()


def list_maps():
    rows = db().execute("SELECT * FROM mind_maps WHERE user_id=? ORDER BY updated_at DESC", (owner_id(),)).fetchall()
    return [summary(row) for row in rows]


def summary(row):
    return {"id": row["id"], "name": row["name"], "description": row["description"], "layout_mode": row["layout_mode"], "created_at": row["created_at"], "updated_at": row["updated_at"]}


def document(row):
    nodes = [dict(item) for item in db().execute("SELECT * FROM mind_map_nodes WHERE map_id=? ORDER BY created_at", (row["id"],))]
    edges = [dict(item) for item in db().execute("SELECT * FROM mind_map_edges WHERE map_id=?", (row["id"],))]
    for node in nodes:
        node["collapsed"] = bool(node["collapsed"])
        node["metadata"] = _loads(node.pop("metadata"), {})
        node["style_override"] = _loads(node.pop("style_override"), {})
    for edge in edges:
        edge["directed"] = bool(edge["directed"])
    return {**summary(row), "viewport": _loads(row["viewport"], {"x": 0, "y": 0, "zoom": 1}), "settings": _loads(row["settings"], {}), "nodes": nodes, "edges": edges}


def create(payload):
    data = validate_document(payload, create=True)
    identifier = str(uuid.uuid4())
    now = timestamp()
    db().execute("INSERT INTO mind_maps(id,user_id,name,description,viewport,layout_mode,settings,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", (
        identifier, owner_id(), data["name"], data["description"], json.dumps(data["viewport"]), data["layout_mode"], json.dumps(data["settings"]), now, now,
    ))
    _replace_graph(identifier, data["nodes"], data["edges"], now)
    db().commit()
    return document(map_row(identifier))


def update(map_id, payload):
    row = map_row(map_id)
    if not row:
        return None
    data = validate_document(payload)
    now = timestamp()
    connection = db()
    connection.execute("UPDATE mind_maps SET name=?,description=?,viewport=?,layout_mode=?,settings=?,updated_at=? WHERE id=? AND user_id=?", (
        data["name"], data["description"], json.dumps(data["viewport"]), data["layout_mode"], json.dumps(data["settings"]), now, map_id, owner_id(),
    ))
    _replace_graph(map_id, data["nodes"], data["edges"], now)
    connection.commit()
    return document(map_row(map_id))


def delete(map_id):
    if not map_row(map_id):
        return False
    connection = db()
    connection.execute("DELETE FROM mind_map_edges WHERE map_id=?", (map_id,))
    connection.execute("DELETE FROM mind_map_nodes WHERE map_id=?", (map_id,))
    connection.execute("DELETE FROM mind_maps WHERE id=? AND user_id=?", (map_id, owner_id()))
    connection.commit()
    return True


def duplicate(map_id):
    source = map_row(map_id)
    if not source:
        return None
    payload = document(source)
    payload["name"] = f"{payload['name']} copy"
    id_map = {node["id"]: str(uuid.uuid4()) for node in payload["nodes"]}
    for node in payload["nodes"]:
        node["id"] = id_map[node["id"]]
    for edge in payload["edges"]:
        edge["id"] = str(uuid.uuid4())
        edge["source_id"] = id_map[edge["source_id"]]
        edge["target_id"] = id_map[edge["target_id"]]
    return create(payload)


def get_settings():
    row = db().execute("SELECT data FROM mind_map_settings WHERE user_id=?", (owner_id(),)).fetchone()
    return _loads(row["data"], {}) if row else {}


def save_settings(data):
    if not isinstance(data, dict):
        raise ValueError("Settings must be an object.")
    db().execute("INSERT INTO mind_map_settings(user_id,data,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at", (owner_id(), json.dumps(data), timestamp()))
    db().commit()
    return data


def _replace_graph(map_id, nodes, edges, now):
    connection = db()
    connection.execute("DELETE FROM mind_map_edges WHERE map_id=?", (map_id,))
    connection.execute("DELETE FROM mind_map_nodes WHERE map_id=?", (map_id,))
    connection.executemany("INSERT INTO mind_map_nodes(id,map_id,title,description,x,y,width,height,type,collapsed,metadata,style_override,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (node["id"], map_id, node["title"], node["description"], node["x"], node["y"], node["width"], node["height"], node["type"], int(node["collapsed"]), json.dumps(node["metadata"]), json.dumps(node["style_override"]), now, now) for node in nodes
    ])
    connection.executemany("INSERT INTO mind_map_edges(id,map_id,source_id,target_id,kind,label,directed) VALUES(?,?,?,?,?,?,?)", [
        (edge["id"], map_id, edge["source_id"], edge["target_id"], edge["kind"], edge["label"], int(edge["directed"])) for edge in edges
    ])


def validate_document(payload, create=False):
    if not isinstance(payload, dict):
        raise ValueError("A mind-map document is required.")
    raw_nodes = payload.get("nodes")
    if create and raw_nodes is None:
        raw_nodes = [_new_root(payload.get("name"))]
    if not isinstance(raw_nodes, list) or len(raw_nodes) > 1000:
        raise ValueError("A map needs between 1 and 1,000 nodes.")
    nodes = [_node(item) for item in raw_nodes]
    node_ids = {node["id"] for node in nodes}
    if len(node_ids) != len(nodes):
        raise ValueError("Node ids must be unique.")
    raw_edges = payload.get("edges", [])
    if not isinstance(raw_edges, list) or len(raw_edges) > 3000:
        raise ValueError("A map can contain up to 3,000 edges.")
    edges = [_edge(item, node_ids) for item in raw_edges]
    if len({edge["id"] for edge in edges}) != len(edges):
        raise ValueError("Edge ids must be unique.")
    _validate_hierarchy(nodes, edges)
    viewport = payload.get("viewport", {"x": 0, "y": 0, "zoom": 1})
    if not isinstance(viewport, dict) or not all(_number(viewport.get(key, 0)) for key in ("x", "y", "zoom")):
        raise ValueError("Viewport values must be numbers.")
    name = str(payload.get("name") or "Untitled mind map").strip()[:120]
    return {"name": name or "Untitled mind map", "description": str(payload.get("description") or "")[:1000], "viewport": {"x": float(viewport.get("x", 0)), "y": float(viewport.get("y", 0)), "zoom": max(.05, min(4, float(viewport.get("zoom", 1))))}, "layout_mode": str(payload.get("layout_mode") or "freeform") if payload.get("layout_mode") in {"freeform", "mindmap", "radial"} else "freeform", "settings": payload.get("settings") if isinstance(payload.get("settings"), dict) else {}, "nodes": nodes, "edges": edges}


def _node(raw):
    if not isinstance(raw, dict) or not raw.get("id"):
        raise ValueError("Every node needs an id.")
    try:
        numeric = {key: float(raw.get(key, default)) for key, default in (("x", 0), ("y", 0), ("width", 180), ("height", 44))}
    except (TypeError, ValueError) as error:
        raise ValueError("Node coordinates must be numbers.") from error
    if not all(_number(value) for value in numeric.values()):
        raise ValueError("Node coordinates must be numbers.")
    node_type = str(raw.get("type") or "topic")
    if node_type not in NODE_TYPES:
        node_type = "topic"
    return {"id": str(raw["id"]), "title": str(raw.get("title") or "New idea")[:300], "description": str(raw.get("description") or "")[:10000], **numeric, "type": node_type, "collapsed": bool(raw.get("collapsed")), "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}, "style_override": raw.get("style_override") if isinstance(raw.get("style_override"), dict) else {}}


def _edge(raw, node_ids):
    if not isinstance(raw, dict) or not raw.get("id"):
        raise ValueError("Every edge needs an id.")
    source, target = str(raw.get("source_id") or ""), str(raw.get("target_id") or "")
    if source not in node_ids or target not in node_ids or source == target:
        raise ValueError("Edges must connect two different nodes in the map.")
    kind = str(raw.get("kind") or "relation")
    if kind not in EDGE_KINDS:
        raise ValueError("Unsupported edge kind.")
    return {"id": str(raw["id"]), "source_id": source, "target_id": target, "kind": kind, "label": str(raw.get("label") or "")[:300], "directed": bool(raw.get("directed")) if kind == "relation" else True}


def _validate_hierarchy(nodes, edges):
    parents = {}
    children = {node["id"]: [] for node in nodes}
    for edge in edges:
        if edge["kind"] != "hierarchy":
            continue
        if edge["target_id"] in parents:
            raise ValueError("A node can have only one hierarchy parent.")
        parents[edge["target_id"]] = edge["source_id"]
        children[edge["source_id"]].append(edge["target_id"])
    seen, visiting = set(), set()
    def visit(node_id):
        if node_id in visiting:
            raise ValueError("Hierarchy edges cannot form a cycle.")
        if node_id in seen:
            return
        visiting.add(node_id)
        for child in children[node_id]:
            visit(child)
        visiting.remove(node_id)
        seen.add(node_id)
    for node in nodes:
        visit(node["id"])


def _number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def _loads(value, fallback):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _new_root(name):
    return {"id": str(uuid.uuid4()), "title": str(name or "Central idea"), "x": 0, "y": 0, "width": 190, "height": 48, "type": "topic", "collapsed": False, "description": "", "metadata": {}, "style_override": {}}
