from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import xarray as xr
from PIL import Image

from app.services.grid import detect_latlon_names, normalize_latlon_coords, reproject_to_web_mercator
from app.services.variable_registry import normalize_api_variable, select_dataarray
from app.services.hrrr_runs import HRRRCacheConfig, enforce_cycle_retention, resolve_hrrr_grib_path
from app.services.paths import default_hrrr_cache_dir

ORIGIN_SHIFT = 20037508.342789244
TILE_SIZE = 256


def tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    tiles_at_zoom = 2**z
    tile_span = (2 * ORIGIN_SHIFT) / tiles_at_zoom
    minx = -ORIGIN_SHIFT + (x * tile_span)
    maxx = -ORIGIN_SHIFT + ((x + 1) * tile_span)
    maxy = ORIGIN_SHIFT - (y * tile_span)
    miny = ORIGIN_SHIFT - ((y + 1) * tile_span)
    return minx, miny, maxx, maxy


def wrap_lon(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0


def lonlat_to_tile(z: int, lon_deg: float, lat_deg: float) -> tuple[int, int]:
    lat = np.clip(lat_deg, -85.05112878, 85.05112878)
    lon = wrap_lon(lon_deg)
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = np.deg2rad(lat)
    y = int((1.0 - np.log(np.tan(lat_rad) + 1.0 / np.cos(lat_rad)) / np.pi) / 2.0 * n)
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))
    return x, y


def tile_bounds_lonlat(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2**z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * y / n))))
    south = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + 1) / n))))
    return west, south, east, north


