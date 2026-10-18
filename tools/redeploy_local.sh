#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PERSONAL_TOOL="${WIDGETDECK_PERSONAL_TOOL:-${DASHBOARD_PERSONAL_TOOL:-}}"
if [[ "${WIDGETDECK_CORE_ONLY:-${DASHBOARD_CORE_ONLY:-0}}" != "1" && -n "$PERSONAL_TOOL" && -f "$PERSONAL_TOOL" ]]; then
  exec python3 "$PERSONAL_TOOL" up --profile "${WIDGETDECK_PERSONAL_PROFILE:-${DASHBOARD_PERSONAL_PROFILE:-testing}}" \
    --image "${WIDGETDECK_IMAGE:-${DASHBOARD_IMAGE:-widgetdeck:personal-testing}}" \
    --name "${WIDGETDECK_CONTAINER:-${DASHBOARD_CONTAINER:-widgetdeck-local}}" --port "${WIDGETDECK_PORT:-${DASHBOARD_PORT:-8020}}" "$@"
fi

IMAGE_NAME="${WIDGETDECK_IMAGE:-${DASHBOARD_IMAGE:-widgetdeck:local}}"
CONTAINER_NAME="${WIDGETDECK_CONTAINER:-${DASHBOARD_CONTAINER:-widgetdeck-local}}"
HOST_PORT="${WIDGETDECK_PORT:-${DASHBOARD_PORT:-8020}}"
HOST_BIND="${WIDGETDECK_BIND:-${DASHBOARD_BIND:-127.0.0.1}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${WIDGETDECK_DATA_DIR:-${DASHBOARD_DATA_DIR:-${PROJECT_ROOT}/instance}}"
ADMIN_USERNAME="${DASHBOARD_ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${DASHBOARD_ADMIN_PASSWORD:-password}"
KANBAN_ENV_FILE="${DASHBOARD_KANBAN_ENV_FILE:-${SCRIPT_DIR}/../.env.kanban}"
KANBAN_ENV_ARGS=()
if [[ -f "$KANBAN_ENV_FILE" ]]; then
  KANBAN_ENV_ARGS=(--env-file "$KANBAN_ENV_FILE")
fi

case "$HOST_PORT" in ''|*[!0-9]*) echo "DASHBOARD_PORT must be numeric" >&2; exit 1;; esac
if [[ -z "$ADMIN_USERNAME" || -z "$ADMIN_PASSWORD" ]]; then
  echo "DASHBOARD_ADMIN_USERNAME and DASHBOARD_ADMIN_PASSWORD must not be empty" >&2
  exit 1
fi
mkdir -p "$DATA_DIR"
DATA_DIR="$(cd "$DATA_DIR" && pwd)"
chmod 700 "$DATA_DIR"
SECRET_FILE="${DASHBOARD_SECRET_FILE:-${DATA_DIR}/.dashboard_secret}"
if [[ -n "${DASHBOARD_SECRET_KEY:-}" ]]; then
  SECRET_KEY="$DASHBOARD_SECRET_KEY"
elif [[ -f "$SECRET_FILE" ]]; then
  SECRET_KEY="$(<"$SECRET_FILE")"
else
  umask 077
  SECRET_KEY="$(openssl rand -hex 48)"
  printf '%s\n' "$SECRET_KEY" > "$SECRET_FILE"
fi
echo "Building $IMAGE_NAME..."
docker build -t "$IMAGE_NAME" "$PROJECT_ROOT"
if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1 && [[ ! -e "${DATA_DIR}/dashboard.sqlite" ]]; then
  echo "Preserving existing dashboard data..."
  docker cp "${CONTAINER_NAME}:/app/instance/." "$DATA_DIR/" 2>/dev/null || true
fi
echo "Replacing $CONTAINER_NAME..."
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER_NAME" --restart unless-stopped \
  "${KANBAN_ENV_ARGS[@]}" \
  --mount "type=bind,source=${DATA_DIR},target=/app/instance" \
  -e "DASHBOARD_SECRET_KEY=${SECRET_KEY}" \
  -e "DASHBOARD_ADMIN_USERNAME=${ADMIN_USERNAME}" \
  -e "DASHBOARD_ADMIN_PASSWORD=${ADMIN_PASSWORD}" \
  -p "${HOST_BIND}:${HOST_PORT}:8000" "$IMAGE_NAME" >/dev/null
URL="http://127.0.0.1:${HOST_PORT}/"
echo "Waiting for $URL..."
for attempt in $(seq 1 30); do
  if curl --fail --silent "$URL" >/dev/null; then
    echo "WidgetDeck is running at $URL"
    exit 0
  fi
  sleep 1
done
docker logs --tail 80 "$CONTAINER_NAME" >&2
exit 1
