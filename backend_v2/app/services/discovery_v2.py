from __future__ import annotations

import time
from typing import Any

from app.services.offline_tiles import (
    list_published_models,
    list_published_runs,
    list_published_vars,
    load_published_var_manifest,
    resolve_published_run,
)
from app.services.run_resolution import RUN_RE

CACHE_TTL_SECONDS = 5.0
_CACHE: dict[tuple[str, str, str, str], tuple[float, list[Any]]] = {}


def is_valid_run_id(value: str) -> bool:
    return RUN_RE.match(value) is not None


def parse_fh_filename(name: str) -> int | None:
    # Legacy helper retained for compatibility with older tests.
    if not name.startswith("fh") or not name.endswith(".cog.tif"):
        return None
    body = name[len("fh") : -len(".cog.tif")]
    if len(body) != 3 or not body.isdigit():
        return None
    return int(body)


def _cache_get(key: tuple[str, str, str, str]) -> list[Any] | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    cached_at, payload = entry
    if (time.time() - cached_at) > CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: tuple[str, str, str, str], payload: list[Any]) -> None:
    _CACHE[key] = (time.time(), payload)


def build_tile_url_template(
    model: str,
    region: str,
    run: str,
    var: str,
    fh: int,
) -> str:
    del region
    return f"/tiles/{model}/{run}/{var}/{fh:03d}.pmtiles"


def list_models() -> list[dict[str, str]]:
    cache_key = ("models", "", "", "")
    cached = _cache_get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]
    payload = list_published_models()
    _cache_set(cache_key, payload)
    return [dict(item) for item in payload]


def list_regions(model: str) -> list[str]:
    del model
    # Offline manifests are model-scoped (no region partition in published contracts).
    return ["published"]


def list_runs(model: str, region: str) -> list[str]:
    del region
    cache_key = ("runs", model, "", "")
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)
    payload = list_published_runs(model)
    _cache_set(cache_key, payload)
    return list(payload)


def list_vars(model: str, region: str, run: str) -> list[str]:
    del region
    resolved_run = resolve_published_run(model, run)
    cache_key = ("vars", model, resolved_run, "")
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached)
    payload = list_published_vars(model, resolved_run)
    _cache_set(cache_key, payload)
    return list(payload)


def list_frames(model: str, region: str, run: str, var: str) -> list[dict[str, Any]]:
    del region
    resolved_run = resolve_published_run(model, run)
    cache_key = ("frames", model, resolved_run, var)
    cached = _cache_get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]

    manifest = load_published_var_manifest(model, resolved_run, var)
    payload: list[dict[str, Any]] = []
    for frame in manifest.get("frames", []):
        frame_id = str(frame["frame_id"])
        fh = int(frame.get("fhr", int(frame_id)))
        payload.append(
            {
                "frame_id": frame_id,
                "fh": fh,
                "valid_time": frame.get("valid_time"),
                "run": resolved_run,
                "url": frame.get("url"),
                # Legacy key kept for compatibility with existing API consumers.
                "tile_url_template": frame.get("url"),
            }
        )

    _cache_set(cache_key, payload)
    return [dict(item) for item in payload]
