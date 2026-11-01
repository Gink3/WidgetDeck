# Private mobile access

Open `/install` for iPhone Home Screen installation instructions. The manifest
uses `/` as its stable identity, scope and launch URL and requests standalone
display. Launching without a valid account session goes to sign-in; protected
deep links retain their destination. Installation help and icon/manifest assets
are public and contain no account data. Verify installation on the target iPhone;
browser emulation cannot prove Home Screen installation or OS lifecycle behavior.

WidgetDeck uses the same account protection in a browser and an installed Home
Screen app. Serve production through trusted HTTPS and set
`DASHBOARD_SESSION_COOKIE_SECURE=1` and a persistent `DASHBOARD_SECRET_KEY` in the
server's private runtime environment. Never embed server credentials in client assets.

## Registration

For a private installation, set `DASHBOARD_REGISTRATION_ENABLED=false` in the
server runtime environment. Both registration GET and POST requests then return
a clear 403 page, including submissions from previously opened forms. Existing
accounts and administrator bootstrap continue to work. The login page directs
new users to contact the administrator instead of offering account creation.

Registration remains enabled by default for compatibility. To enroll someone,
an operator can temporarily enable registration during a controlled enrollment
window, then disable it again. A deployment/restart is a separate operator action.

## Sessions

Sign in with “Keep me signed in” on a personal device to retain the cookie across
browser/app restarts. The default is 30 days, configurable with
`DASHBOARD_REMEMBER_DAYS` (1–365). Without the checkbox, the cookie lasts for the
browser session. New logins also have an absolute server-side expiry: activity
does not extend it. Only a hash of the random session identifier is stored on
the server. Credentials are never stored in localStorage.

Signing out revokes the current new-style session on the server, so replaying
its old cookie cannot restore access. Other devices remain signed in. Sessions
created before this upgrade remain valid under the existing cookie policy;
they acquire the new expiry/revocation protection on their next login. Rotating
the server signing secret invalidates all signed cookies, including legacy
sessions. Removing an account prevents further authenticated access.

`GET /api/session` returns the current browser account ID, persistence flag and
absolute expiry (null for legacy sessions), with `private, no-store`. It returns
401 after expiry or logout; it is not an integration-key endpoint. Sign-in
preserves local deep links, including after incorrect credentials. Draft recovery
and foreground refresh build on this endpoint without replaying failed writes.

## Offline privacy

The root service worker stores only the generic offline page and two public,
versioned app icons. It never stores authenticated pages, API results, documents,
editor scripts, drafts or mutation requests in Cache Storage. Offline navigation
shows a generic retry screen; an offline save fails instead of being queued.
The online app displays connection-loss feedback. This does not add offline
editing or synchronization. Application-specific draft recovery uses a separate,
account-isolated mechanism and must not expose drafts on the offline screen.

Because executable assets are not service-worker cached, the offline fallback
cannot run stale application/editor code. A failed service-worker registration
does not prevent normal online use. Network/Cache Storage tests exercise actual
Chromium service-worker behavior; iPhone standalone checks remain separate.

## Updates

Application source, templates and core/private-widget assets contribute to a
release fingerprint, calculated once after widget registration. Static links
include this fingerprint, so a fresh page loads the matching asset version.
An optional `DASHBOARD_PWA_RELEASE` identifies an immutable deployment; change it
on every upgrade and rollback if configured.

A newly installed worker waits while the current app is open. A notice asks the
user to save work and explicitly reload, with a confirmation before activation.
Cancellation leaves the current page intact. Activating in another tab does not
reload that tab or its editors. Closing all tabs permits the standard browser
activation lifecycle. Activated workers remove only obsolete WidgetDeck PWA
caches; other applications' storage is untouched. No executable code is cached
by the worker, and offline navigation cannot resurrect old editor code.

## Save and session feedback

The shared runtime observes existing same-origin cookie-authenticated API fetches
without changing their requests, response objects or errors. It shows saving,
saved and failed states; an unrelated successful request does not clear a failed
save. HTTP 202 is acceptance, not proof of completed persistence. Interrupted
writes are never retried automatically. Integration-key requests are excluded.

Session checks run on initial load and foreground/online transitions. After an
expired session, the workspace is hidden while its edits remain in memory; use
the sign-in link in another tab, then return. The same account restores the
existing view. A different account cannot reveal that view through the shared
runtime. Full draft recovery after OS eviction is separate work. API calls that
need refreshed CSRF tokens must refresh their widget state before retrying.

The runtime emits `widgetdeck:resume` (with `recovered`),
`widgetdeck:session-expired`, `widgetdeck:account-changed`,
`widgetdeck:connection` and `widgetdeck:save-state` events for widget adapters.
Resume signals do not themselves reload pages or replay writes. Browser network
hints are advisory: an actual successful response clears the connection warning.
Persistent-session cookies are not refreshed on unmodified read responses, so
parallel foreground reads cannot replace newer CSRF state with an older cookie.

### Transient API actions

API computations that use POST without saving user content can pass the optional
local fetch hint `widgetdeckOperation: 'transient'`. For example, OCR extraction
returns editable text that has not yet been captured or saved. This suppresses
the shared Saving/Saved message for that request while preserving connection and
session checks, the native Response/error, and unresolved save failures. It does
not change the API, transmit a header, authorize work, or replay requests. Older
shells without this observer simply ignore the extra fetch option. Widgets still
provide their own action-specific progress, result and error messages.
