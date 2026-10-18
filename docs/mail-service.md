# Widget mail service

Email is disabled by default. Existing installations require no SMTP configuration.
A widget declares the `mail` capability and its deployment profile must grant it.
Inside a signed-in request, `context.mail().enqueue(to=[...], subject=..., text=...,
html=None, idempotency_key=None)` persists a message without network work.
`context.mail().status(message_id)` returns status only for that widget and user;
it remains available when sending is disabled. An idempotency key is scoped to
widget identity and user, survives restarts, and rejects a different payload.

Configure the web process and dedicated worker with identical server settings:

| Variable | Meaning/default |
| --- | --- |
| `DASHBOARD_SMTP_ENABLED` | `1` enables enqueue and worker; default `0` |
| `DASHBOARD_SMTP_HOST` | DNS hostname or IP; private network hosts supported |
| `DASHBOARD_SMTP_MODE` | `starttls` (default), `tls`, or `plain` |
| `DASHBOARD_SMTP_PORT` | 587; 465 for `tls` |
| `DASHBOARD_SMTP_FROM` | Fixed bare sender address |
| `DASHBOARD_SMTP_USERNAME`, `DASHBOARD_SMTP_PASSWORD` | Both set, or both omitted for an authorized relay |
| `DASHBOARD_SMTP_TIMEOUT` | Per socket operation, 1–120 seconds; default 30 |
| `DASHBOARD_SMTP_CA_FILE` | Optional mounted PEM trust file for an internal CA |
| `DASHBOARD_SMTP_MAX_ATTEMPTS` | 1–10; default 5 |
| `DASHBOARD_SMTP_ALLOW_PLAINTEXT` | Must explicitly be `1` to use `plain` |

TLS verifies certificates and hostnames and never falls back to plaintext.
For a local Poste server, use its private DNS name or IP and the matching trusted
certificate. Store secrets in private deployment configuration, outside Git.

Run `python -m dashboard.mail.worker` as a dedicated process with the same
Dashboard configuration, database volume, and filesystem permissions as the web
app. `--once` processes at most one ready message. The web process never starts
a worker automatically. Multiple workers claim messages atomically.

The SQLite outbox adds separate tables without changing existing utility data.
Each recipient has its own outcome. Recipients already accepted by SMTP are not
resent when another recipient receives a temporary refusal. Temporary failures
retry with exponential delay, starting at 60 seconds and capped at one hour,
up to the configured attempt limit. `accepted` means the SMTP server accepted
responsibility; it does not establish inbox delivery.

A lost acknowledgment after DATA, missing outcome, or expired worker lease is
`uncertain`, with no automatic retry. Administrator-reviewed retry and outbox
retention controls remain part of the follow-up email administration work (#84).
Payloads remain in the database until retention is implemented; include the
outbox in the existing database backup and access controls. Error/status output
contains stable reason codes rather than server response text or mail bodies.
