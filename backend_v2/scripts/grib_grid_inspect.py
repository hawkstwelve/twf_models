from __future__ import annotations

import sys
from pathlib import Path

# Add backend_v2 to path so app module can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))

import xarray as xr


def find_coord(ds: xr.Dataset, names: list[str]) -> str | None:
    for name in names:
        if name in ds.coords:
            return name
    return None


def describe_coord(ds: xr.Dataset, coord_name: str) -> None:
    coord = ds.coords[coord_name]
    values = coord.values

    dims = coord.dims
    shape = values.shape
    is_1d = values.ndim == 1
    is_2d = values.ndim == 2

    min_val = float(values.min()) if values.size else float("nan")
    max_val = float(values.max()) if values.size else float("nan")

    print(f"- {coord_name}:")
    print(f"  dims: {dims}")
    print(f"  shape: {shape}")
    print(f"  1D: {is_1d}, 2D: {is_2d}")
    print(f"  min: {min_val}")
    print(f"  max: {max_val}")

    if coord_name in ("latitude", "lat") and is_1d and values.size > 1:
        ascending = bool(values[0] < values[-1])
        order = "ascending" if ascending else "descending"
        print(f"  latitude order: {order}")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python grib_grid_inspect.py <path-to-grib2>")
        return 2

    grib_path = Path(sys.argv[1])
    if not grib_path.exists():
        print(f"File not found: {grib_path}")
        return 2

    try:
        ds = xr.open_dataset(grib_path, engine="cfgrib")
    except Exception as exc:
        print(f"Failed to open GRIB2 file: {exc}")
        return 1

    try:
        print("Dataset dimensions:")
        for dim, size in ds.dims.items():
            print(f"- {dim}: {size}")

        print("\nDataset coordinates:")
        for name in ds.coords.keys():
            print(f"- {name}")

        lat_name = find_coord(ds, ["latitude", "lat"])
        lon_name = find_coord(ds, ["longitude", "lon"])

        if lat_name or lon_name:
            print("\nCoordinate details:")
        if lat_name:
            describe_coord(ds, lat_name)
        else:
            print("- latitude: not found")
        if lon_name:
            describe_coord(ds, lon_name)
        else:
            print("- longitude: not found")

    finally:
        ds.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
