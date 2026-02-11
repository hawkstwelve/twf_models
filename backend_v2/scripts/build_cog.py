from __future__ import annotations

import argparse
import os
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape

# Add backend_v2 to path so app module can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))

import numpy as np
import pyproj
import xarray as xr
from pyproj import CRS, Transformer

from app.models import ModelPlugin, VarSpec, get_model
from app.services.colormaps_v2 import PRECIP_CONFIG, RADAR_CONFIG, VAR_SPECS
from app.services.fetch_engine import fetch_grib
from app.services.grid import detect_latlon_names, normalize_latlon_coords
from app.services.upstream import is_upstream_not_ready_error

EPS = 1e-9
logger = logging.getLogger(__name__)
TWF_REFC_MAX_DBZ = float(os.environ.get("TWF_REFC_MAX_DBZ", "0"))
TWF_RADAR_PTYPE_DEBUG = os.environ.get("TWF_RADAR_PTYPE_DEBUG", "0").strip() == "1"
TWF_GFS_RADAR_DEBUG = os.environ.get("TWF_GFS_RADAR_DEBUG", "0").strip() == "1"
GFS_RADAR_PTYPE_REFL_MIN_DBZ = float(os.environ.get("TWF_GFS_RADAR_PTYPE_REFL_MIN_DBZ", "0"))
GFS_RADAR_PTYPE_FOOTPRINT_MIN_DBZ = float(
    os.environ.get("TWF_GFS_RADAR_PTYPE_FOOTPRINT_MIN_DBZ", "0")
)
RUN_RE = re.compile(r"^\d{8}_\d{2}z$")
TARGET_GRID_METERS_BY_MODEL_REGION: dict[tuple[str, str], tuple[float, float]] = {
    ("hrrr", "pnw"): (3000.0, 3000.0),
    ("gfs", "pnw"): (25000.0, 25000.0),
    ("gfs", "conus"): (25000.0, 25000.0),
    # Future-facing defaults for planned ECMWF support; tune once product is finalized.
    ("ecmwf", "pnw"): (9000.0, 9000.0),
    ("ecmwf", "conus"): (9000.0, 9000.0),
}


class UpstreamNotReadyError(RuntimeError):
    pass


def get_plugin_and_var(model_id: str, var_id: str) -> tuple[ModelPlugin, VarSpec]:
    try:
        plugin = get_model(model_id)
    except Exception as exc:
        raise RuntimeError(f"Unknown model: {model_id}") from exc
    var_spec = plugin.get_var(var_id)
    if var_spec is None:
        raise RuntimeError(f"Unknown variable: {var_id}")
    return plugin, var_spec


def _delete_cfgrib_index_files(grib_path: Path) -> None:
    try:
        parent = grib_path.parent
        for idx_file in parent.glob(grib_path.name + ".*.idx"):
            try:
                idx_file.unlink()
            except OSError:
                pass
        direct_idx = grib_path.with_suffix(grib_path.suffix + ".idx")
        if direct_idx.exists():
            try:
                direct_idx.unlink()
            except OSError:
                pass
    except Exception:
        pass


def _cleanup_upstream_grib_paths(paths: Iterable[Path | None]) -> None:
    for path in paths:
        if path is None:
            continue
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        _delete_cfgrib_index_files(path)


def _collect_fill_values(da: xr.DataArray) -> list[float]:
    candidates: list[float] = []
    for source in (da.attrs, getattr(da, "encoding", {}) or {}):
        for key in ("_FillValue", "missing_value", "GRIB_missingValue", "GRIB_missingValueAtSea"):
            if key not in source:
                continue
            value = source.get(key)
            if isinstance(value, (list, tuple, np.ndarray)):
                for item in value:
                    try:
                        num = float(item)
                    except (TypeError, ValueError):
                        continue
                    if np.isfinite(num):
                        candidates.append(num)
            else:
                try:
                    num = float(value)
                except (TypeError, ValueError):
                    continue
                if np.isfinite(num):
                    candidates.append(num)
    return candidates


def _cfgrib_filter_keys(var_spec: VarSpec | None) -> dict:
    if var_spec is None:
        return {}
    selectors = var_spec.selectors
    if not selectors.filter_by_keys:
        return {}
    filter_keys: dict[str, object] = {}
    for key, value in selectors.filter_by_keys.items():
        if key == "level":
            try:
                filter_keys[key] = int(value)
            except (TypeError, ValueError):
                filter_keys[key] = value
        else:
            filter_keys[key] = value
    return filter_keys


def _open_cfgrib_dataset_strict(path: Path, var_spec: VarSpec | None) -> xr.Dataset:
    """Strict cfgrib open.

    If selector filters exist, all attempts must honor those filters. This avoids
    broad-open fallback choosing a wrong field when mixed GRIB messages exist.
    """
    base_filter_keys = _cfgrib_filter_keys(var_spec)
    retry_filters: list[dict[str, object]] = []
    if base_filter_keys:
        retry_filters.append(dict(base_filter_keys))
        if "stepType" not in base_filter_keys:
            retry_filters.append({**base_filter_keys, "stepType": "instant"})
            retry_filters.append({**base_filter_keys, "stepType": "avg"})

    last_exc: Exception | None = None
    for filter_keys in retry_filters:
        try:
            return xr.open_dataset(
                path,
                engine="cfgrib",
                backend_kwargs={"filter_by_keys": filter_keys, "indexpath": ""},
            )
        except Exception as exc:  # pragma: no cover - retry path
            if is_upstream_not_ready_error(exc):
                raise UpstreamNotReadyError(str(exc)) from exc
            last_exc = exc
            continue

    if retry_filters:
        assert last_exc is not None
        raise RuntimeError(
            f"Failed strict cfgrib open for path={path} filters={retry_filters}: "
            f"{type(last_exc).__name__}: {last_exc}"
        ) from last_exc

    return _open_cfgrib_dataset(path, var_spec)


def _normalize_lon_1d(lon: np.ndarray) -> np.ndarray:
    return ((lon + 180.0) % 360.0) - 180.0


def _infer_spacing(values: np.ndarray, *, axis_name: str) -> float:
    if values.ndim != 1 or values.size < 2:
        raise ValueError(f"{axis_name} must be 1D with at least 2 values")
    diffs = np.diff(values.astype(np.float64))
    abs_diffs = np.abs(diffs[np.isfinite(diffs)])
    if abs_diffs.size == 0:
        raise ValueError(f"Could not infer {axis_name} spacing")
    spacing = float(np.median(abs_diffs))
    if spacing <= 0:
        raise ValueError(f"Invalid non-positive {axis_name} spacing: {spacing}")
    return spacing


def _normalize_latlon_dataarray(da: xr.DataArray) -> tuple[xr.DataArray, str, str]:
    lat_name, lon_name = detect_latlon_names(da)

    lat = da.coords[lat_name].values
    lon = da.coords[lon_name].values
    if lat.ndim != 1 or lon.ndim != 1:
        raise ValueError("Expected 1D latitude/longitude coordinates")

    lon_wrapped = _normalize_lon_1d(lon)
    da = da.assign_coords({lon_name: (da.coords[lon_name].dims, lon_wrapped)})
    da = da.sortby(lon_name)

    lat_sorted = da.coords[lat_name].values
    if lat_sorted[0] < lat_sorted[-1]:
        da = da.sortby(lat_name, ascending=False)

    return da, lat_name, lon_name


def _derive_run_id(path: Path) -> str:
    try:
        day = path.parent.parent.name
        hour = path.parent.name
    except Exception as exc:
        raise RuntimeError(f"Could not derive run_id from path: {path}") from exc
    run_id = f"{day}_{hour}z"
    if not RUN_RE.match(run_id):
        raise RuntimeError(f"Derived invalid run_id={run_id} from path={path}")
    return run_id


def _coerce_run_id(run_id: str | None, path: Path) -> str:
    if run_id and run_id != "unknown" and RUN_RE.match(run_id):
        return run_id
    return _derive_run_id(path)


def _parse_target_grid_override(value: str) -> tuple[float, float]:
    raw = value.strip()
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) == 1:
        res = float(parts[0])
        if res <= 0:
            raise ValueError("grid resolution must be > 0")
        return res, res
    if len(parts) == 2:
        xres = float(parts[0])
        yres = float(parts[1])
        if xres <= 0 or yres <= 0:
            raise ValueError("grid resolution must be > 0")
        return xres, yres
    raise ValueError("Expected one or two comma-separated numbers for TWF_TARGET_GRID_METERS")


def resolve_target_grid_meters(model_id: str, region_id: str) -> tuple[float, float]:
    model_key = model_id.strip().lower()
    region_key = region_id.strip().lower()

    global_override = os.environ.get("TWF_TARGET_GRID_METERS", "").strip()
    if global_override:
        return _parse_target_grid_override(global_override)

    model_region_env = f"TWF_TARGET_GRID_METERS_{model_key.upper()}_{region_key.upper()}"
    model_region_override = os.environ.get(model_region_env, "").strip()
    if model_region_override:
        return _parse_target_grid_override(model_region_override)

    model_env = f"TWF_TARGET_GRID_METERS_{model_key.upper()}"
    model_override = os.environ.get(model_env, "").strip()
    if model_override:
        return _parse_target_grid_override(model_override)

    key = (model_key, region_key)
    if key not in TARGET_GRID_METERS_BY_MODEL_REGION:
        known = ", ".join(
            sorted(f"{model}:{region}" for model, region in TARGET_GRID_METERS_BY_MODEL_REGION.keys())
        )
        raise RuntimeError(
            f"No target grid configured for model='{model_id}' region='{region_id}'. "
            f"Known model+region keys: {known}. "
            "Set TWF_TARGET_GRID_METERS (global) or model/model+region overrides."
        )
    return TARGET_GRID_METERS_BY_MODEL_REGION[key]


def _is_discrete(var: str, meta: dict) -> bool:
    var_key = str(var or "").strip().lower()
    if str(meta.get("kind", "")).strip().lower() == "discrete":
        return True
    return var_key in {"radar_ptype", "ptype", "radar", "radar_ptype_combo", "precip_ptype"}


def _warp_tr_meters(model: str, var: str, meta: dict) -> tuple[float, float] | None:
    model_key = str(model or "").strip().lower()
    if model_key == "gfs":
        return (20000.0, 20000.0)
    return None


def _major_from_version_text(version_text: str) -> int:
    match = re.search(r"(\d+)\.", version_text)
    if not match:
        raise RuntimeError(f"Unable to parse version text: {version_text}")
    return int(match.group(1))


def assert_gdal_proj_version_pins() -> None:
    expected_gdal_major = os.environ.get("TWF_EXPECT_GDAL_MAJOR", "").strip()
    expected_proj_major = os.environ.get("TWF_EXPECT_PROJ_MAJOR", "").strip()
    if not expected_gdal_major and not expected_proj_major:
        return

    if expected_gdal_major:
        require_gdal("gdalinfo")
        gdal_version_output = run_cmd_output(["gdalinfo", "--version"]).strip()
        gdal_major = _major_from_version_text(gdal_version_output)
        if gdal_major != int(expected_gdal_major):
            raise RuntimeError(
                f"GDAL major mismatch: expected={expected_gdal_major} actual={gdal_major} "
                f"raw='{gdal_version_output}'"
            )

    if expected_proj_major:
        proj_version = str(getattr(pyproj, "__proj_version__", "") or "").strip()
        if not proj_version:
            raise RuntimeError("Unable to read PROJ version from pyproj")
        proj_major = _major_from_version_text(proj_version)
        if proj_major != int(expected_proj_major):
            raise RuntimeError(
                f"PROJ major mismatch: expected={expected_proj_major} actual={proj_major} "
                f"raw='{proj_version}'"
            )

def _resolve_uv_paths(component_paths: dict[str, Path]) -> tuple[Path, Path]:
    # Key names can vary by model/plugin; prefer deterministic picks before fallback heuristics.
    u_path: Path | None = None
    v_path: Path | None = None
    key_map = {key.lower(): path for key, path in component_paths.items()}
    for key in ("10u", "u10"):
        if u_path is None and key in key_map:
            u_path = key_map[key]
    for key in ("10v", "v10"):
        if v_path is None and key in key_map:
            v_path = key_map[key]

    if u_path is None:
        for key, path in key_map.items():
            if "ugrd" in key:
                u_path = path
                break
    if v_path is None:
        for key, path in key_map.items():
            if "vgrd" in key:
                v_path = path
                break

    if u_path is None or v_path is None:
        for key, path in key_map.items():
            if u_path is None and key.endswith("u"):
                u_path = path
                continue
            if v_path is None and key.endswith("v"):
                v_path = path
    if u_path is None or v_path is None:
        paths = list(component_paths.values())
        if len(paths) >= 2:
            u_path = u_path or paths[0]
            v_path = v_path or paths[1]
    if u_path is None or v_path is None:
        raise RuntimeError("wspd10m components missing u/v GRIB paths")
    return u_path, v_path


def _component_ids(var_spec: VarSpec) -> tuple[str, str]:
    selectors = var_spec.selectors
    u_key = selectors.hints.get("u_component") or selectors.hints.get("u_var")
    v_key = selectors.hints.get("v_component") or selectors.hints.get("v_var")
    if u_key and v_key:
        return u_key, v_key
    return "10u", "10v"


def _radar_blend_component_ids(var_spec: VarSpec) -> tuple[str, str, str, str, str]:
    selectors = var_spec.selectors
    refl_key = selectors.hints.get("refl_component") or "refc"
    rain_key = selectors.hints.get("rain_component") or "crain"
    snow_key = selectors.hints.get("snow_component") or "csnow"
    sleet_key = selectors.hints.get("sleet_component") or "cicep"
    frzr_key = selectors.hints.get("frzr_component") or "cfrzr"
    return (
        str(refl_key),
        str(rain_key),
        str(snow_key),
        str(sleet_key),
        str(frzr_key),
    )


def _precip_ptype_component_ids(var_spec: VarSpec) -> tuple[str, str, str, str, str]:
    selectors = var_spec.selectors
    prate_key = selectors.hints.get("prate_component") or "prate"
    rain_key = selectors.hints.get("rain_component") or "crain"
    snow_key = selectors.hints.get("snow_component") or "csnow"
    sleet_key = selectors.hints.get("sleet_component") or "cicep"
    frzr_key = selectors.hints.get("frzr_component") or "cfrzr"
    return (
        str(prate_key),
        str(rain_key),
        str(snow_key),
        str(sleet_key),
        str(frzr_key),
    )


def _resolve_radar_blend_component_paths(
    component_paths: dict[str, Path],
    *,
    refl_key: str,
    rain_key: str,
    snow_key: str,
    sleet_key: str,
    frzr_key: str,
) -> tuple[Path, Path, Path, Path, Path]:
    resolved: list[Path] = []
    expected = [refl_key, rain_key, snow_key, sleet_key, frzr_key]
    for key in expected:
        path = component_paths.get(key)
        if path is None:
            available = sorted(component_paths.keys())
            raise RuntimeError(
                f"Missing radar_ptype_combo component file: expected={key} have={available}"
            )
        resolved.append(path)
    return tuple(resolved)  # type: ignore[return-value]


def _resolve_precip_ptype_component_paths(
    component_paths: dict[str, Path],
    *,
    prate_key: str,
    rain_key: str,
    snow_key: str,
    sleet_key: str,
    frzr_key: str,
) -> tuple[Path, Path, Path, Path, Path]:
    resolved: list[Path] = []
    expected = [prate_key, rain_key, snow_key, sleet_key, frzr_key]
    for key in expected:
        path = component_paths.get(key)
        if path is None:
            available = sorted(component_paths.keys())
            raise RuntimeError(
                f"Missing precip_ptype component file: expected={key} have={available}"
            )
        resolved.append(path)
    return tuple(resolved)  # type: ignore[return-value]


def _coerce_grib_path(grib_path: object) -> Path:
    if hasattr(grib_path, "path"):
        grib_path = getattr(grib_path, "path")
    return Path(os.fspath(grib_path))


