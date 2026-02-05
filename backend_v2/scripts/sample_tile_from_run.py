from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

# Add backend_v2 to path so app module can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))

import numpy as np
import xarray as xr
from PIL import Image

from app.services.grid import (
    detect_latlon_names,
    normalize_latlon_coords,
    reproject_to_web_mercator,
)
from app.services.hrrr_fetch import fetch_hrrr_grib
from app.services.hrrr_runs import HRRRCacheConfig
from app.services.paths import default_hrrr_cache_dir
from app.services.variable_registry import (
    VARIABLE_SELECTORS,
    normalize_api_variable,
    select_dataarray,
)

WEB_MERCATOR_RADIUS = 6378137.0
WEB_MERCATOR_ORIGIN = math.pi * WEB_MERCATOR_RADIUS
EPS = 1e-9


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    lon = ((lon + 180.0) % 360.0) - 180.0
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2**z
    xtile = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ytile = int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0
        * n
    )
    return xtile, ytile


def tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2**z
    resolution = 2 * WEB_MERCATOR_ORIGIN / (256 * n)
    minx = -WEB_MERCATOR_ORIGIN + x * 256 * resolution
    maxx = minx + 256 * resolution
    maxy = WEB_MERCATOR_ORIGIN - y * 256 * resolution
    miny = maxy - 256 * resolution
    return minx, miny, maxx, maxy


def _ensure_latlon_2d(da: xr.DataArray) -> tuple[np.ndarray, np.ndarray]:
    lat_name, lon_name = detect_latlon_names(da)
    lat = da.coords[lat_name].values
    lon = da.coords[lon_name].values
    if lat.ndim == 1 and lon.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon, lat)
        return lat2d, lon2d
    return lat, lon


def _safe_percentiles(values: np.ndarray, p_low: float, p_high: float) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    return (
        float(np.nanpercentile(finite, p_low)),
        float(np.nanpercentile(finite, p_high)),
    )


def scale_to_uint8(
    values: np.ndarray,
    *,
    p_low: float,
    p_high: float,
    log_scale: bool,
    eps: float = EPS,
) -> tuple[np.ndarray, tuple[float, float]]:
    data = np.array(values, dtype=np.float32)
    if log_scale:
        data = np.where(data > eps, np.log10(data), np.nan)

    vmin, vmax = _safe_percentiles(data, p_low, p_high)
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin == vmax:
        return np.zeros_like(data, dtype=np.uint8), (vmin, vmax)

    clipped = np.clip(data, vmin, vmax)
    scaled = (clipped - vmin) / (vmax - vmin)
    scaled = np.clip(scaled, 0.0, 1.0)
    scaled = np.where(np.isfinite(scaled), scaled, 0.0)
    return (scaled * 255.0).astype(np.uint8), (vmin, vmax)


def pick_tile_for_center(da: xr.DataArray, z: int) -> tuple[int, int]:
    lat2d, lon2d = _ensure_latlon_2d(da)
    lat_min = float(np.nanmin(lat2d))
    lat_max = float(np.nanmax(lat2d))
    lon_min = float(np.nanmin(lon2d))
    lon_max = float(np.nanmax(lon2d))
    lat_center = (lat_min + lat_max) / 2.0
    lon_center = (lon_min + lon_max) / 2.0
    return lonlat_to_tile(lon_center, lat_center, z)


