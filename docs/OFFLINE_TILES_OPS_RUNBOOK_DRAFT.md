# Offline Tiles Publish Ops Runbook (Draft)

Status: Draft for P0.3 review  
Date: 2026-02-11

## Purpose

Define Phase 0 cutover controls, baseline observability, and rollback procedure for atomic publish.

## Controls

Environment flags:

- `OFFLINE_TILES_ENABLED`
- `STAGING_ROOT`
- `PUBLISH_ROOT`
- `MANIFEST_ROOT`

Current defaults in code (`backend_v2/app/config.py`):

- `OFFLINE_TILES_ENABLED=false`
- `STAGING_ROOT=/opt/twf_models/data/staging`
- `PUBLISH_ROOT=/opt/twf_models/data/published`
- `MANIFEST_ROOT=/opt/twf_models/data/manifests`

## Required Metrics

- Build duration: `twf_offline_tile_build_duration_seconds`
- Validation pass/fail: `twf_offline_tile_validation_results_total`
- Publish pointer switch latency: `twf_offline_tile_publish_pointer_switch_latency_seconds`

Metric expectation:

- Emit build duration per frame build task and run/variable aggregate.
- Emit validation results with pass/fail outcome labeling.
- Emit pointer switch latency around the atomic manifest pointer update operation.

## Publish Validation Checklist (Before Pointer Switch)

- Confirm staged manifest contract validity (`contract_version`, required fields present).
- Confirm frame count consistency:
  - `available_frames <= expected_frames`
  - All listed frames have existing PMTiles archives.
- Sample tile read checks at `z=0` and `z=7` for representative frames.
- Validate nodata transparency behavior against metadata.
- Validate `bounds` and zoom metadata consistency.
- Confirm free disk space is above configured minimum threshold.

## Rollback Procedure

1. Identify previous known-good latest pointer payload for the affected model.
2. Atomically repoint model latest pointer to previous run manifest.
3. Verify discovery and frontend frame resolution now target the prior run.
4. Record incident and root cause.
5. Keep failed run artifacts in staging for postmortem unless disk emergency requires cleanup.

## Runtime Tile Route Deprecation (Phase 0 Notice)

Runtime PNG tile endpoints remain available during transition but now return explicit deprecation headers.  
Removal target remains Phase 2 per `docs/OFFLINE_TILES_REFACTOR_PLAN.md`.
