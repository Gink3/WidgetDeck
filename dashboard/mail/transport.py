"""SMTP outcomes describe acceptance, never confirmed inbox delivery."""
from email.message import EmailMessage
from email.policy import SMTP
import smtplib
import ssl


def _outcome(code):
    return 'transient' if 400<=code<500 else 'failed'



def build_message(message, recipients):
    body = EmailMessage(policy=SMTP)
    body['From'], body['To'], body['Subject'] = message['sender'], ', '.join(recipients), message['subject']
    body['Message-ID'] = '<'+message['id']+'@dashboard.local>'
    body.set_content(message['text_body'])
    if message['html_body'] is not None:
        body.add_alternative(message['html_body'],subtype='html')
    return body


def deliver(config, message, recipients):
    outcomes = {}
    pending = []
    client = None
    data_started = False
    try:
        if config.mode == 'tls':
            client = smtplib.SMTP_SSL(config.host,config.port,timeout=config.timeout,context=config.tls_context())
        else:
            client = smtplib.SMTP(config.host,config.port,timeout=config.timeout)
        client.ehlo_or_helo_if_needed()
        if config.mode == 'starttls':
            client.starttls(context=config.tls_context())
            client.ehlo()
        if config.username:
            client.login(config.username,config.password)
        code, _ = client.mail(message['sender'])
        if not 200<=code<300:
            return {r:dict(status=_outcome(code),code=code,reason='sender_rejected') for r in recipients}
        for recipient in recipients:
            code, _ = client.rcpt(recipient)
            if 200<=code<300:
                pending.append(recipient)
            else:
                outcomes[recipient] = dict(status=_outcome(code),code=code,reason='recipient_rejected')
        if pending:
            body = build_message(message, recipients)
            data_started = True
            code, _ = client.data(body.as_bytes())
            for recipient in pending:
                outcomes[recipient] = dict(status='accepted' if 200<=code<300 else _outcome(code),code=code,reason='smtp_response')
    except smtplib.SMTPResponseException as error:
        # Explicit negative SMTP response establishes nonacceptance even at DATA.
        for recipient in recipients:
            if recipient not in outcomes:
                outcomes[recipient] = dict(status=_outcome(error.smtp_code),code=error.smtp_code,reason='smtp_rejected')
    except (OSError, smtplib.SMTPException, ssl.SSLError):
        for recipient in recipients:
            if recipient not in outcomes:
                outcomes[recipient] = dict(status='uncertain' if data_started and recipient in pending else 'transient',code=None,reason='connection_error')
    finally:
        if client is not None:
            # No QUIT failure can erase an already received DATA acceptance.
            try: client.close()
            except (OSError,smtplib.SMTPException): pass
    return outcomes
