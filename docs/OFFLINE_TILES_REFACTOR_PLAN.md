# Offline Tiles Refactor Plan (V2)

## Feasibility Verdict

Feasible with a moderate-to-large refactor. The current codebase already has key building blocks for this migration:

- Strong model/variable plugin layer (`backend_v2/app/models/`)
- Stable normalization/build entrypoint (`backend_v2/scripts/build_cog.py`)
- Discovery API surface that can be reshaped (`backend_v2/app/api/v2.py`, `backend_v2/app/services/discovery_v2.py`)

Primary gaps:

- Runtime PNG rendering remains in the request path (`backend_v2/titiler_service/main.py`)
- Current run promotion is not contractually atomic for published artifacts
- Frontend currently handles tile-readiness/race states (`frontend_v2/models-v2/src/App.tsx`, `frontend_v2/models-v2/src/components/map-canvas.tsx`)

This plan targets: offline archive tiles (`z<=7`), immutable published artifacts, atomic manifest pointer publish, static serving, and manifest-driven frontend rendering.

## Current vs Target Delta

- `Current`: GRIB -> COG -> runtime tile render -> readiness-aware frontend
- `Target`: GRIB/normalized raster -> offline PMTiles -> staged validation -> atomic publish pointer -> static serving -> manifest-driven frontend

Repository impact:

- Remove runtime raster render responsibilities from request path
- Introduce explicit staging/published publish contract
- Move discovery to published manifests only
- Simplify frontend animation logic around frame manifests

## Non-Negotiable Requirements

- Overlay zoom cap is `z<=7`
- Published overlays are archive-based, static-served, and immutable
- `/published` content is never modified in-place
- Only atomic manifest pointer updates constitute publish
- Frontend discovers availability only through manifests (never by directory scans or readiness guessing)
- Retention deletes full run directories only

## Archive Strategy (Default + Variant B)

### PMTiles Immutability (Mandatory)

PMTiles is read-only once built. It cannot be appended/updated in-place.  
Therefore, progressive publish MUST NOT rely on mutating an already published PMTiles archive.

### Default Path (Recommended): Per-Frame PMTiles

Use per-frame PMTiles archives for raster overlays:

- URL contract: `/tiles/{model}/{run}/{var}/{frame_id}.pmtiles`
- `frame_id` maps to one forecast time step (for example `000`, `003`, `006`, ...)
- Run/variable `manifest.json` enumerates currently available frames and expected total frames

Benefits:

- Progressive availability is trivial: publish additional frame archives + manifest updates
- No PMTiles rewriting for already published frames
- Fast time-to-first-frame under low zoom and low retention constraints

### Variant B (Optional): MBTiles-in-Staging, PMTiles-on-Publish

- Build incrementally into MBTiles in `/staging` only
- Convert to PMTiles at publish time
- Publish PMTiles artifacts only
- MBTiles is internal build artifact and is never exposed to clients

Use this only if operationally needed for build tooling; default remains per-frame PMTiles.

## Atomic Publish Contract

1. All build outputs are produced under `/staging`.
2. `/published` is immutable. After publish, files under a published run path are never modified.
3. Publish is only pointer movement:
- update/swap `latest.json` symlink, or
- write `latest.json.tmp` then atomic rename to `latest.json`
4. Frontend and discovery APIs MUST read only published manifests. They must never scan filesystem paths or infer readiness from missing tiles.
5. No background task may modify a published run’s manifest.json directly. All manifest updates must occur in staging and be promoted via atomic pointer switch.

## Schemas & Versioning

Every `meta.json` and `manifest.json` MUST include `contract_version` as an integer.
Canonical value for Phase 1 is `1`.

### `meta.json` required fields

- `contract_version`
- `model`
- `run`
- `variable_id`
- `frame_id`
- `fhr`
- `valid_time`
- `units`
- `nodata` semantics (value and/or rule)
- `bounds` (WGS84)
- `zoom_min`
- `zoom_max`
- `colormap_id`
- `colormap_version` or `palette_hash`
- `url` (published PMTiles URL for this frame)

### `manifest.json` required fields

- `contract_version`
- `model`
- `run`
- `variable`
- `expected_frames` (full run target)
- `available_frames` (currently published count)
- `frames[]`, each containing:
  - `frame_id`
  - `fhr`
  - `valid_time`
  - `url`
- `last_updated`

### Compatibility and cache-busting rules

- Contract changes:
  - backward-compatible additions: same `contract_version`, additive fields only
  - breaking changes: bump `contract_version` and provide reader migration path
- Colormap/palette changes:
  - update `colormap_version` or `palette_hash`
  - ensure cache busting by new run publish or URL/version change so immutable caches cannot serve stale styling

## Storage Layout & Retention

Published structure (example):

```text
/data/
  /staging/
    gfs/20260211_12z/prate/...
  /published/
    gfs/
      20260211_12z/
        prate/
          frames/
            000.pmtiles
            003.pmtiles
            006.pmtiles
          manifest.json
  /manifests/
    gfs/
      latest.json
```

Retention policy:

