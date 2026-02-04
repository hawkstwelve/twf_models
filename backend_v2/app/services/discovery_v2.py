from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from fastapi import HTTPException

from app.services.run_resolution import RUN_RE, get_data_root

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


def list_models() -> list[dict[str, str]]:
    root = get_data_root()
    models = sorted(p.name for p in _safe_list_dirs(root))
    return [{"id": model, "name": model.upper()} for model in models]


def list_regions(model: str) -> list[str]:
    model_root = get_data_root() / model
    _ensure_dir(model_root, "Unknown model")
    return sorted(p.name for p in _safe_list_dirs(model_root))


def list_runs(model: str, region: str) -> list[str]:
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

    names = [p.name for p in run_dirs]
    if all(is_valid_run_id(name) for name in names):
        runs = sorted(names, reverse=True)
    else:
        run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        runs = [p.name for p in run_dirs]

    _cache_set(cache_key, runs)
    return list(runs)


def resolve_run(model: str, region: str, run: str, *, allow_empty_latest: bool = False) -> str | None:
    model_root = get_data_root() / model
    _ensure_dir(model_root, "Unknown model")
    region_root = model_root / region
    _ensure_dir(region_root, "Unknown region")

    if run != "latest":
        run_root = region_root / run
        _ensure_dir(run_root, "Unknown run")
        return run

    runs = list_runs(model, region)
    if not runs:
        if allow_empty_latest:
            return None
        raise HTTPException(status_code=404, detail="No runs found for model/region")

    return runs[0]


def list_vars(model: str, region: str, run: str) -> list[str]:
    resolved_run = resolve_run(model, region, run)
    if resolved_run is None:
        raise HTTPException(status_code=404, detail="No runs found for model/region")

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
    resolved_run = resolve_run(model, region, run, allow_empty_latest=True)
    if resolved_run is None:
        return []

    cache_key = ("frames", model, region, f"{resolved_run}:{var}")
    cached = _cache_get(cache_key)
    if cached is not None:
        return [frame.copy() for frame in cached]

    var_root = get_data_root() / model / region / resolved_run / var
    _ensure_dir(var_root, "Unknown variable")

    frames: list[dict] = []
    for entry in var_root.iterdir():
        if not entry.is_file():
            continue
        fh = parse_fh_filename(entry.name)
        if fh is None:
            continue
        meta = _read_json(var_root / f"fh{fh:03d}.json")
        if meta is None:
            meta = {"created_utc": None, "var_key": var}
        frames.append({"fh": fh, "has_cog": True, "meta": meta})

    frames.sort(key=lambda item: item["fh"])
    _cache_set(cache_key, frames)
    return [frame.copy() for frame in frames]
