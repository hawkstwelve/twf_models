from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import os
import re

from fastapi import HTTPException

from app.models import get_model
from app.services.gfs_fetch import fetch_gfs_grib
from app.services.hrrr_fetch import fetch_hrrr_grib
from app.services.hrrr_runs import HRRRCacheConfig
from app.services.upstream import is_upstream_not_ready_error

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchResult:
    upstream_run_id: str
    is_full_download: bool
    not_ready_reason: str | None = None
    grib_path: Path | None = None
    component_paths: dict[str, Path] | None = None


def is_not_ready_message(text: str) -> bool:
    return is_upstream_not_ready_error(text)


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


def _fetch_path_or_raise(result: object, *, context: str) -> Path:
    path = getattr(result, "path", None)
    if path is None:
        raise RuntimeError(f"{context} returned no GRIB path")
    return Path(path)


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


def _resolve_radar_blend_component_vars(
    var_spec: object,
    fallback: tuple[str, str, str, str, str],
) -> tuple[str, str, str, str, str]:
    selectors = getattr(var_spec, "selectors", None)
    if selectors is None:
        return fallback
    refl = _hint_value(selectors, "refl_component")
    rain = _hint_value(selectors, "rain_component")
    snow = _hint_value(selectors, "snow_component")
    sleet = _hint_value(selectors, "sleet_component")
    frzr = _hint_value(selectors, "frzr_component")
    values = (refl, rain, snow, sleet, frzr)
    if all(values):
        return values  # type: ignore[return-value]
    return fallback


def _resolve_precip_ptype_component_vars(
    var_spec: object,
    fallback: tuple[str, str, str, str, str],
) -> tuple[str, str, str, str, str]:
    selectors = getattr(var_spec, "selectors", None)
    if selectors is None:
        return fallback
    prate = _hint_value(selectors, "prate_component")
    rain = _hint_value(selectors, "rain_component")
    snow = _hint_value(selectors, "snow_component")
    sleet = _hint_value(selectors, "sleet_component")
    frzr = _hint_value(selectors, "frzr_component")
    values = (prate, rain, snow, sleet, frzr)
    if all(values):
        return values  # type: ignore[return-value]
    return fallback


