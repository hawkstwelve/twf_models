# TWF Models (V2)

V2 weather model pipeline and frontend.

## Current Architecture

- Builder: `backend_v2/scripts/build_cog.py`
- Metadata API: `backend_v2/app` (FastAPI)
- Tile service: `backend_v2/titiler_service`
- Frontend source: `frontend_v2/models-v2-maplibre`
- Frontend deployed artifact path: `frontend_v2/models-v2`

V1 backend/frontend code and legacy tile-serving paths were retired in Phase 7.

## Production Services

- `twf-models-api-v2.service` (metadata API on port 8099)
- `twf-hrrr-v2-scheduler.service`
- `twf-gfs-v2-scheduler.service`
- TiTiler service (separate FastAPI process/unit in production)

## Key URLs

- Frontend: `https://sodakweather.com/models-v2/`
- API root: `https://api.sodakweather.com/api/v2/`
- Canonical tiles: `https://api.sodakweather.com/tiles/v2/...`
- TiTiler shadow route: `https://api.sodakweather.com/tiles-titiler/...`

## Repo Layout

```text
twf_models/
├── backend_v2/
│   ├── app/
│   ├── scripts/
│   │   └── build_cog.py
│   ├── tests/
│   └── titiler_service/
├── frontend_v2/
│   ├── models-v2/              # built deploy artifacts
│   └── models-v2-maplibre/     # React/Vite source
├── deployment/
│   └── systemd/
├── scripts/
│   └── v2/
└── V2_RENDERING_MIGRATION_PLAN.md
```

## Local Development

### Backend tests

```bash
cd /Users/brianaustin/twf_models
/Users/brianaustin/twf_models/venv/bin/python -m pytest -q backend_v2/tests
```

### Frontend build

```bash
cd /Users/brianaustin/twf_models/frontend_v2/models-v2-maplibre
npm ci
npm run build
```

### Sync build artifacts into canonical frontend path

```bash
cd /Users/brianaustin/twf_models
bash scripts/v2/phase5_cutover_sync_frontend.sh
```

## Validation

Run the V2 cutover/health check script:

```bash
cd /Users/brianaustin/twf_models
bash scripts/v2/phase5_shadow_validate.sh
```

Optional shadow frontend check:

```bash
SHADOW_FRONTEND_PATH=models-v2-maplibre bash scripts/v2/phase5_shadow_validate.sh
```

## Notes

- COGs are immutable artifacts under `/opt/twf_models/data/v2` in production.
- Builder, API, and TiTiler should run with pinned compatible GDAL/PROJ majors.
- Discovery endpoints drive frontend frame/layer selection.
