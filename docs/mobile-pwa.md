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