def _use_hrrr_shared_source() -> bool:
    # Backward compatible:
    # - new flag: TWF_HRRR_SUBSET_BUNDLE_PER_HOUR
    # - legacy flag: TWF_HRRR_SHARED_SOURCE_PER_HOUR
    raw = os.environ.get(
        "TWF_HRRR_SUBSET_BUNDLE_PER_HOUR",
        os.environ.get("TWF_HRRR_SHARED_SOURCE_PER_HOUR", "1"),
    ).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _use_gfs_shared_source() -> bool:
    raw = os.environ.get("TWF_GFS_SUBSET_BUNDLE_PER_HOUR", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _join_search_terms(terms: list[str]) -> str | None:
    seen: set[str] = set()
    ordered: list[str] = []
    for term in terms:
        term = term.strip()
        if not term or term in seen:
            continue
        seen.add(term)
        ordered.append(term)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    return "|".join(ordered)


def _supports_radar_ptype(plugin: object) -> bool:
    getter = getattr(plugin, "get_var", None)
    if not callable(getter):
        return False
    try:
        return getter("radar_ptype") is not None
    except Exception:
        return False


def _resolve_hrrr_subset_bundle(
    plugin: object,
    *,
    var_norm: str,
    var_spec: object,
) -> tuple[str, str | None, str, list[str]]:
    # Stable bundle keys per run+fh prevent cache cross-wiring while still reusing
    # a single subset source for related variables in that hour.
    if var_norm == "tmp2m":
        tmp_spec = plugin.get_var("tmp2m") or var_spec
        return (
            "tmp2m",
            _select_search(tmp_spec.selectors),
            "tmp2m",
            ["tmp2m"],
        )

    if var_norm in {"10u", "10v", "wspd10m"} or str(getattr(var_spec, "derive", "") or "") == "wspd10m":
        wspd_spec = plugin.get_var("wspd10m") or var_spec
        u_var, v_var = _resolve_component_vars(wspd_spec, ("10u", "10v"))
        search_terms: list[str] = []
        for comp in (u_var, v_var):
            comp_spec = plugin.get_var(comp)
            if comp_spec is not None:
                comp_search = _select_search(comp_spec.selectors)
                if comp_search:
                    search_terms.append(comp_search)
        required = [u_var, v_var] if var_norm == "wspd10m" else [var_norm]
        return ("wspd10m", _join_search_terms(search_terms), var_norm, required)

    radar_components = ("refc", "crain", "csnow", "cicep", "cfrzr")
    if _supports_radar_ptype(plugin) and (
        var_norm in set(radar_components) | {"radar_ptype"}
        or str(getattr(var_spec, "derive", "") or "") == "radar_ptype_combo"
    ):
        radar_spec = plugin.get_var("radar_ptype") or var_spec
        refl_var, rain_var, snow_var, sleet_var, frzr_var = _resolve_radar_blend_component_vars(
            radar_spec,
            radar_components,
        )
        comps = [refl_var, rain_var, snow_var, sleet_var, frzr_var]
        search_terms = []
        for comp in comps:
            comp_spec = plugin.get_var(comp)
            if comp_spec is not None:
                comp_search = _select_search(comp_spec.selectors)
                if comp_search:
                    search_terms.append(comp_search)
        required = comps if var_norm == "radar_ptype" else [var_norm]
        return ("radar_ptype", _join_search_terms(search_terms), var_norm, required)

    return (var_norm, _select_search(var_spec.selectors), var_norm, [var_norm])


def _resolve_gfs_subset_bundle(
    plugin: object,
    *,
    var_norm: str,
    var_spec: object,
) -> tuple[str, str | None, str, list[str]]:
    # Deterministic bundle keys per run+fh for GFS subsets.
    if var_norm == "tmp2m":
        tmp_spec = plugin.get_var("tmp2m") or var_spec
        return (
            "tmp2m",
            _select_search(tmp_spec.selectors),
            "tmp2m",
            ["tmp2m"],
        )

    if var_norm in {"10u", "10v", "wspd10m"} or str(getattr(var_spec, "derive", "") or "") == "wspd10m":
        wspd_spec = plugin.get_var("wspd10m") or var_spec
        u_var, v_var = _resolve_component_vars(wspd_spec, ("10u", "10v"))
        search_terms: list[str] = []
        for comp in (u_var, v_var):
            comp_spec = plugin.get_var(comp)
            if comp_spec is not None:
                comp_search = _select_search(comp_spec.selectors)
                if comp_search:
                    search_terms.append(comp_search)
        required = [u_var, v_var] if var_norm == "wspd10m" else [var_norm]
        return ("wspd10m", _join_search_terms(search_terms), var_norm, required)

    if var_norm == "precip_ptype" or str(getattr(var_spec, "derive", "") or "") == "precip_ptype_blend":
        precip_spec = plugin.get_var("precip_ptype") or var_spec
        prate_var, rain_var, snow_var, sleet_var, frzr_var = _resolve_precip_ptype_component_vars(
            precip_spec,
            ("precip_ptype", "crain", "csnow", "cicep", "cfrzr"),
        )
        comps = [prate_var, rain_var, snow_var, sleet_var, frzr_var]
        search_terms = []
        for comp in comps:
            comp_spec = plugin.get_var(comp)
            if comp_spec is not None:
                comp_search = _select_search(comp_spec.selectors)
                if comp_search:
                    search_terms.append(comp_search)
        return ("precip_ptype", _join_search_terms(search_terms), var_norm, comps)

    radar_components = ("refc", "crain", "csnow", "cicep", "cfrzr")
    if _supports_radar_ptype(plugin) and (
        var_norm in set(radar_components) | {"radar_ptype"}
        or str(getattr(var_spec, "derive", "") or "") == "radar_ptype_combo"
    ):
        radar_spec = plugin.get_var("radar_ptype") or var_spec
        refl_var, rain_var, snow_var, sleet_var, frzr_var = _resolve_radar_blend_component_vars(
            radar_spec,
            radar_components,
        )
        comps = [refl_var, rain_var, snow_var, sleet_var, frzr_var]
        search_terms = []
        for comp in comps:
            comp_spec = plugin.get_var(comp)
            if comp_spec is not None:
                comp_search = _select_search(comp_spec.selectors)
                if comp_search:
                    search_terms.append(comp_search)
        required = comps if var_norm == "radar_ptype" else [var_norm]
        return ("radar_ptype", _join_search_terms(search_terms), var_norm, required)

    return (var_norm, _select_search(var_spec.selectors), var_norm, [var_norm])


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

    # HRRR shared-source mode (subset bundles): one canonical subset GRIB per run+fh
    # per bundle key, then select variable(s) at build time.
    if model == "hrrr" and _use_hrrr_shared_source():
        bundle_key, bundle_search, fetch_var, required_vars = _resolve_hrrr_subset_bundle(
            plugin,
            var_norm=var_norm,
            var_spec=var_spec,
        )
        try:
            result = fetch_hrrr_grib(
                run=run,
                fh=fh,
                model=model,
                product=product,
                variable=fetch_var,
                search_override=bundle_search,
                cache_key=bundle_key,
                required_vars=required_vars,
                cache_cfg=HRRRCacheConfig(base_dir=cache_dir, keep_runs=1) if cache_dir else None,
            )
        except Exception as exc:
            if is_upstream_not_ready_error(exc):
                return _not_ready(run, exc)
            raise
        not_ready_reason = getattr(result, "not_ready_reason", None)
        if not_ready_reason:
            return _not_ready(run, not_ready_reason)
        path = _fetch_path_or_raise(result, context="HRRR fetch")
        run_id = _normalize_run_id(run, path)
        return FetchResult(
            upstream_run_id=run_id,
            is_full_download=result.is_full_file,
            grib_path=path,
            component_paths=None,
        )

    # GFS shared-source mode (subset bundles): one canonical subset GRIB per run+fh
    # per bundle key, then select variable(s) at build time.
    if model == "gfs" and _use_gfs_shared_source():
        bundle_key, bundle_search, fetch_var, required_vars = _resolve_gfs_subset_bundle(
            plugin,
            var_norm=var_norm,
            var_spec=var_spec,
        )
        try:
            result = fetch_gfs_grib(
                run=run,
                fh=fh,
                model=model,
                product=product,
                variable=fetch_var,
                search_override=bundle_search,
                cache_key=bundle_key,
                required_vars=required_vars,
                cache_dir=cache_dir,
                **kwargs,
            )
        except Exception as exc:
            if is_upstream_not_ready_error(exc):
                return _not_ready(run, exc)
            raise
        not_ready_reason = getattr(result, "not_ready_reason", None)
        if not_ready_reason:
            return _not_ready(run, not_ready_reason)
        path = _fetch_path_or_raise(result, context="GFS fetch")
        run_id = _normalize_run_id(run, path)
        return FetchResult(
            upstream_run_id=run_id,
            is_full_download=result.is_full_file,
            grib_path=path,
            component_paths=None,
        )

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
                if is_upstream_not_ready_error(exc):
                    return _not_ready(run, exc)
                raise
            not_ready_reason = getattr(result, "not_ready_reason", None)
            if not_ready_reason:
                return _not_ready(run, not_ready_reason)
            path = _fetch_path_or_raise(result, context="GFS fetch")
            run_id = _normalize_run_id(run, path)
            return FetchResult(
                upstream_run_id=run_id,
                is_full_download=result.is_full_file,
                grib_path=path,
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
            if is_upstream_not_ready_error(exc):
                return _not_ready(run, exc)
            raise
        not_ready_reason = getattr(result, "not_ready_reason", None)
        if not_ready_reason:
            return _not_ready(run, not_ready_reason)
        path = _fetch_path_or_raise(result, context="HRRR fetch")
        run_id = _normalize_run_id(run, path)
        return FetchResult(
            upstream_run_id=run_id,
            is_full_download=result.is_full_file,
            grib_path=path,
            component_paths=None,
        )

    derive_kind = str(getattr(var_spec, "derive", "") or "")
    if derive_kind == "wspd10m":
        components = _resolve_component_vars(var_spec, ("10u", "10v"))
    elif model == "gfs" and derive_kind == "precip_ptype_blend":
        components = _resolve_precip_ptype_component_vars(
            var_spec,
            ("precip_ptype", "crain", "csnow", "cicep", "cfrzr"),
        )
    elif model == "hrrr" and derive_kind == "radar_ptype_combo":
        components = _resolve_radar_blend_component_vars(
            var_spec,
            ("refc", "crain", "csnow", "cicep", "cfrzr"),
        )
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
                if is_upstream_not_ready_error(exc):
                    known_path = next(iter(component_paths.values()), None)
                    return _not_ready(gfs_component_run, exc, known_path)
                raise
            not_ready_reason = getattr(result, "not_ready_reason", None)
            if not_ready_reason:
                known_path = next(iter(component_paths.values()), None)
                return _not_ready(gfs_component_run, not_ready_reason, known_path)
            path = _fetch_path_or_raise(result, context="GFS component fetch")
            component_paths[component_var] = path
            any_full = any_full or result.is_full_file
            if run.lower() == "latest":
                resolved_run = _normalize_run_id(run, path)
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
            if is_upstream_not_ready_error(exc):
                known_path = next(iter(component_paths.values()), None)
                return _not_ready(run, exc, known_path)
            raise
        not_ready_reason = getattr(result, "not_ready_reason", None)
        if not_ready_reason:
            known_path = next(iter(component_paths.values()), None)
            return _not_ready(run, not_ready_reason, known_path)
        path = _fetch_path_or_raise(result, context="HRRR component fetch")
        component_paths[component_var] = path
        any_full = any_full or result.is_full_file
    run_id = _normalize_run_id(run, next(iter(component_paths.values())))
    return FetchResult(
        upstream_run_id=run_id,
        is_full_download=any_full,
        grib_path=None,
        component_paths=component_paths,
    )