def scale_to_uint8(
    values: np.ndarray,
    *,
    p_low: float,
    p_high: float,
    use_log: bool,
    eps: float,
) -> tuple[np.ndarray, dict[str, float] | None]:
    if np.all(~np.isfinite(values)):
        return np.zeros(values.shape, dtype=np.uint8), None

    valid_mask = np.isfinite(values) & (values > eps)
    if not np.any(valid_mask):
        return np.zeros(values.shape, dtype=np.uint8), None

    transformed = np.full(values.shape, np.nan, dtype=np.float64)
    if use_log:
        transformed[valid_mask] = np.log10(values[valid_mask])
    else:
        transformed[valid_mask] = values[valid_mask]

    finite_vals = transformed[np.isfinite(transformed)]
    if finite_vals.size == 0:
        return np.zeros(values.shape, dtype=np.uint8), None

    vmin = float(np.percentile(finite_vals, p_low))
    vmax = float(np.percentile(finite_vals, p_high))
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin == vmax:
        return np.zeros(values.shape, dtype=np.uint8), None

    scaled = (transformed - vmin) / (vmax - vmin)
    scaled = np.clip(scaled, 0.0, 1.0)
    scaled = np.where(np.isfinite(scaled), scaled, 0.0)
    return (scaled * 255).astype(np.uint8), {
        "p_low": float(p_low),
        "p_high": float(p_high),
        "vmin": vmin,
        "vmax": vmax,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--run", type=str, default="latest")
    parser.add_argument("--fh", type=int, default=1)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--keep-runs", type=int, default=1)
    parser.add_argument("--enforce-retention", action="store_true", default=False)
    parser.add_argument("--grib-path", type=Path, default=None)
    parser.add_argument("variable")
    parser.add_argument("z", type=int)
    parser.add_argument("x", type=int, nargs="?", default=-1)
    parser.add_argument("y", type=int, nargs="?", default=-1)
    parser.add_argument("--p-low", type=float, default=2)
    parser.add_argument("--p-high", type=float, default=98)
    parser.add_argument("--log", action="store_true", default=False)
    parser.add_argument("--out", type=Path, default=Path("tile_test.png"))
    parser.add_argument("--auto-max", action="store_true", default=False)
    parser.add_argument("--auto-p99", type=float, default=None)
    raw_args = sys.argv[1:]
    if raw_args and not raw_args[0].startswith("-") and Path(raw_args[0]).exists():
        raw_args = ["--grib-path", raw_args[0], *raw_args[1:]]

    args = parser.parse_args(raw_args)

    grib_path = args.grib_path
    variable = args.variable
    z = args.z
    x = args.x
    y = args.y

    if args.model == "hrrr":
        base_dir = args.cache_dir or default_hrrr_cache_dir()
        cfg = HRRRCacheConfig(base_dir=base_dir, keep_runs=args.keep_runs)
        if args.enforce_retention:
            try:
                summary = enforce_cycle_retention(cfg)
                print(
                    "Retention: deleted_cycles={deleted_cycles}, deleted_files={deleted_files}, deleted_day_dirs={deleted_day_dirs}, kept_cycles={kept_cycles}".format(
                        **summary
                    )
                )
            except FileNotFoundError as exc:
                print(str(exc))
                return 2

        try:
            grib_path = resolve_hrrr_grib_path(cfg, run=args.run, fh=args.fh)
        except Exception as exc:
            print(str(exc))
            return 2

    if grib_path is None:
        print("GRIB path not provided. Use --model hrrr or pass a GRIB2 file path.")
        return 2

    if not grib_path.exists():
        print(f"File not found: {grib_path}")
        return 2

    try:
        ds = xr.open_dataset(grib_path, engine="cfgrib")
    except Exception as exc:
        if "eccodes" in str(exc).lower():
            print("ERROR: ecCodes native library not found. Check system install.")
            return 1
        print(f"Failed to open GRIB2 file: {exc}")
        return 1

    try:
        try:
            da = select_dataarray(ds, variable)
        except ValueError as exc:
            print(str(exc))
            return 2
        if "time" in da.dims:
            da = da.isel(time=0)
        da = da.squeeze()

        variable = normalize_api_variable(variable)
        da = normalize_latlon_coords(da)
        lat_name, lon_name = detect_latlon_names(da)
        lat_vals = da.coords[lat_name].values
        lon_vals = da.coords[lon_name].values

        lat_min = float(np.nanmin(lat_vals))
        lat_max = float(np.nanmax(lat_vals))
        lon_min = float(np.nanmin(lon_vals))
        lon_max = float(np.nanmax(lon_vals))

        data_vals = np.asarray(da.values)
        finite_vals = data_vals[np.isfinite(data_vals)]
        finite_pos = finite_vals[finite_vals > 0]

        print(f"lat coord: {lat_name} (min={lat_min}, max={lat_max})")
        print(f"lon coord: {lon_name} (min={lon_min}, max={lon_max})")
        if finite_vals.size:
            print(f"data min/max (finite): {float(finite_vals.min())} / {float(finite_vals.max())}")
        else:
            print("data min/max (finite): n/a")

        if finite_pos.size:
            print(
                "data min/max (finite>0): "
                f"{float(finite_pos.min())} / {float(finite_pos.max())}"
            )
            p1, p50, p99 = np.percentile(finite_pos, [1, 50, 99])
            print(f"percentiles (p1, p50, p99): {p1}, {p50}, {p99}")
        else:
            print("data min/max (finite>0): n/a")
            print("percentiles (p1, p50, p99): n/a")

        target_lat = None
        target_lon = None
        target_val = None

        if args.auto_max:
            finite_mask = np.isfinite(data_vals)
            if not np.any(finite_mask):
                print("Auto-max requested but no finite values found; falling back to center.")
                args.auto_max = False
            
        if args.auto_max:
            if args.auto_p99 is not None:
                finite_pos = data_vals[finite_mask & (data_vals > 0)]
                if finite_pos.size:
                    threshold = np.percentile(finite_pos, args.auto_p99)
                    candidate = np.where(
                        finite_mask & (data_vals >= threshold), data_vals, np.nan
                    )
                    if np.all(~np.isfinite(candidate)):
                        idx = np.nanargmax(data_vals)
                    else:
                        idx = np.nanargmax(candidate)
                else:
                    idx = np.nanargmax(data_vals)
            else:
                idx = np.nanargmax(data_vals)

            idx = np.unravel_index(idx, data_vals.shape)
            if lat_vals.ndim == 2:
                target_lat = float(lat_vals[idx])
                target_lon = float(lon_vals[idx])
            else:
                target_lat = float(lat_vals[idx[0]])
                target_lon = float(lon_vals[idx[-1]])
            target_lon = wrap_lon(target_lon)
            target_val = float(data_vals[idx])

            x, y = lonlat_to_tile(z, target_lon, target_lat)
        elif x < 0 or y < 0:
            lat_center = (lat_min + lat_max) / 2.0
            lon_center = (lon_min + lon_max) / 2.0
            x, y = lonlat_to_tile(z, lon_center, lat_center)
            target_lat = lat_center
            target_lon = lon_center
        else:
            if lat_vals.ndim == 2:
                mid_idx = (lat_vals.shape[0] // 2, lat_vals.shape[1] // 2)
                target_lat = float(lat_vals[mid_idx])
                target_lon = float(lon_vals[mid_idx])
                target_val = float(data_vals[mid_idx])
            else:
                mid_lat = lat_vals.shape[0] // 2
                mid_lon = lon_vals.shape[0] // 2
                target_lat = float(lat_vals[mid_lat])
                target_lon = float(lon_vals[mid_lon])
                if data_vals.ndim == 2:
                    target_val = float(data_vals[mid_lat, mid_lon])

        if target_lon is not None:
            target_lon = wrap_lon(target_lon)

        tile_bounds_deg = tile_bounds_lonlat(z, x, y)
        print(f"Chosen z/x/y: {z}/{x}/{y}")
        print(f"Tile bounds lon/lat: {tile_bounds_deg}")
        if target_lat is not None and target_lon is not None:
            print(
                f"Target lon/lat: {target_lon}, {target_lat} "
                f"(value={target_val if target_val is not None else 'n/a'})"
            )

        bounds = tile_bounds_3857(z, x, y)
        print(f"Tile bounds EPSG:3857: {bounds}")
        tile = reproject_to_web_mercator(
            da,
            width=TILE_SIZE,
            height=TILE_SIZE,
            bounds_3857=bounds,
        )

        eps = 1e-9
        tile_uint8, scale_stats = scale_to_uint8(
            tile,
            p_low=args.p_low,
            p_high=args.p_high,
            use_log=args.log,
            eps=eps,
        )
        alpha = np.where(np.isfinite(tile) & (tile > eps), 255, 0).astype(np.uint8)
        rgba = np.dstack([tile_uint8, tile_uint8, tile_uint8, alpha])
        output_path = args.out
        Image.fromarray(rgba, mode="RGBA").save(output_path)

        finite_pixels = int(np.isfinite(tile).sum())
        finite_pos_pixels = int((np.isfinite(tile) & (tile > eps)).sum())
        outside_coverage_pixels = int((~np.isfinite(tile)).sum())
        zero_value_pixels = int((np.isfinite(tile) & (tile <= eps)).sum())
        nonzero_pixels = int((np.isfinite(tile) & (tile > eps)).sum())
        if scale_stats is None:
            print("scale percentiles: n/a")
            print("scale vmin/vmax: n/a")
        else:
            print(
                f"scale percentiles (p{scale_stats['p_low']}, p{scale_stats['p_high']}): "
                f"{scale_stats['vmin']}, {scale_stats['vmax']}"
            )
            print(f"scale vmin/vmax: {scale_stats['vmin']} / {scale_stats['vmax']}")
        file_size = output_path.stat().st_size if output_path.exists() else 0
        print(f"Tile finite pixels: {finite_pixels}")
        print(f"Tile finite>0 pixels: {finite_pos_pixels}")
        print(f"Tile outside-coverage pixels: {outside_coverage_pixels}")
        print(f"Tile zero-value pixels: {zero_value_pixels}")
        print(f"Tile nonzero pixels: {nonzero_pixels}")
        total_pixels = TILE_SIZE * TILE_SIZE
        print(f"Tile finite fraction: {finite_pixels / total_pixels:.6f}")
        print(f"Tile finite>0 fraction: {finite_pos_pixels / total_pixels:.6f}")
        print(f"Wrote {output_path} ({file_size} bytes)")
    finally:
        ds.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
