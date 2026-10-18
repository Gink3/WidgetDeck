import json
import re
import unicodedata
import uuid
from pathlib import Path

from flask import current_app, session

from dashboard.activity import record_edit, record_session_edit
from dashboard.auth import current_user_id
from dashboard.database import db, timestamp


def init_database(app):
    with __import__("sqlite3").connect(app.config["FOUR_AD_DATABASE"]) as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS wiki_pages (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT NOT NULL, slug TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(user_id, slug)
        );
        CREATE INDEX IF NOT EXISTS wiki_pages_owner_updated ON wiki_pages(user_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS wiki_inbox (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, content TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, processed_at TEXT,
            revision INTEGER NOT NULL DEFAULT 0, page_ids TEXT NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS wiki_inbox_owner ON wiki_inbox(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS wiki_page_navigation (
            user_id INTEGER NOT NULL, page_id TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0,
            viewed_at TEXT, PRIMARY KEY(user_id, page_id)
        );
        CREATE TABLE IF NOT EXISTS wiki_images (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, filename TEXT NOT NULL, stored_name TEXT NOT NULL,
            mime_type TEXT NOT NULL, byte_size INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS wiki_images_owner ON wiki_images(user_id, created_at DESC);
        """)

        columns = {row[1] for row in connection.execute("PRAGMA table_info(wiki_pages)")}
        for name, definition in {"metadata": "TEXT NOT NULL DEFAULT '{}'", "deleted_at": "TEXT", "revision": "INTEGER NOT NULL DEFAULT 0"}.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE wiki_pages ADD COLUMN {name} {definition}")
        image_columns = {row[1] for row in connection.execute("PRAGMA table_info(wiki_images)")}
        for name, definition in {"tags": "TEXT NOT NULL DEFAULT '[]'", "revision": "INTEGER NOT NULL DEFAULT 0"}.items():
            if name not in image_columns:
                connection.execute(f"ALTER TABLE wiki_images ADD COLUMN {name} {definition}")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS wiki_aliases (user_id INTEGER NOT NULL, alias TEXT NOT NULL COLLATE NOCASE, page_id TEXT NOT NULL, UNIQUE(user_id, alias));
            CREATE TABLE IF NOT EXISTS wiki_revisions (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, page_id TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS wiki_attachments (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, page_id TEXT NOT NULL,
                filename TEXT NOT NULL, stored_name TEXT NOT NULL, mime_type TEXT NOT NULL,
                byte_size INTEGER NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS wiki_attachments_page ON wiki_attachments(user_id, page_id);
            CREATE TABLE IF NOT EXISTS wiki_macros (user_id INTEGER NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL, UNIQUE(user_id, name));
        """)

        attachment_columns = {r[1] for r in connection.execute("PRAGMA table_info(wiki_attachments)")}
        for name, definition in {"text_content": "TEXT NOT NULL DEFAULT ''", "processing_status": "TEXT NOT NULL DEFAULT 'pending'", "processing_error": "TEXT NOT NULL DEFAULT ''", "preview_type": "TEXT NOT NULL DEFAULT ''", "preview_pages": "INTEGER NOT NULL DEFAULT 0"}.items():
            if name not in attachment_columns:
                connection.execute(f"ALTER TABLE wiki_attachments ADD COLUMN {name} {definition}")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS wiki_backup_settings (user_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1, interval_hours INTEGER NOT NULL DEFAULT 24, retain_count INTEGER NOT NULL DEFAULT 7, last_success TEXT, last_attempt TEXT, error TEXT NOT NULL DEFAULT '', requested INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS wiki_restore_jobs (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, filename TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', imported INTEGER, error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, finished_at TEXT);
        """)


def owner_id():
    value = current_user_id()
    if not value:
        raise PermissionError("Sign in is required.")
    return value


def slugify(value):
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:90] or "untitled"


def unique_slug(title, exclude_id=None):
    base = slugify(title)
    candidate, number = base, 2
    while True:
        row = db().execute("SELECT id FROM wiki_pages WHERE user_id=? AND slug=?", (owner_id(), candidate)).fetchone()
        alias = db().execute("SELECT page_id FROM wiki_aliases WHERE user_id=? AND alias=?", (owner_id(), candidate)).fetchone()
        if (not row or row["id"] == exclude_id) and (not alias or alias[0] == exclude_id):
            return candidate
        candidate = f"{base[:84]}-{number}"
        number += 1


def decode(row):
    if not row:
        return None
    page = dict(row)
    page["metadata"] = normalize_metadata(json.loads(page["metadata"]))
    from .facts import table_facts
    page["metadata"]["properties"] = {**table_facts(page["content"]), **page["metadata"]["properties"]}
    page["aliases"] = [r[0] for r in db().execute("SELECT alias FROM wiki_aliases WHERE user_id=? AND page_id=?", (owner_id(), page["id"]))]
    return page


def summary(row):
    page = decode(row)
    page["preview"] = page.pop("content")[:600]
    return page


def list_pages(query="", category="", review="", trash=False):
    rows = db().execute("SELECT * FROM wiki_pages WHERE user_id=? AND deleted_at IS " + ("NOT NULL" if trash else "NULL") + " ORDER BY updated_at DESC", (owner_id(),)).fetchall()
    results = []
    query = str(query).strip().casefold()
    for row in rows:
        page = summary(row)
        metadata = page["metadata"]
        if category and category not in metadata.get("categories", []):
            continue
        content = row["content"].casefold()
        title = page["title"].casefold()
        aliases = " ".join(page["aliases"]).casefold()
        document_hits = []
        if query:
            document_hits = [dict(r) for r in db().execute("SELECT id,filename,text_content FROM wiki_attachments WHERE user_id=? AND page_id=?", (owner_id(), page["id"])) if query in (r["filename"] + " " + r["text_content"]).casefold()]
            page["document_matches"] = [{"id": d["id"], "filename": d["filename"], "excerpt": d["text_content"][max(0,d["text_content"].casefold().find(query)-60):max(0,d["text_content"].casefold().find(query)-60)+240]} for d in document_hits]
        facts_text = json.dumps(metadata["properties"], ensure_ascii=False).casefold()
        if query and query not in title + " " + aliases + " " + content + " " + facts_text and not document_hits:
            continue
        page["score"] = (100 if title == query else 0) + (30 if query in title else 0) + (20 if query in aliases else 0) + content.count(query) if query else 0
        if query:
            at = content.find(query)
            page["preview"] = row["content"][max(0, at - 80):max(0, at - 80) + 300] if at >= 0 else row["content"][:300]
        if review == "inbox" and metadata.get("status") != "inbox": continue
        if review == "unfinished" and metadata.get("status", "draft") not in ("draft", "inbox"): continue
        if review == "stale":
            from datetime import datetime, timezone, timedelta
            if datetime.fromisoformat(metadata.get("reviewed_at") or page["updated_at"]) > datetime.now(timezone.utc) - timedelta(days=90): continue
        if review in ("unconnected", "missing", "deleted-links"):
            connections = links(page["slug"])
            if review == "unconnected" and (connections["incoming"] or connections["outgoing"]): continue
            if review == "missing" and not connections["missing"]: continue
            if review == "deleted-links" and not connections["deleted"]: continue
        results.append(page)
    return sorted(results, key=lambda p: p["score"], reverse=True)


def get(slug, include_deleted=False):
    row = db().execute("SELECT * FROM wiki_pages WHERE user_id=? AND (slug=? OR id=(SELECT page_id FROM wiki_aliases WHERE user_id=? AND alias=? COLLATE NOCASE)) ORDER BY slug=? DESC LIMIT 1", (owner_id(), slug, owner_id(), slug, slug)).fetchone()
    return decode(row) if row and (include_deleted or not row["deleted_at"]) else None


def snapshot(page):
    db().execute("INSERT INTO wiki_revisions VALUES(?,?,?,?,?)", (str(uuid.uuid4()), owner_id(), page["id"], json.dumps(page), timestamp()))


def revisions(slug):
    page = get(slug)
    if not page: return []
    return [dict(row) | {"snapshot": json.loads(row["snapshot"])} for row in db().execute("SELECT * FROM wiki_revisions WHERE user_id=? AND page_id=? ORDER BY created_at DESC", (owner_id(), page["id"]))]


def normalize_metadata(value):
    if not isinstance(value, dict): raise ValueError("Page properties must be an object.")
    result = {"status": str(value.get("status", "draft")), "type": str(value.get("type", "Article")), "categories": value.get("categories", []), "sources": value.get("sources", []), "properties": value.get("properties", {})}
    if result["status"] not in ("draft", "inbox", "complete"): raise ValueError("Invalid page status.")
    if not isinstance(result["categories"], list) or not all(isinstance(v, str) for v in result["categories"]): raise ValueError("Categories must be a list of names.")
    result["categories"] = list(dict.fromkeys(c.strip() for c in result["categories"] if c.strip()))
    if not isinstance(result["properties"], dict) or not all(isinstance(v, str) for v in result["properties"].values()): raise ValueError("Properties must contain text values.")
    if not isinstance(result["sources"], list) or not all(isinstance(v, dict) and isinstance(v.get("title"), str) and isinstance(v.get("id"), str) for v in result["sources"]): raise ValueError("Each source needs an ID and title.")
    ids = set()
    for source in result["sources"]:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", source["id"]) or source["id"] in ids: raise ValueError("Source IDs must be unique letters, numbers, hyphens or underscores.")
        ids.add(source["id"])
        if not all(isinstance(source.get(key, ""), str) for key in ("url", "locator", "notes")): raise ValueError("Source fields must be text.")
    if "topic" in value:
        topic = value["topic"]
        if not isinstance(topic, dict) or not isinstance(topic.get("enabled", False), bool): raise ValueError("Invalid topic settings.")
        if not all(isinstance(topic.get(k, ""), str) for k in ("title", "category", "type", "status", "property", "value", "sort")): raise ValueError("Topic filters must be text.")
        result["topic"] = {k: topic.get(k, "") for k in ("title", "category", "type", "status", "property", "value", "sort")}
        result["topic"]["enabled"] = topic.get("enabled", False)
        mode = topic.get("mode", "filters")
        selected = topic.get("page_ids", [])
        if mode not in ("filters", "selected"): raise ValueError("Invalid topic selection mode.")
        if not isinstance(selected, list) or not all(isinstance(i, str) for i in selected): raise ValueError("Selected pages must be a list of page IDs.")
        result["topic"]["mode"] = mode
        result["topic"]["page_ids"] = list(dict.fromkeys(selected))
        if result["topic"]["sort"] not in ("", "title", "updated"): raise ValueError("Invalid topic sort order.")
    if value.get("reviewed_at"):
        from datetime import datetime
        parsed = datetime.fromisoformat(str(value["reviewed_at"]))
        if not parsed.tzinfo: raise ValueError("Review date must include a timezone.")
        result["reviewed_at"] = parsed.isoformat()
    if len(json.dumps(result)) > 100000: raise ValueError("Page properties are too large.")
    return result


WIKI_LINK = re.compile(r"\[\[\s*([^\]|]+?)(?:\|[^\]]*)?\s*\]\]")


def linked_slugs(content, pages=()):
    """Return internal page slugs named by wiki links, resolving titles too."""
    titles = {row["title"].casefold(): row["slug"] for row in pages}
    by_id = {row["id"]: row["slug"] for row in pages}
    for alias in db().execute("SELECT alias,page_id FROM wiki_aliases WHERE user_id=?", (owner_id(),)):
        if alias["page_id"] in by_id: titles[alias["alias"].casefold()] = by_id[alias["page_id"]]
    slugs = {row["slug"] for row in pages}
    result = set()
    for match in WIKI_LINK.finditer(str(content or "")):
        target = match.group(1).strip().rstrip("\\")
        result.add(target if target in slugs else titles.get(target.casefold(), slugify(target)))
    return result


def links(slug):
    """Find the existing wiki articles this page points to and that point to it."""
    page = get(slug)
    if not page:
        return None
    rows = db().execute(
        "SELECT id, title, slug, updated_at, content FROM wiki_pages WHERE user_id=? AND deleted_at IS NULL ORDER BY title COLLATE NOCASE",
        (owner_id(),),
    ).fetchall()
    by_slug = {row["slug"]: row for row in rows}
    outgoing = [
        {"title": by_slug[target]["title"], "slug": target}
        for target in sorted(linked_slugs(page["content"], rows), key=lambda target: by_slug[target]["title"].casefold() if target in by_slug else target)
        if target in by_slug and target != page["slug"]
    ]
    incoming = [
        {"title": row["title"], "slug": row["slug"]}
        for row in rows
        if row["slug"] != page["slug"] and page["slug"] in linked_slugs(row["content"], rows)
    ]
    all_rows = db().execute("SELECT id,title,slug,deleted_at FROM wiki_pages WHERE user_id=?", (owner_id(),)).fetchall()
    all_targets = linked_slugs(page["content"], all_rows)
    deleted = [{"slug": r["slug"], "title": r["title"]} for r in all_rows if r["deleted_at"] and r["slug"] in all_targets]
    return {"outgoing": outgoing, "incoming": incoming, "missing": sorted(all_targets - {r["slug"] for r in all_rows}), "deleted": deleted}


def create(title="Untitled page", content="", requested_slug=None):
    title = str(title or "Untitled page").strip()[:160] or "Untitled page"
    slug = unique_slug(requested_slug or title)
    now = timestamp()
    page = {"id": str(uuid.uuid4()), "user_id": owner_id(), "title": title, "slug": slug, "content": str(content or "")[:1_000_000], "created_at": now, "updated_at": now}
    db().execute("INSERT INTO wiki_pages(id,user_id,title,slug,content,created_at,updated_at) VALUES(:id,:user_id,:title,:slug,:content,:created_at,:updated_at)", page)
    db().commit()
    record_edit("wiki", page["id"], page["title"], "", page["content"], action="created")
    return get(slug)


def update(slug, data):
    session_key = data.get("edit_session")
    if session_key is None:
        # Compatibility for clients without a per-editor visit ID.
        session_key = session.setdefault("wiki_edit_session", str(uuid.uuid4()))
    try:
        session_key = str(uuid.UUID(str(session_key)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A valid editing session is required.")
    connection = db()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        page = get(slug)
        if not page:
            return None
        title = str(data.get("title") or page["title"]).strip()[:160] or "Untitled page"
        content = str(data.get("content") if "content" in data else page["content"])[:1_000_000]
        if "revision" in data and data["revision"] != page["revision"]:
            raise ValueError("This page changed in another tab. Reload before saving.")
        metadata = normalize_metadata(data.get("metadata", page["metadata"]))
        from .facts import sync_facts
        content, metadata = sync_facts(content, metadata, page["content"],
                                       rewrite_table=metadata["properties"] != page["metadata"]["properties"])
        aliases = data.get("aliases", page["aliases"])
        if not isinstance(aliases, list) or not all(isinstance(v, str) and v.strip() for v in aliases): raise ValueError("Aliases must be a list of names.")
        aliases = list(dict.fromkeys(a.strip()[:160] for a in aliases))
        if title == page["title"] and content == page["content"] and metadata == page["metadata"] and aliases == page["aliases"]:
            return page
        snapshot(page)
        new_slug = page["slug"]
        is_automatic_name = page["title"].casefold() == "untitled page" or page["slug"] == slugify(page["title"])
        has_placeholder_slug = page["slug"] == "untitled-page" or page["slug"].startswith("untitled-page-")
        if (title != page["title"] and is_automatic_name) or (has_placeholder_slug and title.casefold() != "untitled page"):
            new_slug = unique_slug(title, exclude_id=page["id"])
        if title != page["title"]:
            # Duplicate titles (including imported copies) cannot own the same alias.
            other_title = connection.execute("SELECT id FROM wiki_pages WHERE user_id=? AND title=? COLLATE NOCASE AND id!=?", (owner_id(), page["title"], page["id"])).fetchone()
            title_alias = get(page["title"], include_deleted=True)
            keep_title = page["title"].casefold() != "untitled page" and not other_title and (not title_alias or title_alias["id"] == page["id"])
            aliases = aliases + ([page["title"]] if keep_title else []) + [page["slug"]]
        aliases = list({a.casefold(): a for a in aliases}.values())
        for alias in aliases:
            other = get(alias, include_deleted=True)
            title_owner = connection.execute("SELECT id FROM wiki_pages WHERE user_id=? AND title=? COLLATE NOCASE AND id!=?", (owner_id(), alias, page["id"])).fetchone()
            if (other and other["id"] != page["id"]) or title_owner: raise ValueError(f"Alias already belongs to another page: {alias}")
        connection.execute("DELETE FROM wiki_aliases WHERE user_id=? AND page_id=?", (owner_id(), page["id"]))
        connection.executemany("INSERT INTO wiki_aliases VALUES(?,?,?)", [(owner_id(), a, page["id"]) for a in aliases])
        connection.execute("UPDATE wiki_pages SET title=?,slug=?,content=?,metadata=?,revision=revision+1,updated_at=? WHERE id=? AND user_id=?",
                           (title, new_slug, content, json.dumps(metadata), timestamp(), page["id"], owner_id()))
        if title != page["title"]:
            connection.execute("UPDATE activity_events SET resource_name=? WHERE user_id=? AND area='wiki' AND resource_id=?",
                               (title, owner_id(), page["id"]))
        record_session_edit("wiki", page["id"], title, page["content"], content, session_key)
    return get(new_slug)


def delete(slug):
    page = get(slug)
    if not page:
        return False
    db().execute("DELETE FROM activity_edit_sessions WHERE user_id=? AND area='wiki' AND resource_id=?", (owner_id(), page["id"]))
    snapshot(page)
    db().execute("UPDATE wiki_pages SET deleted_at=? WHERE id=? AND user_id=?", (timestamp(), page["id"], owner_id()))
    db().commit()
    return True


def image_folder():
    path = Path(current_app.instance_path) / "wiki_uploads" / str(owner_id())
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_image(filename, mime_type, byte_size, stored_name):
    image = {"id": str(uuid.uuid4()), "user_id": owner_id(), "filename": filename, "mime_type": mime_type, "byte_size": byte_size, "stored_name": stored_name, "created_at": timestamp()}
    db().execute("INSERT INTO wiki_images(id,user_id,filename,stored_name,mime_type,byte_size,created_at) VALUES(:id,:user_id,:filename,:stored_name,:mime_type,:byte_size,:created_at)", image)
    db().commit()
    return image


def get_image(image_id):
    row = db().execute("SELECT * FROM wiki_images WHERE id=? AND user_id=?", (image_id, owner_id())).fetchone()
    return {**dict(row), "tags": json.loads(row["tags"])} if row else None


def normalize_image_tags(tags):
    if (not isinstance(tags, list) or len(tags) > 20 or any(
            not isinstance(tag, str) or not 1 <= len(tag.strip()) <= 40 for tag in tags)):
        raise ValueError("Use at most 20 tags, each containing 1–40 characters.")
    return list(dict.fromkeys(tag.strip() for tag in tags))


class ImageConflict(ValueError):
    pass


def update_image_tags(image_id, tags, revision):
    tags = normalize_image_tags(tags)
    connection = db()
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        image = get_image(image_id)
        if image is None:
            return None
        if image["revision"] != revision:
            raise ImageConflict("This image changed in another window. Refresh the library before saving.")
        if tags != image["tags"]:
            connection.execute("UPDATE wiki_images SET tags=?,revision=revision+1 WHERE id=? AND user_id=?",
                               (json.dumps(tags, ensure_ascii=False), image_id, owner_id()))
    return get_image(image_id)


def image_library(query=''):
    images = [{**dict(row), "tags": json.loads(row["tags"])} for row in db().execute(
        "SELECT * FROM wiki_images WHERE user_id=? ORDER BY created_at DESC,id", (owner_id(),))]
    pages = db().execute("SELECT title,slug,content FROM wiki_pages WHERE user_id=? AND deleted_at IS NULL", (owner_id(),)).fetchall()
    query = query.strip().casefold()
    result = []
    for image in images:
        if query and query not in (image["filename"]+' '+' '.join(image["tags"])).casefold():
            continue
        url = '/tools/wiki/api/images/'+image['id']
        result.append({key: image[key] for key in ('id', 'filename', 'mime_type', 'byte_size', 'created_at', 'tags', 'revision')}
                      | {"url": url, "pages": [{"title": p["title"], "slug": p["slug"]} for p in pages if url in p["content"]]})
    return result


def attachment_folder():
    path = Path(current_app.instance_path) / "wiki_attachments" / str(owner_id())
    path.mkdir(parents=True, exist_ok=True)
    return path


def attachments(slug):
    page = get(slug)
    if not page: return None
    return [dict(row) for row in db().execute("SELECT id,filename,mime_type,byte_size,sha256,created_at,processing_status,processing_error,preview_type FROM wiki_attachments WHERE user_id=? AND page_id=? ORDER BY created_at", (owner_id(), page["id"]))]


def get_attachment(ident):
    row = db().execute("SELECT a.* FROM wiki_attachments a LEFT JOIN wiki_pages p ON p.id=a.page_id AND p.user_id=a.user_id LEFT JOIN wiki_inbox n ON n.id=a.page_id AND n.user_id=a.user_id WHERE a.user_id=? AND a.id=? AND ((p.id IS NOT NULL AND p.deleted_at IS NULL) OR n.id IS NOT NULL)", (owner_id(), ident)).fetchone()
    return dict(row) if row else None
