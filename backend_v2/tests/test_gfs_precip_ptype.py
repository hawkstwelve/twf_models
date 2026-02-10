from __future__ import annotations

import numpy as np
import xarray as xr

from app.models import get_model


def test_gfs_precip_ptype_varspec_is_prate_based_and_primary() -> None:
    gfs = get_model("gfs")
    hrrr = get_model("hrrr")

    spec = gfs.get_var("precip_ptype")
    assert spec is not None
    assert spec.id == "precip_ptype"
    assert spec.name == "Precipitation Intensity + Type"
    assert spec.primary is True
    assert spec.derived is True
    assert spec.derive == "precip_ptype_blend"
    assert spec.selectors.search == [":PRATE:surface:"]
    assert spec.selectors.hints.get("kind") == "precip_ptype"
    assert spec.selectors.hints.get("units") == "mm/hr"
    assert spec.selectors.hints.get("prate_component") == "precip_ptype"
    assert spec.selectors.hints.get("rain_component") == "crain"
    assert spec.selectors.hints.get("snow_component") == "csnow"
    assert spec.selectors.hints.get("sleet_component") == "cicep"
    assert spec.selectors.hints.get("frzr_component") == "cfrzr"
    assert hrrr.get_var("precip_ptype") is None


def test_gfs_precip_ptype_normalizes_prate_to_mm_per_hour() -> None:
    gfs = get_model("gfs")
    ds = xr.Dataset(
        {
            "prate": xr.DataArray(
                np.array([[0.001]], dtype=np.float32),
                dims=("y", "x"),
                attrs={
                    "GRIB_cfVarName": "prate",
                    "GRIB_shortName": "prate",
                    "GRIB_typeOfLevel": "surface",
                    "GRIB_units": "kg m**-2 s**-1",
                },
            )
        }
    )

    selected = gfs.select_dataarray(ds, "precip_ptype")
    assert isinstance(selected, xr.DataArray)
    assert selected.name == "precip_ptype"
    assert selected.attrs.get("GRIB_units") == "mm/hr"
    assert selected.attrs.get("units") == "mm/hr"
    assert np.isclose(float(selected.values[0, 0]), 0.001 * 3600.0, rtol=1e-6)


def test_gfs_precip_ptype_conversion_helper_mm_per_s_to_mm_per_hr() -> None:
    gfs = get_model("gfs")
    values = np.array([[0.001]], dtype=np.float32)

    converted = gfs._prate_mm_per_s_to_mm_per_hr(values)

    assert np.isclose(float(converted[0, 0]), 3.6, rtol=1e-6)
