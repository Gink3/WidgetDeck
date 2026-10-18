"""Legacy initializer shim; Four Against Darkness is a private package."""

def init_four_ad(app):
    from importlib import import_module
    return import_module('dashboard_private_widgets.four_ad').init_four_ad(app)
