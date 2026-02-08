from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from app.services.grid import detect_latlon_names


def test_detect_latlon_names_from_standard_attrs() -> None:
    data = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    da = xr.DataArray(
        data,
        dims=("y", "x"),
        coords={
            "y": np.array([49.0, 48.5], dtype=np.float32),
            "x": np.array([-123.0, -122.5], dtype=np.float32),
        },
        name="field",
    )
    da.coords["y"].attrs["standard_name"] = "latitude"
    da.coords["y"].attrs["units"] = "degrees_north"
    da.coords["x"].attrs["standard_name"] = "longitude"
    da.coords["x"].attrs["units"] = "degrees_east"

    lat_name, lon_name = detect_latlon_names(da)
    assert lat_name == "y"
    assert lon_name == "x"


def test_detect_latlon_names_raises_without_candidates() -> None:
    da = xr.DataArray(
        np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
        dims=("row", "col"),
        coords={
            "row": np.array([0, 1], dtype=np.int32),
            "col": np.array([0, 1], dtype=np.int32),
        },
        name="field",
    )

    with pytest.raises(ValueError, match="Latitude/longitude coordinates not found"):
        detect_latlon_names(da)

