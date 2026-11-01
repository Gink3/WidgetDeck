"""Public installation/offline assets; no account data enters the PWA cache."""
import hashlib
import os
from pathlib import Path
from flask import render_template, send_from_directory, make_response


def init_pwa(app):
    static = Path(app.static_folder)
    public_assets = ['pwa-offline.html', 'branding/dashboard-icon-192.png', 'branding/dashboard-icon-512.png']

    def release():
        override = app.config.get('DASHBOARD_PWA_RELEASE') or os.environ.get('DASHBOARD_PWA_RELEASE')
        if override:
            return hashlib.sha256(str(override).encode()).hexdigest()[:16]
        if 'dashboard_pwa_release' not in app.extensions:
            # Calculate after widget registration. Only source/assets contribute;
            # runtime instance data and environment credentials are never read.
            paths = {p for directory in ('static', 'templates', 'dashboard')
                     for p in (Path(app.root_path) / directory).rglob('*')
                     if p.is_file() and (directory != 'dashboard' or p.suffix == '.py')}
            paths.add(Path(app.root_path) / 'app.py')
            paths.update(app.extensions.get('dashboard_widget_assets', {}).values())
            for root in app.extensions.get('dashboard_widget_resource_roots', ()):
                paths.update(p for p in root.rglob('*') if p.is_file() and
                             (p.suffix == '.py' or 'templates' in p.parts))
            digest = hashlib.sha256()
            # Relative names sort consistently across public/private build paths.
            for path in sorted(paths, key=lambda path: (path.name, str(path))):
                digest.update(path.name.encode())
                with path.open('rb') as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        digest.update(chunk)
            app.extensions['dashboard_pwa_release'] = digest.hexdigest()[:16]
        return app.extensions['dashboard_pwa_release']

    app.jinja_env.globals['pwa_release'] = release

    @app.url_defaults
    def version_assets(endpoint, values):
        if endpoint == 'static':
            values.setdefault('rev', release())

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
        revision = release()
        offline_url = '/offline.html?v=' + revision
        icons = ['/static/' + name + '?pwa=' + revision for name in public_assets[1:]]
        response = make_response(render_template('service-worker.js', revision=revision,
                                                 offline_url=offline_url, icons=icons))
        response.mimetype = 'application/javascript'
        response.headers['Cache-Control'] = 'no-cache, no-store'
        response.headers['Service-Worker-Allowed'] = '/'
        return response