def _open_cfgrib_dataset(grib_path: object, var_spec: VarSpec | None) -> xr.Dataset:
    path = _coerce_grib_path(grib_path)
    base_filter_keys = _cfgrib_filter_keys(var_spec)
    retry_filters: list[dict[str, object]] = []
    if base_filter_keys:
        retry_filters.append(dict(base_filter_keys))
        if "stepType" not in base_filter_keys:
            # Some fields are published with both instant/avg; try both deterministically.
            retry_filters.append({**base_filter_keys, "stepType": "instant"})
            retry_filters.append({**base_filter_keys, "stepType": "avg"})

    # If we know the target variable, do not broad-open first. Broad opens on full HRRR
    # files can "succeed" with the wrong variable while logging many skipped fields.
    for filter_keys in retry_filters:
        try:
            return xr.open_dataset(
                path,
                engine="cfgrib",
                backend_kwargs={"filter_by_keys": filter_keys, "indexpath": ""},
            )
        except Exception as exc:
            if is_upstream_not_ready_error(exc):
                raise UpstreamNotReadyError(str(exc)) from exc
            continue

    # Fallback for paths/vars where no filter keys are available.
    try:
        return xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    except Exception as exc:
        if is_upstream_not_ready_error(exc):
            raise UpstreamNotReadyError(str(exc)) from exc
        message = str(exc)
        retry_on_multi_key = "multiple values for key" in message or "multiple values for unique key" in message
        retry_on_type_hint = "typeOfLevel" in message
        if (retry_on_multi_key or retry_on_type_hint) and not retry_filters:
            for step_type in ("instant", "avg"):
                try:
                    return xr.open_dataset(
                        path,
                        engine="cfgrib",
                        backend_kwargs={"filter_by_keys": {"stepType": step_type}, "indexpath": ""},
                    )
                except Exception as inner_exc:
                    if is_upstream_not_ready_error(inner_exc):
                        raise UpstreamNotReadyError(str(inner_exc)) from inner_exc
                    continue
        raise


def _open_gfs_precip_ptype_component_optional(
    *,
    plugin: ModelPlugin,
    component_id: str,
    source_path: Path | None,
) -> xr.DataArray | None:
    if source_path is None:
        return None
    component_spec = plugin.get_var(component_id)
    try:
        ds = _open_cfgrib_dataset_strict(source_path, component_spec)
        if len(getattr(ds, "data_vars", {})) == 0:
            return None
        selected = plugin.select_dataarray(ds, component_id)
    except Exception:
        return None
    if "time" in selected.dims:
        selected = selected.isel(time=0)
    selected = selected.squeeze()
    if selected.ndim != 2 or selected.shape[0] == 0 or selected.shape[1] == 0:
        return None
    return selected


def _encode_with_nodata(
    values: np.ndarray,
    *,
    requested_var: str,
    normalized_var: str,
    da: xr.DataArray,
    allow_range_fallback: bool,
    fallback_percentiles: tuple[float, float] = (2.0, 98.0),
) -> tuple[np.ndarray, np.ndarray, dict, np.ndarray, dict, str]:
    spec_key = requested_var if requested_var in VAR_SPECS else normalized_var
    spec = VAR_SPECS.get(spec_key, {})
    kind = spec.get("type", "continuous")
    spec_units = spec.get("units")
    fill_values = _collect_fill_values(da)

    valid_mask = np.isfinite(values)
    for fill_value in fill_values:
        valid_mask &= values != fill_value

    if spec_units == "F":
        values = (values - 273.15) * (9.0 / 5.0) + 32.0

    valid_values = values[valid_mask]
    if valid_values.size == 0:
        raise RuntimeError(f"No valid data found after masking for {requested_var}")

    if kind == "discrete":
        levels = spec.get("levels") or []
        colors = spec.get("colors") or []
        if not levels or not colors:
            raise RuntimeError(f"Discrete spec missing levels/colors for {requested_var}")
        visible_mask = valid_mask & (values >= levels[0])
        bins = np.digitize(np.where(visible_mask, values, levels[0]), levels, right=False) - 1
        bins = np.clip(bins, 0, len(colors) - 1).astype(np.uint8)
        byte_band = bins.astype(np.uint8)
        byte_band[~visible_mask] = 255
        alpha = np.where(byte_band == 255, 0, 255).astype(np.uint8)
        meta = {
            "var_key": requested_var,
            "source_var": normalized_var,
            "spec_key": spec_key,
            "kind": "discrete",
            "units": spec.get("units"),
            "levels": list(levels),
            "colors": list(colors),
        }
        stats = {
            "vmin": float(np.nanmin(valid_values)),
            "vmax": float(np.nanmax(valid_values)),
        }
        return byte_band, alpha, meta, valid_mask, stats, spec_key

    range_vals = spec.get("range")
    range_source = "spec"
    range_percentiles = None
    if range_vals and len(range_vals) == 2:
        vmin, vmax = float(range_vals[0]), float(range_vals[1])
    else:
        if not allow_range_fallback:
            raise RuntimeError(
                f"Missing fixed range for continuous var '{requested_var}'. "
                "Add 'range' to VAR_SPECS or enable fallback explicitly."
            )
        p_low, p_high = fallback_percentiles
        if valid_values.size >= 10:
            vmin, vmax = np.nanpercentile(valid_values, [p_low, p_high])
        else:
            vmin, vmax = float(np.nanmin(valid_values)), float(np.nanmax(valid_values))
        if vmin == vmax:
            vmin -= 1.0
            vmax += 1.0
        range_source = "fallback_percentile"
        range_percentiles = [float(p_low), float(p_high)]

    scaled = np.clip(np.rint((values - vmin) / (vmax - vmin) * 254.0), 0, 254).astype(np.uint8)
    byte_band = scaled
    byte_band[~valid_mask] = 255
    alpha = np.where(byte_band == 255, 0, 255).astype(np.uint8)
    meta = {
        "var_key": requested_var,
        "source_var": normalized_var,
        "spec_key": spec_key,
        "kind": "continuous",
        "units": spec.get("units"),
        "range": [float(vmin), float(vmax)],
        "range_source": range_source,
        "range_percentiles": range_percentiles,
        "colors": list(spec.get("colors", [])),
    }
    stats = {
        "vmin": float(np.nanmin(valid_values)),
        "vmax": float(np.nanmax(valid_values)),
        "scale_min": float(vmin),
        "scale_max": float(vmax),
    }
    return byte_band, alpha, meta, valid_mask, stats, spec_key


def _encode_radar_ptype_combo(
    *,
    requested_var: str,
    normalized_var: str,
    refl_values: np.ndarray,
    ptype_values: dict[str, np.ndarray],
    refl_min_dbz: float | None = None,
    footprint_min_dbz: float = 15.0,
) -> tuple[np.ndarray, np.ndarray, dict]:
    if refl_values.ndim != 2:
        raise RuntimeError(f"Expected 2D reflectivity array, got shape={refl_values.shape}")
    for key, values in ptype_values.items():
        if values.shape != refl_values.shape:
            raise RuntimeError(
                f"P-type component shape mismatch for {key}: refl={refl_values.shape} ptype={values.shape}"
            )

    type_order = ("rain", "snow", "sleet", "frzr")
    type_to_component = {
        "rain": "crain",
        "snow": "csnow",
        "sleet": "cicep",
        "frzr": "cfrzr",
    }

    byte_band = np.full(refl_values.shape, 255, dtype=np.uint8)
    alpha = np.zeros(refl_values.shape, dtype=np.uint8)
    refl = np.asarray(refl_values, dtype=np.float32)
    refl = np.where(np.isfinite(refl), refl, np.nan)
    total_count = int(refl.size)

    flat_colors: list[str] = []
    breaks: dict[str, dict[str, int]] = {}
    color_offset = 0
    for ptype in type_order:
        cfg = RADAR_CONFIG[ptype]
        colors = list(cfg["colors"])
        breaks[ptype] = {"offset": color_offset, "count": len(colors)}
        flat_colors.extend(colors)
        color_offset += len(colors)

    ptype_scale: dict[str, str] = {}

    # Sanitize p-type components and resolve dominant type.
    stack = []
    for ptype in type_order:
        comp_key = type_to_component[ptype]
        comp_vals = np.asarray(ptype_values[comp_key], dtype=np.float32)
        comp_vals = np.where(np.isfinite(comp_vals), comp_vals, 0.0)
        # Some upstream fields can be encoded as percent (0..100) instead of fraction (0..1).
        max_val = float(np.max(comp_vals)) if comp_vals.size else 0.0
        if max_val > 1.01 and max_val <= 100.0:
            comp_vals = comp_vals / 100.0
            ptype_scale[ptype] = "percent_to_fraction"
        else:
            ptype_scale[ptype] = "fraction"
        comp_vals = np.where((comp_vals >= 0.0) & (comp_vals <= 1.0), comp_vals, 0.0)
        stack.append(comp_vals)

    mask_stack = np.stack(stack, axis=0)

    # Binary categorical masks (0/1) should use a higher confidence cutoff.
    binary_like = True
    for channel in mask_stack:
        is_zero_or_one = np.isclose(channel, 0.0, atol=1e-6) | np.isclose(channel, 1.0, atol=1e-6)
        if not bool(np.all(is_zero_or_one)):
            binary_like = False
            break
    type_thresh = 0.5 if binary_like else 0.1

    max_conf = np.max(mask_stack, axis=0)
    winner_idx = np.argmax(mask_stack, axis=0)
    has_type_info = max_conf >= type_thresh
    idx_map = {ptype: idx for idx, ptype in enumerate(type_order)}

    # Fresh approach:
    # 1) Preserve standalone refc footprint/intensity exactly for visibility.
    # 2) Recolor that visible footprint by p-type (fallback to rain where type is unknown).
    rain_levels = list(RADAR_CONFIG["rain"]["levels"])
    default_refl_min_dbz = float(rain_levels[1] if len(rain_levels) > 1 else rain_levels[0])
    rain_min_dbz = float(default_refl_min_dbz if refl_min_dbz is None else refl_min_dbz)
    visible_mask = np.isfinite(refl) & (refl >= footprint_min_dbz)
    rain_colors = list(RADAR_CONFIG["rain"]["colors"])
    rain_offset = int(breaks["rain"]["offset"])
    if np.any(visible_mask):
        rain_bins = np.digitize(refl, rain_levels, right=False) - 1
        rain_bins = np.clip(rain_bins, 0, len(rain_colors) - 1).astype(np.uint8)
        byte_band[visible_mask] = (rain_offset + rain_bins[visible_mask]).astype(np.uint8)
        alpha[visible_mask] = 255

    recolor_counts: dict[str, int] = {}
    for ptype in ("snow", "sleet", "frzr"):
        cfg = RADAR_CONFIG[ptype]
        levels = list(cfg["levels"])
        colors = list(cfg["colors"])
        offset = int(breaks[ptype]["offset"])
        type_mask = visible_mask & has_type_info & (winner_idx == idx_map[ptype])
        if np.any(type_mask):
            bins = np.digitize(refl, levels, right=False) - 1
            bins = np.clip(bins, 0, len(colors) - 1).astype(np.uint8)
            byte_band[type_mask] = (offset + bins[type_mask]).astype(np.uint8)
        recolor_counts[ptype] = int(np.count_nonzero(type_mask))

    fallback_rain_count = int(np.count_nonzero(visible_mask & (~has_type_info)))

    meta = {
        "var_key": requested_var,
        "source_var": normalized_var,
        "spec_key": "radar_ptype",
        "kind": "discrete",
        "units": "dBZ",
        "colors": flat_colors,
        "ptype_order": list(type_order),
        "ptype_breaks": breaks,
        "ptype_levels": {key: list(RADAR_CONFIG[key]["levels"]) for key in type_order},
        "ptype_blend": "winner_argmax_threshold",
        "ptype_threshold": type_thresh,
        "refl_min_dbz": rain_min_dbz,
        "ptype_noinfo_fallback": "rain",
        "ptype_scale": ptype_scale,
        "visible_pixels": int(np.count_nonzero(visible_mask)),
        "fallback_rain_pixels": fallback_rain_count,
        "ptype_recolor_counts": recolor_counts,
    }
    if TWF_RADAR_PTYPE_DEBUG:
        logger.info(
            "radar_ptype_combo summary: visible=%s/%s fallback_rain=%s snow=%s sleet=%s frzr=%s threshold=%.2f binary_like=%s footprint_min_dbz=%.2f",
            meta["visible_pixels"],
            total_count,
            fallback_rain_count,
            recolor_counts.get("snow", 0),
            recolor_counts.get("sleet", 0),
            recolor_counts.get("frzr", 0),
            type_thresh,
            binary_like,
            footprint_min_dbz,
        )
    return byte_band, alpha, meta


def _encode_precip_ptype_blend(
    *,
    requested_var: str,
    normalized_var: str,
    prate_values: np.ndarray,
    ptype_values: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, dict]:
    if prate_values.ndim != 2:
        raise RuntimeError(f"Expected 2D PRATE array, got shape={prate_values.shape}")
    for key, values in ptype_values.items():
        if values.shape != prate_values.shape:
            raise RuntimeError(
                f"P-type component shape mismatch for {key}: prate={prate_values.shape} ptype={values.shape}"
            )

    spec = VAR_SPECS.get("precip_ptype", {})

    # Tie-break priority (highest to lowest): frzr > sleet > snow > rain.
    ptype_order = ("frzr", "sleet", "snow", "rain")
    # Reserve index 0 for NODATA (single-band encoding), so use 63 bins per ptype.
    # Total: 4 ptypes * 63 bins = 252, leaving indices 1..252 for data, 0 for nodata.
    bins_per_ptype = 63
    range_min = 0.0
    spec_range = spec.get("range")
    if (
        isinstance(spec_range, (list, tuple))
        and len(spec_range) == 2
        and all(isinstance(item, (int, float)) for item in spec_range)
    ):
        range_max = float(spec_range[1])
    else:
        range_max = float(max(PRECIP_CONFIG["rain"]["levels"]))
    alpha_threshold = float(PRECIP_CONFIG["rain"]["levels"][0])
    type_to_component = {
        "rain": "crain",
        "snow": "csnow",
        "sleet": "cicep",
        "frzr": "cfrzr",
    }

    byte_band = np.zeros(prate_values.shape, dtype=np.uint8)  # Defaults to 0 (NODATA)
    # Input PRATE is expected in mm/s; encode pipeline works in mm/hr.
    prate = np.asarray(prate_values, dtype=np.float32)
    prate = np.where(np.isfinite(prate), prate, np.nan)
    prate_mmhr = prate * 3600.0
    visible_mask = np.isfinite(prate_mmhr) & (prate_mmhr >= alpha_threshold)

    # --- Smooth precip rate slightly to reduce blockiness (3x3 weighted kernel) ---
    prate_smooth = prate_mmhr.copy()
    kernel = np.array([[1, 2, 1],
                       [2, 4, 2],
                       [1, 2, 1]], dtype=np.float32)
    kernel = kernel / np.sum(kernel)

    # Pad with edge values to preserve footprint
    padded = np.pad(prate_smooth, 1, mode="edge")
    smoothed = np.zeros_like(prate_smooth, dtype=np.float32)

    for i in range(prate_smooth.shape[0]):
        for j in range(prate_smooth.shape[1]):
            window = padded[i:i+3, j:j+3]
            smoothed[i, j] = np.sum(window * kernel)

    prate_mmhr = smoothed

    flat_colors = list(spec.get("colors", []))
    ptype_breaks = {
        ptype: {"offset": idx * bins_per_ptype, "count": bins_per_ptype}
        for idx, ptype in enumerate(ptype_order)
    }
    ptype_levels = {
        ptype: np.linspace(range_min, range_max, num=bins_per_ptype, dtype=np.float32).tolist()
        for ptype in ptype_order
    }

    ptype_scale: dict[str, str] = {}
    ptype_stack = []
    for ptype in ptype_order:
        comp_key = type_to_component[ptype]
        comp_vals = np.asarray(ptype_values[comp_key], dtype=np.float32)
        comp_vals = np.where(np.isfinite(comp_vals), comp_vals, 0.0)
        max_val = float(np.max(comp_vals)) if comp_vals.size else 0.0
        if max_val > 1.01 and max_val <= 100.0:
            comp_vals = comp_vals / 100.0
            ptype_scale[ptype] = "percent_to_fraction"
        else:
            ptype_scale[ptype] = "fraction"
        comp_vals = np.where((comp_vals >= 0.0) & (comp_vals <= 1.0), comp_vals, 0.0)
        ptype_stack.append(comp_vals)

    stack = np.stack(ptype_stack, axis=0)
    winner_idx = np.argmax(stack, axis=0)
    max_conf = np.max(stack, axis=0)
    has_type_info = max_conf > 0.0
    rain_index = int(ptype_order.index("rain"))

    prate_capped = np.clip(prate_mmhr, range_min, range_max)
    denom = range_max - range_min
    if denom <= 0:
        raise RuntimeError("Invalid precip_ptype blend intensity range")

    norm = np.clip((prate_capped - range_min) / denom, 0.0, 1.0)

    # Gamma scaling (<1 boosts light precip for better visual contrast)
    gamma = 0.35
    norm_gamma = np.power(norm, gamma)

    intensity_float = norm_gamma * (bins_per_ptype - 1)
    intensity_bin = np.clip(np.rint(intensity_float), 0, bins_per_ptype - 1).astype(np.uint8)

    ptype_index = np.where(has_type_info, winner_idx, rain_index).astype(np.uint8)
    encoded_raw = (
        ptype_index.astype(np.uint16) * np.uint16(bins_per_ptype)
        + intensity_bin.astype(np.uint16)
    ).astype(np.uint8)
    # Shift by +1 to reserve 0 for NODATA. Visible pixels: 1..252
    byte_band[visible_mask] = (encoded_raw[visible_mask] + 1).astype(np.uint8)
    # byte_band already initialized to 0 (NODATA) for invisible pixels

    ptype_pixel_counts = {
        ptype: int(np.count_nonzero(visible_mask & (ptype_index == idx)))
        for idx, ptype in enumerate(ptype_order)
    }

    meta = {
        "var_key": requested_var,
        "source_var": normalized_var,
        "spec_key": "precip_ptype",
        "kind": "discrete",
        "units": "mm/hr",
        "colors": flat_colors,
        "ptype_order": list(ptype_order),
        "ptype_breaks": ptype_breaks,
        "ptype_levels": ptype_levels,
        "range": [range_min, range_max],
        "bins_per_ptype": bins_per_ptype,
        "alpha_threshold": alpha_threshold,
        "ptype_priority": list(ptype_order),
        "ptype_noinfo_fallback": "rain",
        "ptype_scale": ptype_scale,
        "visible_pixels": int(np.count_nonzero(visible_mask)),
        "ptype_pixel_counts": ptype_pixel_counts,
        "encoding": "singleband_nodata0",  # Mark for renderer
        "index_shift": 1,  # Renderer must subtract 1 from non-zero values
    }
    return byte_band, meta


