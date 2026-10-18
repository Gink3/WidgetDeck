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
`uncertain`, with no automatic retry. Administrators can open **Settings → Email
administration** to see the latest 100 messages across accounts, recipient outcomes,
SMTP reason codes, widget/user attribution and attempt counts. Message bodies and
SMTP credentials are never displayed. This page and every action require an
administrator browser session; bearer API keys cannot use these controls. All
mutations require the existing browser CSRF token and same-origin checks.

The test form enqueues a plain-text message to one explicitly entered address.
The normal 1 MiB encoded-message limit applies; widget submissions retain the
50-recipient limit. Sending still requires the dedicated mail worker. No request
performs SMTP I/O, and a queued test is not proof of inbox delivery.

Failed, partial and uncertain completed messages with retained payloads can be
retried after review. The form carries a revision so concurrent workers, reviews
or retention changes invalidate stale submissions. Accepted recipients are never
resent. Uncertain recipients require explicit acknowledgment of possible duplicate
delivery. Review records retain the administrator ID and time; each approved retry
starts a fresh bounded attempt budget. Active messages and expired payloads cannot
be retried. SMTP must be enabled to queue tests or retries.

Retention removes completed subjects, sender/recipient addresses and text/HTML
payloads after 7 days, then removes message metadata and associated review records
after 30 days. Retention measures from completion, including uncertain outcomes;
queued and processing mail is retained. Existing completed messages use their last
update time when upgrading. Idempotency bindings and payload hashes survive the
7-day purge and expire with metadata at 30 days, after which the key may be reused.
Backups remain subject to the operator's separate backup retention policy.

The worker applies cleanup at startup and at most once per minute while running.
Use the administrator cleanup button or `python -m dashboard.mail.worker --cleanup`
when SMTP is disabled or no worker runs. Cleanup never sends mail. Keep the outbox
in existing database backups and access controls. Error/status output contains
stable reason codes rather than server response text or mail bodies.
