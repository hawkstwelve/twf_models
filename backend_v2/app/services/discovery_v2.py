from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from app.models import MODEL_REGISTRY, get_model
from app.services.run_resolution import RUN_RE, get_data_root, resolve_run

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 15.0
FH_RE = re.compile(r"^fh(\d{3})\.cog\.tif$")


_CACHE: dict[tuple[str, str, str, str], tuple[float, list]] = {}


def is_valid_run_id(value: str) -> bool:
    return RUN_RE.match(value) is not None


def parse_fh_filename(name: str) -> int | None:
    match = FH_RE.match(name)
    if not match:
        return None
    return int(match.group(1))


def _cache_get(key: tuple[str, str, str, str]) -> list | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    cached_at, value = entry
    if (time.time() - cached_at) > CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: tuple[str, str, str, str], value: list) -> None:
    _CACHE[key] = (time.time(), value)


def _ensure_dir(path: Path, detail: str) -> None:
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=404, detail=detail)


def _safe_list_dirs(path: Path) -> list[Path]:
    if not path.exists() or not path.is_dir():
        return []
    return [p for p in path.iterdir() if p.is_dir()]


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        logger.warning("Failed to read JSON: %s", path)
        return None


def build_tile_url_template(
    model: str,
    region: str,
    run: str,
    var: str,
    fh: int,
) -> str:
    return f"/tiles/{model}/{region}/{run}/{var}/{fh}/{{z}}/{{x}}/{{y}}.png"


def list_models() -> list[dict[str, str]]:
    root = get_data_root()
    models = [p.name for p in _safe_list_dirs(root)]
    models = sorted(model for model in models if model in MODEL_REGISTRY)
    return [{"id": model, "name": MODEL_REGISTRY[model].name} for model in models]


def list_regions(model: str) -> list[str]:
    get_model(model)
    model_root = get_data_root() / model
    _ensure_dir(model_root, "Unknown model")
    return sorted(p.name for p in _safe_list_dirs(model_root))


def list_runs(model: str, region: str) -> list[str]:
    get_model(model)
    model_root = get_data_root() / model
    _ensure_dir(model_root, "Unknown model")
    region_root = model_root / region
    _ensure_dir(region_root, "Unknown region")

    cache_key = ("runs", model, region, "")
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)

    run_dirs = _safe_list_dirs(region_root)
    if not run_dirs:
        _cache_set(cache_key, [])
        return []

    matched: list[tuple[datetime, str]] = []
    for path in run_dirs:
        if not is_valid_run_id(path.name):
            continue
        try:
            run_dt = datetime.strptime(path.name, "%Y%m%d_%Hz")
        except ValueError:
            continue
        matched.append((run_dt, path.name))

    if not matched:
        _cache_set(cache_key, [])
        return []

    matched.sort(key=lambda item: item[0], reverse=True)
    runs = [name for _, name in matched]

    _cache_set(cache_key, runs)
    return list(runs)


def list_vars(model: str, region: str, run: str) -> list[str]:
    get_model(model)
    resolved_run = resolve_run(model, region, run)
    if run != "latest":
        run_root = get_data_root() / model / region / resolved_run
        _ensure_dir(run_root, "Unknown run")

    cache_key = ("vars", model, region, resolved_run)
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)

    vars_root = get_data_root() / model / region / resolved_run
    _ensure_dir(vars_root, "Unknown run")
    vars_list = sorted(p.name for p in _safe_list_dirs(vars_root))
    _cache_set(cache_key, vars_list)
    return list(vars_list)


def list_frames(model: str, region: str, run: str, var: str) -> list[dict]:
    get_model(model)
    try:
        resolved_run = resolve_run(model, region, run)
    except HTTPException as exc:
        if run == "latest" and exc.status_code == 404:
            return []
        raise

    run_root = get_data_root() / model / region / resolved_run
    if not run_root.exists() or not run_root.is_dir():
        if run == "latest":
            return []
        raise HTTPException(status_code=404, detail="Unknown run")

    cache_key = ("frames", model, region, f"{resolved_run}:{var}")
    cached = _cache_get(cache_key)
    if cached is not None:
        return [frame.copy() for frame in cached]

    var_root = get_data_root() / model / region / resolved_run / var
    if not var_root.exists() or not var_root.is_dir():
        _cache_set(cache_key, [])
        return []

    frames: list[dict] = []
    seen_fhs: set[int] = set()
    for entry in var_root.glob("fh*.cog.tif"):
        if not entry.is_file():
            continue
        fh = parse_fh_filename(entry.name)
        if fh is None:
            continue
        if fh in seen_fhs:
            continue
        seen_fhs.add(fh)
        sidecar = _read_json(var_root / f"fh{fh:03d}.json")
        meta = {"meta": sidecar} if sidecar is not None else None
        frames.append(
            {
                "fh": fh,
                "has_cog": True,
                "meta": meta,
                "run": resolved_run,
                "tile_url_template": build_tile_url_template(
                    model=model,
                    region=region,
                    run=resolved_run,
                    var=var,
                    fh=fh,
                ),
            }
        )

    frames.sort(key=lambda item: item["fh"])
    _cache_set(cache_key, frames)
    return [frame.copy() for frame in frames]
