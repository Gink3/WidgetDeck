# Private mobile access

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
