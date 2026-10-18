import os

from flask import Flask, jsonify, redirect, render_template, request, url_for
from dashboard.database import init_database as init_core_database
from dashboard.activity import init_database as init_activity_database, recent_activity
from dashboard.auth import bootstrap_admin, current_user, get_user_settings, init_auth, register_auth_routes, save_user_settings
from dashboard.navigation import init_navigation
from dashboard.launcher import init_launcher

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
init_core_database(app)
init_auth(app)
init_activity_database(app)
bootstrap_admin(app)
init_navigation(app)
init_launcher(app)
from dashboard.mail import init_mail
init_mail(app)
register_auth_routes(app)
app.config.update(
    SESSION_COOKIE_NAME=os.environ.get("DASHBOARD_SESSION_COOKIE_NAME", "dashboard_session"),
    SESSION_COOKIE_PATH="/",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


from dashboard.http_security import configure_cookies, configure_headers
configure_cookies(app)
configure_headers(app)

@app.before_request
def require_account():
    """All dashboard tools are private; only the account screens remain public."""
    if request.endpoint in {"static", "login", "login_submit", "register", "register_submit"}:
        return None
    if current_user():
        return None
    if request.path.startswith("/api/") or "/api/" in request.path:
        return jsonify(error="Sign in is required."), 401
    return redirect(url_for("login", next=request.full_path))




























@app.get("/")
def home():
    return render_template("home.html")


@app.get("/api/activity")
def activity_list():
    return jsonify(activity=recent_activity(limit=request.args.get("limit", 12)),
                   areas=app.extensions['dashboard_widgets']['contributions'].activity)






@app.get("/settings")
def settings():
    # Both panels load asynchronously; seed their tokens in the HTML response so
    # concurrent first-load responses cannot replace each other's signed cookie.
    import secrets
    from flask import session
    for key in ('launcher_csrf', 'api_keys_csrf'):
        session.setdefault(key, secrets.token_urlsafe(32))
    return render_template("settings.html", mail_administrator=bool(current_user()["is_admin"]))


@app.get("/api/settings")
def settings_get():
    return jsonify(settings=get_user_settings())


@app.put("/api/settings")
def settings_put():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Supply a settings object."), 400
    existing = get_user_settings()
    changed = False
    try:
        for contribution in app.extensions['dashboard_widgets']['contributions'].settings:
            update = contribution['update']
            result = update(payload, existing) if update else None
            if result is not None:
                existing, changed = result, True
    except ValueError as error:
        return jsonify(error=str(error)), 400
    if not changed:
        return jsonify(error="No supported settings supplied."), 400
    return jsonify(settings=save_user_settings(existing))




from dashboard.widgets.profiles import register_profile
register_profile(app, app.config.get('DASHBOARD_WIDGET_PROFILE') or os.environ.get('DASHBOARD_WIDGET_PROFILE'))


def __getattr__(name):
    from importlib import import_module
    if name in {'apply_wounds', 'battle', 'stat', 'fight_turn', 'simulate', 'grimdark_future', 'keyword_value', 'weapon_in_range', 'prepare_force', 'living_models', 'total_wounds', 'value', 'dice_amount', 'normalize_side', 'living'}:
        return getattr(import_module('dashboard_private_widgets.grimdark_future'), name)
    if name == 'frontline_command':
        return getattr(import_module('dashboard_private_widgets.frontline_command'), name)
    raise AttributeError(name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
