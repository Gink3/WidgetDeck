#!/usr/bin/env bash
set -euo pipefail

LOCAL_IMAGE="${DASHBOARD_IMAGE:-dashboard:latest}"
ZOT_IMAGE="${DASHBOARD_ZOT_IMAGE:-192.168.0.245:8568/dashboard:latest}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Building $LOCAL_IMAGE..."
docker build --tag "$LOCAL_IMAGE" "$PROJECT_ROOT"
echo "Tagging $LOCAL_IMAGE as $ZOT_IMAGE..."
docker tag "$LOCAL_IMAGE" "$ZOT_IMAGE"
echo "Pushing $ZOT_IMAGE..."
docker push "$ZOT_IMAGE"
