"""Capability-controlled widget mail; requests enqueue, dedicated workers send."""
from dataclasses import dataclass, field
import os
import re
import ssl


class MailError(ValueError):
    """A safe, payload-free configuration or submission error."""


def address(value):
    if not isinstance(value, str) or not value.isascii() or any(ord(c)<33 or ord(c)==127 for c in value) or not re.fullmatch(r'[^@\s<>(),;:"\\]+@[^@\s<>(),;:"\\]+', value):
        raise MailError('Use a plain ASCII mailbox address without display names or control characters.')
    return value


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    host: str = ''
    port: int = 587
    mode: str = 'starttls'
    username: str = field(default='', repr=False)
    password: str = field(default='', repr=False)
    sender: str = ''
    timeout: float = 30
    ca_file: str | None = None
    max_attempts: int = 5

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        prefix = 'DASHBOARD_SMTP_'
        enabled = env.get(prefix+'ENABLED', '0')
        if enabled not in {'0','1'}:
            raise MailError('DASHBOARD_SMTP_ENABLED must be 0 or 1.')
        if enabled == '0':
            return cls()
        host, mode = env.get(prefix+'HOST',''), env.get(prefix+'MODE','starttls')
        if not host or any(ord(c)<33 for c in host) or any(c in host for c in '/@\\'):
            raise MailError('Configure a plain SMTP hostname or IP address.')
        if mode not in {'starttls','tls','plain'}:
            raise MailError('SMTP mode must be starttls, tls or explicitly allowed plain.')
        if mode == 'plain' and env.get(prefix+'ALLOW_PLAINTEXT') != '1':
            raise MailError('Plaintext SMTP requires explicit operator opt-in.')
        try:
            port = int(env.get(prefix+'PORT', '465' if mode=='tls' else '587'))
            timeout = float(env.get(prefix+'TIMEOUT','30'))
            attempts = int(env.get(prefix+'MAX_ATTEMPTS','5'))
            if not 1<=port<=65535 or not 1<=timeout<=120 or not 1<=attempts<=10:
                raise ValueError()
        except ValueError as error:
            raise MailError('Invalid SMTP port, timeout or maximum attempts.') from error
        username, password = env.get(prefix+'USERNAME',''), env.get(prefix+'PASSWORD','')
        if bool(username) != bool(password) or any(c in username for c in '\r\n\x00'):
            raise MailError('Configure both SMTP username and password, or neither.')
        sender = address(env.get(prefix+'FROM',''))
        ca_file = env.get(prefix+'CA_FILE') or None
        config = cls(True,host,port,mode,username,password,sender,timeout,ca_file,attempts)
        if mode != 'plain':
            config.tls_context()  # Fail clearly before accepting queued work.
        return config

    def tls_context(self):
        try:
            return ssl.create_default_context(cafile=self.ca_file)
        except (OSError, ssl.SSLError) as error:
            raise MailError('Cannot load the configured SMTP trust certificates.') from error


def init_mail(app):
    config = Config.from_env()
    app.extensions['dashboard_mail'] = config
    from .outbox import initialize
    initialize(app)


class WidgetMail:
    def __init__(self, identity):
        self.identity = identity

    def _context(self, require_enabled=True):
        from flask import current_app
        from dashboard.auth import current_user_id
        owner = current_user_id()
        if owner is None:
            raise MailError('Mail requires a signed-in account.')
        config = current_app.extensions.get('dashboard_mail',Config())
        if require_enabled and not config.enabled:
            raise MailError('Email is not configured on this Dashboard.')
        return config, owner

    def enqueue(self, *, to, subject, text, html=None, idempotency_key=None):
        config, owner = self._context()
        from .outbox import enqueue
        return enqueue(self.identity,owner,config,to,subject,text,html,idempotency_key)

    def status(self, ident):
        _, owner = self._context(require_enabled=False)
        from .outbox import status
        return status(self.identity,owner,ident)
