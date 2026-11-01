"""Public installation help; application data remains behind account protection."""
from flask import render_template


def init_pwa(app):
    @app.get('/install')
    def pwa_install():
        return render_template('pwa_install.html')
