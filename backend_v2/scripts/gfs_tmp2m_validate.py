from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add backend_v2 to path so app module can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))

import numpy as np
import xarray as xr

from app.models import get_model
from app.services.fetch_engine import fetch_grib
from app.services.grid import detect_latlon_names


def _collect_fill_values(da: xr.DataArray) -> list[float]:
    values: list[float] = []
    for source in (da.attrs, getattr(da, "encoding", {}) or {}):
        for key in ("_FillValue", "missing_value", "GRIB_missingValue", "GRIB_missingValueAtSea"):
            raw = source.get(key)
            if raw is None:
                continue
            if isinstance(raw, (list, tuple, np.ndarray)):
                for item in raw:
                    try:
                        num = float(item)
                    except (TypeError, ValueError):
                        continue
                    if np.isfinite(num):
                        values.append(num)
            else:
                try:
                    num = float(raw)
                except (TypeError, ValueError):
                    continue
                if np.isfinite(num):
                    values.append(num)
    return values


def _lat_orientation(lat_values: np.ndarray) -> str:
    if lat_values.ndim == 1:
        if lat_values.size < 2:
            return "unknown"
        return "ascending" if bool(lat_values[0] < lat_values[-1]) else "descending"
    if lat_values.ndim == 2:
        top = float(np.nanmean(lat_values[0, :]))
        bottom = float(np.nanmean(lat_values[-1, :]))
        if np.isclose(top, bottom):
            return "flat"
        return "descending" if top > bottom else "ascending"
    return "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M2.5 validation for GFS tmp2m subset + DataArray extraction.")
    parser.add_argument("--model", default="gfs")
    parser.add_argument("--region", default="pnw")
    parser.add_argument("--run", default="latest")
    parser.add_argument("--fh", type=int, default=0)
    parser.add_argument("--var", default="tmp2m")
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--lookback-hours", type=int, default=18)
    parser.add_argument("--max-probe-seconds", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plugin = get_model(args.model)
    normalized_var = plugin.normalize_var_id(args.var)

    if normalized_var != "tmp2m":
        print(f"ERROR: This validator is scoped to tmp2m, got {args.var} -> {normalized_var}")
        return 2

    result = fetch_grib(
        model=args.model,
        run=args.run,
        fh=args.fh,
        var=normalized_var,
        region=args.region,
        cache_dir=args.cache_dir,
        timeout=args.timeout,
        lookback_hours=args.lookback_hours,
        max_probe_seconds=args.max_probe_seconds,
    )
    if result.not_ready_reason:
        print(f"UPSTREAM_NOT_READY: {result.not_ready_reason}")
        return 3
    if result.grib_path is None:
        print("ERROR: fetch_grib returned no GRIB path")
        return 4

    grib_path = result.grib_path
    print(f"GRIB subset path: {grib_path}")
    print(f"Resolved upstream run: {result.upstream_run_id}")

    var_spec = plugin.get_var(normalized_var)
    backend_kwargs: dict[str, object] = {}
    if var_spec and var_spec.selectors.filter_by_keys:
        filter_keys: dict[str, object] = {}
        for key, value in var_spec.selectors.filter_by_keys.items():
            if key == "level":
                try:
                    filter_keys[key] = int(value)
                except (TypeError, ValueError):
                    filter_keys[key] = value
            else:
                filter_keys[key] = value
        if filter_keys:
            backend_kwargs["filter_by_keys"] = filter_keys

    try:
        ds = xr.open_dataset(grib_path, engine="cfgrib", backend_kwargs=backend_kwargs or None)
    except Exception as exc:
        print(f"ERROR: failed to open GRIB subset with cfgrib: {exc}")
        return 5

    try:
        da = plugin.select_dataarray(ds, normalized_var)
        if "time" in da.dims:
            da = da.isel(time=0)
        da = da.squeeze()

        lat_name, lon_name = detect_latlon_names(da)
        lat_values = da.coords[lat_name].values
        lon_values = da.coords[lon_name].values

        units = str(da.attrs.get("GRIB_units") or "unknown")
        fill_values = _collect_fill_values(da)
        values = np.asarray(da.values, dtype=np.float32)

        valid_mask = np.isfinite(values)
        for fill_value in fill_values:
            valid_mask &= values != fill_value

        valid_count = int(np.count_nonzero(valid_mask))
        total_count = int(values.size)
        nodata_count = total_count - valid_count

        payload = {
            "model": args.model,
            "region": args.region,
            "run_requested": args.run,
            "run_resolved": result.upstream_run_id,
            "fh": args.fh,
            "var_requested": args.var,
            "var_selected": str(da.name),
            "dims": list(da.dims),
            "shape": list(da.shape),
            "coord_names": [lat_name, lon_name],
            "lat_orientation": _lat_orientation(np.asarray(lat_values)),
            "units": units,
            "fill_values": fill_values,
            "valid_count": valid_count,
            "nodata_count": nodata_count,
            "total_count": total_count,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))

        if da.ndim < 2:
            print("ERROR: selected DataArray is not at least 2D")
            return 6
        if not lat_name or not lon_name:
            print("ERROR: lat/lon coordinate names not found")
            return 7
        if valid_count == 0:
            print("ERROR: no valid data after nodata mask")
            return 8
    finally:
        ds.close()

    print("M2.5 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
