#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-https://api.sodakweather.com}"
SITE_BASE="${SITE_BASE:-https://sodakweather.com}"
REGION="${REGION:-pnw}"
Z="${Z:-6}"
X="${X:-10}"
Y="${Y:-22}"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd curl
require_cmd python3

echo "Phase 5 shadow validation"
echo "API_BASE=$API_BASE"
echo "SITE_BASE=$SITE_BASE"

http_code() {
  local url="$1"
  curl -sS -o /dev/null -w "%{http_code}" "$url"
}

header_value() {
  local url="$1"
  local name="$2"
  curl -sS -D - -o /dev/null "$url" \
    | awk -F': ' -v key="$(echo "$name" | tr '[:upper:]' '[:lower:]')" 'tolower($1)==key {print $2}' \
    | tr -d '\r' \
    | tail -n 1
}

latest_run() {
  local model="$1"
  curl -sS "$API_BASE/api/v2/$model/$REGION/runs" | python3 -c 'import json,sys; a=json.load(sys.stdin); print(a[0] if a else "")'
}

first_fh() {
  local model="$1"
  local run_id="$2"
  local var="$3"
  curl -sS "$API_BASE/api/v2/$model/$REGION/$run_id/$var/frames" | python3 -c 'import json,sys; a=json.load(sys.stdin); print(a[0]["fh"] if a else "")'
}

check_frontend() {
  local path="$1"
  local code
  code="$(http_code "$SITE_BASE/$path/")"
  if [[ "$code" != "200" ]]; then
    echo "FAIL frontend $path -> HTTP $code"
    exit 1
  fi
  echo "OK   frontend $path -> HTTP $code"
}

check_tile_pair() {
  local model="$1"
  local run_id="$2"
  local var="$3"
  local fh="$4"

  local canonical="$API_BASE/tiles/v2/$model/$REGION/$run_id/$var/$fh/$Z/$X/$Y.png"
  local shadow="$API_BASE/tiles-titiler/$model/$REGION/$run_id/$var/$fh/$Z/$X/$Y.png"

  local code_a code_b type_a type_b len_a len_b
  code_a="$(http_code "$canonical")"
  code_b="$(http_code "$shadow")"
  if [[ "$code_a" != "200" || "$code_b" != "200" ]]; then
    echo "FAIL tiles $model/$run_id/$var/fh$fh -> canonical=$code_a shadow=$code_b"
    exit 1
  fi

  type_a="$(header_value "$canonical" "Content-Type")"
  type_b="$(header_value "$shadow" "Content-Type")"
  len_a="$(header_value "$canonical" "Content-Length")"
  len_b="$(header_value "$shadow" "Content-Length")"

  if [[ "$type_a" != "image/png" || "$type_b" != "image/png" ]]; then
    echo "FAIL tiles $model/$run_id/$var/fh$fh -> content types $type_a / $type_b"
    exit 1
  fi

  if [[ "$len_a" != "$len_b" ]]; then
    echo "WARN tiles $model/$run_id/$var/fh$fh -> content length mismatch $len_a vs $len_b"
  else
    echo "OK   tiles $model/$run_id/$var/fh$fh -> $len_a bytes"
  fi
}

check_frontend "models-v2"

if [[ -n "${SHADOW_FRONTEND_PATH:-}" ]]; then
  check_frontend "$SHADOW_FRONTEND_PATH"
fi

for model in hrrr gfs; do
  run_id="$(latest_run "$model")"
  if [[ -z "$run_id" ]]; then
    echo "FAIL no run returned for model=$model"
    exit 1
  fi
  echo "Model $model latest run: $run_id"

  for var in tmp2m wspd10m radar_ptype; do
    fh="$(first_fh "$model" "$run_id" "$var")"
    if [[ -z "$fh" ]]; then
      echo "WARN no frames for model=$model var=$var run=$run_id (upstream may still be filling)"
      continue
    fi
    check_tile_pair "$model" "$run_id" "$var" "$fh"
  done

done

echo "Phase 5 shadow validation passed"
