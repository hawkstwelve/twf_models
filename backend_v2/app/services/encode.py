from __future__ import annotations

import logging
import os

import numpy as np
import xarray as xr

from app.services.colormaps_v2 import PRECIP_CONFIG, RADAR_CONFIG, VAR_SPECS

logger = logging.getLogger(__name__)

TWF_RADAR_PTYPE_DEBUG = os.environ.get("TWF_RADAR_PTYPE_DEBUG", "0").strip() == "1"


def _collect_fill_values(da: xr.DataArray) -> list[float]:
    candidates: list[float] = []
    for source in (da.attrs, getattr(da, "encoding", {}) or {}):
        for key in (
            "_FillValue",
            "missing_value",
            "GRIB_missingValue",
            "GRIB_missingValueAtSea",
        ):
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
            "output_mode": "byte_alpha",
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
        "output_mode": "byte_alpha",
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

    stack = []
    for ptype in type_order:
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
        stack.append(comp_vals)

    mask_stack = np.stack(stack, axis=0)

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
        "output_mode": "byte_alpha",
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
) -> tuple[np.ndarray, dict]:
    if prate_values.ndim != 2:
        raise RuntimeError(f"Expected 2D PRATE array, got shape={prate_values.shape}")
    for key, values in ptype_values.items():
        if values.shape != prate_values.shape:
            raise RuntimeError(
                f"P-type component shape mismatch for {key}: prate={prate_values.shape} ptype={values.shape}"
            )

    spec = VAR_SPECS.get("precip_ptype", {})

    ptype_order = ("frzr", "sleet", "snow", "rain")
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

    byte_band = np.zeros(prate_values.shape, dtype=np.uint8)
    prate = np.asarray(prate_values, dtype=np.float32)
    prate = np.where(np.isfinite(prate), prate, np.nan)
    prate_mmhr = prate * 3600.0
    visible_mask = np.isfinite(prate_mmhr) & (prate_mmhr >= alpha_threshold)

    prate_smooth = prate_mmhr.copy()
    kernel = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], dtype=np.float32)
    kernel = kernel / np.sum(kernel)
    padded = np.pad(prate_smooth, 1, mode="edge")
    smoothed = np.zeros_like(prate_smooth, dtype=np.float32)
    for i in range(prate_smooth.shape[0]):
        for j in range(prate_smooth.shape[1]):
            window = padded[i : i + 3, j : j + 3]
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
    gamma = 0.35
    norm_gamma = np.power(norm, gamma)
    intensity_float = norm_gamma * (bins_per_ptype - 1)
    intensity_bin = np.clip(np.rint(intensity_float), 0, bins_per_ptype - 1).astype(np.uint8)

    ptype_index = np.where(has_type_info, winner_idx, rain_index).astype(np.uint8)
    encoded_raw = (
        ptype_index.astype(np.uint16) * np.uint16(bins_per_ptype)
        + intensity_bin.astype(np.uint16)
    ).astype(np.uint8)
    byte_band[visible_mask] = (encoded_raw[visible_mask] + 1).astype(np.uint8)

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
        "encoding": "singleband_nodata0",
        "index_shift": 1,
        "output_mode": "byte_singleband",
    }
    return byte_band, meta