def pick_tile_for_max(
    da: xr.DataArray,
    z: int,
    *,
    threshold_percentile: float | None,
) -> tuple[int, int]:
    lat2d, lon2d = _ensure_latlon_2d(da)
    values = np.asarray(da.values)
    mask = np.isfinite(values)
    if threshold_percentile is not None:
        finite_vals = values[mask]
        if finite_vals.size > 0:
            threshold = np.nanpercentile(finite_vals, threshold_percentile)
            mask &= values >= threshold

    if not np.any(mask):
        mask = np.isfinite(values)

    if not np.any(mask):
        raise ValueError("No finite values found to select auto-max tile")

    masked_values = np.where(mask, values, np.nan)
    idx = np.nanargmax(masked_values)
    lat = float(lat2d.ravel()[idx])
    lon = float(lon2d.ravel()[idx])
    return lonlat_to_tile(lon, lat, z)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample a Web Mercator tile from an HRRR run/fh and write a PNG."
    )
    parser.add_argument("--cache-dir", type=str, default=None)
    parser.add_argument("--run", type=str, default="latest")
    parser.add_argument("--fh", type=int, required=True)
    parser.add_argument("--var", type=str, required=True)
    parser.add_argument("--z", type=int, required=True)
    parser.add_argument("--x", type=int, default=-1)
    parser.add_argument("--y", type=int, default=-1)
    parser.add_argument("--out", type=str, default="tile_from_run.png")
    parser.add_argument("--p-low", type=float, default=2.0)
    parser.add_argument("--p-high", type=float, default=98.0)
    parser.add_argument("--log", action="store_true")
    parser.add_argument("--auto-max", action="store_true")
    parser.add_argument("--auto-p99", type=float, default=None)
    return parser.parse_args()


def open_dataset_with_filters(grib_path: Path, api_var: str) -> xr.Dataset:
    try:
        return xr.open_dataset(grib_path, engine="cfgrib")
    except Exception as exc:
        message = str(exc)
        if "multiple values for unique key" not in message:
            raise

        normalized = normalize_api_variable(api_var)
        selector = VARIABLE_SELECTORS.get(normalized)

        if selector and selector.get("typeOfLevel"):
            tol = selector["typeOfLevel"]
            try:
                return xr.open_dataset(
                    grib_path,
                    engine="cfgrib",
                    backend_kwargs={"filter_by_keys": {"typeOfLevel": tol}},
                )
            except Exception:
                pass

        fallback_tols = [
            "heightAboveGround",
            "surface",
            "meanSea",
            "isobaricInhPa",
            "atmosphere",
        ]
        for tol in fallback_tols:
            try:
                ds = xr.open_dataset(
                    grib_path,
                    engine="cfgrib",
                    backend_kwargs={"filter_by_keys": {"typeOfLevel": tol}},
                )
            except Exception:
                continue
            if ds.data_vars:
                return ds
            ds.close()

        raise RuntimeError(
            "cfgrib index collision; retrying with filter_by_keys failed. "
            f"Original error: {message}"
        ) from exc


