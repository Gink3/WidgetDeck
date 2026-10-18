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

## Container publishing and local deployment

```sh
./tools/push_zot.sh
./tools/redeploy_local.sh
```

Publishing builds `widgetdeck:latest` and pushes `192.168.0.245:8568/widgetdeck:latest` to the existing Zot registry. Set `WIDGETDECK_ZOT_IMAGE` to choose another registry or tag, and `WIDGETDECK_IMAGE` to choose the local image name. GitHub repository publication is a separate operation.

Local deployment defaults to image `widgetdeck:local`, container `widgetdeck-local`, and `127.0.0.1:8020`. Use `WIDGETDECK_CONTAINER`, `WIDGETDECK_PORT`, `WIDGETDECK_BIND`, and `WIDGETDECK_DATA_DIR` to override these settings. Set a different port if another local application uses 8020. Deployment scripts continue to accept their existing `DASHBOARD_*` overrides; a corresponding `WIDGETDECK_*` override takes precedence.

The public deployment script builds this checkout by default. Private builds require an explicit `WIDGETDECK_PERSONAL_TOOL` (or legacy `DASHBOARD_PERSONAL_TOOL`) and a profile configured to use the WidgetDeck checkout. A sibling Dashboard-Personal checkout is never selected automatically.
