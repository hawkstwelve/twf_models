from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from scripts.gfs_build_cog import (
    _coerce_run_id,
    _infer_spacing,
    _normalize_latlon_dataarray,
    _resolve_radar_component_paths,
)


def test_infer_spacing() -> None:
    values = np.array([0.0, 0.25, 0.5, 0.75], dtype=np.float64)
    spacing = _infer_spacing(values, axis_name="longitude")
    assert np.isclose(spacing, 0.25)


def test_normalize_latlon_dataarray_wraps_and_sorts() -> None:
    lat = np.array([10.0, 20.0], dtype=np.float32)  # ascending; should become descending
    lon = np.array([350.0, 0.0, 10.0], dtype=np.float32)  # wraps to [-10, 0, 10]
    values = np.array(
        [
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
        ],
        dtype=np.float32,
    )
    da = xr.DataArray(
        values,
        dims=("latitude", "longitude"),
        coords={"latitude": lat, "longitude": lon},
        name="t2m",
    )

    normalized, lat_name, lon_name = _normalize_latlon_dataarray(da)
    assert lat_name == "latitude"
    assert lon_name == "longitude"

    out_lat = normalized.coords["latitude"].values
    out_lon = normalized.coords["longitude"].values
    assert out_lat[0] > out_lat[-1]
    assert np.allclose(out_lon, np.array([-10.0, 0.0, 10.0], dtype=np.float32))


def test_coerce_run_id_prefers_explicit() -> None:
    fake_path = Path("/tmp/herbie_cache/gfs/gfs/20260206/06/file.grib2")
    assert _coerce_run_id("20260206_06z", fake_path) == "20260206_06z"
    assert _coerce_run_id(None, fake_path) == "20260206_06z"


def test_resolve_radar_component_paths() -> None:
    comp = {
        "refc": Path("/tmp/refc.grib2"),
        "crain": Path("/tmp/crain.grib2"),
    }
    refl, ptype = _resolve_radar_component_paths(comp, refl_key="refc", ptype_key="crain")
    assert refl.name == "refc.grib2"
    assert ptype.name == "crain.grib2"
