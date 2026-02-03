from __future__ import annotations

import sys
from pathlib import Path

import xarray as xr

from app.services.variable_registry import fingerprint_da


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python grib_vars_fingerprint.py <path-to-grib2>")
        return 2

    grib_path = Path(sys.argv[1])
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
        for name in sorted(ds.data_vars):
            print(fingerprint_da(ds[name]))
    finally:
        ds.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
