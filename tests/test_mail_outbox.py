"""Outbox upgrade, ownership, restart and delivery ambiguity regressions."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from dashboard.database import init_database, db
from dashboard.mail import Config, MailError, WidgetMail
from dashboard.mail import outbox
from dashboard.mail.worker import run_once


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Flask(__name__)
        self.app.config['FOUR_AD_DATABASE'] = str(Path(self.temp.name) / 'existing.sqlite')
        init_database(self.app)
        self.config = Config(enabled=True, sender='sender@example.invalid', timeout=1, max_attempts=2)
        self.app.extensions['dashboard_mail'] = self.config
        with self.app.app_context(), db():
            db().execute('CREATE TABLE existing_data (value TEXT)')
            db().execute("INSERT INTO existing_data VALUES ('preserved')")
        outbox.initialize(self.app)
        outbox.initialize(self.app)

    def enqueue(self, recipients=None, key=None, subject='Example'):
        return outbox.enqueue('example/mail', 1, self.config,
                              recipients or ['a@example.invalid'], subject, 'Body', '<p>Body</p>', key)

    def outcome(self, state):
        return dict(status=state, code=250 if state == 'accepted' else 451, reason='fixture')

    def test_additive_schema_and_persistent_owner_scoped_idempotency(self):
        with self.app.app_context():
            first = self.enqueue(key='same')
            self.assertEqual(db().execute('SELECT value FROM existing_data').fetchone()[0], 'preserved')
        with self.app.app_context():
            self.assertEqual(self.enqueue(key='same')['id'], first['id'])
            with self.assertRaises(MailError): self.enqueue(key='same', subject='Changed')
            for widget, owner in [('other/mail', 1), ('example/mail', 2)]:
                with self.assertRaises(MailError): outbox.status(widget, owner, first['id'])
            self.assertNotIn('text_body', outbox.status('example/mail', 1, first['id']))

    def test_claim_is_exclusive_and_restart_retains_message(self):
        with self.app.app_context():
            ident = self.enqueue()['id']
            first = outbox.claim(self.config, 100)
        with self.app.app_context():
            self.assertIsNone(outbox.claim(self.config, 101))
            self.assertTrue(outbox.finish(self.config, first, {'a@example.invalid': self.outcome('accepted')}, 102))
            self.assertEqual(outbox.status('example/mail', 1, ident)['status'], 'accepted')

    def test_only_transient_recipients_retry_with_bounded_backoff(self):
        with self.app.app_context():
            ident = self.enqueue(['a@example.invalid', 'b@example.invalid'])['id']
            first = outbox.claim(self.config, 100)
            outbox.finish(self.config, first, {'a@example.invalid': self.outcome('accepted'),
                                             'b@example.invalid': self.outcome('transient')}, 100)
            self.assertIsNone(outbox.claim(self.config, 159))
            retry = outbox.claim(self.config, 160)
            self.assertEqual(retry['recipients'], ['b@example.invalid'])
            outbox.finish(self.config, retry, {'b@example.invalid': self.outcome('transient')}, 160)
            result = outbox.status('example/mail', 1, ident)
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(result['recipients'][1]['reason'], 'retry_exhausted')
            self.assertIsNone(outbox.claim(self.config, 9999))

    def test_expired_worker_is_uncertain_and_stale_finish_cannot_overwrite(self):
        with self.app.app_context():
            ident = self.enqueue()['id']
            claimed = outbox.claim(self.config, 100)
            self.assertIsNone(outbox.claim(self.config, 221))
            self.assertFalse(outbox.finish(self.config, claimed, {'a@example.invalid': self.outcome('accepted')}, 222))
            self.assertEqual(outbox.status('example/mail', 1, ident)['status'], 'uncertain')
            self.assertIsNone(outbox.claim(self.config, 9999))

    def test_missing_delivery_result_is_never_automatically_retried(self):
        with self.app.app_context():
            ident = self.enqueue()['id']
            outbox.finish(self.config, outbox.claim(self.config, 100), {}, 101)
            self.assertEqual(outbox.status('example/mail', 1, ident)['status'], 'uncertain')
            self.assertIsNone(outbox.claim(self.config, 9999))

    def test_worker_dispatch_and_disabled_read_only_status(self):
        with self.app.app_context(): ident = self.enqueue()['id']
        with patch('dashboard.mail.worker.deliver', return_value={'a@example.invalid': self.outcome('accepted')}) as send:
            self.assertTrue(run_once(self.app, 100))
            self.assertFalse(run_once(self.app, 101))
            send.assert_called_once()
        self.app.extensions['dashboard_mail'] = replace(self.config, enabled=False)
        with self.app.test_request_context(), patch('dashboard.auth.current_user_id', return_value=1):
            mail = WidgetMail('example/mail')
            self.assertEqual(mail.status(ident)['status'], 'accepted')
            with self.assertRaises(MailError): mail.enqueue(to=['a@example.invalid'], subject='X', text='X')
        with self.assertRaises(MailError): run_once(self.app)

    def test_invalid_payload_is_not_persisted(self):
        with self.app.app_context():
            for recipients, subject in [([], 'Example'), (['a@example.invalid\r\nBcc:x'], 'Example'),
                                        (['a@example.invalid'], 'Header\nInjection')]:
                with self.assertRaises(MailError):
                    outbox.enqueue('example/mail', 1, self.config, recipients, subject, 'Body', None, None)
            self.assertEqual(db().execute(f'SELECT count(*) FROM {outbox.MESSAGES}').fetchone()[0], 0)