- Delete entire run directories (for example `/data/published/GFS/20260211_12z/`)
- Never delete or rewrite individual frame archives in-place under a published run

## Frontend Integration (MapLibre + PMTiles)

- Integrate PMTiles protocol with MapLibre via `addProtocol`.
- Overlay rendering flow:
1. Load latest manifest(s)
2. Select model/run/variable
3. Resolve current animation frame via `frame_id` entry in manifest
4. Point raster source at that frame’s PMTiles URL
5. Animate by swapping to the next frame URL (or source recreation with minimal churn)

Overlay non-goal after cutover:

- No dynamic XYZ overlay endpoints in normal operation
- Legacy XYZ paths are transitional only and removed after decommission

## Progressive Publish Behavior

Progressive publish is manifest-driven, not tile-endpoint probing.

- Minimum animation-ready threshold (default): publish when:
  - run/variable manifest exists
  - metadata is valid
  - first `N=6` frames exist and pass validation
- Continue publishing additional frames by updating staged manifest then atomically updating published/latest pointers
- UI uses:
  - `expected_frames`
  - `available_frames`
to render explicit `building...` status without guessing
- Once a frame is listed in manifest.json, that frame’s PMTiles file is immutable and guaranteed complete.

## Ops Guardrails

- Disk safety checks before publish:
  - fail publish if free space is below configured threshold
- Rollback:
  - repoint `latest` manifest pointer to previous known-good run
- Validation checklist before pointer switch:
  - sample read z=0 and z=7 tiles for representative frames
  - verify transparency/nodata semantics
  - verify bounds and zoom metadata consistency

## Phase 0 - Contract, Cleanup, and Migration Guardrails

### Objective
Lock contracts and remove ambiguity before implementation.

### Deliverables

1. Contract lock
- Finalize `Atomic Publish Contract`, `Schemas & Versioning`, and default archive strategy (per-frame PMTiles)
- Document Variant B as optional implementation path only

2. Cleanup pass on stale/inconsistent code/tests/docs
- Align stale tests with implemented behavior before migration:
  - `backend_v2/tests/test_discovery_v2.py`
  - `backend_v2/tests/test_run_resolution.py`
- Mark prior runtime-rendering migration docs as superseded
- Add deprecation notices for runtime tile routes

3. Cutover controls and observability
- Define flags:
  - `OFFLINE_TILES_ENABLED`
  - `STAGING_ROOT`
  - `PUBLISH_ROOT`
- Define metrics:
  - build duration
  - validation pass/fail
  - publish pointer switch latency

### Checkpoints

- Checkpoint P0.1: contracts approved (no unresolved schema or publish semantics)
- Checkpoint P0.2: baseline tests green after cleanup
- Checkpoint P0.3: rollback and ops runbook draft approved

### Milestone

- **M0: Contract Locked + Codebase Sanitized**

## Phase 1 - Backend Refactor (Offline Builder + Atomic Publisher + Manifest API)

### Objective
Implement offline per-frame PMTiles build/publish pipeline and published-only discovery.

### Deliverables

1. Offline builder path
- Produce frame artifacts in staging for `z<=7`:
  - `/staging/{model}/{run}/{var}/frames/{frame_id}.pmtiles`
  - `/staging/{model}/{run}/{var}/meta/{frame_id}.json` (or embedded per-frame metadata file strategy)
  - `/staging/{model}/{run}/{var}/manifest.json`
- Keep variable normalization/plugin logic in existing model layer
- Validate each staged frame prior to availability

2. Publisher implementation
- Enforce immutable `/published` contract
- Promote staged artifacts to published run path without modifying already published files
- Publish visibility only through atomic pointer update in `/data/manifests/{model}/latest.json` (canonical lowercase model path)
- Optional legacy alias `{MODEL}_latest.json` may exist only for compatibility callers; it is not canonical

3. Progressive publish mechanics
- Initial publish gate at `N=6` validated frames (default)
- Manifest accurately tracks `expected_frames` and `available_frames`
- Additional frames become visible only via manifest updates and pointer switch contract

4. Discovery/API migration
- Discovery returns published-only manifests and frame URLs:
  - `GET /api/models`
  - `GET /api/runs?model=...`
  - `GET /api/vars?model=...&run=...`
  - `GET /api/run/{model}/{run}/manifest.json`
- Remove readiness-by-tile assumptions from API responses

5. Static serving integration
- Serve published PMTiles and manifests statically:
  - `/tiles/{model}/{run}/{var}/{frame_id}.pmtiles`
  - `/manifests/{model}/latest.json` (or equivalent model pointer path)

6. Ensure parallelism on production server
- Builder parallelism must be bounded (e.g., max_workers configurable, default 4–6) to prevent RAM exhaustion and I/O thrash.

### Checkpoints

- Checkpoint P1.1: staged frame PMTiles build is stable for HRRR + GFS reference vars
- Checkpoint P1.2: atomic pointer switch is validated and rollback tested
- Checkpoint P1.3: discovery exposes only published manifests; no staging leakage
- Checkpoint P1.4: progressive publish UX data (`expected_frames`/`available_frames`) verified

### Milestone

