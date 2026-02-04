# V2 Implementation Plan
## Sodak Weather – Dynamic Model Maps (V2)

**Status:** Planning / In Development  
**Target Readiness:** Summer 2026  
**Intended Outcome:** Full replacement of V1 static maps  
**Audience:** Human maintainers and AI coding agents (GitHub Copilot / Codex)

---

## 1. Executive Summary

V2 replaces the current V1 static-image weather model maps with a **dynamic, tile-based mapping system**.  
The primary goals are:

- Interactive pan/zoom weather maps
- Efficient server-side rendering through precomputed tiles
- Scalable architecture for future geographic expansion and additional models
- Shareable, permalink-driven views suitable for forum discussion
- Strict separation from V1 until V2 is production-ready

V1 remains operational and untouched until V2 is complete.

---

## 2. Core Principles (Non-Negotiable)

1. **V1 and V2 are isolated**
   - V1 code paths must not be modified during V2 development.
   - V2 lives entirely under new directories and APIs.

2. **Precompute, don’t render on demand**
   - All weather overlays are rendered ahead of time.
   - No cartopy or matplotlib in the runtime API.

3. **Immutable tiles**
   - Tiles are generated once per run and never modified.
   - Cache-friendly and safe for sharing.

4. **Permalinks are first-class**
   - Every map state must be reproducible via URL.

---

## 3. Backend Architecture

### 3.1 Tile Format (Decision)
**Primary format:** Paletted PNG

**Rationale:**
- Excellent compression for meteorological rasters
- Predictable color reproduction
- Broad browser support
- Smaller or comparable size to WebP for indexed weather data

WebP may be evaluated later, but PNG is the baseline.

---

### 3.2 Tile Storage (Decision)
**Storage format:** MBTiles (SQLite)

**Rationale:**
- Single-file storage per model/run/variable
- Easy retention and deletion
- Avoids millions of small files
- Well-supported by GDAL

Future object storage or CDN integration is possible without changing tile semantics.

---

### 3.3 Projection & Scheme
- **Projection:** EPSG:3857 (Web Mercator)
- **Tile scheme:** XYZ (slippy map standard)
- MBTiles TMS row inversion must be handled correctly in the API

---

### 3.4 Zoom Levels (Initial)
**Overlay zoom cap:** z = 5–11

**Rationale:**
- Appropriate for regional meteorological analysis
- Avoids exponential tile growth
- Can be expanded later if justified by UX

---

### 3.5 Geographic Extent
- **Initial:** Pacific Northwest (PNW)
- **Planned expansion:** CONUS subsets → Full CONUS

Extent expansion must not require frontend changes.

---

## 4. Data & Models

### 4.1 Initial Model
- **HRRR only** for MVP

### 4.2 Expansion Roadmap
- GFS
- ECMWF
- NAM
- Additional models as storage and compute allow

### 4.3 Run Retention
- **Initial:** Latest run only
- Future: configurable retention (2–4 runs)

---

## 5. Tile Generation Pipeline (Offline)

**Runs outside the API. Never on-demand.**

1. Fetch GRIB2 using Herbie
2. Extract scalar field(s)
3. Write GeoTIFF in native projection
4. Reproject to EPSG:3857
5. Generate tiles for z=5–11
6. Write tiles to MBTiles
7. Enforce retention policy

Tile generation failures must never affect API uptime.

---

## 6. API Design (V2)

### 6.1 Base Paths
- `/api/v2/*` — metadata
- `/tiles/v2/*` — raster tiles

### 6.2 Required Endpoints
- `GET /api/v2/models`
- `GET /api/v2/{model}/runs`
- `GET /api/v2/{model}/{run}/vars`
- `GET /api/v2/{model}/{run}/{var}/frames`
- `GET /tiles/v2/{model}/{run}/{var}/{fh}/{z}/{x}/{y}.png`

### 6.3 API Stability (Clarified)
**Initial stance:** Internal/Beta

Meaning:
- Schema may evolve during V2 development
- Changes must remain backward-compatible once V2 replaces V1
- Versioning (`/api/v2`) is mandatory to protect clients

---

## 7. Frontend Architecture

### 7.1 Framework
- **Leaflet**

### 7.2 Feature Priority (High → Low)
1. Variable selector
2. Legend
3. Time slider + play
4. Click-to-read value
5. Compare mode
6. Opacity control

### 7.3 Design Rules
- Frontend never computes meteorological data
- Frontend only consumes tiles + metadata
- No assumptions about model count or extent

---

## 8. Sharing & Forum Integration

### 8.1 Permalinks (Required at Launch)
Permalinks must encode:
- model
- run
- variable
- forecast hour
- zoom
- center or bounds

Example:
```
/models?m=hrrr&run=20260601_00z&v=tmp2m&fh=18&z=9&lat=47.6&lon=-122.3
```

### 8.2 Static Snapshots
- **Phase 2 feature**
- Implement after core interactivity is stable
- Used for forum embeds and previews

### 8.3 Forum Support
- Invision Community v4 and v5
- Link previews via OpenGraph
- No iframe dependence at launch

---

## 9. Deployment Strategy

