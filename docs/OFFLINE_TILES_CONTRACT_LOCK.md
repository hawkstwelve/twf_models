# Offline Tiles Contract Lock (Phase 0)

Status: Locked  
Locked on: 2026-02-11  
Owner: Backend + Frontend platform

## Scope

This document is the Phase 0 contract lock for the offline tiles refactor. It finalizes:

- Atomic publish semantics
- Schema/versioning requirements
- Default archive strategy

The implementation roadmap remains in `docs/OFFLINE_TILES_REFACTOR_PLAN.md`.

## Locked Decisions

1. Archive strategy default: per-frame PMTiles.
- Canonical frame URL shape: `/tiles/{model}/{run}/{var}/{frame_id}.pmtiles`
- Published artifacts are immutable.
- Progressive availability is manifest-driven only.

2. Variant B is optional implementation-only.
- MBTiles may exist in staging as an internal build artifact.
- PMTiles is the only published/public archive format.

3. Publish is pointer-based and atomic.
- Staging writes happen under `STAGING_ROOT`.
- Published data under `PUBLISH_ROOT` is never mutated in place.
- Visibility changes only through atomic update of a model latest pointer in `MANIFEST_ROOT`.

4. Discovery/clients consume published manifests only.
- No readiness probing by tile endpoint.
- No filesystem scans in frontend for availability inference.

## Schema Baseline

`contract_version` is required in all publish contracts.

## `meta.json` required fields

- `contract_version`
- `model`
- `run`
- `variable_id`
- `frame_id`
- `fhr`
- `valid_time`
- `units`
- `nodata`
- `bounds`
- `zoom_min`
- `zoom_max`
- `colormap_id`
- `colormap_version` or `palette_hash`
- `url`

## `manifest.json` required fields

- `contract_version`
- `model`
- `run`
- `variable`
- `expected_frames`
- `available_frames`
- `frames[]`:
  - `frame_id`
  - `fhr`
  - `valid_time`
  - `url`
- `last_updated`

## Versioning Rules

- Additive backward-compatible fields: no `contract_version` bump.
- Breaking contract changes: bump `contract_version` and provide reader migration.
- Palette/colormap changes must force cache busting through new run publish or URL/version change.

## Operational Constraints

- Overlay zoom cap remains `z<=7`.
- Retention deletes whole run directories only.
- No per-frame archive rewrite/delete under a published run.
