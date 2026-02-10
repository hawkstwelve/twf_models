# AGENTS.md

This repository contains **V2** backend + frontend code for a filesystem-backed weather model artifact pipeline and tile serving stack.

The closest `AGENTS.md` to the file you’re editing should be treated as the source of truth for agent instructions.

## Repo layout (V2)

- `backend_v2/`: Python FastAPI services + artifact-building pipeline
  - `backend_v2/app/`: FastAPI app code
  - `backend_v2/app/api/`: HTTP routes (V2 API under `/api/v2`)
  - `backend_v2/app/services/`: discovery, fetch/build pipeline, scheduling, tiling helpers
  - `backend_v2/titiler_service/`: PNG tile service (reads COGs)
  - `backend_v2/scripts/`: CLI-like utilities (e.g. `build_cog.py`)
  - `backend_v2/tests/`: pytest test suite
- `frontend_v2/models-v2/`: Vite + React + MapLibre UI
- `deployment/systemd/`: example unit files for long-running schedulers
- `docs/`: architecture and migration notes

V1 and V2 may coexist, but **new work should target V2** (`backend_v2/` + `frontend_v2/`).

## System prerequisites (local dev)

- Python (virtualenv recommended)
- Node.js + npm (for the frontend)
- Native geo dependencies may be required for `rasterio` / GDAL / PROJ depending on your platform and Python environment.

If Python package installation fails around GDAL/PROJ/rasterio, fix that first (the rest of the stack depends on it).

## Environment variables

Backend services and scripts primarily use these:

- `TWF_DATA_V2_ROOT`
  - Root directory for V2 artifacts (default: `/opt/twf_models/data/v2`)
  - Used by API discovery + tile service + schedulers
- `TWF_MBTILES_ROOT`
  - Root directory for MBTiles (default: `/var/lib/twf-models/mbtiles`)
  - Used by code paths that read/write MBTiles

For local dev, it’s common to point `TWF_DATA_V2_ROOT` to a workspace folder:

```bash
export TWF_DATA_V2_ROOT="$PWD/.data/v2"
mkdir -p "$TWF_DATA_V2_ROOT"
```

## Setup (backend)

From repo root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r backend_v2/requirements.txt
```

Tile service deps (adds `rio-tiler`):

```bash
python -m pip install -r backend_v2/requirements-titiler.txt
```

## Run (backend)

### Metadata API (FastAPI)

```bash
cd backend_v2
python -m uvicorn app.main:app --reload --port 8099
```

- Health: `GET http://127.0.0.1:8099/health`
- V2 API base: `http://127.0.0.1:8099/api/v2`

### Tile service (FastAPI)

```bash
cd backend_v2
python -m uvicorn titiler_service.main:app --reload --port 8101
```

- Health: `GET http://127.0.0.1:8101/health`
- Canonical tiles: `GET /tiles/{model}/{region}/{run}/{var}/{fh}/{z}/{x}/{y}.png`

Notes:
- Path segments are validated against `^[a-z0-9_-]+$`.
- When a tile is missing/unavailable, the service returns `204` with a short cache TTL.
- If `rio-tiler` isn’t installed, tile requests can return `503` with an explicit message.

## Setup + run (frontend)

```bash
cd frontend_v2/models-v2
npm install
npm run dev
```

The UI is designed to target local services when served from `localhost/127.0.0.1`.

## Building artifacts (pipeline)

A common manual workflow is building a single frame into the data root:

```bash
python backend_v2/scripts/build_cog.py \
  --model hrrr --region pnw \
  --run latest --fh 6 --var tmp2m \
  --out-root "$TWF_DATA_V2_ROOT"
```

Schedulers are long-running workers that fetch upstream GRIB2, build COGs + sidecars, update `LATEST.json`, and enforce retention. See `deployment/systemd/` for examples.

## Artifact contract (filesystem)

For each built frame, the pipeline writes under `TWF_DATA_V2_ROOT`:

- COG: `{root}/{model}/{region}/{run_id}/{var}/fhNNN.cog.tif`
- Sidecar JSON: `{root}/{model}/{region}/{run_id}/{var}/fhNNN.json`
- Latest pointer: `{root}/{model}/{region}/LATEST.json`

`run=latest` is resolved via `LATEST.json` when valid; otherwise the code scans run directories.

## Testing (backend)

Tests live in `backend_v2/tests/` and use `pytest`.

Run all backend tests:

```bash
python -m pip install -U pytest
pytest -q backend_v2/tests
```

Run a subset:

```bash
pytest -q backend_v2/tests -k "discovery"
```

## Code conventions (practical)

There is no repo-wide lint/format config checked in (no `pyproject.toml`, `ruff.toml`, or pre-commit config detected), so follow existing code style:

- Prefer **type hints** and small, testable functions.
- Use `pathlib.Path` for paths and avoid hard-coded absolute paths (rely on `TWF_DATA_V2_ROOT`).
- For HTTP routes, keep input validation consistent with existing segment validation patterns.
- Don’t add new dependencies unless necessary; keep geo/tiling dependency changes minimal (they’re the easiest to break in CI/ops).

## Troubleshooting

- Install failures around rasterio/GDAL/PROJ are environment issues, not app logic—solve those before debugging Python.
- Browser CORS: the FastAPI apps may not include CORS middleware; if local dev hits CORS errors, run services behind one origin or add CORS locally.

## Where to look first (common changes)

- Add/adjust API responses: `backend_v2/app/api/`
- Discovery logic (models/regions/runs/frames): `backend_v2/app/services/discovery_v2.py`
- Tile rendering: `backend_v2/titiler_service/main.py`
- Model scheduling/fetch/build: `backend_v2/app/services/`

## Docs

- Architecture blueprint: `docs/Project_Architecture_Blueprint.md`
