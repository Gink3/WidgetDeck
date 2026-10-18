"""Durable, owner/widget-scoped outbox; no network work in web requests."""
from contextlib import closing
import hashlib
import json
import sqlite3
import time
import uuid

from dashboard.database import db,timestamp
from . import MailError,address
from .transport import build_message

MESSAGES='dashboard_mail_messages'
RECIPIENTS='dashboard_mail_recipients'


def initialize(app):
    with closing(sqlite3.connect(app.config['FOUR_AD_DATABASE'])) as connection, connection:
        connection.executescript(f'''
            CREATE TABLE IF NOT EXISTS {MESSAGES} (
                id TEXT PRIMARY KEY, widget TEXT NOT NULL, user_id INTEGER NOT NULL,
                subject TEXT NOT NULL, text_body TEXT, html_body TEXT, sender TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                lease_owner TEXT, lease_until REAL, idempotency_key TEXT, payload_hash TEXT NOT NULL,
                UNIQUE(widget,user_id,idempotency_key));
            CREATE INDEX IF NOT EXISTS dashboard_mail_ready ON {MESSAGES}(status,next_attempt);
            CREATE TABLE IF NOT EXISTS {RECIPIENTS} (
                message_id TEXT NOT NULL, recipient TEXT NOT NULL, status TEXT NOT NULL,
                code INTEGER, reason TEXT NOT NULL DEFAULT '', PRIMARY KEY(message_id,recipient));
        ''')


def enqueue(widget,owner,config,recipients,subject,text,html,key):
    if not isinstance(recipients,(list,tuple)) or not 1<=len(recipients)<=50:
        raise MailError('Supply between 1 and 50 recipient addresses.')
    recipients=list(dict.fromkeys(address(r) for r in recipients))
    if not isinstance(subject,str) or not 1<=len(subject)<=998 or any(ord(c)<32 or ord(c)==127 for c in subject):
        raise MailError('Supply a subject without control characters (up to 998 characters).')
    if not isinstance(text,str) or (html is not None and not isinstance(html,str)) or not (text or html):
        raise MailError('Supply text and optional HTML message content.')
    if len(text.encode())+len((html or '').encode())>1024*1024:
        raise MailError('Messages must not exceed 1 MiB.')
    if key is not None and (not isinstance(key,str) or not 1<=len(key)<=200 or any(ord(c)<32 for c in key)):
        raise MailError('Idempotency keys use 1–200 visible characters.')
    ident=uuid.uuid4().hex;now=timestamp()
    message=dict(id=ident,sender=config.sender,subject=subject,text_body=text,html_body=html)
    if len(build_message(message,recipients).as_bytes())>1024*1024:
        raise MailError('Encoded messages must not exceed 1 MiB.')
    payload={**message,'recipients':recipients};payload.pop('id')
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    with db():
        db().execute('BEGIN IMMEDIATE')
        if key is not None:
            previous=db().execute(f'SELECT id,payload_hash FROM {MESSAGES} WHERE widget=? AND user_id=? AND idempotency_key=?',(widget,owner,key)).fetchone()
            if previous:
                if previous['payload_hash']!=digest:
                    raise MailError('Idempotency key already belongs to a different message.')
                return status(widget,owner,previous['id'])
        db().execute(f'''INSERT INTO {MESSAGES}
            (id,widget,user_id,subject,text_body,html_body,sender,created_at,updated_at,status,idempotency_key,payload_hash)
            VALUES(?,?,?,?,?,?,?,?,?,'queued',?,?)''',
            (ident,widget,owner,subject,text,html,config.sender,now,now,key,digest))
        db().executemany(f'INSERT INTO {RECIPIENTS}(message_id,recipient,status) VALUES(?,?,?)',[(ident,r,'queued') for r in recipients])
    return status(widget,owner,ident)


def status(widget,owner,ident):
    row=db().execute(f'SELECT id,widget,status,attempts,created_at,updated_at FROM {MESSAGES} WHERE id=? AND widget=? AND user_id=?',(ident,widget,owner)).fetchone()
    if not row:raise MailError('Mail message not found.')
    return {**dict(row),'recipients':[dict(r) for r in db().execute(f'SELECT recipient,status,code,reason FROM {RECIPIENTS} WHERE message_id=? ORDER BY recipient',(ident,))]}


def claim(config,now=None):
    now=time.time() if now is None else now
    token=uuid.uuid4().hex
    with db():
        db().execute('BEGIN IMMEDIATE')
        expired=[r[0] for r in db().execute(f"SELECT id FROM {MESSAGES} WHERE status='processing' AND lease_until<=?",(now,))]
        for ident in expired:
            db().execute(f"UPDATE {RECIPIENTS} SET status='uncertain',reason='expired_lease' WHERE message_id=? AND status IN ('queued','transient')",(ident,))
            db().execute(f"UPDATE {MESSAGES} SET status='uncertain',lease_owner=NULL,lease_until=NULL,updated_at=? WHERE id=?",(timestamp(),ident))
        row=db().execute(f"SELECT * FROM {MESSAGES} WHERE status='queued' AND next_attempt<=? ORDER BY created_at,id LIMIT 1",(now,)).fetchone()
        if not row:return None
        message=dict(row)
        recipients=[r[0] for r in db().execute(f"SELECT recipient FROM {RECIPIENTS} WHERE message_id=? AND status IN ('queued','transient') ORDER BY recipient",(message['id'],))]
        lease=max(120,(len(recipients)+20)*config.timeout)
        db().execute(f"UPDATE {MESSAGES} SET status='processing',lease_owner=?,lease_until=?,attempts=attempts+1,updated_at=? WHERE id=?",(token,now+lease,timestamp(),message['id']))
    return dict(message=message,recipients=recipients,token=token,attempt=message['attempts']+1)


def finish(config,claimed,outcomes,now=None):
    now=time.time() if now is None else now
    ident,token,attempt=claimed['message']['id'],claimed['token'],claimed['attempt']
    with db():
        db().execute('BEGIN IMMEDIATE')
        row=db().execute(f"SELECT 1 FROM {MESSAGES} WHERE id=? AND status='processing' AND lease_owner=?",(ident,token)).fetchone()
        if not row:return False  # A stale worker cannot overwrite uncertain state.
        for recipient in claimed['recipients']:
            outcome=outcomes.get(recipient,dict(status='uncertain',code=None,reason='missing_outcome'))
            state=outcome['status'];reason=outcome['reason']
            if state=='transient' and attempt>=config.max_attempts:
                state,reason='failed','retry_exhausted'
            db().execute(f'UPDATE {RECIPIENTS} SET status=?,code=?,reason=? WHERE message_id=? AND recipient=?',
                         (state,outcome['code'],reason,ident,recipient))
        states={r[0] for r in db().execute(f'SELECT status FROM {RECIPIENTS} WHERE message_id=?',(ident,))}
        state=('uncertain' if 'uncertain' in states else 'queued' if 'transient' in states
               else 'accepted' if states=={'accepted'} else 'partial' if 'accepted' in states else 'failed')
        delay=min(3600,60*2**(attempt-1)) if state=='queued' else 0
        db().execute(f'UPDATE {MESSAGES} SET status=?,next_attempt=?,lease_owner=NULL,lease_until=NULL,updated_at=? WHERE id=?',
                     (state,now+delay,timestamp(),ident))
    return True