def require_gdal(cmd_name: str) -> None:
    if shutil.which(cmd_name) is None:
        raise RuntimeError(
            f"Missing '{cmd_name}'. Install GDAL (gdalwarp/gdal_translate) and ensure it is on PATH."
        )


def run_cmd(args: list[str]) -> None:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Command failed ({' '.join(args)}): {stderr or 'unknown error'}")


def run_cmd_output(args: list[str]) -> str:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Command failed ({' '.join(args)}): {stderr or 'unknown error'}")
    return "\n".join(chunk for chunk in (result.stdout, result.stderr) if chunk)


def run_cmd_json(args: list[str]) -> dict:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Command failed ({' '.join(args)}): {stderr or 'unknown error'}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse JSON from {' '.join(args)}") from exc


def wgs84_bbox_to_3857(bbox_wgs84: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    min_lon, min_lat, max_lon, max_lat = bbox_wgs84
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    minx, miny = transformer.transform(min_lon, min_lat)
    maxx, maxy = transformer.transform(max_lon, max_lat)
    return minx, miny, maxx, maxy


def _lambert_grid_from_attrs(da: xr.DataArray) -> dict:
    attrs = da.attrs
    try:
        nx = int(attrs.get("GRIB_Nx"))
        ny = int(attrs.get("GRIB_Ny"))
        dx = float(attrs.get("GRIB_DxInMetres"))
        dy = float(attrs.get("GRIB_DyInMetres"))
        lon_0 = float(attrs.get("GRIB_LoVInDegrees"))
        lat_1 = float(attrs.get("GRIB_Latin1InDegrees"))
        lat_2 = float(attrs.get("GRIB_Latin2InDegrees"))
        lat_0 = float(attrs.get("GRIB_LaDInDegrees"))
        lat_first = float(attrs.get("GRIB_latitudeOfFirstGridPointInDegrees"))
        lon_first = float(attrs.get("GRIB_longitudeOfFirstGridPointInDegrees"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Lambert attrs missing: {exc}") from exc
    if nx < 2 or ny < 2:
        raise ValueError(f"Lambert grid too small for transform: nx={nx} ny={ny}")

    lambert_crs = CRS.from_proj4(
        f"+proj=lcc +lat_1={lat_1} +lat_2={lat_2} +lat_0={lat_0} "
        f"+lon_0={lon_0} +datum=WGS84 +units=m +no_defs"
    )
    ll_to_lambert = Transformer.from_crs("EPSG:4326", lambert_crs, always_xy=True)
    x0, y0 = ll_to_lambert.transform(lon_first, lat_first)

    i_scans_neg = int(attrs.get("GRIB_iScansNegatively", 0)) == 1
    j_scans_pos = int(attrs.get("GRIB_jScansPositively", 1)) == 1

    x_coords = x0 + np.arange(nx) * dx
    y_coords = y0 + np.arange(ny) * dy

    return {
        "nx": nx,
        "ny": ny,
        "x_coords": x_coords,
        "y_coords": y_coords,
        "lambert_crs": lambert_crs,
        "i_scans_neg": i_scans_neg,
        "j_scans_pos": j_scans_pos,
    }


def _latlon_axes_from_grib_attrs(
    da: xr.DataArray,
    *,
    expected_shape: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    attrs = da.attrs
    ny_expected, nx_expected = expected_shape

    def _int_attr(*keys: str, default: int | None = None) -> int:
        for key in keys:
            value = attrs.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        if default is not None:
            return default
        raise ValueError(f"Missing integer GRIB attr: one of {keys}")

    def _float_attr(*keys: str) -> float:
        for key in keys:
            value = attrs.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        raise ValueError(f"Missing float GRIB attr: one of {keys}")

    nx = _int_attr("GRIB_Nx", "GRIB_Ni", default=nx_expected)
    ny = _int_attr("GRIB_Ny", "GRIB_Nj", default=ny_expected)
    if nx != nx_expected or ny != ny_expected:
        raise ValueError(
            f"GRIB axis shape mismatch: attrs={ny}x{nx} expected={ny_expected}x{nx_expected}"
        )

    lon_first = _float_attr("GRIB_longitudeOfFirstGridPointInDegrees")
    lat_first = _float_attr("GRIB_latitudeOfFirstGridPointInDegrees")
    lon_last = _float_attr("GRIB_longitudeOfLastGridPointInDegrees")
    lat_last = _float_attr("GRIB_latitudeOfLastGridPointInDegrees")

    i_scan_neg = int(attrs.get("GRIB_iScansNegatively", 0)) == 1
    j_scan_pos = int(attrs.get("GRIB_jScansPositively", 1)) == 1

    try:
        dx_deg = abs(float(attrs.get("GRIB_iDirectionIncrementInDegrees")))
    except (TypeError, ValueError):
        dx_deg = None
    try:
        dy_deg = abs(float(attrs.get("GRIB_jDirectionIncrementInDegrees")))
    except (TypeError, ValueError):
        dy_deg = None

    if dx_deg and np.isfinite(dx_deg) and dx_deg > 0:
        lon_sign = -1.0 if i_scan_neg else 1.0
        lon = lon_first + lon_sign * np.arange(nx, dtype=np.float64) * dx_deg
    else:
        lon = np.linspace(lon_first, lon_last, nx, dtype=np.float64)

    if dy_deg and np.isfinite(dy_deg) and dy_deg > 0:
        lat_sign = 1.0 if j_scan_pos else -1.0
        lat = lat_first + lat_sign * np.arange(ny, dtype=np.float64) * dy_deg
    else:
        lat = np.linspace(lat_first, lat_last, ny, dtype=np.float64)

    return np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)


def _apply_scan_order(data: np.ndarray, grid: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    nx = grid["nx"]
    ny = grid["ny"]
    if data.shape != (ny, nx):
        raise ValueError(f"Values shape {data.shape} does not match GRIB grid {ny}x{nx}")

    x_coords = np.array(grid["x_coords"], copy=True)
    y_coords = np.array(grid["y_coords"], copy=True)

    if grid["i_scans_neg"]:
        x_coords = x_coords[::-1]
        data = data[:, ::-1]
    if not grid["j_scans_pos"]:
        y_coords = y_coords[::-1]
        data = data[::-1, :]

    if x_coords[1] < x_coords[0]:
        x_coords = x_coords[::-1]
        data = data[:, ::-1]
    if y_coords[1] > y_coords[0]:
        y_coords = y_coords[::-1]
        data = data[::-1, :]

    return data, x_coords, y_coords


def _write_vrt(
    vrt_path: Path,
    *,
    x_size: int,
    y_size: int,
    geotransform: tuple[float, float, float, float, float, float],
    srs_wkt: str,
    band1_path: Path,
    band2_path: Path,
) -> None:
    srs_escaped = escape(srs_wkt)
    vrt = f"""
<VRTDataset rasterXSize=\"{x_size}\" rasterYSize=\"{y_size}\">
  <SRS>{srs_escaped}</SRS>
  <GeoTransform>{','.join(f'{v:.10f}' for v in geotransform)}</GeoTransform>
  <VRTRasterBand dataType=\"Byte\" band=\"1\" subClass=\"VRTRawRasterBand\">
    <Description>intensity</Description>
    <ColorInterp>Gray</ColorInterp>
    <SourceFilename relativeToVRT=\"0\">{band1_path}</SourceFilename>
    <ImageOffset>0</ImageOffset>
    <PixelOffset>1</PixelOffset>
    <LineOffset>{x_size}</LineOffset>
    <ByteOrder>LSB</ByteOrder>
  </VRTRasterBand>
  <VRTRasterBand dataType=\"Byte\" band=\"2\" subClass=\"VRTRawRasterBand\">
    <Description>alpha</Description>
    <ColorInterp>Alpha</ColorInterp>
    <SourceFilename relativeToVRT=\"0\">{band2_path}</SourceFilename>
    <ImageOffset>0</ImageOffset>
    <PixelOffset>1</PixelOffset>
    <LineOffset>{x_size}</LineOffset>
    <ByteOrder>LSB</ByteOrder>
  </VRTRasterBand>
</VRTDataset>
""".strip()
    vrt_path.write_text(vrt)


def _write_single_band_vrt(
    vrt_path: Path,
    *,
    x_size: int,
    y_size: int,
    geotransform: tuple[float, float, float, float, float, float],
    srs_wkt: str,
    band_path: Path,
    data_type: str,
    nodata: float | None = None,
) -> None:
    srs_escaped = escape(srs_wkt)
    nodata_xml = f"\n    <NoDataValue>{nodata}</NoDataValue>" if nodata is not None else ""
    vrt = f"""
<VRTDataset rasterXSize=\"{x_size}\" rasterYSize=\"{y_size}\">
  <SRS>{srs_escaped}</SRS>
  <GeoTransform>{','.join(f'{v:.10f}' for v in geotransform)}</GeoTransform>
  <VRTRasterBand dataType=\"{data_type}\" band=\"1\" subClass=\"VRTRawRasterBand\">
    <Description>values</Description>
    <ColorInterp>Gray</ColorInterp>{nodata_xml}
    <SourceFilename relativeToVRT=\"0\">{band_path}</SourceFilename>
    <ImageOffset>0</ImageOffset>
    <PixelOffset>{4 if data_type == 'Float32' else 1}</PixelOffset>
    <LineOffset>{x_size * (4 if data_type == 'Float32' else 1)}</LineOffset>
    <ByteOrder>LSB</ByteOrder>
  </VRTRasterBand>
</VRTDataset>
""".strip()
    vrt_path.write_text(vrt)


def write_byte_geotiff_from_arrays(
    da: xr.DataArray,
    byte_band: np.ndarray,
    alpha_band: np.ndarray,
    out_tif: Path,
) -> tuple[Path, bool]:
    used_latlon = False
    try:
        grid = _lambert_grid_from_attrs(da)

        byte_data, x_coords, y_coords = _apply_scan_order(byte_band, grid)
        alpha_data, _, _ = _apply_scan_order(alpha_band, grid)

        dx = abs(x_coords[1] - x_coords[0]) if x_coords.size > 1 else 1.0
        dy = abs(y_coords[1] - y_coords[0]) if y_coords.size > 1 else 1.0
        x_min = float(np.min(x_coords))
        x_max = float(np.max(x_coords))
        y_min = float(np.min(y_coords))
        y_max = float(np.max(y_coords))
        geotransform = (x_min, dx, 0.0, y_max, 0.0, -dy)
        srs_wkt = grid["lambert_crs"].to_wkt()
        print(
            "Lambert grid transform: "
            f"dx={dx:.3f} dy={dy:.3f} "
            f"x=[{x_min:.2f},{x_max:.2f}] y=[{y_min:.2f},{y_max:.2f}]"
        )
        print(f"Lambert grid SRS: {grid['lambert_crs'].to_string()}")
    except ValueError:
        used_latlon = True
        byte_data = byte_band
        alpha_data = alpha_band

        latlon_source = "coords"
        try:
            normalized_da = normalize_latlon_coords(da)
            lat_name, lon_name = detect_latlon_names(normalized_da)
            lat = normalized_da.coords[lat_name].values
            lon = normalized_da.coords[lon_name].values
        except ValueError:
            latlon_source = "grib_attrs"
            lat, lon = _latlon_axes_from_grib_attrs(da, expected_shape=byte_band.shape)
            logger.warning(
                "Lat/lon coords missing for '%s'; using GRIB attr fallback",
                da.name or "unknown_var",
            )

        if lat.ndim != 1 or lon.ndim != 1:
            raise ValueError("Lat/lon fallback expects 1D latitude/longitude arrays")

        lon_wrapped = _normalize_lon_1d(lon.astype(np.float64))
        lon_order = np.argsort(lon_wrapped)
        if not np.array_equal(lon_order, np.arange(lon_order.size)):
            lon_wrapped = lon_wrapped[lon_order]
            byte_data = byte_data[:, lon_order]
            alpha_data = alpha_data[:, lon_order]
        lon = lon_wrapped

        if lat[0] < lat[-1]:
            byte_data = byte_data[::-1, :]
            alpha_data = alpha_data[::-1, :]
            lat = lat[::-1]

        dx = _infer_spacing(lon, axis_name="longitude") if lon.size > 1 else 1.0
        dy = _infer_spacing(lat, axis_name="latitude") if lat.size > 1 else 1.0
        x_min = float(np.min(lon))
        x_max = float(np.max(lon))
        y_min = float(np.min(lat))
        y_max = float(np.max(lat))
        geotransform = (x_min, dx, 0.0, y_max, 0.0, -dy)
        srs_wkt = CRS.from_epsg(4326).to_wkt()
        print(
            "Lat/lon fallback transform: "
            f"dx={dx:.3f} dy={dy:.3f} "
            f"x=[{x_min:.2f},{x_max:.2f}] y=[{y_min:.2f},{y_max:.2f}] source={latlon_source}"
        )
        print("Lat/lon fallback SRS: EPSG:4326")

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    band1_path = out_tif.with_suffix(".band1.bin")
    band2_path = out_tif.with_suffix(".band2.bin")
    vrt_path = out_tif.with_suffix(".vrt")

    byte_data.tofile(band1_path)
    alpha_data.tofile(band2_path)

    _write_vrt(
        vrt_path,
        x_size=byte_data.shape[1],
        y_size=byte_data.shape[0],
        geotransform=geotransform,
        srs_wkt=srs_wkt,
        band1_path=band1_path,
        band2_path=band2_path,
    )

    require_gdal("gdal_translate")
    run_cmd(
        [
            "gdal_translate",
            "-of",
            "GTiff",
            "-co",
            "TILED=YES",
            "-co",
            "COMPRESS=DEFLATE",
            "-co",
            "PHOTOMETRIC=MINISBLACK",
            "-co",
            "ALPHA=YES",
            "-b",
            "1",
            "-b",
            "2",
            str(vrt_path),
            str(out_tif),
        ]
    )

    for temp_path in (band1_path, band2_path, vrt_path):
        try:
            temp_path.unlink()
        except OSError:
            pass

    return out_tif, used_latlon


def write_float_geotiff_from_array(
    da: xr.DataArray,
    float_band: np.ndarray,
    out_tif: Path,
) -> tuple[Path, bool]:
    used_latlon = False
    nodata = -9999.0
    try:
        grid = _lambert_grid_from_attrs(da)

        float_data, x_coords, y_coords = _apply_scan_order(float_band, grid)
        float_data = np.asarray(float_data, dtype=np.float32)
        float_data = np.where(np.isfinite(float_data), float_data, nodata).astype(np.float32)

        dx = abs(x_coords[1] - x_coords[0]) if x_coords.size > 1 else 1.0
        dy = abs(y_coords[1] - y_coords[0]) if y_coords.size > 1 else 1.0
        x_min = float(np.min(x_coords))
        x_max = float(np.max(x_coords))
        y_min = float(np.min(y_coords))
        y_max = float(np.max(y_coords))
        geotransform = (x_min, dx, 0.0, y_max, 0.0, -dy)
        srs_wkt = grid["lambert_crs"].to_wkt()
    except ValueError:
        used_latlon = True
        float_data = np.asarray(float_band, dtype=np.float32)
        float_data = np.where(np.isfinite(float_data), float_data, nodata).astype(np.float32)

        try:
            normalized_da = normalize_latlon_coords(da)
            lat_name, lon_name = detect_latlon_names(normalized_da)
            lat = normalized_da.coords[lat_name].values
            lon = normalized_da.coords[lon_name].values
        except ValueError:
            lat, lon = _latlon_axes_from_grib_attrs(da, expected_shape=float_band.shape)
            logger.warning(
                "Lat/lon coords missing for '%s'; using GRIB attr fallback",
                da.name or "unknown_var",
            )

        if lat.ndim != 1 or lon.ndim != 1:
            raise ValueError("Lat/lon fallback expects 1D latitude/longitude arrays")

        lon_wrapped = _normalize_lon_1d(lon.astype(np.float64))
        lon_order = np.argsort(lon_wrapped)
        if not np.array_equal(lon_order, np.arange(lon_order.size)):
            lon_wrapped = lon_wrapped[lon_order]
            float_data = float_data[:, lon_order]
        lon = lon_wrapped

        if lat[0] < lat[-1]:
            float_data = float_data[::-1, :]
            lat = lat[::-1]

        dx = _infer_spacing(lon, axis_name="longitude") if lon.size > 1 else 1.0
        dy = _infer_spacing(lat, axis_name="latitude") if lat.size > 1 else 1.0
        x_min = float(np.min(lon))
        y_max = float(np.max(lat))
        geotransform = (x_min, dx, 0.0, y_max, 0.0, -dy)
        srs_wkt = CRS.from_epsg(4326).to_wkt()

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    band_path = out_tif.with_suffix(".band1.f32.bin")
    vrt_path = out_tif.with_suffix(".vrt")

    float_data.astype(np.float32).tofile(band_path)

    _write_single_band_vrt(
        vrt_path,
        x_size=float_data.shape[1],
        y_size=float_data.shape[0],
        geotransform=geotransform,
        srs_wkt=srs_wkt,
        band_path=band_path,
        data_type="Float32",
        nodata=nodata,
    )

    require_gdal("gdal_translate")
    run_cmd(
        [
            "gdal_translate",
            "-of",
            "GTiff",
            "-co",
            "TILED=YES",
            "-co",
            "COMPRESS=DEFLATE",
            str(vrt_path),
            str(out_tif),
        ]
    )

    for temp_path in (band_path, vrt_path):
        try:
            temp_path.unlink()
        except OSError:
            pass

    return out_tif, used_latlon


def _read_geotiff_band_float32(path: Path, *, band: int = 1) -> np.ndarray:
    info = gdalinfo_json(path)
    size = info.get("size") or []
    if len(size) != 2:
        raise RuntimeError(f"Unable to read raster size from {path}")
    width = int(size[0])
    height = int(size[1])
    nodata_value = None
    bands = info.get("bands") or []
    if 1 <= band <= len(bands):
        nodata_value = (bands[band - 1] or {}).get("noDataValue")

    raw_path = path.with_suffix(f".band{band}.f32.envi")
    require_gdal("gdal_translate")
    run_cmd(
        [
            "gdal_translate",
            "-of",
            "ENVI",
            "-ot",
            "Float32",
            "-b",
            str(band),
            str(path),
            str(raw_path),
        ]
    )
    try:
        arr = np.fromfile(raw_path, dtype=np.float32)
        expected = width * height
        if arr.size != expected:
            raise RuntimeError(
                f"Unexpected raster byte count for {path}: got={arr.size} expected={expected}"
            )
        arr = arr.reshape((height, width))
        if nodata_value is not None:
            nodata_float = float(nodata_value)
            arr = np.where(np.isclose(arr, nodata_float, atol=1e-6), np.nan, arr)
        return arr
    finally:
        for suffix in ("", ".hdr", ".aux.xml"):
            try:
                Path(str(raw_path) + suffix).unlink()
            except OSError:
                pass


def _extract_raster_georef(path: Path) -> tuple[int, int, tuple[float, float, float, float, float, float], str]:
    info = gdalinfo_json(path)
    size = info.get("size") or []
    if len(size) != 2:
        raise RuntimeError(f"Unable to read raster size from {path}")
    geotransform_values = info.get("geoTransform") or []
    if len(geotransform_values) != 6:
        raise RuntimeError(f"Unable to read geoTransform from {path}")
    coord_sys = info.get("coordinateSystem") or {}
    srs_wkt = str(coord_sys.get("wkt") or "").strip()
    if not srs_wkt:
        raise RuntimeError(f"Unable to read coordinate system WKT from {path}")
    width = int(size[0])
    height = int(size[1])
    geotransform = tuple(float(v) for v in geotransform_values)
    return width, height, geotransform, srs_wkt


def write_byte_geotiff_singleband_from_georef(
    *,
    byte_band: np.ndarray,
    out_tif: Path,
    geotransform: tuple[float, float, float, float, float, float],
    srs_wkt: str,
    nodata: int = 0,
) -> Path:
    """Write a single-band byte GeoTIFF with NODATA value (for precip_ptype).
    
    This avoids alpha band overview mismatch issues that cause zoom-dependent washout.
    """
    if byte_band.ndim != 2:
        raise ValueError(f"Expected 2D byte array, got shape={byte_band.shape}")

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    band1_path = out_tif.with_suffix(".band1.bin")
    vrt_path = out_tif.with_suffix(".vrt")

    np.asarray(byte_band, dtype=np.uint8).tofile(band1_path)

    _write_single_band_vrt(
        vrt_path,
        x_size=byte_band.shape[1],
        y_size=byte_band.shape[0],
        geotransform=geotransform,
        srs_wkt=srs_wkt,
        band_path=band1_path,
        data_type="Byte",
        nodata=float(nodata),
    )

    require_gdal("gdal_translate")
    run_cmd(
        [
            "gdal_translate",
            "-of",
            "GTiff",
            "-co",
            "TILED=YES",
            "-co",
            "COMPRESS=DEFLATE",
            "-co",
            "PHOTOMETRIC=MINISBLACK",
            "-a_nodata",
            str(nodata),
            "-b",
            "1",
            str(vrt_path),
            str(out_tif),
        ]
    )

    for temp_path in (band1_path, vrt_path):
        try:
            temp_path.unlink()
        except OSError:
            pass

    return out_tif


def write_byte_geotiff_from_georef(
    *,
    byte_band: np.ndarray,
    alpha_band: np.ndarray,
    out_tif: Path,
    geotransform: tuple[float, float, float, float, float, float],
    srs_wkt: str,
) -> Path:
    if byte_band.shape != alpha_band.shape:
        raise ValueError(
            f"byte/alpha shape mismatch: byte={byte_band.shape} alpha={alpha_band.shape}"
        )
    if byte_band.ndim != 2:
        raise ValueError(f"Expected 2D byte array, got shape={byte_band.shape}")

    out_tif.parent.mkdir(parents=True, exist_ok=True)
    band1_path = out_tif.with_suffix(".band1.bin")
    band2_path = out_tif.with_suffix(".band2.bin")
    vrt_path = out_tif.with_suffix(".vrt")

    np.asarray(byte_band, dtype=np.uint8).tofile(band1_path)
    np.asarray(alpha_band, dtype=np.uint8).tofile(band2_path)

    _write_vrt(
        vrt_path,
        x_size=byte_band.shape[1],
        y_size=byte_band.shape[0],
        geotransform=geotransform,
        srs_wkt=srs_wkt,
        band1_path=band1_path,
        band2_path=band2_path,
    )

    require_gdal("gdal_translate")
    run_cmd(
        [
            "gdal_translate",
            "-of",
            "GTiff",
            "-co",
            "TILED=YES",
            "-co",
            "COMPRESS=DEFLATE",
            "-co",
            "PHOTOMETRIC=MINISBLACK",
            "-co",
            "ALPHA=YES",
            "-b",
            "1",
            "-b",
            "2",
            str(vrt_path),
            str(out_tif),
        ]
    )

    for temp_path in (band1_path, band2_path, vrt_path):
        try:
            temp_path.unlink()
        except OSError:
            pass

    return out_tif


def warp_to_3857(
    src_tif: Path,
    dst_tif: Path,
    clip_bounds_3857: tuple[float, float, float, float] | None = None,
    *,
    resampling: str = "bilinear",
    tr_meters: tuple[float, float] | None = None,
    tap: bool = True,
    with_alpha: bool = True,
) -> None:
    require_gdal("gdalwarp")
    dst_tif.parent.mkdir(parents=True, exist_ok=True)
    if resampling not in {"near", "bilinear"}:
        raise ValueError(f"Unsupported warp resampling: {resampling}")

    cmd = [
        "gdalwarp",
        "-t_srs",
        "EPSG:3857",
        "-r",
        resampling,
        "-co",
        "TILED=YES",
        "-co",
        "COMPRESS=DEFLATE",
        "-overwrite",
    ]
    if with_alpha:
        cmd.extend(["-srcalpha", "-dstalpha"])

    if tr_meters is not None:
        xres, yres = tr_meters
        cmd.extend([
            "-tr",
            str(xres),
            str(yres),
        ])
        if tap:
            cmd.append("-tap")

    if clip_bounds_3857 is not None:
        minx, miny, maxx, maxy = clip_bounds_3857
        cmd.extend([
            "-te",
            str(minx),
            str(miny),
            str(maxx),
            str(maxy),
            "-te_srs",
            "EPSG:3857",
        ])

    cmd.extend([str(src_tif), str(dst_tif)])
    if os.environ.get("TWF_GDAL_DEBUG", "0").strip() == "1":
        print("GDAL cmd:", " ".join(cmd))
    run_cmd(cmd)


def gdalinfo_json(path: Path) -> dict:
    require_gdal("gdalinfo")
    return run_cmd_json(["gdalinfo", "-json", str(path)])


def assert_single_internal_overview_cog(path: Path) -> None:
    info = gdalinfo_json(path)
    files = [str(item).lower() for item in (info.get("files") or [])]
    if any(item.endswith(".ovr") for item in files):
        raise RuntimeError(f"COG invariant failed: external .ovr found for {path}")

    bands = info.get("bands") or []
    if len(bands) < 1:
        raise RuntimeError(f"COG invariant failed: expected at least 1 band for {path}")

    missing_band_overviews_idx = [
        index
        for index, band in enumerate(bands)
        if not ((band or {}).get("overviews") or [])
    ]
    missing_band_overviews = [str(index + 1) for index in missing_band_overviews_idx]
    if missing_band_overviews:
        alpha_band_indexes = [
            index
            for index, band in enumerate(bands)
            if str((band or {}).get("colorInterpretation", "")).lower() == "alpha"
            or str((band or {}).get("description", "")).lower() == "alpha"
        ]
        data_band_has_overviews = any(
            ((band or {}).get("overviews") or [])
            for index, band in enumerate(bands)
            if index not in alpha_band_indexes
        )
        missing_only_alpha = (
            bool(alpha_band_indexes)
            and set(missing_band_overviews_idx).issubset(set(alpha_band_indexes))
        )
        if missing_only_alpha and data_band_has_overviews:
            logger.warning(
                "COG invariant relaxed: missing internal overviews on alpha band(s)=%s",
                ",".join(missing_band_overviews),
            )
            missing_band_overviews = []

    if missing_band_overviews:
        raise RuntimeError(
            f"COG invariant failed: missing internal band overviews on bands={','.join(missing_band_overviews)}"
        )

    missing_mask_overviews = [
        str(index + 1)
        for index, band in enumerate(bands)
        if not (((band or {}).get("mask") or {}).get("overviews") or [])
    ]
    if missing_mask_overviews:
        if _gdaladdo_supports_mask():
            raise RuntimeError(
                f"COG invariant failed: missing internal mask overviews on bands={','.join(missing_mask_overviews)}"
            )
        logger.warning(
            "COG invariant relaxed: missing internal mask overviews on bands=%s because gdaladdo -mask is unavailable",
            ",".join(missing_mask_overviews),
        )


_OVERVIEW_LEVELS = ["2", "4", "8", "16", "32", "64"]
_GDALADDO_MASK_SUPPORTED: bool | None = None


def _is_external_overview_conflict(exc: RuntimeError) -> bool:
    return "Cannot add external overviews when there are already internal overviews" in str(exc)


def _is_copy_src_overviews_unsupported(exc: RuntimeError) -> bool:
    message = str(exc)
    return (
        "driver COG does not support creation option COPY_SRC_OVERVIEWS" in message
        or "COPY_SRC_OVERVIEWS cannot be used" in message
    )


def _gdaladdo_supports_mask() -> bool:
    global _GDALADDO_MASK_SUPPORTED
    if _GDALADDO_MASK_SUPPORTED is not None:
        return _GDALADDO_MASK_SUPPORTED
    try:
        output = run_cmd_output(["gdaladdo", "--help"])
    except RuntimeError:
        _GDALADDO_MASK_SUPPORTED = False
        return False
    _GDALADDO_MASK_SUPPORTED = "-mask" in output
    return _GDALADDO_MASK_SUPPORTED


def run_gdaladdo_overviews(
    cog_path: Path,
    band1_resampling: str,
    band2_resampling: str,
) -> None:
    require_gdal("gdaladdo")
    base_cmd = [
        "gdaladdo",
        "--config",
        "GDAL_TIFF_INTERNAL_OVERVIEW",
        "YES",
        "--config",
        "COMPRESS_OVERVIEW",
        "DEFLATE",
        "--config",
        "INTERLEAVE_OVERVIEW",
        "PIXEL",
        "--config",
        "GTIFF_FORCE_EXTERNAL_OVR",
        "NO",
        "--config",
        "USE_RRD",
        "NO",
    ]

    def _run(resampling: str, extra_args: list[str]) -> None:
        run_cmd(
            base_cmd
            + ["-r", resampling]
            + extra_args
            + [str(cog_path)]
            + _OVERVIEW_LEVELS
        )

    # Ensure a clean slate if COG driver produced internal overviews unexpectedly.
    run_cmd(base_cmd + ["-clean", str(cog_path)])

    # Debug: check band info before adding overviews
    info_before = gdalinfo_json(cog_path)
    bands_before = info_before.get("bands") or []
    ovr_counts_before = [len((b or {}).get("overviews") or []) for b in bands_before]
    logger.info(
        "gdaladdo: before adding overviews path=%s bands=%d band_overview_counts=%s",
        cog_path.name,
        len(bands_before),
        ovr_counts_before,
    )

    # Check if we have an alpha band (Band 2 with Alpha color interp or mask flags)
    has_alpha_band = False
    if len(bands_before) >= 2:
        band2 = bands_before[1] or {}
        color_interp = band2.get("colorInterpretation", "")
        mask_flags = band2.get("mask", {}).get("flags", []) if isinstance(band2.get("mask"), dict) else []
        if color_interp == "Alpha" or "ALPHA" in str(mask_flags):
            has_alpha_band = True
            logger.info("Detected alpha band; adjusting overview generation strategy")

    try:
        if has_alpha_band and band1_resampling == "nearest":
            # For alpha-channel COGs with nearest resampling, use all-band approach
            # since per-band gdaladdo often fails to create alpha band overviews correctly
            logger.info("Using all-band nearest resampling for alpha-channel COG")
            _run("nearest", [])
        elif has_alpha_band and band1_resampling != "nearest":
            # For alpha-channel COGs with non-nearest resampling (e.g., average for continuous vars),
            # we need different resampling per band. Try per-band approach and fall back if needed.
            _run(band1_resampling, ["-b", "1"])
            _run("nearest", ["-b", "2"])
        else:
            # No alpha band: single-band file (e.g., precip_ptype with NODATA)
            _run(band1_resampling, ["-b", "1"])
            # Only add band 2 overviews if we have at least 2 bands
            if len(bands_before) >= 2:
                _run("nearest", ["-b", "2"])
        # Debug: check after overview generation
        info_after_band = gdalinfo_json(cog_path)
        bands_after_band = info_after_band.get("bands") or []
        ovr_counts_after_band = [len((b or {}).get("overviews") or []) for b in bands_after_band]
        logger.info(
            "gdaladdo: after overview generation path=%s bands=%d band_overview_counts=%s",
            cog_path.name,
            len(bands_after_band),
            ovr_counts_after_band,
        )
    except RuntimeError as exc:
        if not _is_external_overview_conflict(exc):
            raise
        logger.warning(
            "Band-specific gdaladdo overviews are not supported by this GDAL build; "
            "falling back to all-band overviews with resampling=%s",
            band1_resampling,
        )
        run_cmd(base_cmd + ["-clean", str(cog_path)])
        _run(band1_resampling, [])
        return

    if _gdaladdo_supports_mask():
        try:
            _run("nearest", ["-mask", "1"])
        except RuntimeError as exc:
            logger.warning("gdaladdo -mask failed; keeping current internal overviews: %s", exc)
    else:
        logger.warning("gdaladdo does not support -mask; keeping current internal overviews")


def assert_alpha_present(info: dict) -> int:
    bands = info.get("bands") or []
    if not bands:
        raise RuntimeError("GDAL info returned no bands")
    alpha_present = any(
        band.get("colorInterpretation") == "Alpha"
        or str(band.get("description", "")).lower() == "alpha"
        for band in bands
    )
    if not alpha_present or len(bands) < 2:
        raise RuntimeError("Warped GeoTIFF is missing alpha band (expected >= 2 bands)")
    return len(bands)


def log_warped_info(path: Path, info: dict) -> None:
    size = info.get("size") or [0, 0]
    corner = info.get("cornerCoordinates") or {}
    lower_left = corner.get("lowerLeft") or [0.0, 0.0]
    upper_right = corner.get("upperRight") or [0.0, 0.0]
    print(
        "Warped GeoTIFF info: "
        f"path={path} width={size[0]} height={size[1]} bands={len(info.get('bands') or [])} "
        f"bounds_3857=({lower_left[0]:.2f},{lower_left[1]:.2f},{upper_right[0]:.2f},{upper_right[1]:.2f})"
    )


def _band_min_max(info: dict, band_index: int) -> tuple[float | None, float | None]:
    bands = info.get("bands") or []
    if band_index < 1 or band_index > len(bands):
        return None, None
    band = bands[band_index - 1] or {}

    def _to_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    min_val = _to_float(band.get("minimum"))
    max_val = _to_float(band.get("maximum"))
    if min_val is not None and max_val is not None:
        return min_val, max_val

    metadata = band.get("metadata") or {}
    if isinstance(metadata, dict):
        for _, domain_values in metadata.items():
            if not isinstance(domain_values, dict):
                continue
            if min_val is None:
                min_val = _to_float(
                    domain_values.get("STATISTICS_MINIMUM")
                    or domain_values.get("STATISTICS_APPROXIMATE_MINIMUM")
                )
            if max_val is None:
                max_val = _to_float(
                    domain_values.get("STATISTICS_MAXIMUM")
                    or domain_values.get("STATISTICS_APPROXIMATE_MAXIMUM")
                )
            if min_val is not None and max_val is not None:
                break

    return min_val, max_val


def _assert_precip_ptype_singleband_stats(path: Path, meta: dict | None = None) -> None:
    """Validate single-band precip_ptype COG with NODATA=0 encoding."""
    # If meta indicates no visible pixels, skip validation (all-nodata is valid)
    if meta is not None:
        visible_pixels = meta.get("visible_pixels", -1)
        if visible_pixels == 0:
            logger.info(
                "precip_ptype validation skipped: no visible pixels (no precipitation above threshold)"
            )
            return

    require_gdal("gdalinfo")
    output = run_cmd_output(["gdalinfo", "-stats", str(path)])
    section_match = re.search(r"Band\s+1\b([\s\S]*?)(?:\nBand\s+\d+\b|$)", output, flags=re.IGNORECASE)
    if section_match is None:
        raise RuntimeError(f"Could not find Band 1 stats in gdalinfo output for {path}")
    section = section_match.group(1)

    def _pick_float(patterns: list[str]) -> float | None:
        for pattern in patterns:
            match = re.search(pattern, section, flags=re.IGNORECASE)
            if match is None:
                continue
            try:
                return float(match.group(1))
            except (TypeError, ValueError):
                continue
        return None

    # For single-band with NODATA=0, expect max in range 1..252 and nonzero mean
    max_val = _pick_float([r"STATISTICS_MAXIMUM=([0-9eE.+-]+)", r"Maximum=([0-9eE.+-]+)"])
    mean_val = _pick_float([r"STATISTICS_MEAN=([0-9eE.+-]+)", r"Mean=([0-9eE.+-]+)"])
    if max_val is None or max_val < 1.0 or max_val > 252.0:
        raise RuntimeError(
            f"precip_ptype byte stats invalid for {path}: expected STATISTICS_MAXIMUM in 1..252, got {max_val}"
        )
    if mean_val is None or mean_val <= 0.0:
        raise RuntimeError(
            f"precip_ptype byte stats invalid for {path}: expected nonzero mean, got {mean_val}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build V2 COG for a run/fh/variable.")
    parser.add_argument("--cache-dir", type=str, default=None)
    parser.add_argument("--model", type=str, default="hrrr")
    parser.add_argument("--region", type=str, default="pnw")
    parser.add_argument("--out-root", type=str, default="/opt/twf_models/data/v2")
    parser.add_argument("--run", type=str, default="latest")
    parser.add_argument("--fh", type=int, required=True)
    parser.add_argument("--var", type=str, required=True)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--smooth",
        action="store_true",
        help="(stub) Enable smoothing for continuous variables only (not yet implemented)",
    )
    parser.add_argument("--keep-cycles", type=int, default=None)
    parser.add_argument(
        "--bbox",
        type=str,
        default=None,
        help="Clip to custom WGS84 bbox: 'min_lon,min_lat,max_lon,max_lat' (default: PNW region)",
    )
    parser.add_argument(
        "--no-clip",
        action="store_true",
        help="Disable geographic clipping (generates tiles for full HRRR domain)",
    )
    parser.add_argument(
        "--allow-range-fallback",
        action="store_true",
        help="Allow percentile fallback if a continuous var lacks a fixed range",
    )
    parser.add_argument(
        "--target-grid-meters",
        type=str,
        default=None,
        help="Override target grid resolution in meters (single value or 'xres,yres').",
    )
    return parser.parse_args()


def _resolve_run_id(grib_path: Path) -> str:
    cycle_dir = grib_path.parent
    day_dir = cycle_dir.parent
    return f"{day_dir.name}_{cycle_dir.name}z"


def _normalize_run_arg(value: str) -> str:
    if re.fullmatch(r"\d{8}_\d{2}z", value):
        return value[:-1]
    return value


def _write_sidecar_json(
    path: Path,
    *,
    model: str,
    region: str,
    run: str,
    var: str,
    fh: int,
    meta: dict,
) -> None:
    payload = {
        "model": model,
        "region": region,
        "run": run,
        "var": var,
        "fh": fh,
        "meta": meta,
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _log_upstream_not_ready(args: argparse.Namespace, reason: str) -> None:
    logger.warning(
        "Upstream not ready: run=%s var=%s fh=%s reason=%s",
        args.run,
        args.var,
        args.fh,
        reason,
    )


def _handle_upstream_not_ready(
    args: argparse.Namespace,
    reason: BaseException | str,
    paths: Iterable[Path | None],
) -> None:
    _log_upstream_not_ready(args, str(reason))
    _cleanup_upstream_grib_paths(paths)


def _collect_fetch_paths(fetch_result: object | None) -> list[Path | None]:
    if fetch_result is None:
        return []
    paths: list[Path | None] = []
    grib_path = getattr(fetch_result, "grib_path", None)
    if grib_path is not None:
        paths.append(grib_path)
    component_paths = getattr(fetch_result, "component_paths", None)
    if isinstance(component_paths, dict):
        for path in component_paths.values():
            paths.append(path)
    return paths


def main() -> int:
    args = parse_args()
    normalized_run = _normalize_run_arg(args.run)
    if normalized_run != args.run and args.debug:
        print(f"Normalized --run from {args.run} to {normalized_run}")
    args.run = normalized_run
    cache_dir = Path(args.cache_dir) if args.cache_dir else None

    try:
        plugin = get_model(args.model)
    except Exception as exc:
        raise RuntimeError(f"Unknown model: {args.model}") from exc
    region_spec = plugin.get_region(args.region)
    if region_spec is None:
        raise RuntimeError(f"Unknown region: {args.region}")

    if args.target_grid_meters:
        os.environ["TWF_TARGET_GRID_METERS"] = args.target_grid_meters
    try:
        target_grid_meters = resolve_target_grid_meters(args.model, args.region)
    except Exception as exc:
        logger.exception("Failed to resolve target grid")
        return 1

    try:
        assert_gdal_proj_version_pins()
    except Exception:
        logger.exception("Runtime version pin validation failed")
        return 1

    if args.no_clip:
        clip_bbox_wgs84 = None
        clip_bounds_3857 = None
        print("Clipping disabled: will generate tiles for full model domain")
    elif args.bbox:
        try:
            parts = [float(x.strip()) for x in args.bbox.split(",")]
            if len(parts) != 4:
                raise ValueError("Expected 4 values")
            clip_bbox_wgs84 = tuple(parts)
            clip_bounds_3857 = wgs84_bbox_to_3857(clip_bbox_wgs84)
            print(f"Using custom clip bbox (WGS84): {clip_bbox_wgs84}")
        except Exception as exc:
            print(f"ERROR: Invalid --bbox format: {exc}", file=sys.stderr)
            return 1
    else:
        clip_bbox_wgs84 = region_spec.bbox_wgs84 if region_spec.clip else None
        if clip_bbox_wgs84:
            clip_bounds_3857 = wgs84_bbox_to_3857(clip_bbox_wgs84)
            label = region_spec.id.upper()
            print(f"Using default {label} clip bbox (WGS84): {clip_bbox_wgs84}")
        else:
            clip_bounds_3857 = None

    if clip_bounds_3857:
        print(
            f"Clip bounds (EPSG:3857): minx={clip_bounds_3857[0]:.2f} miny={clip_bounds_3857[1]:.2f} "
            f"maxx={clip_bounds_3857[2]:.2f} maxy={clip_bounds_3857[3]:.2f}"
        )
    print(f"Target grid (meters): x={target_grid_meters[0]:.3f} y={target_grid_meters[1]:.3f}")

    allow_range_fallback = bool(
        args.allow_range_fallback or os.environ.get("TWF_V2_ALLOW_RANGE_FALLBACK")
    )
    smooth_enabled = bool(args.smooth or os.environ.get("TWF_V2_SMOOTH"))
    if smooth_enabled and args.debug:
        print("Smooth stub enabled (continuous-only, not yet implemented)")
    normalized_var = plugin.normalize_var_id(args.var)
    grib_path: Path | None = None
    u_path: Path | None = None
    v_path: Path | None = None
    prate_path: Path | None = None
    refl_path: Path | None = None
    rain_path: Path | None = None
    snow_path: Path | None = None
    sleet_path: Path | None = None
    frzr_path: Path | None = None
    fetch_result = None

    try:
        _, var_spec = get_plugin_and_var(args.model, normalized_var)
    except Exception:
        logger.exception("Failed to resolve plugin var spec")
        return 1

    derive_kind = str(var_spec.derive or "") if var_spec.derived else ""
    if derive_kind == "radar_ptype_combo" and args.model != "hrrr":
        logger.error("radar_ptype_combo derivation is only supported for model=hrrr")
        return 1

    if derive_kind == "wspd10m":
        try:
            fetch_result = fetch_grib(
                model=args.model,
                run=args.run,
                fh=args.fh,
                var=normalized_var,
                region=args.region,
                cache_dir=cache_dir,
            )
            if fetch_result.not_ready_reason:
                _handle_upstream_not_ready(args, fetch_result.not_ready_reason, _collect_fetch_paths(fetch_result))
                return 2
            if fetch_result.component_paths:
                u_path, v_path = _resolve_uv_paths(fetch_result.component_paths)
                grib_path = u_path
            elif fetch_result.grib_path is not None:
                grib_path = fetch_result.grib_path
            else:
                raise RuntimeError("Missing GRIB source for wspd10m")
        except Exception as exc:
            if is_upstream_not_ready_error(exc):
                _log_upstream_not_ready(args, str(exc))
                return 2
            logger.exception("Failed to fetch HRRR GRIB for wspd10m")
            return 1

        if u_path is not None and v_path is not None:
            print(f"GRIB path (u10): {u_path}")
            print(f"GRIB path (v10): {v_path}")
        else:
            print(f"GRIB path (shared): {grib_path}")
    elif args.model == "hrrr" and derive_kind == "radar_ptype_combo":
        try:
            fetch_result = fetch_grib(
                model=args.model,
                run=args.run,
                fh=args.fh,
                var=normalized_var,
                region=args.region,
                cache_dir=cache_dir,
            )
            if fetch_result.not_ready_reason:
                _handle_upstream_not_ready(args, fetch_result.not_ready_reason, _collect_fetch_paths(fetch_result))
                return 2
            refl_component, rain_component, snow_component, sleet_component, frzr_component = (
                _radar_blend_component_ids(var_spec)
            )
            if fetch_result.component_paths:
                refl_path, rain_path, snow_path, sleet_path, frzr_path = _resolve_radar_blend_component_paths(
                    fetch_result.component_paths,
                    refl_key=refl_component,
                    rain_key=rain_component,
                    snow_key=snow_component,
                    sleet_key=sleet_component,
                    frzr_key=frzr_component,
                )
                grib_path = refl_path
            elif fetch_result.grib_path is not None:
                grib_path = fetch_result.grib_path
            else:
                raise RuntimeError("Missing GRIB source for radar_ptype_combo")
        except Exception as exc:
            if is_upstream_not_ready_error(exc):
                _log_upstream_not_ready(args, str(exc))
                return 2
            logger.exception("Failed to fetch GRIB components for radar_ptype_combo")
            return 1
        if all(path is not None for path in (refl_path, rain_path, snow_path, sleet_path, frzr_path)):
            print(f"GRIB path (reflectivity): {refl_path}")
            print(f"GRIB path (rain mask): {rain_path}")
            print(f"GRIB path (snow mask): {snow_path}")
            print(f"GRIB path (sleet mask): {sleet_path}")
            print(f"GRIB path (frzr mask): {frzr_path}")
        else:
            print(f"GRIB path (shared): {grib_path}")
    elif args.model == "gfs" and derive_kind == "precip_ptype_blend":
        try:
            fetch_result = fetch_grib(
                model=args.model,
                run=args.run,
                fh=args.fh,
                var=normalized_var,
                region=args.region,
                cache_dir=cache_dir,
            )
            if fetch_result.not_ready_reason:
                _handle_upstream_not_ready(args, fetch_result.not_ready_reason, _collect_fetch_paths(fetch_result))
                return 2
            prate_component, rain_component, snow_component, sleet_component, frzr_component = (
                _precip_ptype_component_ids(var_spec)
            )
            if fetch_result.component_paths:
                prate_path = fetch_result.component_paths.get(prate_component)
                if prate_path is None:
                    available = sorted(fetch_result.component_paths.keys())
                    raise RuntimeError(
                        f"Missing precip_ptype PRATE component file: expected={prate_component} have={available}"
                    )
                rain_path = fetch_result.component_paths.get(rain_component)
                snow_path = fetch_result.component_paths.get(snow_component)
                sleet_path = fetch_result.component_paths.get(sleet_component)
                frzr_path = fetch_result.component_paths.get(frzr_component)
                grib_path = prate_path
            elif fetch_result.grib_path is not None:
                grib_path = fetch_result.grib_path
            else:
                raise RuntimeError("Missing GRIB source for precip_ptype_blend")
        except Exception as exc:
            if is_upstream_not_ready_error(exc):
                _log_upstream_not_ready(args, str(exc))
                return 2
            logger.exception("Failed to fetch GRIB components for precip_ptype_blend")
            return 1
        print(f"GRIB path (prate): {prate_path or grib_path}")
        print(f"GRIB path (rain mask): {rain_path or 'missing'}")
        print(f"GRIB path (snow mask): {snow_path or 'missing'}")
        print(f"GRIB path (sleet mask): {sleet_path or 'missing'}")
        print(f"GRIB path (frzr mask): {frzr_path or 'missing'}")
    else:
        try:
            fetch_result = fetch_grib(
                model=args.model,
                run=args.run,
                fh=args.fh,
                var=normalized_var,
                region=args.region,
                cache_dir=cache_dir,
            )
            if fetch_result.not_ready_reason:
                _handle_upstream_not_ready(args, fetch_result.not_ready_reason, _collect_fetch_paths(fetch_result))
                return 2
            grib_path = fetch_result.grib_path
            if grib_path is None:
                raise RuntimeError("Missing GRIB path from fetch_engine")
        except Exception as exc:
            if is_upstream_not_ready_error(exc):
                _log_upstream_not_ready(args, str(exc))
                return 2
            logger.exception("Failed to fetch HRRR GRIB")
            return 1

        print(f"GRIB path: {grib_path}")

    ds: xr.Dataset | None = None
    ds_u: xr.Dataset | None = None
    ds_v: xr.Dataset | None = None
    ds_prate: xr.Dataset | None = None
    ds_refl: xr.Dataset | None = None
    ds_rain: xr.Dataset | None = None
    ds_snow: xr.Dataset | None = None
    ds_sleet: xr.Dataset | None = None
    ds_frzr: xr.Dataset | None = None
    pre_encoded: tuple[np.ndarray, np.ndarray, dict] | None = None
    precip_ptype_components: dict[str, np.ndarray] | None = None
    precip_ptype_fallback_components: list[str] = []
    try:
        if derive_kind == "wspd10m":
            try:
                u_da: xr.DataArray | None = None
                v_da: xr.DataArray | None = None

                def log_debug(message: str) -> None:
                    if args.debug:
                        print(message)

                def summarize_da(name: str, da: xr.DataArray) -> str:
                    grib_keys = [key for key in da.attrs.keys() if key.startswith("GRIB_")]
                    return (
                        f"{name}: name={da.name} dims={da.dims} shape={da.shape} "
                        f"coords={list(da.coords.keys())} grib_keys={grib_keys}"
                    )

                def select_first(ds: xr.Dataset, candidates: list[str], label: str) -> tuple[xr.DataArray, str]:
                    errors: list[str] = []
                    for cand in candidates:
                        try:
                            return plugin.select_dataarray(ds, cand), cand
                        except Exception as exc:
                            errors.append(f"{cand}: {type(exc).__name__}: {exc}")
                    available = sorted(ds.data_vars.keys())
                    if len(available) == 1:
                        only_key = available[0]
                        return ds[only_key], only_key
                    raise RuntimeError(
                        f"Failed to select {label}. Tried {candidates}. "
                        f"Available: {available}. Errors: {errors}"
                    )

                u_component, v_component = _component_ids(var_spec)
                u_spec = plugin.get_var(u_component)
                v_spec = plugin.get_var(v_component)
                source_u_path = u_path or grib_path
                source_v_path = v_path or grib_path
                if source_u_path is None or source_v_path is None:
                    raise RuntimeError("Missing GRIB path for wspd10m components")
                if args.model == "gfs":
                    ds_u = _open_cfgrib_dataset_strict(source_u_path, u_spec)
                    ds_v = _open_cfgrib_dataset_strict(source_v_path, v_spec)
                else:
                    ds_u = _open_cfgrib_dataset(source_u_path, u_spec)
                    ds_v = _open_cfgrib_dataset(source_v_path, v_spec)
                u_candidates = [u_component, "ugrd10m", "u10", "10u"]
                v_candidates = [v_component, "vgrd10m", "v10", "10v"]
                u_da, u_key = select_first(ds_u, u_candidates, "u wind")
                v_da, v_key = select_first(ds_v, v_candidates, "v wind")
                log_debug(f"wspd10m: selected u_key={u_key} v_key={v_key}")
                log_debug(summarize_da("u_da", u_da))
                log_debug(summarize_da("v_da", v_da))

                if "time" in u_da.dims:
                    u_da = u_da.isel(time=0)
                    log_debug("wspd10m: selected time=0 for u_da")
                if "time" in v_da.dims:
                    v_da = v_da.isel(time=0)
                    log_debug("wspd10m: selected time=0 for v_da")

                u_da = u_da.squeeze()
                v_da = v_da.squeeze()

                if u_da.shape != v_da.shape:
                    raise RuntimeError(
                        "U/V grids have different shapes after squeeze. "
                        f"u_shape={u_da.shape} v_shape={v_da.shape} "
                        f"u_dims={u_da.dims} v_dims={v_da.dims}"
                    )
                if u_da.ndim != 2 or v_da.ndim != 2:
                    raise RuntimeError(
                        "U/V grids are not 2D after squeeze. "
                        f"u_dims={u_da.dims} v_dims={v_da.dims}"
                    )

                u_vals = np.asarray(u_da.data, dtype=np.float32)
                v_vals = np.asarray(v_da.data, dtype=np.float32)
                wspd_np = np.hypot(u_vals, v_vals).astype(np.float32)
                if args.model == "gfs":
                    wspd_np = wspd_np * 2.23694
                wspd = xr.DataArray(wspd_np, dims=("y", "x"), name="wspd10m")
                wspd.attrs = {key: value for key, value in u_da.attrs.items() if key.startswith("GRIB_")}
                wspd.attrs["GRIB_units"] = "mph" if args.model == "gfs" else "m/s"
                da = wspd
                log_debug(f"wspd10m: wspd dims={da.dims} shape={da.shape}")
                log_debug(f"wspd10m: attrs keys={sorted(list(da.attrs.keys()))}")

                print(
                    "Derived wspd10m: "
                    f"min={float(np.nanmin(da.values)):.2f} max={float(np.nanmax(da.values)):.2f}"
                )
            except Exception as exc:
                if isinstance(exc, UpstreamNotReadyError):
                    raise
                if args.debug and u_da is not None:
                    print(summarize_da("u_da", u_da))
                if args.debug and v_da is not None:
                    print(summarize_da("v_da", v_da))
                logger.exception("wspd10m derivation failed")
                raise RuntimeError(
                    f"Failed to derive wspd10m: {type(exc).__name__}: {exc}"
                ) from exc
        elif args.model == "hrrr" and derive_kind == "radar_ptype_combo":
            try:
                refl_component, rain_component, snow_component, sleet_component, frzr_component = (
                    _radar_blend_component_ids(var_spec)
                )
                shared_source_path = grib_path
                refl_source = refl_path or shared_source_path
                rain_source = rain_path or shared_source_path
                snow_source = snow_path or shared_source_path
                sleet_source = sleet_path or shared_source_path
                frzr_source = frzr_path or shared_source_path
                if any(src is None for src in (refl_source, rain_source, snow_source, sleet_source, frzr_source)):
                    raise RuntimeError("Missing GRIB source path for radar_ptype components")
                open_dataset = _open_cfgrib_dataset_strict if args.model == "gfs" else _open_cfgrib_dataset
                ds_refl = open_dataset(refl_source, plugin.get_var(refl_component))
                ds_rain = open_dataset(rain_source, plugin.get_var(rain_component))
                ds_snow = open_dataset(snow_source, plugin.get_var(snow_component))
                ds_sleet = open_dataset(sleet_source, plugin.get_var(sleet_component))
                ds_frzr = open_dataset(frzr_source, plugin.get_var(frzr_component))

                refl_da = plugin.select_dataarray(ds_refl, refl_component)
                rain_da = plugin.select_dataarray(ds_rain, rain_component)
                snow_da = plugin.select_dataarray(ds_snow, snow_component)
                sleet_da = plugin.select_dataarray(ds_sleet, sleet_component)
                frzr_da = plugin.select_dataarray(ds_frzr, frzr_component)

                arrays = [refl_da, rain_da, snow_da, sleet_da, frzr_da]
                arrays = [arr.isel(time=0) if "time" in arr.dims else arr for arr in arrays]
                refl_da, rain_da, snow_da, sleet_da, frzr_da = [arr.squeeze() for arr in arrays]
                if args.model == "gfs":
                    refl_da, lat_name, lon_name = _normalize_latlon_dataarray(refl_da)
                    rain_da, _, _ = _normalize_latlon_dataarray(rain_da)
                    snow_da, _, _ = _normalize_latlon_dataarray(snow_da)
                    sleet_da, _, _ = _normalize_latlon_dataarray(sleet_da)
                    frzr_da, _, _ = _normalize_latlon_dataarray(frzr_da)

                    if not np.array_equal(rain_da.coords[lat_name].values, refl_da.coords[lat_name].values) or not np.array_equal(
                        rain_da.coords[lon_name].values, refl_da.coords[lon_name].values
                    ):
                        rain_da = rain_da.reindex_like(refl_da, method=None)
                    if not np.array_equal(snow_da.coords[lat_name].values, refl_da.coords[lat_name].values) or not np.array_equal(
                        snow_da.coords[lon_name].values, refl_da.coords[lon_name].values
                    ):
                        snow_da = snow_da.reindex_like(refl_da, method=None)
                    if not np.array_equal(sleet_da.coords[lat_name].values, refl_da.coords[lat_name].values) or not np.array_equal(
                        sleet_da.coords[lon_name].values, refl_da.coords[lon_name].values
                    ):
                        sleet_da = sleet_da.reindex_like(refl_da, method=None)
                    if not np.array_equal(frzr_da.coords[lat_name].values, refl_da.coords[lat_name].values) or not np.array_equal(
                        frzr_da.coords[lon_name].values, refl_da.coords[lon_name].values
                    ):
                        frzr_da = frzr_da.reindex_like(refl_da, method=None)
                da = refl_da

                if args.model == "gfs" and TWF_GFS_RADAR_DEBUG:
                    def _log_component_stats(label: str, comp: xr.DataArray) -> None:
                        values = np.asarray(comp.values, dtype=np.float32)
                        finite_mask = np.isfinite(values)
                        total = int(values.size)
                        finite_count = int(np.count_nonzero(finite_mask))
                        finite_pct = (finite_count / total * 100.0) if total else 0.0
                        zero_filled = np.where(finite_mask, values, 0.0)
                        nonzero_count = int(np.count_nonzero(zero_filled))
                        nonzero_pct = (nonzero_count / total * 100.0) if total else 0.0
                        if finite_count:
                            finite_vals = values[finite_mask]
                            p50, p90, p99 = np.nanpercentile(finite_vals, [50, 90, 99])
                            vmin = float(np.nanmin(finite_vals))
                            vmax = float(np.nanmax(finite_vals))
                        else:
                            p50 = p90 = p99 = float("nan")
                            vmin = vmax = float("nan")

                        attrs = comp.attrs
                        scan_i = attrs.get("GRIB_iScansNegatively")
                        scan_j = attrs.get("GRIB_jScansPositively")
                        grid_nx = attrs.get("GRIB_Nx")
                        grid_ny = attrs.get("GRIB_Ny")
                        grid_dx = attrs.get("GRIB_DxInMetres")
                        grid_dy = attrs.get("GRIB_DyInMetres")

                        unique_vals = None
                        counts = None
                        is_int = np.issubdtype(values.dtype, np.integer)
                        if finite_count and (is_int or finite_count <= 0):
                            unique_vals = np.array([], dtype=values.dtype)
                        if finite_count:
                            try:
                                unique_vals, counts = np.unique(finite_vals, return_counts=True)
                            except Exception:
                                unique_vals, counts = None, None

                        if unique_vals is not None and counts is not None:
                            if unique_vals.size <= 64 or is_int:
                                sample_size = min(32, unique_vals.size)
                                sample_vals = unique_vals[:sample_size].tolist()
                                sample_counts = counts[:sample_size].tolist()
                                logger.info(
                                    "gfs radar %s: name=%s dims=%s shape=%s dtype=%s iScan=%s jScan=%s "
                                    "Nx=%s Ny=%s Dx=%s Dy=%s finite=%.2f%% nonzero=%.2f%% "
                                    "min=%.3f p50=%.3f p90=%.3f p99=%.3f max=%.3f uniq=%s counts=%s",
                                    label,
                                    comp.name,
                                    comp.dims,
                                    comp.shape,
                                    str(values.dtype),
                                    scan_i,
                                    scan_j,
                                    grid_nx,
                                    grid_ny,
                                    grid_dx,
                                    grid_dy,
                                    finite_pct,
                                    nonzero_pct,
                                    vmin,
                                    p50,
                                    p90,
                                    p99,
                                    vmax,
                                    sample_vals,
                                    sample_counts,
                                )
                                return

                        if finite_count:
                            p999 = float(np.nanpercentile(finite_vals, [99.9])[0])
                        else:
                            p999 = float("nan")
                        gt1 = int(np.count_nonzero(values > 1))
                        gt100 = int(np.count_nonzero(values > 100))
                        gt200 = int(np.count_nonzero(values > 200))
                        logger.info(
                            "gfs radar %s: name=%s dims=%s shape=%s dtype=%s iScan=%s jScan=%s "
                            "Nx=%s Ny=%s Dx=%s Dy=%s finite=%.2f%% nonzero=%.2f%% "
                            "min=%.3f p50=%.3f p90=%.3f p99=%.3f max=%.3f p999=%.3f gt1=%s gt100=%s gt200=%s",
                            label,
                            comp.name,
                            comp.dims,
                            comp.shape,
                            str(values.dtype),
                            scan_i,
                            scan_j,
                            grid_nx,
                            grid_ny,
                            grid_dx,
                            grid_dy,
                            finite_pct,
                            nonzero_pct,
                            vmin,
                            p50,
                            p90,
                            p99,
                            vmax,
                            p999,
                            gt1,
                            gt100,
                            gt200,
                        )

                    _log_component_stats("refl", refl_da)
                    _log_component_stats("crain", rain_da)
                    _log_component_stats("csnow", snow_da)
                    _log_component_stats("cicep", sleet_da)
                    _log_component_stats("cfrzr", frzr_da)

                    def _scan_flags(da: xr.DataArray) -> tuple[object, object]:
                        return (
                            da.attrs.get("GRIB_iScansNegatively"),
                            da.attrs.get("GRIB_jScansPositively"),
                        )

                    refl_flags = _scan_flags(refl_da)
                    for name, comp in (
                        ("crain", rain_da),
                        ("csnow", snow_da),
                        ("cicep", sleet_da),
                        ("cfrzr", frzr_da),
                    ):
                        comp_flags = _scan_flags(comp)
                        if comp_flags != refl_flags:
                            logger.warning(
                                "gfs radar scan mismatch: component=%s refl=%s component_flags=%s",
                                name,
                                refl_flags,
                                comp_flags,
                            )

                    def _ptype_scale_stats(label: str, comp: xr.DataArray) -> None:
                        values = np.asarray(comp.values, dtype=np.float32)
                        finite_mask = np.isfinite(values)
                        finite_vals = values[finite_mask]
                        if finite_vals.size:
                            p99 = float(np.nanpercentile(finite_vals, [99])[0])
                            vmax = float(np.nanmax(finite_vals))
                        else:
                            p99 = float("nan")
                            vmax = float("nan")
                        total = int(values.size)
                        gt0 = int(np.count_nonzero(values > 0))
                        gt1 = int(np.count_nonzero(values > 1))
                        gt100 = int(np.count_nonzero(values > 100))
                        gt200 = int(np.count_nonzero(values > 200))
                        frac = lambda count: (count / total) if total else 0.0
                        logger.info(
                            "gfs radar ptype scale %s: max=%.3f p99=%.3f frac>0=%.4f frac>1=%.4f frac>100=%.4f frac>200=%.4f",
                            label,
                            vmax,
                            p99,
                            frac(gt0),
                            frac(gt1),
                            frac(gt100),
                            frac(gt200),
                        )

                    _ptype_scale_stats("crain", rain_da)
                    _ptype_scale_stats("csnow", snow_da)
                    _ptype_scale_stats("cicep", sleet_da)
                    _ptype_scale_stats("cfrzr", frzr_da)

                pre_encoded = _encode_radar_ptype_combo(
                    requested_var=args.var,
                    normalized_var=normalized_var,
                    refl_values=np.asarray(refl_da.values, dtype=np.float32),
                    ptype_values={
                        "crain": np.asarray(rain_da.values, dtype=np.float32),
                        "csnow": np.asarray(snow_da.values, dtype=np.float32),
                        "cicep": np.asarray(sleet_da.values, dtype=np.float32),
                        "cfrzr": np.asarray(frzr_da.values, dtype=np.float32),
                    },
                    refl_min_dbz=GFS_RADAR_PTYPE_REFL_MIN_DBZ if args.model == "gfs" else None,
                    footprint_min_dbz=(
                        GFS_RADAR_PTYPE_FOOTPRINT_MIN_DBZ if args.model == "gfs" else 15.0
                    ),
                )
            except Exception as exc:
                if isinstance(exc, UpstreamNotReadyError):
                    raise
                logger.exception("radar_ptype_combo derivation failed")
                raise RuntimeError(
                    f"Failed to derive radar_ptype_combo: {type(exc).__name__}: {exc}"
                ) from exc
        elif args.model == "gfs" and derive_kind == "precip_ptype_blend":
            try:
                prate_component, rain_component, snow_component, sleet_component, frzr_component = (
                    _precip_ptype_component_ids(var_spec)
                )
                shared_source_path = grib_path
                prate_source = prate_path or shared_source_path
                rain_source = rain_path or shared_source_path
                snow_source = snow_path or shared_source_path
                sleet_source = sleet_path or shared_source_path
                frzr_source = frzr_path or shared_source_path
                if any(src is None for src in (prate_source, rain_source, snow_source, sleet_source, frzr_source)):
                    raise RuntimeError("Missing GRIB source path for precip_ptype components")

                ds_prate = _open_cfgrib_dataset_strict(prate_source, plugin.get_var(prate_component))
                prate_da = plugin.select_dataarray(ds_prate, prate_component)
                if "time" in prate_da.dims:
                    prate_da = prate_da.isel(time=0)
                prate_da = prate_da.squeeze()

                prate_da, lat_name, lon_name = _normalize_latlon_dataarray(prate_da)

                optional_sources = {
                    rain_component: rain_source,
                    snow_component: snow_source,
                    sleet_component: sleet_source,
                    frzr_component: frzr_source,
                }
                optional_arrays: dict[str, xr.DataArray] = {}
                missing_components: list[str] = []
                for component_id, source in optional_sources.items():
                    selected = _open_gfs_precip_ptype_component_optional(
                        plugin=plugin,
                        component_id=component_id,
                        source_path=source,
                    )
                    if selected is None:
                        missing_components.append(component_id)
                        continue
                    selected, _, _ = _normalize_latlon_dataarray(selected)
                    if not np.array_equal(selected.coords[lat_name].values, prate_da.coords[lat_name].values) or not np.array_equal(
                        selected.coords[lon_name].values, prate_da.coords[lon_name].values
                    ):
                        selected = selected.reindex_like(prate_da, method=None)
                    optional_arrays[component_id] = selected

                if missing_components:
                    precip_ptype_fallback_components = sorted(set(missing_components))
                    logger.warning(
                        "GFS precip_ptype: optional p-type components unavailable; using PRATE-only fallback. "
                        "missing=%s run=%s fh=%s",
                        precip_ptype_fallback_components,
                        args.run,
                        args.fh,
                    )
                    rain_da = xr.zeros_like(prate_da, dtype=np.float32)
                    snow_da = xr.zeros_like(prate_da, dtype=np.float32)
                    sleet_da = xr.zeros_like(prate_da, dtype=np.float32)
                    frzr_da = xr.zeros_like(prate_da, dtype=np.float32)
                else:
                    rain_da = optional_arrays[rain_component]
                    snow_da = optional_arrays[snow_component]
                    sleet_da = optional_arrays[sleet_component]
                    frzr_da = optional_arrays[frzr_component]

                prate_vals = np.asarray(prate_da.values, dtype=np.float32)
                prate_units = str(
                    prate_da.attrs.get("units")
                    or prate_da.attrs.get("GRIB_units")
                    or ""
                ).strip().lower()
                if "mm/hr" in prate_units or "mm h-1" in prate_units:
                    prate_vals = prate_vals / np.float32(3600.0)

                da = prate_da
                precip_ptype_components = {
                    "prate": prate_vals,
                    "crain": np.asarray(rain_da.values, dtype=np.float32),
                    "csnow": np.asarray(snow_da.values, dtype=np.float32),
                    "cicep": np.asarray(sleet_da.values, dtype=np.float32),
                    "cfrzr": np.asarray(frzr_da.values, dtype=np.float32),
                }
            except Exception as exc:
                if isinstance(exc, UpstreamNotReadyError):
                    raise
                logger.exception("precip_ptype_blend derivation failed")
                raise RuntimeError(
                    f"Failed to derive precip_ptype_blend: {type(exc).__name__}: {exc}"
                ) from exc
        else:
            try:
                open_dataset = _open_cfgrib_dataset_strict if args.model == "gfs" else _open_cfgrib_dataset
                ds = open_dataset(grib_path, var_spec)
            except Exception as exc:
                if is_upstream_not_ready_error(exc):
                    _handle_upstream_not_ready(args, exc, [grib_path])
                    return 2
                message = str(exc)
                if "multiple values for unique key" in message:
                    logger.exception(
                        "cfgrib index collision. Ensure subsetting worked for the requested variable."
                    )
                elif "eccodes" in message.lower() or "ecCodes" in message or "Cannot find the ecCodes library" in message:
                    logger.exception("Failed to open GRIB with cfgrib. ecCodes library not available.")
                else:
                    logger.exception("Failed to open GRIB with cfgrib.")
                return 3

            try:
                da = plugin.select_dataarray(ds, normalized_var)
            except Exception as exc:
                logger.exception(
                    "Failed to select variable '%s' (normalized='%s')",
                    args.var,
                    normalized_var,
                )
                return 4
    except UpstreamNotReadyError as exc:
        _handle_upstream_not_ready(
            args,
            exc,
            [
                grib_path,
                u_path,
                v_path,
                prate_path,
                refl_path,
                rain_path,
                snow_path,
                sleet_path,
                frzr_path,
            ],
        )
        return 2
    except RuntimeError as exc:
        if is_upstream_not_ready_error(exc):
            _handle_upstream_not_ready(
                args,
                exc,
                [
                    grib_path,
                    u_path,
                    v_path,
                    prate_path,
                    refl_path,
                    rain_path,
                    snow_path,
                    sleet_path,
                    frzr_path,
                ],
            )
            return 2
        logger.exception("Runtime error during data selection")
        return 4

    if "time" in da.dims:
        da = da.isel(time=0)
    da = da.squeeze()

    values = np.asarray(da.values, dtype=np.float32)
    if values.ndim != 2:
        raise RuntimeError(
            "Expected 2D values after squeeze. "
            f"dims={da.dims} shape={values.shape} coords={list(da.coords.keys())} "
            f"attrs_keys={sorted(list(da.attrs.keys()))}"
        )

    lat_name = None
    lon_name = None
    try:
        if not (args.model == "gfs" and pre_encoded is not None):
            da = normalize_latlon_coords(da)
        lat_name, lon_name = detect_latlon_names(da)
    except ValueError:
        logger.info("No lat/lon coords present; using region bounds for metadata")
    except Exception:
        logger.exception("Failed to normalize lat/lon coords")
        return 5

    if lat_name and lon_name:
        lat_vals = da.coords[lat_name].values
        lon_vals = da.coords[lon_name].values
        print(
            f"Requested var '{args.var}' normalized to '{normalized_var}' using dataset var '{da.name}'\n"
            f"GRIB domain: lat[{lat_name}] min={np.nanmin(lat_vals):.4f} max={np.nanmax(lat_vals):.4f}\n"
            f"GRIB domain: lon[{lon_name}] min={np.nanmin(lon_vals):.4f} max={np.nanmax(lon_vals):.4f}"
        )
    else:
        lat_vals = None
        lon_vals = None

    if clip_bbox_wgs84:
        bounds_wgs84 = clip_bbox_wgs84
        print(f"Metadata will use clipped bounds: {bounds_wgs84}")
    else:
        if lat_vals is None or lon_vals is None:
            bounds_wgs84 = region_spec.bbox_wgs84
            print(f"Metadata will use region bounds: {bounds_wgs84}")
        else:
            bounds_wgs84 = (
                float(np.nanmin(lon_vals)),
                float(np.nanmin(lat_vals)),
                float(np.nanmax(lon_vals)),
                float(np.nanmax(lat_vals)),
            )
            print(f"Metadata will use full GRIB bounds: {bounds_wgs84}")

    try:
        start_time = time.time()
        use_precip_ptype_prewarp = (
            args.model == "gfs"
            and derive_kind == "precip_ptype_blend"
            and precip_ptype_components is not None
        )
        if use_precip_ptype_prewarp:
            assert precip_ptype_components is not None
            byte_band, meta = _encode_precip_ptype_blend(
                requested_var=args.var,
                normalized_var=normalized_var,
                prate_values=precip_ptype_components["prate"],
                ptype_values={
                    "crain": precip_ptype_components["crain"],
                    "csnow": precip_ptype_components["csnow"],
                    "cicep": precip_ptype_components["cicep"],
                    "cfrzr": precip_ptype_components["cfrzr"],
                },
            )
            if precip_ptype_fallback_components:
                meta["ptype_data_mode"] = "prate_only_fallback"
                meta["ptype_missing_components"] = list(precip_ptype_fallback_components)
            else:
                meta["ptype_data_mode"] = "blended"
            valid_mask = np.isfinite(precip_ptype_components["prate"])
            stats = {
                "vmin": float(np.nanmin(precip_ptype_components["prate"][valid_mask])) if np.any(valid_mask) else float("nan"),
                "vmax": float(np.nanmax(precip_ptype_components["prate"][valid_mask])) if np.any(valid_mask) else float("nan"),
            }
            spec_key_used = str(meta.get("spec_key") or normalized_var)
        elif pre_encoded is None:
            byte_band, alpha_band, meta, valid_mask, stats, spec_key_used = _encode_with_nodata(
                values,
                requested_var=args.var,
                normalized_var=normalized_var,
                da=da,
                allow_range_fallback=allow_range_fallback,
            )
        elif pre_encoded is not None:
            byte_band, alpha_band, meta = pre_encoded
            valid_mask = np.isfinite(values)
            stats = {
                "vmin": float(np.nanmin(values[valid_mask])) if np.any(valid_mask) else float("nan"),
                "vmax": float(np.nanmax(values[valid_mask])) if np.any(valid_mask) else float("nan"),
            }
            spec_key_used = str(meta.get("spec_key") or normalized_var)

        if args.var == "tmp2m":
            valid_count = int(np.count_nonzero(valid_mask))
            total_count = int(values.size)
            nodata_count = int(np.count_nonzero(byte_band == 255))
            nodata_pct = (nodata_count / total_count * 100.0) if total_count else 0.0
            alpha_nonzero = int(np.count_nonzero(alpha_band))
            alpha_pct = (alpha_nonzero / total_count * 100.0) if total_count else 0.0
            valid_bytes = byte_band[byte_band != 255]
            if valid_bytes.size:
                byte_min = int(valid_bytes.min())
                byte_max = int(valid_bytes.max())
            else:
                byte_min = 255
                byte_max = 255
            print(
                "tmp2m stats: "
                f"float_min={stats.get('vmin'):.2f} float_max={stats.get('vmax'):.2f} "
                f"byte_min={byte_min} byte_max={byte_max} "
                f"nodata_pct={nodata_pct:.2f} alpha_pct={alpha_pct:.2f} valid={valid_count}/{total_count}"
            )

            if nodata_pct == 0.0 and byte_min == 255 and byte_max == 255:
                raise RuntimeError(
                    "tmp2m scaling failed: byte range is 255-only with no nodata; "
                    "check units/range or valid-mask logic."
                )

        print(
            "Meta debug: "
            f"requested_var={args.var} normalized_var={normalized_var} "
            f"spec_key_used={spec_key_used} units={meta.get('units')} "
            f"range={meta.get('range')} colors_len={len(meta.get('colors') or [])}"
        )

        upstream_run_id = getattr(fetch_result, "upstream_run_id", None)
        run_id = _coerce_run_id(upstream_run_id, grib_path)
        out_dir = Path(args.out_root) / args.model / args.region / run_id / args.var
        out_dir.mkdir(parents=True, exist_ok=True)

        cog_path = out_dir / f"fh{args.fh:03d}.cog.tif"
        sidecar_path = out_dir / f"fh{args.fh:03d}.json"

        with tempfile.TemporaryDirectory(prefix="hrrr_cog_") as temp_dir:
            temp_root = Path(temp_dir)
            base_name = grib_path.stem
            byte_tif = temp_root / f"{base_name}.byte.tif"
            warped_tif = temp_root / f"{base_name}.3857.tif"
            ovr_tif = temp_root / f"{base_name}.3857.ovrsrc.tif"

            tr_meters = _warp_tr_meters(args.model, args.var, meta) or target_grid_meters
            tap = True
            if use_precip_ptype_prewarp:
                assert precip_ptype_components is not None
                warped_components: dict[str, Path] = {}
                for component_name in ("prate", "crain", "csnow", "cicep", "cfrzr"):
                    src_component_tif = temp_root / f"{base_name}.{component_name}.native.f32.tif"
                    dst_component_tif = temp_root / f"{base_name}.{component_name}.3857.f32.tif"
                    write_float_geotiff_from_array(
                        da,
                        precip_ptype_components[component_name],
                        src_component_tif,
                    )
                    warp_to_3857(
                        src_component_tif,
                        dst_component_tif,
                        clip_bounds_3857=clip_bounds_3857,
                        resampling="bilinear",
                        tr_meters=tr_meters,
                        tap=tap,
                        with_alpha=False,
                    )
                    warped_components[component_name] = dst_component_tif

                warped_prate = _read_geotiff_band_float32(warped_components["prate"])
                warped_rain = _read_geotiff_band_float32(warped_components["crain"])
                warped_snow = _read_geotiff_band_float32(warped_components["csnow"])
                warped_sleet = _read_geotiff_band_float32(warped_components["cicep"])
                warped_frzr = _read_geotiff_band_float32(warped_components["cfrzr"])

                byte_band, meta = _encode_precip_ptype_blend(
                    requested_var=args.var,
                    normalized_var=normalized_var,
                    prate_values=warped_prate,
                    ptype_values={
                        "crain": warped_rain,
                        "csnow": warped_snow,
                        "cicep": warped_sleet,
                        "cfrzr": warped_frzr,
                    },
                )
                if precip_ptype_fallback_components:
                    meta["ptype_data_mode"] = "prate_only_fallback"
                    meta["ptype_missing_components"] = list(precip_ptype_fallback_components)
                else:
                    meta["ptype_data_mode"] = "blended"
                valid_mask = np.isfinite(warped_prate)
                stats = {
                    "vmin": float(np.nanmin(warped_prate[valid_mask])) if np.any(valid_mask) else float("nan"),
                    "vmax": float(np.nanmax(warped_prate[valid_mask])) if np.any(valid_mask) else float("nan"),
                }
                spec_key_used = str(meta.get("spec_key") or normalized_var)
                
                # Debug: check byte band stats immediately after encoding
                byte_nonzero = int(np.count_nonzero(byte_band))
                byte_max = int(np.max(byte_band)) if byte_band.size > 0 else 0
                visible_pixels_meta = meta.get("visible_pixels", 0)
                print(
                    f"precip_ptype encode debug: visible_pixels={visible_pixels_meta} "
                    f"byte_nonzero={byte_nonzero} byte_max={byte_max} (expect 1..252) "
                    f"prate_min_mm_s={stats['vmin']:.6f} prate_max_mm_s={stats['vmax']:.6f}"
                )

                width, height, geotransform, srs_wkt = _extract_raster_georef(warped_components["prate"])
                if byte_band.shape != (height, width):
                    raise RuntimeError(
                        "Warped precip_ptype shape mismatch: "
                        f"encoded={byte_band.shape} expected={(height, width)}"
                    )
                print(f"Writing prewarped precip_ptype single-band GeoTIFF (NODATA=0): {warped_tif}")
                write_byte_geotiff_singleband_from_georef(
                    byte_band=byte_band,
                    out_tif=warped_tif,
                    geotransform=geotransform,
                    srs_wkt=srs_wkt,
                    nodata=0,
                )
                # Debug: check byte band after writing warped_tif
                _info = gdalinfo_json(warped_tif)
                _byte_min, _byte_max = _band_min_max(_info, 1)
                print(f"Debug: warped_tif byte band after write: min={_byte_min} max={_byte_max}")
                if args.debug:
                    print(
                        "Warp debug: "
                        f"model={args.model} var={args.var} used_latlon=True "
                        "resampling=bilinear(pre-encode) "
                        f"tr_meters={tr_meters} tap={tap}"
                    )
            else:
                print(f"Writing byte GeoTIFF: {byte_tif}")
                _, used_latlon = write_byte_geotiff_from_arrays(da, byte_band, alpha_band, byte_tif)

                is_discrete = _is_discrete(args.var, meta)
                warp_resampling = "near" if is_discrete else "bilinear"
                print(f"Warping to EPSG:3857 ({warp_resampling}): {warped_tif}")
                warp_to_3857(
                    byte_tif,
                    warped_tif,
                    clip_bounds_3857=clip_bounds_3857,
                    resampling=warp_resampling,
                    tr_meters=tr_meters,
                    tap=tap,
                )
                if args.debug:
                    print(
                        "Warp debug: "
                        f"model={args.model} var={args.var} used_latlon={used_latlon} "
                        f"resampling={warp_resampling} tr_meters={tr_meters} tap={tap}"
                    )

            precip_ptype_singleband = bool(use_precip_ptype_prewarp)
            if spec_key_used == "precip_ptype" and not use_precip_ptype_prewarp:
                info_prestrip = gdalinfo_json(warped_tif)
                band_count_prestrip = len(info_prestrip.get("bands") or [])
                if band_count_prestrip == 1:
                    precip_ptype_singleband = True
                if band_count_prestrip > 1:
                    print(
                        "precip_ptype: stripping alpha band to enforce single-band NODATA encoding"
                    )
                    singleband_tif = temp_root / f"{base_name}.3857.singleband.tif"
                    require_gdal("gdal_translate")
                    run_cmd(
                        [
                            "gdal_translate",
                            "-of",
                            "GTiff",
                            "-co",
                            "TILED=YES",
                            "-co",
                            "COMPRESS=DEFLATE",
                            "-co",
                            "PHOTOMETRIC=MINISBLACK",
                            "-b",
                            "1",
                            "-a_nodata",
                            "0",
                            str(warped_tif),
                            str(singleband_tif),
                        ]
                    )
                    try:
                        warped_tif.unlink()
                    except OSError:
                        pass
                    singleband_tif.replace(warped_tif)
                    precip_ptype_singleband = True

            info = gdalinfo_json(warped_tif)
            if args.debug:
                band_count = len(info.get("bands") or [])
                if use_precip_ptype_prewarp or precip_ptype_singleband:
                    byte_min, byte_max = _band_min_max(info, 1)
                    print(
                        "Warp debug: "
                        f"bands={band_count} "
                        f"byte_band1_min={byte_min if byte_min is not None else 'n/a'} "
                        f"byte_band1_max={byte_max if byte_max is not None else 'n/a'}"
                    )
                else:
                    alpha_min, alpha_max = _band_min_max(info, 2)
                    print(
                        "Warp debug: "
                        f"bands={band_count} "
                        f"alpha_band2_min={alpha_min if alpha_min is not None else 'n/a'} "
                        f"alpha_band2_max={alpha_max if alpha_max is not None else 'n/a'}"
                    )
            # Skip alpha validation for single-band precip_ptype
            if not precip_ptype_singleband:
                assert_alpha_present(info)
            log_warped_info(warped_tif, info)

            if clip_bounds_3857:
                corner = info.get("cornerCoordinates") or {}
                ll = corner.get("lowerLeft") or [0.0, 0.0]
                ur = corner.get("upperRight") or [0.0, 0.0]
                print(
                    f"Warped GeoTIFF bounds (EPSG:3857): [{ll[0]:.2f}, {ll[1]:.2f}] to [{ur[0]:.2f}, {ur[1]:.2f}]"
                )
                print(
                    f"Expected clip bounds (EPSG:3857): [{clip_bounds_3857[0]:.2f}, {clip_bounds_3857[1]:.2f}] "
                    f"to [{clip_bounds_3857[2]:.2f}, {clip_bounds_3857[3]:.2f}]"
                )

            # Build per-band internal overviews on an intermediate GeoTIFF, then copy them into the final COG.
            # This avoids relying on gdaladdo -mask (not available in some GDAL builds) and prevents one-zoom-level
            # artifacts caused by inconsistent mask/overview handling.
            addo_resampling = (
                "nearest"
                if meta.get("kind") == "discrete" or spec_key_used in ("radar_ptype", "precip_ptype")
                else "average"
            )

            # Create a plain GeoTIFF copy we can safely add internal overviews to.
            require_gdal("gdal_translate")
            translate_cmd = [
                "gdal_translate",
                "-of",
                "GTiff",
                "-co",
                "TILED=YES",
                "-co",
                "COMPRESS=DEFLATE",
                "-co",
                "PHOTOMETRIC=MINISBLACK",
            ]
            # Only add ALPHA=YES for 2-band (byte+alpha) files, not for single-band NODATA files
            if not use_precip_ptype_prewarp:
                translate_cmd.extend(["-co", "ALPHA=YES"])
            translate_cmd.extend([str(warped_tif), str(ovr_tif)])
            run_cmd(translate_cmd)
            
            # Debug: check alpha after creating ovr_tif from warped_tif
            _info_ovr_initial = gdalinfo_json(ovr_tif)
            _alpha_min_ovr_init, _alpha_max_ovr_init = _band_min_max(_info_ovr_initial, 2)
            print(f"Debug: ovr_tif alpha after gdal_translate from warped_tif: min={_alpha_min_ovr_init} max={_alpha_max_ovr_init}")

            # Add internal overviews per band (band 1 uses average/nearest depending on var; band 2 (alpha) always nearest).
            # Debug: check alpha before adding overviews
            _info_before = gdalinfo_json(ovr_tif)
            _alpha_min_before, _alpha_max_before = _band_min_max(_info_before, 2)
            print(f"Debug: ovr_tif alpha before gdaladdo: min={_alpha_min_before} max={_alpha_max_before}")
            
            run_gdaladdo_overviews(ovr_tif, addo_resampling, "nearest")
            
            # Debug: check alpha after adding overviews
            _info_after = gdalinfo_json(ovr_tif)
            _alpha_min_after, _alpha_max_after = _band_min_max(_info_after, 2)
            print(f"Debug: ovr_tif alpha after gdaladdo: min={_alpha_min_after} max={_alpha_max_after}")

            # If band overviews are mismatched (common when alpha is treated as mask),
            # skip COPY_SRC_OVERVIEWS and rebuild overviews on the COG instead.
            use_copy_src_overviews = True
            _bands = _info_after.get("bands") or []
            _overview_counts = [len((band or {}).get("overviews") or []) for band in _bands]
            if _overview_counts and len(set(_overview_counts)) > 1:
                use_copy_src_overviews = False
                logger.warning(
                    "Skipping COPY_SRC_OVERVIEWS due to mismatched band overviews: counts=%s",
                    _overview_counts,
                )
            elif _overview_counts and any(count == 0 for count in _overview_counts):
                use_copy_src_overviews = False
                logger.warning(
                    "Skipping COPY_SRC_OVERVIEWS due to missing band overviews: counts=%s",
                    _overview_counts,
                )

            # Now build the final COG and copy the already-built overviews.
            print(f"Writing COG: {cog_path}")
            try:
                if use_copy_src_overviews:
                    run_cmd(
                        [
                            "gdal_translate",
                            "-of",
                            "COG",
                            "-co",
                            "COMPRESS=DEFLATE",
                            "-co",
                            "COPY_SRC_OVERVIEWS=YES",
                            str(ovr_tif),
                            str(cog_path),
                        ]
                    )
                else:
                    run_cmd(
                        [
                            "gdal_translate",
                            "-of",
                            "COG",
                            "-co",
                            "COMPRESS=DEFLATE",
                            "-co",
                            "OVERVIEWS=NONE",
                            str(ovr_tif),
                            str(cog_path),
                        ]
                    )
                    run_gdaladdo_overviews(cog_path, addo_resampling, "nearest")
            except RuntimeError as exc:
                if not _is_copy_src_overviews_unsupported(exc):
                    raise
                logger.warning(
                    "COG COPY_SRC_OVERVIEWS unsupported/incompatible; retrying with COG-driver overview build: %s",
                    exc,
                )
                require_gdal("gdaladdo")
                # Older GDAL COG builds may still try to reuse source overviews unless they are explicitly removed.
                run_cmd(["gdaladdo", "-clean", str(ovr_tif)])
                if cog_path.exists():
                    cog_path.unlink()
                manual_overviews_needed = False
                try:
                    run_cmd(
                        [
                            "gdal_translate",
                            "-of",
                            "COG",
                            "-co",
                            "COMPRESS=DEFLATE",
                            "-co",
                            "OVERVIEWS=IGNORE_EXISTING",
                            "-co",
                            f"RESAMPLING={addo_resampling}",
                            str(ovr_tif),
                            str(cog_path),
                        ]
                    )
                except RuntimeError as fallback_exc:
                    if not _is_copy_src_overviews_unsupported(fallback_exc):
                        raise
                    logger.warning(
                        "COG still rejected source overview state; creating COG with OVERVIEWS=NONE and rebuilding overviews: %s",
                        fallback_exc,
                    )
                    if cog_path.exists():
                        cog_path.unlink()
                    run_cmd(
                        [
                            "gdal_translate",
                            "-of",
                            "COG",
                            "-co",
                            "COMPRESS=DEFLATE",
                            "-co",
                            "OVERVIEWS=NONE",
                            str(ovr_tif),
                            str(cog_path),
                        ]
                    )
                    manual_overviews_needed = True
                if manual_overviews_needed:
                    run_gdaladdo_overviews(cog_path, addo_resampling, "nearest")
            try:
                assert_single_internal_overview_cog(cog_path)
            except RuntimeError as exc:
                logger.warning(
                    "COG invariant failed after translate; retrying with explicit gdaladdo overviews: %s",
                    exc,
                )
                run_gdaladdo_overviews(cog_path, addo_resampling, "nearest")
                assert_single_internal_overview_cog(cog_path)

            if args.model == "gfs" and derive_kind == "precip_ptype_blend":
                _assert_precip_ptype_singleband_stats(cog_path, meta=meta)

            if args.debug:
                cog_info = gdalinfo_json(cog_path)
                cog_files = [str(path) for path in (cog_info.get("files") or [])]
                band_overviews = [
                    len((band or {}).get("overviews") or [])
                    for band in (cog_info.get("bands") or [])
                ]
                mask_overviews = []
                for band in (cog_info.get("bands") or []):
                    mask = (band or {}).get("mask") or {}
                    mask_overviews.append(len((mask.get("overviews") or [])))
                has_external_ovr = any(path.lower().endswith(".ovr") for path in cog_files)
                print(
                    "COG overview debug: "
                    f"resampling={addo_resampling} "
                    f"bands={len(cog_info.get('bands') or [])} "
                    f"overviews_per_band={band_overviews} "
                    f"mask_overviews_per_band={mask_overviews} "
                    f"internal_overviews={not has_external_ovr}"
                )
                if has_external_ovr or any(count == 0 for count in band_overviews):
                    print("WARNING: Missing internal band overviews or found external .ovr")
                if any(count == 0 for count in mask_overviews):
                    print("WARNING: Missing mask overviews on one or more bands")

        _write_sidecar_json(
            sidecar_path,
            model=args.model,
            region=args.region,
            run=run_id,
            var=args.var,
            fh=args.fh,
            meta=meta,
        )

        elapsed = time.time() - start_time
        print(f"Done: COG built in {elapsed:.1f}s")
    except Exception as exc:
        logger.exception("GDAL pipeline failed")
        return 6
    finally:
        if ds is not None:
            ds.close()
        if ds_u is not None:
            ds_u.close()
        if ds_v is not None:
            ds_v.close()
        if ds_prate is not None:
            ds_prate.close()
        if ds_refl is not None:
            ds_refl.close()
        if ds_rain is not None:
            ds_rain.close()
        if ds_snow is not None:
            ds_snow.close()
        if ds_sleet is not None:
            ds_sleet.close()
        if ds_frzr is not None:
            ds_frzr.close()

    if args.keep_cycles:
        try:
            summary = plugin.ensure_latest_cycles(args.keep_cycles, cache_dir=cache_dir)
        except Exception as exc:
            logger.exception("Failed to enforce cycle retention")
            return 7
        print(f"Retention: {summary}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
