"""Small local account system shared by every Dashboard tool."""

import json
import hmac
import os
import sqlite3
from functools import wraps

from flask import current_app, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


def init_auth(app):
    from dashboard.database import init_database
    init_database(app)
    # Deployments should set DASHBOARD_SECRET_KEY so sessions survive restarts.
    # A random local fallback is safer than a publicly known signing key.
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = os.environ.get("DASHBOARD_SECRET_KEY") or os.urandom(32).hex()
    with sqlite3.connect(app.config["DASHBOARD_DATABASE"]) as connection:
        connection.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_user_settings (
                user_id INTEGER PRIMARY KEY,
                data TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            )
        """)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(dashboard_users)")}
        if "is_admin" not in columns:
            connection.execute("ALTER TABLE dashboard_users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")

    with sqlite3.connect(app.config["DASHBOARD_DATABASE"]) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS dashboard_auth_attempts(id INTEGER PRIMARY KEY, bucket TEXT NOT NULL, attempted_at REAL NOT NULL)")
        connection.execute("CREATE INDEX IF NOT EXISTS dashboard_auth_attempt_bucket ON dashboard_auth_attempts(bucket,attempted_at)")
    from dashboard.auth_security import csrf_token
    app.jinja_env.globals["auth_csrf_token"] = csrf_token

    from dashboard.api_keys import init_api_keys
    init_api_keys(app)


def bootstrap_admin(app):
    """Create the deployment's initial administrator exactly once."""
    username = str(os.environ.get("DASHBOARD_ADMIN_USERNAME") or "").strip()
    password = str(os.environ.get("DASHBOARD_ADMIN_PASSWORD") or "")
    if not username or not password:
        return
    with sqlite3.connect(app.config["DASHBOARD_DATABASE"]) as connection:
        existing = connection.execute("SELECT id FROM dashboard_users WHERE username=?", (username,)).fetchone()
        if existing:
            connection.execute("UPDATE dashboard_users SET is_admin=1 WHERE id=?", (existing[0],))
            return
        from dashboard.database import timestamp
        connection.execute(
            """INSERT INTO dashboard_users(username,password_hash,is_admin,created_at)
               VALUES(?,?,1,?) ON CONFLICT(username) DO UPDATE SET is_admin=1""",
            (username, generate_password_hash(password), timestamp()),
        )


