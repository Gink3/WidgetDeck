"""Account-owned integration keys; browser sessions alone manage credentials."""
import hashlib
import hmac
import json
import secrets
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, request, session

SERVICES = {
    'kanban': 'Kanban',
    'wiki': 'Wiki',
    'mindmaps': 'Mind maps',
    'four_ad': 'Four Against Darkness',
    'grimdark': 'Grimdark Future simulator',
    'chapter_painter': 'Chapter Painter',
    'flashcards': 'Flashcards',
    'wordle': 'Wordle',
    'paint_rack': 'Paint Rack',
    'zettelkasten': 'Zettelkasten',
}
PREFIXES = {
    'kanban': '/api/tools/kanban/',
    'wiki': '/tools/wiki/api/',
    'mindmaps': '/tools/mindmaps/api/',
    'four_ad': '/four-ad/api/',
    'grimdark': '/api/tools/grimdark-future/',
    'chapter_painter': '/api/tools/chapter-painter/',
    'flashcards': '/api/tools/flashcards/',
    'wordle': '/api/tools/wordle/',
    'paint_rack': '/api/tools/paint-rack/',
    'zettelkasten': '/api/tools/zettelkasten/',
}


def available_services():
    state = current_app.extensions.get('dashboard_widgets')
    if state is None:
        return SERVICES, PREFIXES
    registered = state['contributions'].services
    return ({ident: item['label'] for ident, item in registered.items()},
            {ident: item['prefix'] for ident, item in registered.items()})


def init_api_keys(app):
    import sqlite3
    with sqlite3.connect(app.config['DASHBOARD_DATABASE']) as connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS dashboard_api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES dashboard_users(id),
            name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
            prefix TEXT NOT NULL, permissions TEXT NOT NULL,
            created_at TEXT NOT NULL, revoked_at TEXT)''')
    app.register_blueprint(routes)


def authenticate(token):
    from dashboard.database import db
    if not token.startswith('dash_') or len(token) > 200:
        return None
    key = db().execute('SELECT * FROM dashboard_api_keys WHERE token_hash=?',
                       (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not key:
        return None
    g.account_api_key_seen = True
    if key['revoked_at'] or not request.url_rule:
        return None
    service = next((name for name, prefix in available_services()[1].items()
                    if request.url_rule.rule.startswith(prefix)), None)
    permissions = json.loads(key['permissions'])
    level = permissions.get(service)
    if level not in {'read', 'write'}:
        return None
    if request.method not in {'GET', 'HEAD'} and level != 'write':
        return None
    return db().execute('SELECT id,username,is_admin FROM dashboard_users WHERE id=?',
                        (key['user_id'],)).fetchone()


def session_only(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        from dashboard.auth import current_user
        if (request.headers.get('Authorization', '').partition(' ')[0].lower() == 'bearer'
                or not session.get('user_id') or not current_user()):
            return jsonify(error='Sign in to manage API keys.'), 401
        if request.method != 'GET':
            expected = session.get('api_keys_csrf', '')
            supplied = request.headers.get('X-CSRF-Token', '')
            if not expected or not hmac.compare_digest(expected.encode(), supplied.encode()):
                return jsonify(error='Reload Settings and try again.'), 403
        response = view(*args, **kwargs)
        from flask import make_response
        response = make_response(response)
        response.headers['Cache-Control'] = 'no-store'
        return response
    return wrapped


routes = Blueprint('api_keys', __name__)


@routes.get('/api/account/keys')
@session_only
def list_keys():
    from dashboard.database import db
    session.setdefault('api_keys_csrf', secrets.token_urlsafe(32))
    keys = []
    for row in db().execute('SELECT id,name,prefix,permissions,created_at FROM dashboard_api_keys WHERE user_id=? AND revoked_at IS NULL ORDER BY id DESC', (session['user_id'],)):
        key = dict(row)
        key['permissions'] = json.loads(key['permissions'])
        keys.append(key)
    return jsonify(keys=keys, services=available_services()[0], csrf_token=session['api_keys_csrf'])


@routes.post('/api/account/keys')
@session_only
def create_key():
    from dashboard.database import db, timestamp
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Supply a name and service permissions.'), 400
    name, permissions = data.get('name'), data.get('permissions')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        return jsonify(error='Use a key name of 1–80 characters.'), 400
    if (not isinstance(permissions, dict) or not permissions
            or any(service not in available_services()[0] or level not in ('read', 'write')
                   for service, level in permissions.items())):
        return jsonify(error='Choose read or read and write access for at least one service.'), 400
    token = 'dash_' + secrets.token_urlsafe(32)
    cursor = db().execute('INSERT INTO dashboard_api_keys(user_id,name,token_hash,prefix,permissions,created_at) VALUES(?,?,?,?,?,?)',
                         (session['user_id'], name.strip(), hashlib.sha256(token.encode()).hexdigest(), token[:13], json.dumps(permissions), timestamp()))
    db().commit()
    return jsonify(id=cursor.lastrowid, token=token), 201


@routes.delete('/api/account/keys/<int:key_id>')
@session_only
def revoke_key(key_id):
    from dashboard.database import db, timestamp
    cursor = db().execute('UPDATE dashboard_api_keys SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL', (timestamp(), key_id, session['user_id']))
    db().commit()
    if not cursor.rowcount:
        return jsonify(error='API key not found.'), 404
    return '', 204
