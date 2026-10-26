"""Browser-owned launcher preferences and safe, identity-based destinations."""
from datetime import datetime, timezone
import hmac
import json
import secrets
import sqlite3
from urllib.parse import urlencode
from flask import Blueprint, current_app, jsonify, request, session, url_for
from dashboard.auth import current_user, current_user_id
from dashboard.database import db, timestamp
from dashboard.navigation import utility_groups

routes=Blueprint('launcher',__name__)


def init_launcher(app):
    with sqlite3.connect(app.config['FOUR_AD_DATABASE']) as connection:
        connection.executescript('''
        CREATE TABLE IF NOT EXISTS launcher_favourites(user_id INTEGER NOT NULL,utility TEXT NOT NULL,PRIMARY KEY(user_id,utility));
        CREATE TABLE IF NOT EXISTS launcher_favourite_targets(user_id INTEGER NOT NULL,utility TEXT NOT NULL,resource_id TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT '',PRIMARY KEY(user_id,utility,resource_id,kind));
        CREATE TABLE IF NOT EXISTS launcher_visits(user_id INTEGER NOT NULL,utility TEXT NOT NULL,resource_id TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT '',opened_at TEXT NOT NULL,PRIMARY KEY(user_id,utility,resource_id,kind));
        CREATE INDEX IF NOT EXISTS launcher_visits_recent ON launcher_visits(user_id,opened_at DESC);
        ''')
    from dashboard.utility_categories import init_categories
    init_categories(app)
    app.config["LAUNCHER_ENABLED"]=True
    app.register_blueprint(routes)
    from .search import routes as search_routes
    app.register_blueprint(search_routes)


def _legacy_resolve(utility,ident,kind=''):
    """Resolve current names and URLs only after checking the caller's ownership."""
    links={link['id']:link for group in utility_groups() for link in group['links']}
    if utility not in links:return None
    if kind=='action' and ident==utility:
        link=links[utility]
        return {'utility':utility,'utility_label':link['label'],'id':utility,'kind':'action',
                'label':link['action_label'],'context':'Action','url':link['action_url'],'external':link['external']}
    owner=current_user_id();row=None;reference=''
    if utility == 'wiki':
        row=db().execute('SELECT title,slug FROM wiki_pages WHERE id=? AND user_id=? AND deleted_at IS NULL',(ident,owner)).fetchone()
        url=url_for('wiki.editor',slug=row['slug']) if row else ''
    elif utility == 'kanban':
        if kind == 'item':
            row=db().execute('SELECT i.title,i.board_id FROM kanban_items i JOIN kanban_boards b ON b.id=i.board_id WHERE i.id=? AND b.user_id=?',(ident,owner)).fetchone()
            url='/tools/kanban?'+urlencode({'board':row['board_id'],'item':ident}) if row else ''
            reference='#'+str(ident)
        else:
            row=db().execute('SELECT name AS title FROM kanban_boards WHERE id=? AND user_id=?',(ident,owner)).fetchone()
            url='/tools/kanban?'+urlencode({'board':ident})
    elif utility == 'mind-maps':
        row=db().execute('SELECT name AS title FROM mind_maps WHERE id=? AND user_id=?',(ident,owner)).fetchone()
        url='/tools/mindmaps/'+ident
    else:
        modules = {'zettelkasten': 'zettelkasten', 'paint-rack': 'paint_rack', 'flashcards': 'flashcards', 'chapter-painter': 'chapter_painter', 'frostgrave': 'frostgrave', 'roguelike-death-tracker': 'rdt'}
        if utility not in modules:
            return None
        from importlib import import_module
        return import_module('dashboard_private_widgets.'+modules[utility]+'.hooks').resolve(ident,kind)
    if not row:return None
    labels={link['id']:link['label'] for group in utility_groups() for link in group['links']}
    return {'utility':utility,'utility_label':labels.get(utility,utility),'id':str(ident),'kind':kind,
            'label':row['title'],'context':reference,'url':url}


def resolve(utility, ident, kind=''):
    state = current_app.extensions.get('dashboard_widgets')
    if state is None:
        return _legacy_resolve(utility, ident, kind)
    active = {link['id'] for group in utility_groups() for link in group['links']}
    if utility not in active:
        return None
    if kind == 'action' and ident == utility:
        return _legacy_resolve(utility, ident, kind)
    resolver = state['contributions'].resolvers.get(utility)
    return resolver(ident, kind) if resolver else None


def recent(limit=8,utility=None):
    sql='SELECT * FROM launcher_visits WHERE user_id=?';args=[current_user_id()]
    if utility:sql+=' AND utility=?';args.append(utility)
    results=[]
    for row in db().execute(sql+' ORDER BY opened_at DESC,rowid DESC',args):
        target=resolve(row['utility'],row['resource_id'],row['kind'])
        if target:
            results.append({**target,'opened_at':row['opened_at']})
            if len(results)>=limit:break
    return results


