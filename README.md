# TWF Models (V2)

Filesystem-backed weather model artifact pipeline + tile serving stack.

This repo contains a V2 backend that builds immutable raster artifacts (Cloud-Optimized GeoTIFFs + JSON sidecars) and serves:
- a **metadata discovery API** (`/api/v2/...`) for listing models/regions/runs/vars/frames
- a **PNG tile service** (`/tiles/...`) that renders map tiles from prebuilt COGs

A V2 frontend (Vite + React + MapLibre) consumes those endpoints to render and animate forecast frames.

> Note: V1 and V2 may coexist. New work should target **V2** (`backend_v2/` + `frontend_v2/`).

## Technology Stack

**Backend (V2)**
- Python 3.10+
- FastAPI `0.110.0`, Uvicorn `0.29.0`, Pydantic `2.6.4`
- Data processing: `xarray`, `cfgrib`, `numpy`, `scipy`
- Geo/raster: `rasterio`, `pyproj`

**Tile service (V2)**
- FastAPI + `rio-tiler` (via `backend_v2/requirements-titiler.txt`)

**Frontend (V2)**
- React `19.1.1`, TypeScript `5.9.2`, Vite `7.1.7`
- MapLibre GL `4.7.1`
- Tailwind CSS `3.4.17` + Radix UI primitives

Details: `.github/copilot/technology_stack.md`

## Project Architecture

High-level idea:
- **Schedulers / scripts** fetch upstream GRIB2 and build immutable artifacts under `TWF_DATA_V2_ROOT`
- **Metadata API** scans the filesystem and exposes discovery endpoints under `/api/v2`
- **Tile service** reads COGs and renders `256×256` PNG tiles under `/tiles/...`
- **Frontend** drives discovery and swaps tile sources to animate frames

```mermaid
flowchart LR
  U[User Browser] --> F[Frontend (React/Vite)]
  F -->|HTTP JSON| A[Metadata API (FastAPI)\n/api/v2/...]
  F -->|HTTP PNG tiles| T[Tile Service (FastAPI)\n/tiles/...]

  S1[GFS Scheduler] -->|build artifacts| FS[(TWF_DATA_V2_ROOT)]
  S2[HRRR Scheduler] -->|build artifacts| FS

  A -->|scan/list| FS
  T -->|read COG + render tile| FS
```

More detail: `.github/copilot/architecture.md`

## Getting Started

### Prerequisites

- Python (virtualenv recommended)
- Node.js + npm (for the frontend)
- Native geo deps may be required for `rasterio` / GDAL / PROJ depending on your machine

### Configure data root

The backend and tile service both read artifacts from `TWF_DATA_V2_ROOT`.

For local dev:

```bash
export TWF_DATA_V2_ROOT="$PWD/.data/v2"
mkdir -p "$TWF_DATA_V2_ROOT"
```

Optional (used by some code paths):

```bash
export TWF_MBTILES_ROOT="$PWD/.data/mbtiles"
mkdir -p "$TWF_MBTILES_ROOT"
```

### Backend setup (metadata API)

From repo root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r backend_v2/requirements.txt
```

Run:

```bash
cd backend_v2
python -m uvicorn app.main:app --reload --port 8099
```

- Health: `GET http://127.0.0.1:8099/health`
- API base: `http://127.0.0.1:8099/api/v2`

### Tile service setup

Install tile extras (adds `rio-tiler`):

```bash
python -m pip install -r backend_v2/requirements-titiler.txt
```

Run:

```bash
cd backend_v2
python -m uvicorn titiler_service.main:app --reload --port 8101
```

- Health: `GET http://127.0.0.1:8101/health`
- Tiles: `GET /tiles/{model}/{region}/{run}/{var}/{fh}/{z}/{x}/{y}.png`

Behavior notes:
- Path segments are validated against `^[a-z0-9_-]+$`.
- Missing/unavailable tiles typically return `204` with a short cache TTL.
- If `rio-tiler` is not installed, tile requests may return `503` with an explicit message.

### Frontend setup

```bash
cd frontend_v2/models-v2
npm install
npm run dev
```

The UI is designed to target local services when served from `localhost/127.0.0.1`.

## Project Structure

- `backend_v2/` — V2 Python services + pipeline
  - `app/` — metadata API (`/api/v2`)
  - `titiler_service/` — PNG tile service (`/tiles/...`)
  - `scripts/` — CLI-like tools (build/debug)
  - `tests/` — pytest suite
- `frontend_v2/models-v2/` — V2 web UI (Vite + React + MapLibre)
- `deployment/systemd/` — example systemd units for schedulers
- `docs/` — roadmap + migration notes

More detail: `.github/copilot/project_folder_structure.md`

## Key Features

- Filesystem-backed artifact contract for deterministic, cacheable tile rendering
- Discovery API for models → regions → runs → vars → frames
- Tile rendering from COGs with stable caching semantics (ETag / immutable where applicable)
- Long-running schedulers that build artifacts, update `LATEST.json`, and enforce retention

## Artifact Contract (V2)

Artifacts live under `TWF_DATA_V2_ROOT`:

- COG: `{root}/{model}/{region}/{run_id}/{var}/fhNNN.cog.tif`
- Sidecar JSON: `{root}/{model}/{region}/{run_id}/{var}/fhNNN.json`
- Latest pointer: `{root}/{model}/{region}/LATEST.json`

`run=latest` is resolved via `LATEST.json` when present/valid; otherwise by scanning run directories.

## Building Artifacts (manual)

Example: build one HRRR frame into your local data root:

```bash
python backend_v2/scripts/build_cog.py \
  --model hrrr --region pnw \
  --run latest --fh 6 --var tmp2m \
  --out-root "$TWF_DATA_V2_ROOT"
```

## Development Workflow

- Keep V1 and V2 isolated; new work should target `backend_v2/` and `frontend_v2/`.
- For backend endpoints, keep route logic thin and put logic in `backend_v2/app/services/`.
- Preserve path segment validation (`^[a-z0-9_-]+$`) for any new route params.
- Avoid new dependencies unless necessary (geo deps are fragile).

Representative workflows: `.github/copilot/workflow_analysis.md`

## Coding Standards (practical)

- Prefer type hints and small, testable functions.
- Use `pathlib.Path` and keep filesystem roots anchored at `TWF_DATA_V2_ROOT`.
- Use `fastapi.HTTPException` for client-facing errors with clear `status_code` + `detail`.
- Keep the tile service behaviors stable (204 for unavailable, 503 when optional deps missing).

## Testing

Backend tests use `pytest` and live in `backend_v2/tests/`.

```bash
python -m pip install -U pytest
pytest -q backend_v2/tests
```

Target a subset:

```bash
pytest -q backend_v2/tests -k "discovery"
```

## Contributing

- Follow the V2 patterns described in:
  - `.github/copilot/copilot-instructions.md`
  - `.github/copilot/architecture.md`
  - `.github/copilot/workflow_analysis.md`
- Add/extend pytest coverage for backend/service changes.
- Keep changes minimal and consistent with surrounding code.
