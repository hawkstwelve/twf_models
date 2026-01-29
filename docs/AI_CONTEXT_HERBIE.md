# AI Context: Herbie Integration

This document is the **authoritative technical reference** for integrating the
Herbie Python package into this repository.

AI agents **must follow this document exactly** when implementing or modifying
Herbie-related code. If behavior is ambiguous, consult the approved Herbie
documentation via Context7.

---

## 1. Purpose of Herbie in This Project

Herbie is used **only as a data discovery, download, and read layer** for GRIB2
model data.

Herbie is **not** responsible for:
- Scheduling
- Automation
- Derived field computation
- Accumulations
- Snowfall classification
- Map rendering
- API responses

All of the above are handled by existing pipeline components.

---

## 2. Fetcher Contract (Non-Negotiable)

All Herbie-based fetchers **must** conform to the existing fetcher interface.

### Base Class

All fetchers subclass: `BaseDataFetcher`

### Required Method

```python
def fetch_raw_data(
    run_time: datetime,
    forecast_hour: int,
    raw_fields: Set[str],
    subset_region: bool = True,
) -> xr.Dataset:
    ...
```

### Mandatory Requirements

- Must return an **xarray.Dataset**
- Dataset must contain **only** the requested `raw_fields`
- Dataset variable names must **exactly match** the raw field names
- `run_time` must be **timezone-aware UTC**
- Must handle regional subsetting if `subset_region=True`
- Must NOT compute derived fields  
  - Derived fields are handled by `build_dataset_for_maps()`
- May use utilities inherited from `BaseDataFetcher`  
  - Example: `get_latest_run_time()`

Violation of this contract breaks the pipeline.

---

## 3. GRIB Cache Contract (Critical)

GRIB files are **immutable, shared artifacts**.

### Cache Layout

```
grib_cache/{model_id}/
    {model_id}_{YYYYMMDD}_{HH}_f{FFF}_{product}.grib2
```

### Rules

- Files are immutable once written
- Shared across workers and processes
- Fetchers must **never delete or overwrite** cached GRIBs
- Deterministic naming is required for cache hits
- No temporary directories outside the cache root
- Do NOT rely on Herbie defaults that delete files
  - `remove_grib` must not violate immutability
  - Herbie must be configured so it does not delete downloaded GRIB files
    (e.g., do not enable behavior equivalent to `remove_grib=True`)

Any cleanup or GC is handled elsewhere, not by fetchers.

---

## 4. What Herbie Is Allowed to Do

Herbie may be used to:
- Discover model data across sources (AWS, Google, NOMADS, etc.)
- Download GRIB2 files into the existing cache
- Read GRIB messages into xarray
- Select specific messages via search strings
- Wait for data availability using `HerbieWait`

Herbie may **not**:
- Rename variables arbitrarily
- Infer derived fields
- Manage cache lifecycle
- Decide product naming conventions

---

## 5. Context7 Usage Policy (Herbie Only)

Context7 is available to retrieve **authoritative Herbie documentation**.
It must be used **sparingly and intentionally**.

### Use Context7 ONLY when:

1. Implementing or modifying Herbie-specific code
2. Mapping `raw_fields` to Herbie search patterns
3. Resolving ambiguity in Herbie behavior
4. Adding a new model, product, or data source
5. Debugging unexpected Herbie behavior

### Do NOT use Context7 when:

- Refactoring non-Herbie code
- Working on scheduling, API, UI, or rendering
- Writing tests or mocks unrelated to Herbie semantics
- Applying known internal rules already defined here

### Budget

- Maximum **one Context7 call per file change**
- Additional calls only allowed when debugging a failure

### When Context7 is used:

- Extract only the **minimum required facts**
- Summarize and proceed
- Do not paste large documentation sections

---

## 6. Approved Herbie Documentation Sources

Use **only** these sources when consulting Context7:

- Herbie core API (`Herbie` class)  
  https://herbie.readthedocs.io/en/stable/api_reference/_autosummary/herbie.core.Herbie.html

- Waiting for data (`HerbieWait`)  
  https://herbie.readthedocs.io/en/latest/api_reference/_autosummary/herbie.latest.HerbieWait.html

- Search / GRIB message selection  
  https://herbie.readthedocs.io/en/latest/user_guide/tutorial/search.html

- Installation and runtime dependencies  
  https://herbie.readthedocs.io/en/stable/user_guide/install.html

---

## 7. raw_fields → Herbie Search Mapping

Herbie selects GRIB messages using **search strings** (wgrib2-style matching).
`raw_fields` do **not** automatically map 1:1 to GRIB variables.

A translation layer is required.

### Rules

- Each `raw_field` must map to one or more Herbie search patterns
- Multiple GRIB messages per field are allowed
- The adapter is responsible for returning a clean Dataset
- No derived fields may be computed here

### Mapping Table

| raw_field | Herbie search pattern | Notes |
|---------|----------------------|------|
| TMP_2M | `TMP:2 m` | Direct GRIB match |
| UGRD_10M | `UGRD:10 m` | Wind component |
| VGRD_10M | `VGRD:10 m` | Wind component |

If a mapping is uncertain, consult Herbie docs via Context7.

---

## 8. Versioning

Herbie behavior may change over time.

- Prefer **stable** documentation
- Pin Herbie versions in environments when possible
- Do not assume undocumented behavior

---

## 9. Golden Rule

If there is a conflict between:
- Herbie defaults
- Agent assumptions
- This document

**This document wins.**