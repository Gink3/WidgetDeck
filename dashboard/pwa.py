"""Public installation/offline assets; no account data enters the PWA cache."""
import hashlib
from pathlib import Path
from flask import render_template, send_from_directory, make_response


def init_pwa(app):
    static = Path(app.static_folder)
    public_assets = ['pwa-offline.html', 'branding/dashboard-icon-192.png', 'branding/dashboard-icon-512.png']
    revision = hashlib.sha256(b''.join((static / name).read_bytes() for name in public_assets)).hexdigest()[:16]
    offline_url = '/offline.html?v=' + revision
    icons = ['/static/' + name + '?pwa=' + revision for name in public_assets[1:]]

    @app.get('/install')
    def pwa_install():
        return render_template('pwa_install.html')

    @app.get('/offline.html')
    def pwa_offline():
        response = send_from_directory(static, 'pwa-offline.html')
        response.headers['Cache-Control'] = 'no-cache'
        return response

    @app.get('/service-worker.js')
    def pwa_service_worker():
        response = make_response(render_template('service-worker.js', revision=revision,
                                                 offline_url=offline_url, icons=icons))
        response.mimetype = 'application/javascript'
        response.headers['Cache-Control'] = 'no-cache, no-store'
        response.headers['Service-Worker-Allowed'] = '/'
        return response
