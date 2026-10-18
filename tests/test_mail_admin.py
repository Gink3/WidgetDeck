"""Browser authorization, reviewed retries and additive retention regressions."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from flask import Flask
from dashboard.auth import init_auth
from dashboard.database import db
from dashboard.mail import Config, MailError
from dashboard.mail import outbox
from dashboard.mail.admin import routes

ROOT = Path(__file__).resolve().parents[1]


class MailAdministrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Flask(__name__, instance_path=self.temp.name, template_folder=str(ROOT/'templates'))
        self.app.config.update(TESTING=True, SECRET_KEY='mail-admin-fixture')
        init_auth(self.app)
        outbox.initialize(self.app)
        self.config = Config(enabled=True, sender='sender@example.invalid', timeout=1)
        self.app.extensions['dashboard_mail'] = self.config
        self.app.register_blueprint(routes)
        for endpoint in ('home', 'settings', 'logout'):
            self.app.add_url_rule('/fixture/'+endpoint, endpoint, lambda: '')
        self.client = self.app.test_client()
        with self.app.app_context(), db():
            db().executemany('INSERT INTO dashboard_users(id,username,password_hash,is_admin,created_at) VALUES(?,?,?,?,?)',
                             [(1,'admin','fixture',1,'old'), (2,'ordinary','fixture',0,'old')])
        self.sign_in(1)

    def sign_in(self, owner):
        with self.client.session_transaction() as session:
            session.clear()
            session['user_id'] = owner
            session['auth_csrf_token'] = 'fixture-csrf'

    def post(self, path, **data):
        return self.client.post(path, data={'csrf_token':'fixture-csrf', **data})

    def enqueue(self, recipients=None):
        return outbox.enqueue('example/mail', 2, self.config, recipients or ['a@example.invalid'],
                              'private-subject', 'private-body', '<p>private-html</p>', 'persistent-key')['id']

    def complete(self, ident, states):
        claimed = outbox.claim(self.config, 100)
        self.assertEqual(claimed['message']['id'], ident)
        outcomes = {recipient:dict(status=state, code=250 if state=='accepted' else 451, reason='fixture')
                    for recipient,state in states.items()}
        outbox.finish(self.config, claimed, outcomes, 101)
        return db().execute(f'SELECT revision FROM {outbox.MESSAGES} WHERE id=?',(ident,)).fetchone()[0]

    def test_controls_require_admin_session_and_csrf_even_with_bearer(self):
        self.sign_in(2)
        for path in ['/admin/mail','/admin/mail/test','/admin/mail/x/retry','/admin/mail/retention']:
            response = self.client.get(path) if path=='/admin/mail' else self.post(path)
            self.assertEqual(response.status_code,403)
        self.sign_in(1)
        self.assertEqual(self.client.get('/admin/mail',headers={'Authorization':'Bearer fixture'}).status_code,401)
        self.assertEqual(self.client.post('/admin/mail/test',data={'recipient':'a@example.invalid'}).status_code,403)
        self.assertEqual(self.post('/admin/mail/retention').status_code,303)
        self.assertEqual(self.client.post('/admin/mail/retention',data={'csrf_token':'fixture-csrf'},headers={'Origin':'https://foreign.invalid'}).status_code,403)
        with self.client.session_transaction() as session: session.clear()
        self.assertEqual(self.client.get('/admin/mail').status_code,401)

    def test_test_message_only_enqueues_and_is_attributed(self):
        with patch('dashboard.mail.transport.deliver') as send:
            response=self.post('/admin/mail/test',recipient='a@example.invalid',subject='test',text='body')
        self.assertEqual(response.status_code,303)
        send.assert_not_called()
        with self.app.app_context():
            row=db().execute(f'SELECT widget,user_id,status FROM {outbox.MESSAGES}').fetchone()
            self.assertEqual(tuple(row),('core/mail-admin',1,'queued'))

    def test_invalid_submission_and_size_limits_leave_no_records(self):
        for data in [dict(recipient='bad',subject='x',text='x'),
                     dict(recipient='a@example.invalid',subject='x\r\nBcc:y',text='x'),
                     dict(recipient='a@example.invalid',subject='x',text='a'*(1024*1024+1))]:
            self.assertEqual(self.post('/admin/mail/test',**data).status_code,400)
        self.assertEqual(self.post('/admin/mail/test',recipient='a@example.invalid',subject='x',text='a'*(2*1024*1024)).status_code,413)
        with self.app.app_context():
            for recipients in [['a@example.invalid']*51]:
                with self.assertRaises(MailError): outbox.enqueue('example/mail',2,self.config,recipients,'x','x',None,None)
            self.assertEqual(db().execute(f'SELECT count(*) FROM {outbox.MESSAGES}').fetchone()[0],0)

    def test_uncertain_retry_requires_ack_preserves_accepted_and_records_admin(self):
        with self.app.app_context():
            ident=self.enqueue(['a@example.invalid','b@example.invalid'])
            revision=self.complete(ident,{'a@example.invalid':'accepted','b@example.invalid':'uncertain'})
        self.assertEqual(self.post(f'/admin/mail/{ident}/retry',revision=revision).status_code,400)
        self.assertEqual(self.post(f'/admin/mail/{ident}/retry',revision=revision,acknowledge_uncertain='yes').status_code,303)
        self.assertEqual(self.post(f'/admin/mail/{ident}/retry',revision=revision,acknowledge_uncertain='yes').status_code,400)
        with self.app.app_context():
            claimed=outbox.claim(self.config,200)
            self.assertEqual(claimed['recipients'],['b@example.invalid'])
            self.assertEqual(claimed['attempt'],1)
            review=db().execute('SELECT administrator,uncertain_acknowledged FROM dashboard_mail_reviews').fetchone()
            self.assertEqual(tuple(review),(1,1))

    def test_queued_processing_accepted_and_stale_retries_fail(self):
        with self.app.app_context():
            ident=self.enqueue()
            with self.assertRaises(MailError): outbox.reviewed_retry(ident,0,1)
            claimed=outbox.claim(self.config,100)
            with self.assertRaises(MailError): outbox.reviewed_retry(ident,1,1)
            outbox.finish(self.config,claimed,{'a@example.invalid':dict(status='accepted',code=250,reason='fixture')},101)
            with self.assertRaises(MailError): outbox.reviewed_retry(ident,2,1)
            with self.assertRaises(MailError): outbox.reviewed_retry('missing',0,1)

    def test_expired_lease_then_review_cannot_be_overwritten_by_stale_worker(self):
        with self.app.app_context():
            ident=self.enqueue()
            claimed=outbox.claim(self.config,100)
            outbox.claim(self.config,10000)
            revision=db().execute(f'SELECT revision FROM {outbox.MESSAGES} WHERE id=?',(ident,)).fetchone()[0]
            outbox.reviewed_retry(ident,revision,1,True)
            self.assertFalse(outbox.finish(self.config,claimed,{},10001))
            self.assertEqual(outbox.claim(self.config,10001)['recipients'],['a@example.invalid'])

    def age(self, ident, days):
        now=datetime.now(timezone.utc)
        old=(now-timedelta(days=days)).isoformat(timespec='seconds')
        with db(): db().execute(f'UPDATE {outbox.MESSAGES} SET completed_at=?,updated_at=? WHERE id=?',(old,old,ident))
        return now

    def test_retention_preserves_active_and_idempotency_then_expires_metadata(self):
        with self.app.app_context():
            ident=self.enqueue()
            self.complete(ident,{'a@example.invalid':'failed'})
            now=self.age(ident,7)
            active=outbox.enqueue('other/mail',2,self.config,['b@example.invalid'],'active','body',None,None)['id']
            self.age(active,40)
            self.assertEqual(outbox.retain(now),dict(payloads_purged=1,metadata_deleted=0))
            self.assertEqual(self.enqueue(),ident)
            row=db().execute(f'SELECT * FROM {outbox.MESSAGES} WHERE id=?',(ident,)).fetchone()
            self.assertEqual(row['subject'],'')
            self.assertIsNone(row['text_body'])
            self.assertIsNone(row['html_body'])
            self.assertEqual(row['sender'],'')
            self.assertEqual(outbox.status('example/mail',2,ident)['recipients'],[])
            with self.assertRaises(MailError): outbox.reviewed_retry(ident,row['revision'],1)
            self.assertEqual(outbox.retain(now),dict(payloads_purged=0,metadata_deleted=0))
            self.assertEqual(outbox.retain(now+timedelta(days=23))['metadata_deleted'],1)
            self.assertIsNotNone(db().execute(f'SELECT 1 FROM {outbox.MESSAGES} WHERE id=?',(active,)).fetchone())

    def test_retention_does_not_purge_recent_completed_payload(self):
        with self.app.app_context():
            ident=self.enqueue()
            self.complete(ident,{'a@example.invalid':'uncertain'})
            now=self.age(ident,6)
            self.assertEqual(outbox.retain(now)['payloads_purged'],0)
            self.assertEqual(db().execute(f'SELECT text_body FROM {outbox.MESSAGES} WHERE id=?',(ident,)).fetchone()[0],'private-body')

    def test_upgrade_backfills_terminal_dates_once_preserving_existing_rows(self):
        with self.app.app_context():
            ident=self.enqueue()
            self.complete(ident,{'a@example.invalid':'failed'})
            with db():
                db().execute(f'UPDATE {outbox.MESSAGES} SET completed_at=NULL WHERE id=?',(ident,))
                for column in ('revision', 'completed_at', 'payload_purged_at'):
                    db().execute(f'ALTER TABLE {outbox.MESSAGES} DROP COLUMN {column}')
        outbox.initialize(self.app)
        outbox.initialize(self.app)
        with self.app.app_context():
            row=db().execute(f'SELECT completed_at,updated_at,text_body FROM {outbox.MESSAGES} WHERE id=?',(ident,)).fetchone()
            self.assertEqual(row['completed_at'],row['updated_at'])
            self.assertEqual(row['text_body'],'private-body')

    def test_disabled_mail_blocks_submission_and_retry_but_allows_retention(self):
        self.app.extensions['dashboard_mail']=Config()
        self.assertEqual(self.post('/admin/mail/test',recipient='a@example.invalid',subject='x',text='x').status_code,400)
        self.assertEqual(self.post('/admin/mail/missing/retry',revision=0).status_code,400)
        self.assertEqual(self.post('/admin/mail/retention').status_code,303)

    def test_metadata_excludes_bodies_and_credentials_and_is_bounded(self):
        with self.app.app_context():
            self.enqueue()
            messages=outbox.admin_messages()
            self.assertNotIn('private-body',str(messages))
            self.assertNotIn('private-subject',str(messages))
            self.assertNotIn('private-html',str(messages))
            self.assertNotIn('payload_hash',messages[0])
            self.assertNotIn('idempotency_key',messages[0])
        response = self.client.get('/admin/mail')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertNotIn(b'private-body',response.data)
        self.assertNotIn(b'private-subject',response.data)
        self.assertIn(b'a@example.invalid',response.data)
        self.assertIn(b'fixture-csrf',response.data)

    def test_concurrent_upgrade_and_retry_have_one_winner(self):
        with self.app.app_context():
            ident=self.enqueue()
            revision=self.complete(ident,{'a@example.invalid':'failed'})
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: outbox.initialize(self.app), range(2)))
        def retry(_):
            with self.app.app_context():
                try:
                    outbox.reviewed_retry(ident,revision,1)
                    return True
                except MailError:
                    return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(retry,range(2))),[False,True])
        with self.app.app_context():
            self.assertEqual(db().execute('SELECT count(*) FROM dashboard_mail_reviews').fetchone()[0],1)

    def test_status_list_is_bounded_and_escapes_widget_labels(self):
        with self.app.app_context():
            ident=self.enqueue()
            with db():
                for number in range(101):
                    db().execute(f'''INSERT INTO {outbox.MESSAGES}
                        (id,widget,user_id,subject,sender,created_at,updated_at,status,payload_hash)
                        VALUES(?, '<script>fixture</script>',2,'','', '2099-01-01', '2099-01-01','queued','fixture')''',
                        (str(number),))
            messages=outbox.admin_messages()
            self.assertEqual(len(messages),100)
            self.assertNotIn(ident,[m['id'] for m in messages])
        response=self.client.get('/admin/mail')
        self.assertNotIn(b'<script>fixture</script>',response.data)
        self.assertIn(b'&lt;script&gt;fixture&lt;/script&gt;',response.data)
