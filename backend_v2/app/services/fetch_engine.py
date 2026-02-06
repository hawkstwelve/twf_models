from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import re

from fastapi import HTTPException

from app.models import get_model
from app.services.gfs_fetch import fetch_gfs_grib, is_upstream_not_ready as is_gfs_not_ready
from app.services.hrrr_fetch import fetch_hrrr_grib, is_upstream_not_ready
from app.services.hrrr_runs import HRRRCacheConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchResult:
    upstream_run_id: str
    is_full_download: bool
    not_ready_reason: str | None = None
    grib_path: Path | None = None
    component_paths: dict[str, Path] | None = None


def is_not_ready_message(text: str) -> bool:
    lowered = text.lower()
    patterns = [
        "upstream not ready",
        "grib2 file not found",
        "herbie did not return a grib2 path",
        "could not resolve latest hrrr cycle",
        "index not ready",
        "idx missing",
        "no index file was found",
        "download the full file first",
    ]
    return any(pattern in lowered for pattern in patterns)


def _run_id_from_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        day = path.parent.parent.name
        hour = path.parent.name
    except Exception:
        return None
    if len(day) == 8 and day.isdigit() and len(hour) == 2 and hour.isdigit():
        return f"{day}_{hour}z"
    return None


def _normalize_run_id(run: str, path: Path | None) -> str:
    from_path = _run_id_from_path(path)
    if from_path:
        return from_path
    if run.lower() == "latest":
        raise RuntimeError("Cannot normalize 'latest' without a resolved GRIB path")
    for fmt in ("%Y%m%d%H", "%Y%m%d_%H", "%Y%m%dT%H"):
        try:
            run_dt = datetime.strptime(run, fmt)
            return run_dt.strftime("%Y%m%d_%Hz")
        except ValueError:
            continue
    if len(run) == 8 and run.isdigit():
        run_dt = datetime.strptime(run + "00", "%Y%m%d%H")
        return run_dt.strftime("%Y%m%d_%Hz")
    return run


def _not_ready(run: str, reason: Exception | str, path: Path | None = None) -> FetchResult:
    message = reason if isinstance(reason, str) else str(reason)
    try:
        upstream_run_id = _normalize_run_id(run, path)
    except RuntimeError:
        upstream_run_id = "unknown"
    return FetchResult(
        upstream_run_id=upstream_run_id,
        is_full_download=False,
        not_ready_reason=message,
        grib_path=None,
        component_paths=None,
    )


RUN_ID_RE = re.compile(r"^(?P<day>\d{8})_(?P<hour>\d{2})z$")


def _fetch_run_arg_from_run_id(run_id: str) -> str:
    match = RUN_ID_RE.match(run_id)
    if not match:
        return run_id
    return f"{match.group('day')}_{match.group('hour')}"


def _hint_value(selectors: object, key: str) -> str | None:
    try:
        value = getattr(selectors, "hints", {}).get(key)
    except AttributeError:
        return None
    if value is None:
        return None
    return str(value)


def _select_search(selectors: object) -> str | None:
    try:
        values = list(getattr(selectors, "search", []))
    except AttributeError:
        return None
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return "|".join(values)


def _resolve_upstream_var(var_spec: object, fallback: str) -> str:
    selectors = getattr(var_spec, "selectors", None)
    if selectors is None:
        return fallback
    hint = _hint_value(selectors, "upstream_var")
    return hint or fallback


def _resolve_component_vars(var_spec: object, fallback: tuple[str, str]) -> tuple[str, str]:
    selectors = getattr(var_spec, "selectors", None)
    if selectors is None:
        return fallback
    u_hint = _hint_value(selectors, "u_component") or _hint_value(selectors, "u_var")
    v_hint = _hint_value(selectors, "v_component") or _hint_value(selectors, "v_var")
    if u_hint and v_hint:
        return u_hint, v_hint
    return fallback


def _resolve_radar_component_vars(var_spec: object, fallback: tuple[str, str]) -> tuple[str, str]:
    selectors = getattr(var_spec, "selectors", None)
    if selectors is None:
        return fallback
    refl_hint = _hint_value(selectors, "refl_component")
    ptype_hint = _hint_value(selectors, "ptype_component")
    if refl_hint and ptype_hint:
        return refl_hint, ptype_hint
    return fallback