- **M1: Backend Serving Path Fully Offline + Atomic**

## Phase 2 - Frontend Cutover + Runtime Decommission + Final Cleanup

### Objective
Switch frontend to manifest-driven per-frame PMTiles and remove runtime overlay rendering stack.
Cut over the single existing frontend to manifest-driven PMTiles. Keep a temporary fallback switch (query param) to force legacy runtime overlays during soak.

### Deliverables

1. Frontend integration
- Implement MapLibre + PMTiles protocol flow from manifests, including `maplibregl.addProtocol` via PMTiles `Protocol`.
- Default renderer is offline PMTiles.
- Add runtime override via query param:
  - `?legacy=1` forces legacy runtime overlay path
  - optional: persist the choice in `localStorage` until cleared
- Delete readiness polling; drive UI state solely from manifests (`expected_frames`/`available_frames` + `frames` list).
- UI lists ONLY published models/runs/vars returned by discovery; do not show placeholders for unpublished models.
- Handle partial availability: animate only over frames present in manifest; show progress (`available_frames`/`expected_frames`) and explicit `still publishing` state.
- Show explicit build-progress UX from `available_frames` vs `expected_frames`
- No separate deploy environment, account allowlist, or IP allowlist is required.

2. Runtime decommission
- Sub-phase A - Soak fallback:
  - Runtime stack remains functional only as fallback when `?legacy=1` is used (or when frontend flag forces it).
- Sub-phase B - Soft disable:
  - After soak, runtime endpoints return `410` (`Gone`) in prod.
  - Remove/disable fallback path usage in frontend.
- Sub-phase C - Hard removal:
  - After longer soak, delete runtime rendering code/routes/config.
- Remove frontend dependence on legacy XYZ/PNG overlay endpoints.
- Do not remove runtime stack until offline PMTiles path is verified end-to-end through nginx and on the public domain.

3. Optional query API
- Add point/hover API only if needed:
  - `GET /api/value?...`
- If implemented, read from source-of-truth grid/query artifacts (not PMTiles, not rendered tiles) to avoid reintroducing runtime rendering complexity.

4. Edge/Proxy correctness
- Verify nginx/public domain behavior for:
  - `/manifests/{model}/latest.json`: `Cache-Control` around `max-age=5` and revalidation on `GET`.
  - `/tiles/{model}/{run}/{var}/{frame_id}.pmtiles`: `Cache-Control` one year immutable and correct `Content-Length` on `GET`.
  - PMTiles range access: `Range` `GET` returns `206 Partial Content` through nginx/public domain.
  - CORS headers for manifests and PMTiles when frontend origin differs.

5. Final hardening
- Remove dead feature flags after soak period
- Update docs/tests/runbooks to reflect final operating model

### Checkpoints

- Checkpoint P2.0: public-domain verification passes for `/manifests/{model}/latest.json` and `/tiles/...pmtiles` through nginx; PMTiles range requests return `206`; caching headers are correct on `GET`.
- Checkpoint P2.1: default path uses manifests -> PMTiles; no readiness polling; no legacy overlay requests during normal operation.
- Checkpoint P2.1a: fallback works when `?legacy=1` is used (only during soak).
- Checkpoint P2.2: after soak, runtime endpoints return `410` in prod and fallback is removed/disabled.
- Checkpoint P2.3: end-to-end tests pass for published-only manifest + PMTiles.

### Cutover Sequence

1. Deploy PMTiles frontend as default.
2. Validate public-domain behavior.
3. Use `?legacy=1` only if needed during soak.
4. After short soak, remove fallback usage and return `410` from runtime endpoints in prod.
5. After longer soak, delete runtime stack.

### Verification Commands

```bash
# latest.json GET headers (check Cache-Control on GET)
curl -sD - -o /dev/null "https://<public-domain>/manifests/hrrr/latest.json"

# PMTiles GET + Range through nginx/public domain (expect HTTP/1.1 206)
curl -sv -H "Range: bytes=0-1023" "https://<public-domain>/tiles/hrrr/<run>/tmp2m/000.pmtiles" -o /dev/null
```

Prefer `GET` for header validation; `HEAD` behavior may differ by proxy configuration.

### Milestone

- **M2: Offline Tiles Architecture in Production**

## Acceptance Criteria (Program-Level)

- No runtime raster-to-PNG rendering in production request path
- No in-place mutation of published PMTiles artifacts
- Publish visibility controlled only by atomic manifest pointer updates
- Frontend discovery/render flow is manifest-driven only
- New variable onboarding requires plugin + colormap metadata + build/publish
- Retention remains bounded by deleting entire run directories

## Risk Register (Short)

- Build tooling availability for PMTiles generation at scale
- Publish latency if validation windows are oversized
- Schema/version drift if `contract_version` governance is not enforced
- Transitional complexity during legacy endpoint decommission

## Suggested Execution Order

1. Complete Phase 0 (contract lock and cleanup) before backend implementation.
2. Implement Phase 1 with per-frame PMTiles default and atomic publish pointer contract.
3. Execute Phase 2 frontend cutover, then decommission legacy runtime overlay paths.
