from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.config import settings
from app.models import MODEL_REGISTRY, get_model
from app.services.colormaps_v2 import VAR_SPECS
from app.services.run_resolution import RUN_RE

logger = logging.getLogger(__name__)

CONTRACT_VERSION = 1
ZOOM_MIN = 0
ZOOM_MAX = 7
INITIAL_PUBLISH_GATE = 6
PUBLISH_BATCH_SIZE = 6
COG_FRAME_RE = re.compile(r"^fh(?P<fh>\d{3})\.cog\.tif$")
FRAME_ID_RE = re.compile(r"^\d{3}$")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_run_datetime(run: str) -> datetime:
    if RUN_RE.match(run) is None:
        raise ValueError(f"Invalid run id: {run}")
    return datetime.strptime(run, "%Y%m%d_%Hz").replace(tzinfo=timezone.utc)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp_path.replace(path)


def _atomic_symlink(path: Path, target_rel: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    os.symlink(target_rel, tmp_path)
    tmp_path.replace(path)


@contextmanager
def model_run_lock(model: str, run: str, *, timeout_seconds: float = 30.0):
    lock_path = settings.STAGING_ROOT / ".locks" / model / f"{run}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_seconds
    while True:
        try:
            lock_path.mkdir()
            break
        except FileExistsError:
            if time.time() >= deadline:
                raise TimeoutError(f"Timed out acquiring lock for model={model} run={run}")
            time.sleep(0.05)
    try:
        yield
    finally:
        shutil.rmtree(lock_path, ignore_errors=True)


def _frame_id_for_fh(fh: int) -> str:
    if fh < 0:
        raise ValueError("fh must be >= 0")
    return f"{fh:03d}"


def _fh_for_frame_id(frame_id: str) -> int:
    if FRAME_ID_RE.match(frame_id) is None:
        raise ValueError(f"Invalid frame_id: {frame_id}")
    return int(frame_id)


def _expected_frame_fhs(model: str, run: str, var: str) -> list[int]:
    plugin = get_model(model)
    run_dt = _parse_run_datetime(run)
    fhs = list(plugin.target_fhs(run_dt.hour))
    normalized_var = plugin.normalize_var_id(var)
    if model == "gfs" and normalized_var == "precip_ptype":
        fhs = [fh for fh in fhs if fh >= 6 and (fh % 6) == 0]
    return fhs


def _expected_frame_count(model: str, run: str, var: str) -> int:
    return len(_expected_frame_fhs(model, run, var))


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _resolve_bounds(model: str, region: str) -> list[float]:
    plugin = get_model(model)
    region_spec = plugin.get_region(region)
    if region_spec and region_spec.bbox_wgs84:
        return [float(value) for value in region_spec.bbox_wgs84]
    return [-180.0, -90.0, 180.0, 90.0]


def _resolve_units(normalized_var: str, sidecar_meta: dict[str, Any] | None) -> str:
    if sidecar_meta:
        sidecar_units = sidecar_meta.get("units")
        if isinstance(sidecar_units, str) and sidecar_units.strip():
            return sidecar_units.strip()
    spec = VAR_SPECS.get(normalized_var, {})
    units = spec.get("units")
    if isinstance(units, str) and units.strip():
        return units.strip()
    return "unknown"


def _resolve_nodata(sidecar_meta: dict[str, Any] | None) -> dict[str, Any]:
    output_mode = str((sidecar_meta or {}).get("output_mode") or "").strip()
    if output_mode == "byte_singleband":
        return {"value": 0, "rule": "value=0 is nodata/transparent"}
    return {"value": 255, "rule": "value=255 is nodata/transparent"}


def _frame_url(model: str, run: str, var: str, frame_id: str) -> str:
    return f"/tiles/{model}/{run}/{var}/{frame_id}.pmtiles"


def _validate_contract_version(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("contract_version must be an integer")
    if value != CONTRACT_VERSION:
        raise ValueError(f"Unsupported contract_version: {value}")


def validate_frame_meta_contract(meta: dict[str, Any]) -> None:
    required = [
        "contract_version",
        "model",
        "run",
        "variable_id",
        "frame_id",
        "fhr",
        "valid_time",
        "units",
        "nodata",
        "bounds",
        "zoom_min",
        "zoom_max",
        "colormap_id",
        "colormap_version",
        "url",
    ]
    missing = [key for key in required if key not in meta]
    if missing:
        raise ValueError(f"Frame meta missing required keys: {missing}")
    _validate_contract_version(meta["contract_version"])
    if RUN_RE.match(str(meta["run"])) is None:
        raise ValueError("run must match YYYYMMDD_HHz")
    frame_id = str(meta["frame_id"])
    if FRAME_ID_RE.match(frame_id) is None:
        raise ValueError("frame_id must match ^\\d{3}$")
    fhr = meta["fhr"]
    if isinstance(fhr, bool) or not isinstance(fhr, int) or fhr < 0:
        raise ValueError("fhr must be a non-negative integer")
    bounds = meta["bounds"]
    if not isinstance(bounds, list) or len(bounds) != 4:
        raise ValueError("bounds must be a list[4]")
    for value in bounds:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("bounds values must be numeric")
    zoom_min = meta["zoom_min"]
    zoom_max = meta["zoom_max"]
    if zoom_min != ZOOM_MIN or zoom_max != ZOOM_MAX:
        raise ValueError(f"zoom range must be {ZOOM_MIN}..{ZOOM_MAX}")
    if not str(meta["url"]).startswith("/tiles/"):
        raise ValueError("url must be a /tiles/ path")


def validate_manifest_contract(manifest: dict[str, Any]) -> None:
    required = [
        "contract_version",
        "model",
        "run",
        "variable",
        "expected_frames",
        "available_frames",
        "frames",
        "last_updated",
    ]
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ValueError(f"Manifest missing required keys: {missing}")
    _validate_contract_version(manifest["contract_version"])
    expected_frames = manifest["expected_frames"]
    available_frames = manifest["available_frames"]
    if isinstance(expected_frames, bool) or not isinstance(expected_frames, int) or expected_frames < 0:
        raise ValueError("expected_frames must be a non-negative integer")
    if isinstance(available_frames, bool) or not isinstance(available_frames, int) or available_frames < 0:
        raise ValueError("available_frames must be a non-negative integer")
    if available_frames > expected_frames and expected_frames > 0:
        raise ValueError("available_frames cannot exceed expected_frames")
    frames = manifest["frames"]
    if not isinstance(frames, list):
        raise ValueError("frames must be a list")
    if len(frames) != available_frames:
        raise ValueError("frames length must equal available_frames")
    for frame in frames:
        for key in ("frame_id", "fhr", "valid_time", "url"):
            if key not in frame:
                raise ValueError(f"frame entry missing key={key}")
        _fh_for_frame_id(str(frame["frame_id"]))
        if isinstance(frame["fhr"], bool) or not isinstance(frame["fhr"], int) or frame["fhr"] < 0:
            raise ValueError("frame fhr must be a non-negative integer")
        if not str(frame["url"]).startswith("/tiles/"):
            raise ValueError("frame url must be a /tiles/ path")


def _staging_var_root(model: str, run: str, var: str) -> Path:
    return settings.STAGING_ROOT / model / run / var


def _published_var_root(model: str, run: str, var: str) -> Path:
    return settings.PUBLISH_ROOT / model / run / var


def _source_var_root(model: str, region: str, run: str, var: str) -> Path:
    return settings.DATA_V2_ROOT / model / region / run / var


def _build_pmtiles_from_cog(
    source_cog_path: Path,
    destination_pmtiles_path: Path,
    *,
    frame_id: str,
    var: str,
) -> None:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "build_pmtiles.py"
    if not script_path.exists():
        raise RuntimeError(f"Missing PMTiles build script: {script_path}")

    destination_pmtiles_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_pmtiles_path.exists():
        destination_pmtiles_path.unlink()

    validation_path = destination_pmtiles_path.with_suffix(".tiles.json")
    if validation_path.exists():
        validation_path.unlink()

    command = [
        sys.executable,
        str(script_path),
        "--src",
        str(source_cog_path),
        "--dst",
        str(destination_pmtiles_path),
        "--var",
        var,
        "--zoom-min",
        str(ZOOM_MIN),
        "--zoom-max",
        str(ZOOM_MAX),
        "--validation-json",
        str(validation_path),
    ]

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        details = stderr or stdout or f"exit_code={exc.returncode}"
        raise RuntimeError(
            f"COG->PMTiles conversion failed for frame_id={frame_id} source={source_cog_path}: {details}"
        ) from exc


def _validate_pmtiles_magic(pmtiles_path: Path) -> None:
    with pmtiles_path.open("rb") as fp:
        header = fp.read(8)
    if len(header) < 8:
        raise ValueError(f"PMTiles header too short: {pmtiles_path}")
    if header.startswith(b"II*\x00") or header.startswith(b"MM\x00*"):
        raise ValueError(
            f"Invalid PMTiles magic for {pmtiles_path}: produced GeoTIFF, not PMTiles"
        )
    if not header.startswith(b"PMTiles"):
        raise ValueError(f"Invalid PMTiles magic for {pmtiles_path}: header={header!r}")


def validate_staged_pmtiles(pmtiles_path: Path) -> None:
    if not pmtiles_path.exists() or not pmtiles_path.is_file():
        raise ValueError(f"PMTiles missing: {pmtiles_path}")
    if pmtiles_path.stat().st_size <= 0:
        raise ValueError(f"PMTiles empty: {pmtiles_path}")
    _validate_pmtiles_magic(pmtiles_path)
    validation_path = pmtiles_path.with_suffix(".tiles.json")
    payload = _read_json(validation_path)
    if payload is None:
        raise ValueError(f"Missing tile presence metadata: {validation_path}")
    tile_presence = payload.get("tile_presence")
    if not isinstance(tile_presence, dict):
        raise ValueError("tile presence metadata missing 'tile_presence' object")
    if "z0" not in tile_presence or "z7" not in tile_presence:
        raise ValueError("tile presence metadata must include z0 and z7 checks")
    z0_presence = tile_presence.get("z0")
    z7_presence = tile_presence.get("z7")
    if isinstance(z0_presence, dict) and z0_presence.get("present") is False:
        raise ValueError("tile presence validation failed: z0 tile missing")
    if isinstance(z7_presence, dict) and z7_presence.get("present") is False:
        raise ValueError("tile presence validation failed: z7 tile missing")


def stage_single_frame(
    *,
    model: str,
    region: str,
    run: str,
    var: str,
    fh: int,
) -> dict[str, Any]:
    plugin = get_model(model)
    normalized_var = plugin.normalize_var_id(var)
    if plugin.get_var(normalized_var) is None:
        raise ValueError(f"Unknown variable for model={model}: {var}")

    frame_id = _frame_id_for_fh(fh)
    source_var_root = _source_var_root(model, region, run, normalized_var)
    source_cog_path = source_var_root / f"fh{fh:03d}.cog.tif"
    if not source_cog_path.exists():
        raise FileNotFoundError(f"Missing COG source for offline build: {source_cog_path}")

    staging_var_root = _staging_var_root(model, run, normalized_var)
    staging_frames_root = staging_var_root / "frames"
    staging_meta_root = staging_var_root / "meta"
    staging_frames_root.mkdir(parents=True, exist_ok=True)
    staging_meta_root.mkdir(parents=True, exist_ok=True)

    staging_pmtiles_path = staging_frames_root / f"{frame_id}.pmtiles"
    _build_pmtiles_from_cog(
        source_cog_path,
        staging_pmtiles_path,
        frame_id=frame_id,
        var=normalized_var,
    )
    validate_staged_pmtiles(staging_pmtiles_path)

    sidecar_payload = _read_json(source_var_root / f"fh{fh:03d}.json") or {}
    sidecar_meta = sidecar_payload.get("meta") if isinstance(sidecar_payload.get("meta"), dict) else None

    run_dt = _parse_run_datetime(run)
    valid_time = (run_dt + timedelta(hours=fh)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    frame_meta = {
        "contract_version": CONTRACT_VERSION,
        "model": model,
        "run": run,
        "variable_id": normalized_var,
        "frame_id": frame_id,
        "fhr": fh,
        "valid_time": valid_time,
        "units": _resolve_units(normalized_var, sidecar_meta),
        "nodata": _resolve_nodata(sidecar_meta),
        "bounds": _resolve_bounds(model, region),
        "zoom_min": ZOOM_MIN,
        "zoom_max": ZOOM_MAX,
        "colormap_id": normalized_var,
        "colormap_version": CONTRACT_VERSION,
        "url": _frame_url(model, run, normalized_var, frame_id),
    }
    validate_frame_meta_contract(frame_meta)
    _atomic_write_json(staging_meta_root / f"{frame_id}.json", frame_meta)
    return frame_meta


def _load_validated_staging_frames(model: str, run: str, var: str) -> list[dict[str, Any]]:
    staging_var_root = _staging_var_root(model, run, var)
    staging_meta_root = staging_var_root / "meta"
    staging_frames_root = staging_var_root / "frames"
    if not staging_meta_root.exists() or not staging_frames_root.exists():
        return []

    frames: list[dict[str, Any]] = []
    for meta_path in sorted(staging_meta_root.glob("*.json")):
        payload = _read_json(meta_path)
        if payload is None:
            continue
        try:
            validate_frame_meta_contract(payload)
            frame_id = str(payload["frame_id"])
            pmtiles_path = staging_frames_root / f"{frame_id}.pmtiles"
            validate_staged_pmtiles(pmtiles_path)
        except Exception as exc:
            logger.warning("Skipping invalid staged frame: path=%s reason=%s", meta_path, exc)
            continue
        frames.append(payload)

    frames.sort(key=lambda item: int(item["fhr"]))
    return frames


def _build_manifest_payload(
    *,
    model: str,
    run: str,
    var: str,
    frames_meta: list[dict[str, Any]],
) -> dict[str, Any]:
    frames = [
        {
            "frame_id": str(meta["frame_id"]),
            "fhr": int(meta["fhr"]),
            "valid_time": str(meta["valid_time"]),
            "url": str(meta["url"]),
        }
        for meta in frames_meta
    ]
    payload = {
        "contract_version": CONTRACT_VERSION,
        "model": model,
        "run": run,
        "variable": var,
        "expected_frames": _expected_frame_count(model, run, var),
        "available_frames": len(frames),
        "frames": frames,
        "last_updated": _now_utc_iso(),
    }
    validate_manifest_contract(payload)
    return payload


def rebuild_staging_manifest(model: str, run: str, var: str) -> dict[str, Any]:
    frames_meta = _load_validated_staging_frames(model, run, var)
    payload = _build_manifest_payload(model=model, run=run, var=var, frames_meta=frames_meta)
    _atomic_write_json(_staging_var_root(model, run, var) / "manifest.json", payload)
    return payload


def _copy_if_missing(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    shutil.copy2(src, dst)


def _read_published_manifest(model: str, run: str, var: str) -> dict[str, Any] | None:
    manifest_path = _published_var_root(model, run, var) / "manifest.json"
    payload = _read_json(manifest_path)
    if payload is None:
        return None
    try:
        validate_manifest_contract(payload)
    except Exception:
        return None
    return payload


def _latest_pointer_path(model: str) -> Path:
    return settings.MANIFEST_ROOT / model / "latest.json"


def _write_latest_pointer_alias_if_enabled(model: str, latest_path: Path) -> None:
    if not settings.WRITE_LEGACY_MODEL_LATEST_ALIAS:
        return
    alias_path = settings.MANIFEST_ROOT / f"{model.upper()}_latest.json"
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = alias_path.with_name(f".{alias_path.name}.{uuid.uuid4().hex}.tmp")
    shutil.copy2(latest_path, tmp_path)
    tmp_path.replace(alias_path)


def _update_latest_pointer(model: str, run: str, var: str, manifest_payload: dict[str, Any]) -> None:
    latest_path = _latest_pointer_path(model)
    existing = _read_json(latest_path) or {}
    pointer: dict[str, Any]
    if (
        isinstance(existing, dict)
        and existing.get("contract_version") == CONTRACT_VERSION
        and existing.get("model") == model
        and isinstance(existing.get("variables"), dict)
        and isinstance(existing.get("run"), str)
        and existing.get("run") == run
    ):
        pointer = dict(existing)
    else:
        pointer = {
            "contract_version": CONTRACT_VERSION,
            "model": model,
            "run": run,
            "variables": {},
        }

    variables = dict(pointer.get("variables") or {})
    variables[var] = {
        "manifest_url": f"/published/{model}/{run}/{var}/manifest.json",
        "available_frames": int(manifest_payload["available_frames"]),
        "expected_frames": int(manifest_payload["expected_frames"]),
        "last_updated": _now_utc_iso(),
    }
    pointer["variables"] = variables
    pointer["run"] = run
    pointer["last_updated"] = _now_utc_iso()
    _atomic_write_json(latest_path, pointer)
    _write_latest_pointer_alias_if_enabled(model, latest_path)


def publish_from_staging(model: str, run: str, var: str) -> dict[str, Any]:
    with model_run_lock(model, run):
        staging_manifest = rebuild_staging_manifest(model, run, var)
        stage_available = int(staging_manifest["available_frames"])
        expected_frames = int(staging_manifest["expected_frames"])
        if stage_available < INITIAL_PUBLISH_GATE:
            return {
                "published": False,
                "reason": "gate_not_met",
                "available_frames": stage_available,
                "expected_frames": expected_frames,
                "published_frames": int(
                    ((_read_published_manifest(model, run, var) or {}).get("available_frames") or 0)
                ),
            }

        published_manifest = _read_published_manifest(model, run, var)
        published_available = int((published_manifest or {}).get("available_frames") or 0)
        target_available = published_available

        if published_available == 0:
            target_available = stage_available
        else:
            delta = stage_available - published_available
            if stage_available == expected_frames and stage_available > published_available:
                target_available = stage_available
            elif delta >= PUBLISH_BATCH_SIZE:
                target_available = published_available + (delta // PUBLISH_BATCH_SIZE) * PUBLISH_BATCH_SIZE

        if target_available <= published_available:
            return {
                "published": False,
                "reason": "batch_threshold_not_met",
                "available_frames": stage_available,
                "expected_frames": expected_frames,
                "published_frames": published_available,
            }

        selected_frames = list(staging_manifest["frames"][:target_available])
        staging_var_root = _staging_var_root(model, run, var)
        published_var_root = _published_var_root(model, run, var)
        for frame in selected_frames:
            frame_id = str(frame["frame_id"])
            src_pmtiles = staging_var_root / "frames" / f"{frame_id}.pmtiles"
            src_meta = staging_var_root / "meta" / f"{frame_id}.json"
            validate_staged_pmtiles(src_pmtiles)
            payload = _read_json(src_meta)
            if payload is None:
                raise ValueError(f"Missing staged meta for frame_id={frame_id}")
            validate_frame_meta_contract(payload)
            dst_pmtiles = published_var_root / "frames" / f"{frame_id}.pmtiles"
            dst_meta = published_var_root / "meta" / f"{frame_id}.json"
            _copy_if_missing(src_pmtiles, dst_pmtiles)
            _copy_if_missing(src_pmtiles.with_suffix(".tiles.json"), dst_pmtiles.with_suffix(".tiles.json"))
            _copy_if_missing(src_meta, dst_meta)

        selected_meta = _load_validated_staging_frames(model, run, var)[:target_available]
        publish_manifest = _build_manifest_payload(model=model, run=run, var=var, frames_meta=selected_meta)
        snapshots_root = published_var_root / "manifests"
        snapshots_root.mkdir(parents=True, exist_ok=True)
        snapshot_name = f"manifest.{target_available}.json"
        snapshot_path = snapshots_root / snapshot_name
        if not snapshot_path.exists():
            _atomic_write_json(snapshot_path, publish_manifest)

        manifest_symlink = published_var_root / "manifest.json"
        _atomic_symlink(manifest_symlink, str(Path("manifests") / snapshot_name))
        _update_latest_pointer(model, run, var, publish_manifest)
        return {
            "published": True,
            "available_frames": stage_available,
            "expected_frames": expected_frames,
            "published_frames": target_available,
            "manifest_path": str(manifest_symlink),
        }


def stage_and_publish_single_frame(
    *,
    model: str,
    region: str,
    run: str,
    var: str,
    fh: int,
) -> dict[str, Any]:
    frame_meta = stage_single_frame(model=model, region=region, run=run, var=var, fh=fh)
    publish_state = publish_from_staging(model=model, run=run, var=get_model(model).normalize_var_id(var))
    return {
        "frame_id": frame_meta["frame_id"],
        "publish_state": publish_state,
    }


def discover_source_fhs(model: str, region: str, run: str, var: str) -> list[int]:
    plugin = get_model(model)
    normalized_var = plugin.normalize_var_id(var)
    source_root = _source_var_root(model, region, run, normalized_var)
    if not source_root.exists() or not source_root.is_dir():
        return []
    fhs: list[int] = []
    for path in source_root.glob("fh*.cog.tif"):
        match = COG_FRAME_RE.match(path.name)
        if not match:
            continue
        fhs.append(int(match.group("fh")))
    return sorted(set(fhs))


def build_and_publish_run_var(
    *,
    model: str,
    region: str,
    run: str,
    var: str,
    fhs: list[int] | None = None,
) -> dict[str, Any]:
    plugin = get_model(model)
    normalized_var = plugin.normalize_var_id(var)
    requested_fhs = sorted(set(fhs or discover_source_fhs(model, region, run, normalized_var)))
    for fh in requested_fhs:
        stage_single_frame(model=model, region=region, run=run, var=normalized_var, fh=fh)
        publish_from_staging(model=model, run=run, var=normalized_var)
    manifest = _read_published_manifest(model, run, normalized_var)
    return {
        "model": model,
        "run": run,
        "variable": normalized_var,
        "processed_frames": requested_fhs,
        "published_frames": int((manifest or {}).get("available_frames") or 0),
    }


def list_published_models() -> list[dict[str, str]]:
    models: set[str] = set()
    if settings.PUBLISH_ROOT.exists():
        for path in settings.PUBLISH_ROOT.iterdir():
            if path.is_dir() and path.name in MODEL_REGISTRY:
                models.add(path.name)
    if settings.MANIFEST_ROOT.exists():
        for path in settings.MANIFEST_ROOT.iterdir():
            if path.is_dir() and path.name in MODEL_REGISTRY:
                models.add(path.name)
    ordered = sorted(models)
    return [{"id": model, "name": MODEL_REGISTRY[model].name} for model in ordered]


def list_published_runs(model: str) -> list[str]:
    get_model(model)
    model_root = settings.PUBLISH_ROOT / model
    if not model_root.exists() or not model_root.is_dir():
        return []
    runs: list[str] = []
    for path in model_root.iterdir():
        if not path.is_dir():
            continue
        if RUN_RE.match(path.name) is None:
            continue
        runs.append(path.name)
    runs.sort(reverse=True)
    return runs


def resolve_published_run(model: str, run: str) -> str:
    if run != "latest":
        return run
    pointer_path = _latest_pointer_path(model)
    payload = _read_json(pointer_path) or {}
    pointer_run = payload.get("run")
    if isinstance(pointer_run, str) and RUN_RE.match(pointer_run):
        return pointer_run
    runs = list_published_runs(model)
    if not runs:
        raise HTTPException(status_code=404, detail=f"No published runs found for model={model}")
    return runs[0]


def list_published_vars(model: str, run: str) -> list[str]:
    get_model(model)
    resolved_run = resolve_published_run(model, run)
    run_root = settings.PUBLISH_ROOT / model / resolved_run
    if not run_root.exists() or not run_root.is_dir():
        return []
    vars_list: list[str] = []
    for path in run_root.iterdir():
        if not path.is_dir():
            continue
        manifest = _read_json(path / "manifest.json")
        if manifest is None:
            continue
        try:
            validate_manifest_contract(manifest)
        except Exception:
            continue
        vars_list.append(path.name)
    return sorted(vars_list)


def load_published_var_manifest(model: str, run: str, var: str) -> dict[str, Any]:
    get_model(model)
    plugin = get_model(model)
    normalized_var = plugin.normalize_var_id(var)
    resolved_run = resolve_published_run(model, run)
    manifest_path = settings.PUBLISH_ROOT / model / resolved_run / normalized_var / "manifest.json"
    payload = _read_json(manifest_path)
    if payload is None:
        raise HTTPException(status_code=404, detail="Published manifest not found")
    try:
        validate_manifest_contract(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Invalid published manifest: {exc}") from exc
    return payload


def load_published_run_manifest(model: str, run: str) -> dict[str, Any]:
    resolved_run = resolve_published_run(model, run)
    vars_list = list_published_vars(model, resolved_run)
    variables: dict[str, dict[str, Any]] = {}
    for var in vars_list:
        variables[var] = load_published_var_manifest(model, resolved_run, var)
    return {
        "contract_version": CONTRACT_VERSION,
        "model": model,
        "run": resolved_run,
        "variables": variables,
        "last_updated": _now_utc_iso(),
    }
