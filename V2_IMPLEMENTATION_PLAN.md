# V2 Implementation Plan
## Sodak Weather – Dynamic Model Maps (V2)

**Status:** In Development (architecture updated Feb 2026)  
**Intended Outcome:** Full replacement of V1 static maps  
**Audience:** Human maintainers and AI coding agents (GitHub Copilot / Codex)

---

## 1. Executive Summary

V2 replaces V1 static-image model maps with a **dynamic, interactive Leaflet map** backed by a **raster tile service**.

**Key architectural update (performance + scalability):** V2 does **not** precompute PNG tile pyramids into MBTiles as the primary artifact. Instead, V2 precomputes **Cloud Optimized GeoTIFF (COG) frames with internal overviews** and serves XYZ PNG tiles **on-demand** via fast raster window reads + caching.

**Key visual consistency update (colorbars):** V2 stores **palette-index bytes** (discrete bins) or **fixed-range bytes** (continuous) in Band 1, with an **explicit alpha** in Band 2, and applies the V1 colorbars as a LUT at tile-render time. This guarantees legends match tiles across regions/runs/models.

References:
- [OGC, OGC Cloud Optimized GeoTIFF Standard, https://www.ogc.org/standards/ogc-cloud-optimized-geotiff/]
- [GDAL, gdaladdo — GDAL documentation, https://gdal.org/en/stable/programs/gdaladdo.html]
- [GDAL, COG driver docs, https://gdal.org/en/stable/drivers/raster/cog.html]
- [rio-tiler, rio-tiler docs, https://cogeotiff.github.io/rio-tiler/]
- [nginx.org, ngx_http_proxy_module (proxy_cache), https://nginx.org/en/docs/http/ngx_http_proxy_module.html]

---

## 2. Core Principles (Non-Negotiable)

1. **V1 and V2 are isolated**
   - V1 code paths must not be modified during V2 development.
   - V2 lives entirely under new directories and APIs.
   - V2 may copy constants (e.g., palette definitions) but must not import V1 modules.

2. **Precompute rasters; do not render meteorology at runtime**
   - Offline: decode GRIB, project, clip, and write optimized raster artifacts (COGs).
   - Runtime: only read raster windows and encode tiles. No cartopy/matplotlib, no meteorology computation.

3. **Immutable frame artifacts**
   - A frame is identified by `{model}/{region}/{run}/{var}/{fh}`.
   - Once written, it is immutable; new runs write new directories/files.
   - This enables aggressive caching and safe permalinks.

4. **Palette consistency**
   - Do not use percentile-based scaling for variables with defined levels/colors.
   - Store “palette index” bytes (or fixed-range bytes) and apply LUT at tile time.

---

## 3. Backend Architecture

### 3.1 Primary Artifact Format (Decision)
**Primary artifact:** Cloud Optimized GeoTIFF (COG) per frame (forecast hour).

**Rationale:**
- Efficient window reads via internal tiling and overviews.
- Avoids generating/storing millions of PNG files or slow per-tile Python loops.
- Works well with proxy/browser caching.

### 3.2 Raster Encoding (Decision)
Each COG frame stores exactly **two bands**:

- **Band 1:** `Byte` data encoding
  - **Discrete variables** (levels/colors): `byte = palette bin index` (0..N-1)
  - **Continuous variables** (256-color ramps): `byte = 0..255` from a **fixed configured physical range**
- **Band 2:** `Byte` alpha (0 transparent, 255 opaque)

**Tile rendering:** `RGBA = LUT[band1]` then `RGBA.a = band2`.

### 3.3 Projection & Scheme
- **Projection:** EPSG:3857 (Web Mercator)
- **Tile scheme:** XYZ (slippy map standard)

### 3.4 Zoom Levels (Initial)
**Overlay zoom cap:** z = 5–11  
May be expanded later after measuring tile-serving latency under animation.

### 3.5 Geographic Extent
- **Initial region key:** `pnw` (WA, OR, NW ID, W MT)
- **Planned expansion:** multiple regions → CONUS → Full CONUS

### 3.6 Storage Layout (Decision)

**Root:** `/opt/twf_models/data/v2`

```
/opt/twf_models/data/v2/{model}/{region}/{run}/{var}/fh{FH:03d}.cog.tif
/opt/twf_models/data/v2/{model}/{region}/{run}/{var}/fh{FH:03d}.json
```

Example:
```
/opt/twf_models/data/v2/hrrr/pnw/20260204_15z/tmp2m/fh000.cog.tif
/opt/twf_models/data/v2/hrrr/pnw/20260204_15z/tmp2m/fh000.json
```

The sidecar JSON stores scale/palette metadata used to render tiles consistently.

---

## 4. Variables & Colorbars (Updated)

### 4.1 Palette Source
V1 palettes live in `v1/mapgenerator.py`. V2 will **copy** the palette constants into a V2 module:
- `backend_v2/app/services/colormaps_v2.py`

V2 must not import V1.

### 4.2 Discrete vs Continuous Handling
**Discrete examples (levels + colors):**
- precip / snowfall / total precip
- radar reflectivity

Encoding:
- `bin = digitize(values, levels) - 1`
- clamp to `[0..N-1]`
- alpha = 255 where finite and value >= min level; else 0

**Continuous examples (256-step gradient):**
- tmp2m
- other smooth scalar fields

Encoding:
- choose fixed range per variable (config)
- `byte = clip((value - min)/(max-min) * 255, 0..255)`
- alpha = 255 where finite; else 0

### 4.3 Precip/Radar Type Decision (Selected)
**Decision:** separate variables per subtype (Option #1).

Examples:
- `radar_rain`, `radar_snow`, `radar_sleet`, `radar_frzr`
- `ptype_rainrate`, `ptype_snowrate`, etc.

This keeps:
- URLs stable and cache-friendly
- discovery clean
- no subtype query params

---

## 5. Data & Models

### 5.1 Initial Model (MVP)
- **HRRR**

### 5.2 MVP Scope (Target)
- Region: `pnw`
- Forecast hours:
  - most cycles: 0–18
  - 00z/06z/12z/18z: 0–48
- Variables: 2–3 initially (examples):
  - `tmp2m`
  - `wind10m` or `gust`
  - optional: one discrete palette var (e.g. `qpf` or a radar-like field if available)

### 5.3 Expansion Roadmap
- Regions: additional CONUS subsets → full CONUS
- Models: GFS, NAM, ECMWF (subject to data access/licensing and pipeline fit)

### 5.4 Retention
- **Initial:** latest run only per `{model}/{region}`
- Future: configurable retention (2–4 runs)

---

## 6. Frame Generation Pipeline (Offline)

**Runs outside the API. Never on-demand meteorology.**

1. Fetch GRIB2 (Herbie for HRRR)
2. Select field by V2 variable key (e.g., `tmp2m`, `radar_rain`)
3. Encode to:
   - Band 1 `byte` (palette index or fixed-range)
   - Band 2 `alpha`
4. Write intermediate GeoTIFF/VRT in native projection
5. Reproject + clip to EPSG:3857 using `gdalwarp` (with `-te` for region bbox)
6. Write final **COG** using `gdal_translate -of COG`
7. Build overviews using `gdaladdo`
8. Write sidecar JSON (palette/range/units metadata)
9. Enforce retention (delete old run dirs)

GDAL references:
- [GDAL, gdalwarp, https://gdal.org/en/stable/programs/gdalwarp.html]
- [GDAL, gdal_translate, https://gdal.org/en/stable/programs/gdal_translate.html]
- [GDAL, gdaladdo, https://gdal.org/en/stable/programs/gdaladdo.html]

---

## 7. API Design (V2)

### 7.1 Base Paths
- `/api/v2/*` — metadata / discovery
- `/tiles/v2/*` — raster tiles (PNG)

### 7.2 Required Endpoints (Updated)
- `GET /api/v2/models`
- `GET /api/v2/{model}/regions`
- `GET /api/v2/{model}/{region}/runs`
- `GET /api/v2/{model}/{region}/{run}/vars`
- `GET /api/v2/{model}/{region}/{run}/{var}/frames`
- `GET /tiles/v2/{model}/{region}/{run}/{var}/{fh}/{z}/{x}/{y}.png`

### 7.3 Discovery Implementation (Decision)
Discovery is filesystem-based under `/opt/twf_models/data/v2`:
- models = directory names
- regions = directory names
- runs = directory names (e.g., `YYYYMMDD_HHz`)
- vars = directory names
- frames = `fh*.cog.tif`

No database required for MVP.

---

## 8. Caching & Performance (Production MVP)

### 8.1 HTTP Caching
For immutable tiles (a specific run/var/fh/z/x/y):
- `Cache-Control: public, max-age=31536000, immutable`
- `ETag`: based on `(cog_size, cog_mtime, z, x, y)` (and/or a short hash)

### 8.2 Reverse Proxy Cache
Put Nginx in front of the V2 tile endpoint with `proxy_cache` for hot tiles.

Reference:
- [nginx.org, ngx_http_proxy_module, https://nginx.org/en/docs/http/ngx_http_proxy_module.html]

---

## 9. Frontend Architecture

### 9.1 Framework
- Leaflet

### 9.2 Updated Requirements
- Frontend must not hardcode models/regions/vars.
- Frontend must query discovery endpoints and build selectors dynamically.
- Frontend keeps using existing legend assets for chosen variable.

### 9.3 Tile URL Template
```
/tiles/v2/{model}/{region}/{run}/{var}/{fh}/{z}/{x}/{y}.png
```

---

## 10. Milestones & Progress Checklist

### Milestone 0 — Safety & Guardrails (COMPLETED)
- [x] V1 pinned to tagged release in production
- [x] Branch strategy established
- [x] AGENTS.md guardrails documented

### Milestone 1 — V2 Backend Skeleton (COMPLETED)
- [x] FastAPI app boots (V2)
- [x] Versioned routing (`/api/v2`, `/tiles/v2`)
- [x] No V1 dependencies

### Milestone 2 — Colorbar/LUT System (NEXT)
- [x] Create `app/services/colormaps_v2.py`
- [x] Copy palettes from V1 (no imports)
- [x] Implement LUT builders:
  - [x] discrete palettes (levels + colors)
  - [x] continuous 256-step palettes
- [x] Implement encoder: values → (byte, alpha) + sidecar metadata

**Exit criteria:** given an array, can produce byte/alpha and a LUT that renders correctly.

### Milestone 3 — HRRR COG Frame Writer (IN PROGRESS)
- [x] Replace MBTiles output with COG output + overviews
- [x] Output to `/opt/twf_models/data/v2/.../fhNNN.cog.tif`
- [x] Write `fhNNN.json`
- [x] Standardize run dir naming `YYYYMMDD_HHz`
- [x] Retention: keep latest run only

**Exit criteria:** HRRR `tmp2m` fh000 generates a COG + JSON under the new root.

### Milestone 4 — COG Tile Serving (NEXT)
- [x] Implement `/tiles/v2/{model}/{region}/{run}/{var}/{fh}/{z}/{x}/{y}.png`
- [x] Read a 256×256 window from COG (overview-aware)
- [x] Apply LUT + alpha → PNG
- [x] Add caching headers (`Cache-Control`, `ETag`)
- [x] Validate overlay renders in Leaflet at z=5–11

**Exit criteria:** Leaflet displays `tmp2m` overlay from COG tiles smoothly.

### Milestone 5 — Discovery APIs (NEXT)
- [ ] Implement filesystem discovery endpoints
- [ ] Frontend consumes discovery endpoints (no hardcoding)
- [ ] Default selection: latest run, var=tmp2m, fh=0

### Milestone 6 — HRRR Orchestration + Schedule (MVP)
- [x] Create `generate_hrrr_frames.py` to loop vars × fh
- [ ] Schedule on server (cron or systemd timer)
- [ ] Logging + failure isolation per frame

### Milestone 7 — Production Hardening
- [ ] Nginx proxy_cache for tiles
- [ ] Env var config for data root
- [ ] Resource usage verified under animation

### Milestone 8 — Expansion
- [ ] Add regions (CONUS subsets)
- [ ] Add models (GFS/NAM/ECMWF)
- [ ] Validate storage growth + retention

---

## 11. Explicit DO-NOT List (For AI Agents)

- DO NOT modify V1 directories or import V1 modules in V2
- DO NOT reintroduce Python-per-tile PNG precomputation as the production path
- DO NOT use percentile scaling for palette-driven variables
- DO NOT store generated runtime data inside the git repo
- DO NOT bypass API versioning