def main() -> int:
    args = parse_args()

    cache_dir = Path(args.cache_dir) if args.cache_dir else default_hrrr_cache_dir()
    cfg = HRRRCacheConfig(base_dir=cache_dir, keep_runs=1)

    try:
        grib_path = fetch_hrrr_grib(
            run=args.run,
            fh=args.fh,
            variable=args.var,
            cache_cfg=cfg,
        )
    except Exception as exc:
        print(f"ERROR: Failed to fetch HRRR GRIB: {exc}", file=sys.stderr)
        return 2

    print(f"GRIB path: {grib_path}")

    ds: xr.Dataset | None = None
    normalized_var = normalize_api_variable(args.var)
    try:
        try:
            ds = open_dataset_with_filters(grib_path, args.var)
        except Exception as exc:
            message = str(exc)
            if "multiple values for unique key" in message or "index collision" in message:
                print(
                    "ERROR: cfgrib index collision; retrying with filter_by_keys "
                    "(typeOfLevel=...) failed.\n"
                    f"{exc}",
                    file=sys.stderr,
                )
            elif "eccodes" in message.lower() or "ecCodes" in message or "Cannot find the ecCodes library" in message:
                print(
                    "ERROR: Failed to open GRIB with cfgrib. "
                    "ecCodes library not available.\n"
                    f"{exc}",
                    file=sys.stderr,
                )
            else:
                print(
                    "ERROR: Failed to open GRIB with cfgrib.\n"
                    f"{exc}",
                    file=sys.stderr,
                )
            return 3

        try:
            da = select_dataarray(ds, normalized_var)
        except Exception as exc:
            print(
                f"ERROR: Failed to select variable '{args.var}' (normalized='{normalized_var}'): {exc}",
                file=sys.stderr,
            )
            return 4

        if "time" in da.dims:
            da = da.isel(time=0)
        da = da.squeeze()

        try:
            da = normalize_latlon_coords(da)
            lat_name, lon_name = detect_latlon_names(da)
        except Exception as exc:
            print(f"ERROR: Failed to normalize lat/lon coords: {exc}", file=sys.stderr)
            return 5

        lat_vals = da.coords[lat_name].values
        lon_vals = da.coords[lon_name].values
        print(
            f"Requested var '{args.var}' normalized to '{normalized_var}' using dataset var '{da.name}'\n"
            f"lat[{lat_name}] min={np.nanmin(lat_vals):.4f} max={np.nanmax(lat_vals):.4f}\n"
            f"lon[{lon_name}] min={np.nanmin(lon_vals):.4f} max={np.nanmax(lon_vals):.4f}"
        )

        if args.auto_max:
            try:
                x, y = pick_tile_for_max(da, args.z, threshold_percentile=args.auto_p99)
            except Exception as exc:
                print(f"ERROR: Failed to pick auto-max tile: {exc}", file=sys.stderr)
                return 6
        else:
            if (args.x >= 0) != (args.y >= 0):
                print("ERROR: --x and --y must be provided together", file=sys.stderr)
                return 7
            if args.x >= 0 and args.y >= 0:
                x, y = args.x, args.y
            else:
                x, y = pick_tile_for_center(da, args.z)

        bounds_3857 = tile_bounds_3857(args.z, x, y)
        print(f"Tile z/x/y = {args.z}/{x}/{y}")
        print(
            "Bounds EPSG:3857 "
            f"minx={bounds_3857[0]:.2f} miny={bounds_3857[1]:.2f} "
            f"maxx={bounds_3857[2]:.2f} maxy={bounds_3857[3]:.2f}"
        )

        try:
            tile = reproject_to_web_mercator(
                da,
                width=256,
                height=256,
                bounds_3857=bounds_3857,
            )
        except Exception as exc:
            print(f"ERROR: Reprojection failed: {exc}", file=sys.stderr)
            return 8

        scaled, (vmin, vmax) = scale_to_uint8(
            tile,
            p_low=args.p_low,
            p_high=args.p_high,
            log_scale=args.log,
        )

        finite_mask = np.isfinite(tile)
        nonzero_mask = tile > EPS
        alpha_mask = finite_mask & nonzero_mask
        alpha = np.where(alpha_mask, 255, 0).astype(np.uint8)

        rgba = np.dstack([scaled, scaled, scaled, alpha])
        image = Image.fromarray(rgba, mode="RGBA")

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(out_path)

        tile_vals = tile[np.isfinite(tile)]
        if tile_vals.size:
            p_low = np.nanpercentile(tile_vals, args.p_low)
            p_high = np.nanpercentile(tile_vals, args.p_high)
            p50 = np.nanpercentile(tile_vals, 50)
        else:
            p_low = p_high = p50 = float("nan")

        total = tile.size
        finite_count = int(np.isfinite(tile).sum())
        nonzero_count = int((tile > EPS).sum())
        print(
            f"Tile stats: total={total} finite={finite_count} "
            f"({finite_count / total:.2%}) nonzero={nonzero_count} "
            f"({nonzero_count / total:.2%})"
        )
        print(
            f"Tile percentiles (raw): p{args.p_low}={p_low:.4f} "
            f"p50={p50:.4f} p{args.p_high}={p_high:.4f}"
        )
        print(f"Scaled range (after log={args.log}): vmin={vmin:.4f} vmax={vmax:.4f}")

        size = out_path.stat().st_size if out_path.exists() else 0
        print(f"Wrote {out_path} ({size} bytes)")

    finally:
        if ds is not None:
            ds.close()


if __name__ == "__main__":
    raise SystemExit(main())
