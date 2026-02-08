#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_DIR="$ROOT_DIR/frontend_v2/models-v2-maplibre"
SRC_DIST="$APP_DIR/dist"
DST_DIR="$ROOT_DIR/frontend_v2/models-v2"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd cp
require_cmd mkdir

if [[ ! -f "$SRC_DIST/index.html" ]]; then
  require_cmd npm
  echo "No dist build found. Building MapLibre frontend..."
  (
    cd "$APP_DIR"
    npm ci
    npm run build
  )
fi

mkdir -p "$DST_DIR"
mkdir -p "$DST_DIR/assets"

if [[ -f "$DST_DIR/index.html" && ! -f "$DST_DIR/index.phase5.backup.html" ]]; then
  cp "$DST_DIR/index.html" "$DST_DIR/index.phase5.backup.html"
fi

cp "$SRC_DIST/index.html" "$DST_DIR/index.html"
cp "$SRC_DIST"/assets/* "$DST_DIR/assets/"

echo "Phase 5 frontend cutover sync complete"
echo "Source: $SRC_DIST"
echo "Target: $DST_DIR"
