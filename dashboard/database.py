"""Shared SQLite infrastructure, independent of optional utility packages."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_database(app):
    """Configure shared storage without creating any utility-owned tables.

    Keep the legacy setting and connection cache compatible with existing callers.
    Explicitly distinct settings retain their existing meanings; otherwise either
    setting can configure the shared file. Runtime legacy overrides still work.
    """
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    default = str(Path(app.instance_path) / "dashboard.sqlite")
    app.config.setdefault("FOUR_AD_DATABASE", app.config.get("DASHBOARD_DATABASE", default))
    app.config.setdefault("DASHBOARD_DATABASE", app.config["FOUR_AD_DATABASE"])
    if not app.extensions.get("dashboard_database"):
        app.teardown_appcontext(close_database)
        app.extensions["dashboard_database"] = True


def db():
    if "four_ad_db" not in g:
        g.four_ad_db = sqlite3.connect(current_app.config["FOUR_AD_DATABASE"])
        g.four_ad_db.row_factory = sqlite3.Row
    return g.four_ad_db


def close_database(_error=None):
    connection = g.pop("four_ad_db", None)
    if connection is not None:
        connection.close()