def fetch_grib(
    model: str,
    run: str,
    fh: int,
    var: str,
    region: str,
    *,
    cache_dir: Path | None = None,
    **kwargs: object,
) -> FetchResult:
    plugin = get_model(model)
    var_norm = plugin.normalize_var_id(var)

    if plugin.get_region(region) is None:
        raise HTTPException(status_code=404, detail="Unknown region")

    var_spec = plugin.get_var(var_norm)
    if var_spec is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown variable: {var} (normalized={var_norm})",
        )

    if model != "hrrr":
        if model != "gfs":
            raise HTTPException(status_code=501, detail="Fetch not implemented for model")

    product = plugin.product

    if not var_spec.derived:
        fetch_var = _resolve_upstream_var(var_spec, var_spec.id)
        search = _select_search(var_spec.selectors)
        if model == "gfs":
            try:
                result = fetch_gfs_grib(
                    run=run,
                    fh=fh,
                    model=model,
                    product=product,
                    variable=fetch_var,
                    search_override=search,
                    cache_dir=cache_dir,
                    **kwargs,
                )
            except Exception as exc:
                if is_gfs_not_ready(exc):
                    return _not_ready(run, exc)
                raise
            run_id = _normalize_run_id(run, result.path)
            return FetchResult(
                upstream_run_id=run_id,
                is_full_download=result.is_full_file,
                grib_path=result.path,
                component_paths=None,
            )
        try:
            result = fetch_hrrr_grib(
                run=run,
                fh=fh,
                model=model,
                product=product,
                variable=fetch_var,
                search_override=search,
                cache_cfg=HRRRCacheConfig(base_dir=cache_dir, keep_runs=1) if cache_dir else None,
            )
        except Exception as exc:
            if is_upstream_not_ready(exc):
                return _not_ready(run, exc)
            raise
        run_id = _normalize_run_id(run, result.path)
        return FetchResult(
            upstream_run_id=run_id,
            is_full_download=result.is_full_file,
            grib_path=result.path,
            component_paths=None,
        )

    derive_kind = str(getattr(var_spec, "derive", "") or "")
    if derive_kind == "wspd10m":
        components = _resolve_component_vars(var_spec, ("10u", "10v"))
    elif derive_kind == "radar_ptype":
        components = _resolve_radar_component_vars(var_spec, ("refc", "crain"))
    else:
        raise HTTPException(
            status_code=501,
            detail=f"Derived variable fetch not implemented: {var_spec.id} ({derive_kind})",
        )

    component_paths: dict[str, Path] = {}
    any_full = False
    gfs_component_run = run
    for component_var in components:
        component_spec = plugin.get_var(component_var)
        search = _select_search(component_spec.selectors) if component_spec else None
        if model == "gfs":
            try:
                result = fetch_gfs_grib(
                    run=gfs_component_run,
                    fh=fh,
                    model=model,
                    product=product,
                    variable=component_var,
                    search_override=search,
                    cache_dir=cache_dir,
                    **kwargs,
                )
            except Exception as exc:
                if is_gfs_not_ready(exc):
                    known_path = next(iter(component_paths.values()), None)
                    return _not_ready(gfs_component_run, exc, known_path)
                raise
            component_paths[component_var] = result.path
            any_full = any_full or result.is_full_file
            if run.lower() == "latest":
                resolved_run = _normalize_run_id(run, result.path)
                gfs_component_run = _fetch_run_arg_from_run_id(resolved_run)
            continue
        try:
            result = fetch_hrrr_grib(
                run=run,
                fh=fh,
                model=model,
                product=product,
                variable=component_var,
                search_override=search,
                cache_cfg=HRRRCacheConfig(base_dir=cache_dir, keep_runs=1) if cache_dir else None,
            )
        except Exception as exc:
            if is_upstream_not_ready(exc):
                known_path = next(iter(component_paths.values()), None)
                return _not_ready(run, exc, known_path)
            raise
        component_paths[component_var] = result.path
        any_full = any_full or result.is_full_file
    run_id = _normalize_run_id(run, next(iter(component_paths.values())))
    return FetchResult(
        upstream_run_id=run_id,
        is_full_download=any_full,
        grib_path=None,
        component_paths=component_paths,
    )
