"""Account-owned launcher groups; overrides never change widget defaults or data."""
import sqlite3
import unicodedata
from flask import current_app, g
from dashboard.auth import current_user_id
from dashboard.database import db


def category_name(value):
    if not isinstance(value, str):
        raise ValueError('Category name must be text.')
    value = value.strip()
    if not value or len(value) > 64 or any(unicodedata.category(c).startswith('C') for c in value):
        raise ValueError('Category names must contain 1–64 characters without control characters.')
    return value


def init_categories(app):
    with sqlite3.connect(app.config['FOUR_AD_DATABASE']) as connection:
        connection.executescript('''
        CREATE TABLE IF NOT EXISTS utility_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            name TEXT NOT NULL, name_key TEXT NOT NULL, UNIQUE(user_id,name_key));
        CREATE TABLE IF NOT EXISTS utility_category_assignments (
            user_id INTEGER NOT NULL, utility TEXT NOT NULL, category TEXT NOT NULL,
            PRIMARY KEY(user_id,utility));
        ''')


def preferences():
    owner = current_user_id()
    if not owner or not current_app.config.get('LAUNCHER_ENABLED'):
        return [], {}
    cached = g.get('utility_category_preferences')
    if cached is not None and cached[0] == owner:
        return cached[1], cached[2]
    custom = [dict(row) for row in db().execute(
        'SELECT id,name FROM utility_categories WHERE user_id=? ORDER BY id', (owner,))]
    overrides = dict(db().execute('SELECT utility,category FROM utility_category_assignments WHERE user_id=?', (owner,)))
    g.utility_category_preferences = (owner, custom, overrides)
    return custom, overrides


def snapshot():
    from dashboard.navigation import utility_groups
    defaults = utility_groups(personalized=False)
    custom, overrides = preferences()
    categories = [{'id': None, 'name': group['name'], 'default': True} for group in defaults]
    # Personal names/IDs stay manageable if a newly enabled widget supplies the same name.
    for item in custom:
        index = next((i for i, existing in enumerate(categories) if existing['name'].casefold() == item['name'].casefold()), None)
        if index is None:
            categories.append(dict(item, default=False))
        else:
            categories[index] = dict(item, default=False)
    known = {item['name'].casefold() for item in categories}
    # A valid saved destination remains available when its original widget is disabled.
    for name in overrides.values():
        if name.casefold() not in known:
            categories.append(dict(id=None, name=name, default=True))
            known.add(name.casefold())
    valid = {item['name'].casefold(): item['name'] for item in categories}
    utilities = []
    for group in defaults:
        for link in group['links']:
            override = overrides.get(link['id'])
            utilities.append({'id': link['id'], 'label': link['label'], 'default_category': group['name'],
                'category': valid.get((override or group['name']).casefold(), group['name']),
                'override': valid.get(override.casefold()) if override else None})
    return dict(categories=categories, utilities=utilities)


def create(name):
    name = category_name(name)
    connection = db()
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        g.pop('utility_category_preferences', None)
        state = snapshot()
        if any(item['name'].casefold() == name.casefold() for item in state['categories']):
            raise ValueError('A category with that name already exists.')
        if connection.execute('SELECT COUNT(*) FROM utility_categories WHERE user_id=?', (current_user_id(),)).fetchone()[0] >= 50:
            raise ValueError('You can create up to 50 categories.')
        connection.execute('INSERT INTO utility_categories(user_id,name,name_key) VALUES(?,?,?)',
                           (current_user_id(), name, name.casefold()))
    g.pop('utility_category_preferences', None)
    return snapshot()


def delete(ident):
    connection = db()
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        g.pop('utility_category_preferences', None)
        row = connection.execute('SELECT name FROM utility_categories WHERE id=? AND user_id=?',
                                 (ident, current_user_id())).fetchone()
        if row is None:
            return None
        connection.execute('DELETE FROM utility_category_assignments WHERE user_id=? AND category=?',
                           (current_user_id(), row['name']))
        connection.execute('DELETE FROM utility_categories WHERE id=? AND user_id=?', (ident, current_user_id()))
    g.pop('utility_category_preferences', None)
    return snapshot()


def assign(utility, category):
    connection = db()
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        g.pop('utility_category_preferences', None)
        state = snapshot()
        if utility not in {item['id'] for item in state['utilities']}:
            return None
        if category is None or category == '':
            connection.execute('DELETE FROM utility_category_assignments WHERE user_id=? AND utility=?',
                               (current_user_id(), utility))
        else:
            name = category_name(category)
            selected = next((item['name'] for item in state['categories'] if item['name'].casefold() == name.casefold()), None)
            if selected is None:
                raise ValueError('Choose one of your existing categories.')
            connection.execute('''INSERT INTO utility_category_assignments(user_id,utility,category) VALUES(?,?,?)
                ON CONFLICT(user_id,utility) DO UPDATE SET category=excluded.category''',
                (current_user_id(), utility, selected))
    g.pop('utility_category_preferences', None)
    return snapshot()
