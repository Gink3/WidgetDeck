"""Deployment-aware cookie and response defaults without proxy-header trust."""
import os
from flask import request


def configure_cookies(app):
    app.config.setdefault('DASHBOARD_HTTPS', os.environ.get('DASHBOARD_SESSION_COOKIE_SECURE', '').lower() in {'1','true','yes'})
    app.config['SESSION_COOKIE_SECURE'] = app.config['DASHBOARD_HTTPS']


def configure_headers(app):
    @app.after_request
    def security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        if request.is_secure or app.config.get('DASHBOARD_HTTPS'):
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
        response.headers.setdefault('Content-Security-Policy-Report-Only',
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; font-src 'self' data:; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
        if response.mimetype == 'text/html':
            response.headers.setdefault('Cache-Control', 'private, no-store')
        return response