@routes.before_request
def browser_only():
    if request.headers.get('Authorization','').partition(' ')[0].lower()=='bearer' or not session.get('user_id') or not current_user():
        return jsonify(error='Sign in to use the launcher.'),401
    if request.method not in ('GET','HEAD','OPTIONS'):
        expected=session.get('launcher_csrf','');supplied=request.headers.get('X-CSRF-Token','')
        if not expected or not hmac.compare_digest(expected.encode(),supplied.encode()):return jsonify(error='Reload Dashboard and try again.'),403


@routes.after_request
def private(response):
    response.headers['Cache-Control']='private, no-store';return response


@routes.get('/api/launcher')
def state():
    session.setdefault('launcher_csrf',secrets.token_urlsafe(32))
    return jsonify(csrf_token=session['launcher_csrf'],favourites=[r[0] for r in db().execute('SELECT utility FROM launcher_favourites WHERE user_id=? ORDER BY utility',(current_user_id(),))],recent=recent(),favourite_destinations=favourite_targets())


@routes.put('/api/launcher/favourites/<utility>')
def favourite(utility):
    data=request.get_json(silent=True)
    allowed={link['id'] for group in utility_groups() for link in group['links']}
    if utility not in allowed:return jsonify(error='Utility not found.'),404
    if not isinstance(data,dict) or type(data.get('pinned')) is not bool:return jsonify(error='Supply pinned as a boolean.'),400
    with db():
        if data['pinned']:db().execute('INSERT OR IGNORE INTO launcher_favourites VALUES(?,?)',(current_user_id(),utility))
        else:db().execute('DELETE FROM launcher_favourites WHERE user_id=? AND utility=?',(current_user_id(),utility))
    return jsonify(pinned=data['pinned'])


@routes.get('/api/launcher/recent')
def visits():return jsonify(recent=recent(),last=recent(1,request.args['utility']) if request.args.get('utility') else [])


@routes.post('/api/launcher/recent')
def visit():
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or not isinstance(data.get('utility'),str) or not isinstance(data.get('id'),(str,int)) or isinstance(data.get('id'),bool) or not isinstance(data.get('kind',''),str):return jsonify(error='Supply utility and resource ID.'),400
    target=resolve(data['utility'],str(data['id']),data.get('kind',''))
    if not target:return jsonify(error='Item not found.'),404
    with db():
        db().execute('INSERT INTO launcher_visits VALUES(?,?,?,?,?) ON CONFLICT(user_id,utility,resource_id,kind) DO UPDATE SET opened_at=excluded.opened_at',
                     (current_user_id(),target['utility'],target['id'],target['kind'],datetime.now(timezone.utc).isoformat()))
    return jsonify(item=target)


def favourite_targets():
    results=[]
    for row in db().execute('SELECT * FROM launcher_favourite_targets WHERE user_id=? ORDER BY rowid',(current_user_id(),)):
        target=resolve(row['utility'],row['resource_id'],row['kind'])
        if target:results.append(target)
    return results


@routes.put('/api/launcher/favourite-targets')
def favourite_target():
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or not isinstance(data.get('utility'),str) or not isinstance(data.get('id'),(str,int)) or isinstance(data.get('id'),bool) or not isinstance(data.get('kind',''),str) or type(data.get('pinned')) is not bool:
        return jsonify(error='Supply utility, resource ID, kind and pinned boolean.'),400
    utility,ident,kind=data['utility'],str(data['id']),data.get('kind','')
    if len(ident)>200 or len(kind)>30:return jsonify(error='Invalid destination.'),400
    target=resolve(utility,ident,kind)
    if data['pinned'] and not target:return jsonify(error='Item not found.'),404
    with db():
        if data['pinned']:db().execute('INSERT OR IGNORE INTO launcher_favourite_targets VALUES(?,?,?,?)',(current_user_id(),utility,ident,kind))
        else:db().execute('DELETE FROM launcher_favourite_targets WHERE user_id=? AND utility=? AND resource_id=? AND kind=?',(current_user_id(),utility,ident,kind))
    return jsonify(pinned=data['pinned'],favourite_destinations=favourite_targets())


@routes.get('/api/launcher/categories')
def category_state():
    from dashboard.utility_categories import snapshot
    session.setdefault('launcher_csrf', secrets.token_urlsafe(32))
    return jsonify(**snapshot(), csrf_token=session['launcher_csrf'])


@routes.post('/api/launcher/categories')
def category_create():
    from dashboard.utility_categories import create
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {'name'}:
        return jsonify(error='Supply a category name.'), 400
    try:
        return jsonify(**create(payload['name'])), 201
    except ValueError as error:
        return jsonify(error=str(error)), 400


@routes.delete('/api/launcher/categories/<int:ident>')
def category_delete(ident):
    from dashboard.utility_categories import delete
    result = delete(ident)
    return (jsonify(**result), 200) if result is not None else (jsonify(error='Category not found.'), 404)


@routes.put('/api/launcher/categories/utilities/<utility>')
def category_assign(utility):
    from dashboard.utility_categories import assign
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {'category'}:
        return jsonify(error='Supply a category or null to use the widget default.'), 400
    try:
        result = assign(utility, payload['category'])
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return (jsonify(**result), 200) if result is not None else (jsonify(error='Utility not found.'), 404)
