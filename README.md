# WidgetDeck

WidgetDeck is a modular workspace with authentication, persistent storage, and five bundled tools: **Wiki, Mind Maps, Kanban, Wordle, and Image Converter**.

This repository starts from an audited application snapshot. Dashboard's old Git history, private widgets, content packs, runtime data, and internal audit reports are not included.

## Build and run

```sh
docker build -t widgetdeck:core .
docker run --name widgetdeck-local -p 127.0.0.1:8020:8000 \
  --env-file /path/to/private/runtime.env \
  --mount type=bind,source=/absolute/path/to/instance,target=/app/instance \
  widgetdeck:core
```

Create the persistent instance directory first. Configure `DASHBOARD_SECRET_KEY`, `DASHBOARD_ADMIN_USERNAME`, and `DASHBOARD_ADMIN_PASSWORD` in your private runtime environment file. Use explicit credentials for production and preserve the instance directory and session secret when upgrading. SMTP is disabled unless explicitly configured; see [mail configuration](docs/mail-service.md).

The Python package, widget provider IDs, API routes, database formats, and `DASHBOARD_*` application configuration keep their existing identifiers for compatibility. Private extensions can be installed separately and selected through an explicit widget profile; they are not downloaded at runtime. See the [widget API](docs/widget-api.md).

## Checks

```sh
python -m pip install -r requirements.txt
python -m dashboard.widgets validate --profile profiles/public.json
python -m unittest discover -s tests
node --test tests/*.mjs
```

Browser checks require Playwright and a separate test application. SMTP transport tests use a disposable loopback fixture; exclude them when no SMTP connections are permitted.

Wordle's word-list source and license are included under `dashboard/wordle/`.
