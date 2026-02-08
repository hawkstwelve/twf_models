#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIMARY_APP_DIR="$ROOT_DIR/frontend_v2/models-v2"
APP_DIR="${APP_DIR:-$PRIMARY_APP_DIR}"
DST_DIR="${DST_DIR:-$PRIMARY_APP_DIR}"

if [[ ! -f "$APP_DIR/package.json" ]]; then
  echo "Frontend app dir does not look buildable (missing package.json): $APP_DIR" >&2
  exit 1
fi

SRC_DIST="$APP_DIR/dist"

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
  echo "No dist build found. Building frontend..."
  (
    cd "$APP_DIR"
    npm ci
    npm run build
  )
fi

if [[ "$APP_DIR" != "$DST_DIR" ]]; then
  mkdir -p "$DST_DIR"
  mkdir -p "$DST_DIR/assets"

  if [[ -f "$DST_DIR/index.html" && ! -f "$DST_DIR/index.phase5.backup.html" ]]; then
    cp "$DST_DIR/index.html" "$DST_DIR/index.phase5.backup.html"
  fi

  cp "$SRC_DIST/index.html" "$DST_DIR/index.html"
  cp "$SRC_DIST"/assets/* "$DST_DIR/assets/"
fi

echo "Phase 5 frontend cutover sync complete"
echo "App dir: $APP_DIR"
echo "Dist: $SRC_DIST"
echo "Target: $DST_DIR"
