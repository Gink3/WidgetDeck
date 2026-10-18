"""SMTP tests use invented addresses and an ephemeral loopback server only."""
import socketserver
import threading
import unittest
from unittest.mock import patch,MagicMock

from dashboard.mail import Config,MailError
from dashboard.mail.transport import deliver
from dashboard.widgets import Context,Contributions,Manifest
from test_widget_api import document


class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b'220 fixture ESMTP\r\n')
        while True:
            line=self.rfile.readline()
            if not line:return
            verb=line.split(b' ',1)[0].strip().upper()
            if verb in {b'EHLO',b'HELO'}:self.wfile.write(b'250 fixture\r\n')
            elif verb==b'MAIL':self.wfile.write(b'250 sender\r\n')
            elif verb==b'RCPT':self.wfile.write(b'451 later\r\n' if b'defer@' in line else b'250 recipient\r\n')
            elif verb==b'DATA':
                self.wfile.write(b'354 content\r\n')
                parts=[]
                while True:
                    piece=self.rfile.readline()
                    if not piece:return
                    if piece==b'.\r\n':break
                    parts.append(piece)
                self.server.messages.append(b''.join(parts))
                if self.server.drop_after_data:return
                self.wfile.write(b'250 accepted\r\n')
            elif verb==b'QUIT':self.wfile.write(b'221 bye\r\n');return
            else:self.wfile.write(b'500 unsupported\r\n')


class MailTransportTests(unittest.TestCase):
    def config(self,**values):
        return Config.from_env({'DASHBOARD_SMTP_ENABLED':'1','DASHBOARD_SMTP_HOST':'mail.internal',
            'DASHBOARD_SMTP_FROM':'dashboard@example.invalid',**values})

    def test_disabled_default_tls_modes_private_ca_and_secret_redaction(self):
        self.assertFalse(Config.from_env({}).enabled)
        config=self.config(DASHBOARD_SMTP_USERNAME='account',DASHBOARD_SMTP_PASSWORD='invented-test-password')
        self.assertEqual(config.mode,'starttls');self.assertEqual(config.port,587)
        self.assertNotIn('invented-test-password',repr(config))
        self.assertTrue(config.tls_context().check_hostname)
        self.assertEqual(self.config(DASHBOARD_SMTP_MODE='tls').port,465)
        with patch('dashboard.mail.ssl.create_default_context') as create:
            self.config(DASHBOARD_SMTP_CA_FILE='/fixture/internal-ca.pem')
            create.assert_called_with(cafile='/fixture/internal-ca.pem')

    def test_invalid_config_and_plaintext_without_optin_are_rejected(self):
        for values in [{'DASHBOARD_SMTP_MODE':'plain'},{'DASHBOARD_SMTP_PORT':'0'},
            {'DASHBOARD_SMTP_TIMEOUT':'nan'},{'DASHBOARD_SMTP_USERNAME':'name'},
            {'DASHBOARD_SMTP_FROM':'sender@example.invalid\r\nBcc:other@example.invalid'},
            {'DASHBOARD_SMTP_HOST':'https://mail.internal'}]:
            with self.subTest(values=values),self.assertRaises(MailError):self.config(**values)

    def test_capability_requires_declared_profile_grant(self):
        manifest=Manifest.from_dict(document(capabilities=['mail']))
        with self.assertRaises(MailError):Context(manifest,Contributions()).mail()
        self.assertEqual(Context(manifest,Contributions(),['mail']).mail().identity,'dashboard/example')

    def test_starttls_verifies_then_authenticates_without_plaintext_fallback(self):
        config=self.config(DASHBOARD_SMTP_USERNAME='account',DASHBOARD_SMTP_PASSWORD='invented-test-password')
        client=MagicMock();client.mail.return_value=(250,b'ok');client.rcpt.return_value=(250,b'ok');client.data.return_value=(250,b'ok')
        with patch('dashboard.mail.transport.smtplib.SMTP',return_value=client):
            result=deliver(config,self.message(),['one@example.invalid'])
        self.assertEqual(result['one@example.invalid']['status'],'accepted')
        calls=[c[0] for c in client.method_calls]
        self.assertLess(calls.index('starttls'),calls.index('login'))
        self.assertTrue(client.starttls.call_args.kwargs['context'].check_hostname)

    def message(self):
        return dict(id='fixture-message',sender='dashboard@example.invalid',subject='Invented test',
                    text_body='Invented message body',html_body='<p>Invented message body</p>')

    def server(self,drop=False):
        server=socketserver.ThreadingTCPServer(('127.0.0.1',0),SMTPHandler)
        server.daemon_threads=True;server.messages=[];server.drop_after_data=drop
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return server

    def test_real_local_smtp_mime_partial_recipient_outcomes(self):
        server=self.server()
        config=self.config(DASHBOARD_SMTP_HOST='127.0.0.1',DASHBOARD_SMTP_PORT=str(server.server_address[1]),
                           DASHBOARD_SMTP_MODE='plain',DASHBOARD_SMTP_ALLOW_PLAINTEXT='1')
        outcomes=deliver(config,self.message(),['defer@example.invalid','one@example.invalid'])
        self.assertEqual(outcomes['defer@example.invalid']['status'],'transient')
        self.assertEqual(outcomes['one@example.invalid']['status'],'accepted')
        self.assertEqual(len(server.messages),1)
        self.assertIn(b'multipart/alternative',server.messages[0])

    def test_lost_data_ack_is_uncertain(self):
        server=self.server(True)
        config=self.config(DASHBOARD_SMTP_HOST='127.0.0.1',DASHBOARD_SMTP_PORT=str(server.server_address[1]),
                           DASHBOARD_SMTP_MODE='plain',DASHBOARD_SMTP_ALLOW_PLAINTEXT='1')
        self.assertEqual(deliver(config,self.message(),['one@example.invalid'])['one@example.invalid']['status'],'uncertain')