def current_user():
    if "dashboard_user" not in g:
        # Bearer credentials never fall back to browser sessions.
        # Keep the legacy read-only Kanban environment key supported.
        authorization = request.headers.get("Authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        if scheme.lower() == "bearer":
            from dashboard.api_keys import authenticate
            g.dashboard_user = authenticate(supplied)
            if g.dashboard_user is not None or g.get("account_api_key_seen"):
                return g.dashboard_user
            allowed = {"campaign_tools.kanban_list_boards", "campaign_tools.kanban_read_board", "campaign_tools.kanban_get_item"}
            key = current_app.config.get("DASHBOARD_KANBAN_API_KEY") or os.environ.get("DASHBOARD_KANBAN_API_KEY", "")
            username = current_app.config.get("DASHBOARD_KANBAN_API_USERNAME") or os.environ.get("DASHBOARD_KANBAN_API_USERNAME", "")
            if (request.method in {"GET", "HEAD"} and request.endpoint in allowed
                    and key and username and scheme.lower() == "bearer"
                    and hmac.compare_digest(supplied.encode(), key.encode())):
                from dashboard.database import db
                g.dashboard_user = db().execute(
                    "SELECT id, username, is_admin FROM dashboard_users WHERE username=?", (username,)
                ).fetchone()
            return g.dashboard_user
        user_id = session.get("user_id")
        if not user_id:
            g.dashboard_user = None
        else:
            from dashboard.database import db
            g.dashboard_user = db().execute(
                "SELECT id, username, is_admin FROM dashboard_users WHERE id=?", (user_id,)
            ).fetchone()
    return g.dashboard_user


def current_user_id():
    user = current_user()
    return int(user["id"]) if user else None


def get_user_settings():
    user_id=current_user_id()
    if not user_id:return {}
    from dashboard.database import db
    row=db().execute("SELECT data FROM dashboard_user_settings WHERE user_id=?", (user_id,)).fetchone()
    try:return json.loads(row["data"]) if row else {}
    except (TypeError,json.JSONDecodeError):return {}


def save_user_settings(data):
    user_id=current_user_id()
    if not user_id:raise RuntimeError("A signed-in user is required.")
    from dashboard.database import db, timestamp
    db().execute("INSERT INTO dashboard_user_settings(user_id,data,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at", (user_id,json.dumps(data),timestamp()))
    db().commit()
    return data


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user():
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify(error="Sign in is required."), 401
        return redirect(url_for("login", next=request.full_path))
    return wrapped


def register_auth_routes(app):
    @app.get("/login")
    def login():
        if current_user():
            return redirect(url_for("home"))
        return current_app.jinja_env.get_or_select_template("login.html").render(next=request.args.get("next", ""))

    @app.post("/login")
    def login_submit():
        error = _check_auth_form("login")
        if error: return error
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        from dashboard.database import db
        user = db().execute("SELECT * FROM dashboard_users WHERE username=?", (username,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            return current_app.jinja_env.get_or_select_template("login.html").render(
                error="Username or password is incorrect.", next=request.form.get("next", "")
            ), 401
        session.clear()
        session["user_id"] = user["id"]
        return redirect(_safe_destination(request.form.get("next")))

    @app.get("/register")
    def register():
        if current_user():
            return redirect(url_for("home"))
        return current_app.jinja_env.get_or_select_template("register.html").render()

    @app.post("/register")
    def register_submit():
        error = _check_auth_form("register")
        if error: return error
        username = str(request.form.get("username") or "").strip()
        password = str(request.form.get("password") or "")
        if not 3 <= len(username) <= 40 or not username.replace("_", "").replace("-", "").isalnum():
            return current_app.jinja_env.get_or_select_template("register.html").render(error="Use 3–40 letters, numbers, hyphens, or underscores."), 400
        reserved = [current_app.config.get('DASHBOARD_LEGACY_OWNER_USERNAME'),
                    os.environ.get('DASHBOARD_LEGACY_OWNER_USERNAME'), os.environ.get('DASHBOARD_ADMIN_USERNAME')]
        if any(name and username.casefold() == str(name).casefold() for name in reserved):
            return current_app.jinja_env.get_template("register.html").render(error="That username is unavailable."), 409
        if len(password) < 10:
            return current_app.jinja_env.get_or_select_template("register.html").render(error="Use a password of at least 10 characters."), 400
        from dashboard.database import db, timestamp
        try:
            cursor = db().execute(
                "INSERT INTO dashboard_users(username,password_hash,created_at) VALUES(?,?,?)",
                (username, generate_password_hash(password), timestamp()),
            )
            db().commit()
        except sqlite3.IntegrityError:
            return current_app.jinja_env.get_or_select_template("register.html").render(error="That username is already taken."), 409
        session.clear()
        session["user_id"] = cursor.lastrowid
        return redirect(url_for("home"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))


def _safe_destination(destination):
    if destination and destination.startswith("/") and not destination.startswith("//"):
        return destination
    return url_for("home")


def _check_auth_form(action):
    from dashboard.auth_security import valid_csrf, consume_budget
    if not valid_csrf():
        return current_app.jinja_env.get_template(action+".html").render(error="Reload this page and try again."), 403
    if not consume_budget(action):
        response = current_app.make_response((current_app.jinja_env.get_template(action+".html").render(error="Too many attempts. Try again later."),429))
        response.headers['Retry-After'] = str(current_app.config.get('AUTH_RATE_WINDOW',900))
        return response
