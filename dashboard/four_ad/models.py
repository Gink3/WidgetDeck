"""Legacy shared-database exports work without installing the private utility."""
from dashboard.database import db, timestamp, close_database


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    from importlib import import_module
    return getattr(import_module('dashboard_private_widgets.four_ad.models'), name)
