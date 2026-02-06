from __future__ import annotations

import numpy as np
import xarray as xr

from app.models.gfs import GFS_INITIAL_FHS, GFS_MODEL
from app.services.variable_registry import herbie_search_for


def _make_da(
    name: str,
    value: float,
    *,
    cf_var: str,
    short_name: str,
    type_of_level: str,
    level: int,
) -> xr.DataArray:
    return xr.DataArray(
        np.full((2, 2), value, dtype=np.float32),
        dims=("y", "x"),
        name=name,
        attrs={
            "GRIB_cfVarName": cf_var,
            "GRIB_shortName": short_name,
            "GRIB_typeOfLevel": type_of_level,
            "GRIB_level": level,
        },
    )


def test_herbie_search_for_model_gfs() -> None:
    assert herbie_search_for("tmp2m", model="gfs") == ":TMP:2 m above ground:"
    assert herbie_search_for("10u", model="gfs") == ":UGRD:10 m above ground:"
    assert herbie_search_for("refc", model="gfs") == ":REFC:"
    assert herbie_search_for("crain", model="gfs") == ":CRAIN:surface:"
    assert herbie_search_for("prate", model="gfs") is None


def test_gfs_plugin_initial_fh_policy() -> None:
    assert GFS_MODEL.target_fhs(0) == list(GFS_INITIAL_FHS)
    assert GFS_MODEL.target_fhs(18) == list(GFS_INITIAL_FHS)


def test_gfs_plugin_normalize_var_id() -> None:
    assert GFS_MODEL.normalize_var_id("tmp2m") == "tmp2m"
    assert GFS_MODEL.normalize_var_id("t2m") == "tmp2m"
    assert GFS_MODEL.normalize_var_id("2t") == "tmp2m"
    assert GFS_MODEL.normalize_var_id("wspd10m") == "wspd10m"
    assert GFS_MODEL.normalize_var_id("cref") == "refc"
    assert GFS_MODEL.normalize_var_id("refc") == "refc"
    assert GFS_MODEL.normalize_var_id("ugrd10m") == "10u"
    assert GFS_MODEL.normalize_var_id("radar_ptype") == "radar_ptype"


def test_gfs_plugin_contains_radar_ptype_specs() -> None:
    combo = GFS_MODEL.get_var("radar_ptype")
    assert combo is not None
    assert combo.derived is True
    assert combo.derive == "radar_ptype_combo"


def test_gfs_plugin_select_tmp2m_from_selector_attrs() -> None:
    da_bad = _make_da(
        "noise",
        100.0,
        cf_var="t2m",
        short_name="2t",
        type_of_level="surface",
        level=0,
    )
    da_good = _make_da(
        "candidate",
        273.15,
        cf_var="t2m",
        short_name="2t",
        type_of_level="heightAboveGround",
        level=2,
    )
    ds = xr.Dataset({"noise": da_bad, "candidate": da_good})

    selected = GFS_MODEL.select_dataarray(ds, "tmp2m")
    assert selected.name == "candidate"
    assert np.isclose(float(selected.values[0, 0]), 273.15)


def test_gfs_plugin_select_wspd10m_derivation() -> None:
    u = _make_da(
        "u_component",
        3.0,
        cf_var="u10",
        short_name="10u",
        type_of_level="heightAboveGround",
        level=10,
    )
    v = _make_da(
        "v_component",
        4.0,
        cf_var="v10",
        short_name="10v",
        type_of_level="heightAboveGround",
        level=10,
    )
    ds = xr.Dataset({"u_component": u, "v_component": v})

    speed = GFS_MODEL.select_dataarray(ds, "wspd10m")
    expected = 5.0 * 2.23694
    assert speed.name == "wspd10m"
    assert speed.attrs.get("GRIB_units") == "mph"
    assert np.allclose(speed.values, expected)


def test_gfs_plugin_select_wspd10m_ignores_nondim_coord_merge() -> None:
    u = _make_da(
        "u_component",
        3.0,
        cf_var="u10",
        short_name="10u",
        type_of_level="heightAboveGround",
        level=10,
    ).assign_coords(step=np.timedelta64(0, "h"))
    v = _make_da(
        "v_component",
        4.0,
        cf_var="v10",
        short_name="10v",
        type_of_level="heightAboveGround",
        level=10,
    ).assign_coords(step=np.timedelta64(0, "h"))
    ds = xr.Dataset({"u_component": u, "v_component": v})

    speed = GFS_MODEL.select_dataarray(ds, "wspd10m")
    assert speed.name == "wspd10m"
    assert np.allclose(speed.values, 5.0 * 2.23694)