### 9.1 Hosting Model (Decision)
- **Same server**
- **Separate systemd services** (recommended)
  - `twf-models-api` (V1)
  - `twf-models-api-v2` (V2)
- Shared server simplifies ops and cost
- Containers optional later, not required now

### 9.2 Safety Guarantees
- Production deploys pinned to git tags
- V2 can be stopped or removed without affecting V1
- Rollback is instant

---

## 10. Migration Plan (V1 → V2)

1. Develop V2 in parallel
2. Validate HRRR + PNW end-to-end
3. Add models and extent
4. Enable permalinks
5. User testing
6. Flip `/models` to V2
7. Retire V1 after validation period

---

## 11. Explicit DO-NOT List (For AI Agents)

- DO NOT modify V1 directories
- DO NOT introduce runtime rendering
- DO NOT generate tiles on request
- DO NOT assume CONUS-scale tiling initially
- DO NOT store runtime data inside the git repo
- DO NOT bypass API versioning

---

## 12. AI Agent Instructions (Authoritative)

When assisting with this repository:
- Default all new work to V2 paths
- Follow this document as source of truth
- Ask before changing architecture decisions
- Prefer clarity and isolation over reuse

---

**This document is authoritative for V2 development.**


---

## 13. Milestones & Progress Checklist

This section is used to track V2 development progress and serves as a concrete checklist for both humans and AI agents.
Items should only be marked complete when validated locally **and** reviewed against this plan.

### Milestone 0 — Safety & Guardrails (COMPLETED)
- [x] V1 pinned to tagged release in production
- [x] Branch protection enabled on `main`
- [x] `maintenance/v1` branch created
- [x] `feature/v2-tiles` branch created
- [x] AGENTS.md updated with V1/V2 guardrails
- [x] V2 implementation plan committed

---

### Milestone 1 — V2 Backend Skeleton
- [x] `backend_v2/` directory scaffolded
- [x] FastAPI app boots locally
- [x] `/api/v2/models` endpoint responds
- [x] Versioned routing (`/api/v2`) enforced
- [x] No imports or dependencies from V1

**Exit criteria:** Backend runs locally without touching V1.

---

### Milestone 2 — MBTiles Tile Serving
- [x] MBTiles reader implemented
- [x] XYZ tile endpoint implemented
- [x] Correct TMS → XYZ row inversion verified
- [x] PNG tiles served with correct headers
- [x] Fake/test MBTiles used for validation

**Exit criteria:** Tiles load correctly in a browser or Leaflet test map.

---

### Milestone 3 — Tile Generation Pipeline (HRRR)
- [x] Herbie-based HRRR fetch working
- [x] GRIB → GeoTIFF conversion implemented
- [x] Reprojection to EPSG:3857 validated
- [x] z=5–11 tile generation working
- [x] MBTiles written correctly
- [x] Latest-run-only retention enforced

**Exit criteria:** A full HRRR run produces usable tiles end-to-end.

---

### Milestone 4 — V2 Frontend (MVP)
- [x] Leaflet map loads
- [x] Tile overlay renders
- [x] Variable selector wired to API
- [x] Legend displays correctly
- [x] Time slider + play works
- [x] Forecast hour switching updates tiles

**Exit criteria:** Interactive HRRR map usable for PNW.

---

### Milestone 5 — Interactivity Enhancements
- [ ] Click-to-read value implemented
- [ ] Compare mode (side-by-side or swipe)
- [ ] Opacity control
- [ ] UI performance verified under animation

**Exit criteria:** UX parity or better than V1 for analysis.

---

### Milestone 6 — Permalinks & State Management
- [ ] Map state fully encoded in URL
- [ ] Permalinks restore exact view
- [ ] Default view logic defined
- [ ] Backward compatibility for shared links ensured

**Exit criteria:** Users can reliably share links.

---

### Milestone 7 — Production Hardening
- [ ] Separate systemd service for V2 API
- [ ] Configurable data paths (no runtime data in repo)
- [ ] Logging and error handling reviewed
- [ ] Resource usage measured (CPU, disk, IO)
- [ ] Retention policies verified

**Exit criteria:** V2 is safe to run alongside V1 in prod.

---

### Milestone 8 — Model & Region Expansion
- [ ] Add GFS
- [ ] Add ECMWF
- [ ] Expand geographic extent beyond PNW
- [ ] Validate storage growth assumptions

**Exit criteria:** Architecture scales without redesign.

---

### Milestone 9 — Sharing Enhancements (Phase 2)
- [ ] Static snapshot rendering
- [ ] OpenGraph metadata
- [ ] Forum-friendly share UX
- [ ] Invision v4/v5 verification

**Exit criteria:** Maps integrate cleanly into forum discussions.

---

### Milestone 10 — Cutover & V1 Retirement
- [ ] V2 enabled at `/models`
- [ ] V1 retained as fallback during validation
- [ ] User feedback incorporated
- [ ] V1 officially retired

**Exit criteria:** V2 is the primary production system.

---

**Rule:** Never skip milestones. If a later milestone exposes flaws in an earlier one, return and fix it before proceeding.
