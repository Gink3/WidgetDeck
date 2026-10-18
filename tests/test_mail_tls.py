"""Real TLS handshakes with a temporary fixture CA and loopback-only SMTP."""
from dataclasses import replace
from pathlib import Path
import shutil
import socketserver
import ssl
import subprocess
import tempfile
import threading
import unittest

from dashboard.mail import Config
from dashboard.mail.transport import deliver


class Handler(socketserver.StreamRequestHandler):
    def finish(self):
        try:
            super().finish()
        finally:
            self.connection.close()

    def handle(self):
        secure = self.server.implicit
        try:
            self.wfile.write(b'220 fixture ESMTP\r\n')
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                verb = line.split(b' ', 1)[0].strip().upper()
                if verb in (b'EHLO', b'HELO'):
                    self.wfile.write(b'250 fixture\r\n' if secure else b'250-fixture\r\n250 STARTTLS\r\n')
                elif verb == b'STARTTLS' and not secure:
                    self.wfile.write(b'220 ready\r\n')
                    self.wfile.flush()
                    self.rfile.close()
                    self.wfile.close()
                    self.connection = self.server.context.wrap_socket(self.connection, server_side=True)
                    self.rfile = self.connection.makefile('rb')
                    self.wfile = self.connection.makefile('wb', buffering=0)
                    secure = True
                elif verb in (b'MAIL', b'RCPT') and secure:
                    self.wfile.write(b'250 accepted\r\n')
                elif verb == b'DATA' and secure:
                    self.wfile.write(b'354 content\r\n')
                    while True:
                        piece = self.rfile.readline()
                        if not piece:
                            return
                        if piece == b'.\r\n':
                            break
                    self.server.accepted += 1
                    self.wfile.write(b'250 accepted\r\n')
                else:
                    self.wfile.write(b'500 unsupported\r\n')
        except (OSError, ssl.SSLError):
            pass  # Expected when the client rejects the fixture certificate.


class FixtureServer(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def get_request(self):
        connection, address = super().get_request()
        if self.implicit:
            try:
                connection = self.context.wrap_socket(connection, server_side=True)
            except Exception:
                connection.close()
                raise
        return connection, address


@unittest.skipUnless(shutil.which('openssl'), 'Fixture certificate generation needs OpenSSL')
class MailTLSChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='smtp-fixture-ca-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.certificate = cls.root / 'fixture.pem'
        cls.key = cls.root / 'fixture-key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-nodes', '-newkey', 'rsa:2048',
                        '-days', '1', '-keyout', str(cls.key), '-out', str(cls.certificate),
                        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.key.chmod(0o600)

    def server(self, implicit):
        server = FixtureServer(('127.0.0.1', 0), Handler)
        server.implicit = implicit
        server.accepted = 0
        server.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server.context.load_cert_chain(self.certificate, self.key)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def message(self):
        return dict(id='tls-fixture', sender='fixture@example.invalid', subject='fixture',
                    text_body='independently authored fixture', html_body=None)

    def config(self, server, mode):
        return Config.from_env({'DASHBOARD_SMTP_ENABLED':'1', 'DASHBOARD_SMTP_HOST':'localhost',
            'DASHBOARD_SMTP_PORT':str(server.server_address[1]), 'DASHBOARD_SMTP_MODE':mode,
            'DASHBOARD_SMTP_FROM':'fixture@example.invalid', 'DASHBOARD_SMTP_TIMEOUT':'2',
            'DASHBOARD_SMTP_CA_FILE':str(self.certificate)})

    def test_private_ca_starttls_and_implicit_tls_accept(self):
        for mode in ('starttls', 'tls'):
            with self.subTest(mode=mode):
                server = self.server(mode == 'tls')
                result = deliver(self.config(server, mode), self.message(), ['one@example.invalid'])
                self.assertEqual(result['one@example.invalid']['status'], 'accepted')
                self.assertEqual(server.accepted, 1)

    def test_untrusted_certificate_never_sends_data_or_falls_back(self):
        for mode in ('starttls', 'tls'):
            with self.subTest(mode=mode):
                server = self.server(mode == 'tls')
                config = replace(self.config(server, mode), ca_file=None)
                result = deliver(config, self.message(), ['one@example.invalid'])
                self.assertNotEqual(result['one@example.invalid']['status'], 'accepted')
                self.assertEqual(server.accepted, 0)

    def test_trusted_ca_still_requires_matching_hostname(self):
        for mode in ('starttls', 'tls'):
            with self.subTest(mode=mode):
                server = self.server(mode == 'tls')
                config = replace(self.config(server, mode), host='127.0.0.1')
                result = deliver(config, self.message(), ['one@example.invalid'])
                self.assertNotEqual(result['one@example.invalid']['status'], 'accepted')
                self.assertEqual(server.accepted, 0)
