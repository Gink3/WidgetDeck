"""Browser form CSRF checks and process-independent, expiring login budgets."""
import hashlib
import hmac
import secrets
import os
import time
from urllib.parse import urlsplit
from flask import current_app, request, session
from dashboard.database import db


def csrf_token():
    if not session.get('auth_csrf_token'):
        session['auth_csrf_token'] = secrets.token_urlsafe(32)
    return session['auth_csrf_token']


def valid_csrf():
    supplied = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token') or ''
    expected = session.get('auth_csrf_token') or ''
    if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
        return False
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        return False
    for header in ('Origin', 'Referer'):
        if request.headers.get(header):
            source = urlsplit(request.headers[header])
            # Compare authority; TLS may terminate at a trusted upstream proxy.
            if source.scheme not in ('http', 'https') or source.netloc.casefold() != request.host.casefold():
                return False
    return True


def consume_budget(action, now=None):
    now = time.time() if now is None else now
    window = max(1, int(current_app.config.get('AUTH_RATE_WINDOW', 900)))
    default = os.environ.get('DASHBOARD_AUTH_LOGIN_LIMIT' if action == 'login' else 'DASHBOARD_AUTH_REGISTER_LIMIT', 10 if action == 'login' else 20)
    limit = max(1, int(current_app.config.get('AUTH_RATE_LIMIT', default)))
    # Never trust arbitrary forwarded IP headers. Proxy deployment must normalize
    # REMOTE_ADDR, or apply its own per-client rate limits at the trusted boundary.
    key = hashlib.sha256((action+':'+(request.remote_addr or 'unknown')).encode()).hexdigest()
    connection = db()
    connection.execute('BEGIN IMMEDIATE')
    try:
        connection.execute('DELETE FROM dashboard_auth_attempts WHERE attempted_at<=?', (now-window,))
        count = connection.execute('SELECT COUNT(*) FROM dashboard_auth_attempts WHERE bucket=?', (key,)).fetchone()[0]
        if count >= limit:
            connection.commit()
            return False
        connection.execute('INSERT INTO dashboard_auth_attempts(bucket,attempted_at) VALUES(?,?)', (key,now))
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
