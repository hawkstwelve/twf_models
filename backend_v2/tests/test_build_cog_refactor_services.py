from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from app.models.base import VarSelectors, VarSpec
from app.services.georef import derive_georef
from scripts import build_cog


def test_open_cfgrib_dataset_strict_never_broad_opens_when_filters_exist(monkeypatch) -> None:
    calls: list[dict | None] = []

    def fake_open_dataset(path, *, engine=None, backend_kwargs=None):
        del path
        assert engine == "cfgrib"
        calls.append(backend_kwargs)
        raise Exception("still failing")

    monkeypatch.setattr(build_cog.xr, "open_dataset", fake_open_dataset)
    spec = VarSpec(
        id="tmp2m",
        name="2m Temp",
        selectors=VarSelectors(filter_by_keys={"typeOfLevel": "heightAboveGround", "level": "2"}),
    )

    with pytest.raises(RuntimeError, match="Failed strict cfgrib open"):
        build_cog._open_cfgrib_dataset_strict("/tmp/fake.grib2", spec)

    assert calls
    assert not any(call == {"indexpath": ""} for call in calls)
    assert all("filter_by_keys" in (call or {}) for call in calls)


def test_open_cfgrib_dataset_strict_without_filters_falls_back_to_broad_open(monkeypatch) -> None:
    calls: list[dict | None] = []

    def fake_open_dataset(path, *, engine=None, backend_kwargs=None):
        del path
        assert engine == "cfgrib"
        calls.append(backend_kwargs)
        if backend_kwargs == {"indexpath": ""}:
            return "ok"
        raise Exception("unexpected filtered retry")

    monkeypatch.setattr(build_cog.xr, "open_dataset", fake_open_dataset)
    spec = VarSpec(id="unknown", name="Unknown", selectors=VarSelectors())
    result = build_cog._open_cfgrib_dataset_strict("/tmp/fake.grib2", spec)
    assert result == "ok"
    assert calls == [{"indexpath": ""}]


def test_derive_georef_latlon_coords_matches_grib_attr_fallback() -> None:
    values = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)

    da_coords = xr.DataArray(
        values,
        dims=("latitude", "longitude"),
        coords={
            "latitude": np.array([44.0, 45.0], dtype=np.float32),
            "longitude": np.array([0.0, 1.0, 2.0], dtype=np.float32),
        },
    )
    georef_coords = derive_georef(da_coords, [values])

    da_attrs = xr.DataArray(
        values,
        dims=("y", "x"),
        attrs={
            "GRIB_Nx": 3,
            "GRIB_Ny": 2,
            "GRIB_longitudeOfFirstGridPointInDegrees": 0.0,
            "GRIB_longitudeOfLastGridPointInDegrees": 2.0,
            "GRIB_latitudeOfFirstGridPointInDegrees": 44.0,
            "GRIB_latitudeOfLastGridPointInDegrees": 45.0,
            "GRIB_iDirectionIncrementInDegrees": 1.0,
            "GRIB_jDirectionIncrementInDegrees": 1.0,
            "GRIB_iScansNegatively": 0,
            "GRIB_jScansPositively": 1,
        },
    )
    georef_attrs = derive_georef(da_attrs, [values])

    assert georef_coords.used_latlon is True
    assert georef_attrs.used_latlon is True
    assert georef_coords.geotransform == georef_attrs.geotransform
    assert np.array_equal(georef_coords.arrays[0], georef_attrs.arrays[0])


def test_derive_georef_uses_lambert_when_attrs_present() -> None:
    values = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    da = xr.DataArray(
        values,
        dims=("y", "x"),
        attrs={
            "GRIB_Nx": 2,
            "GRIB_Ny": 2,
            "GRIB_DxInMetres": 3000.0,
            "GRIB_DyInMetres": 3000.0,
            "GRIB_LoVInDegrees": -97.5,
            "GRIB_Latin1InDegrees": 38.5,
            "GRIB_Latin2InDegrees": 38.5,
            "GRIB_LaDInDegrees": 38.5,
            "GRIB_latitudeOfFirstGridPointInDegrees": 21.138,
            "GRIB_longitudeOfFirstGridPointInDegrees": -122.719,
            "GRIB_iScansNegatively": 0,
            "GRIB_jScansPositively": 1,
        },
    )

    georef = derive_georef(da, [values])
    assert georef.used_latlon is False
    assert georef.source == "lambert"
    assert georef.arrays[0].shape == values.shape


def test_encode_meta_tmp2m_unchanged() -> None:
    values = np.array([[273.15, 300.0], [250.0, 260.0]], dtype=np.float32)
    da = xr.DataArray(values, dims=("y", "x"), name="tmp2m")
    _, _, meta, _, _, _ = build_cog._encode_with_nodata(
        values,
        requested_var="tmp2m",
        normalized_var="tmp2m",
        da=da,
        allow_range_fallback=False,
    )
    assert meta["spec_key"] == "tmp2m"
    assert meta["kind"] == "continuous"
    assert meta["units"] == "F"
    assert meta["range"] == [-40.0, 120.0]
    assert meta["output_mode"] == "byte_alpha"


def test_encode_meta_radar_ptype_combo_unchanged() -> None:
    refl = np.array([[30.0]], dtype=np.float32)
    rain = np.array([[1.0]], dtype=np.float32)
    zeros = np.zeros((1, 1), dtype=np.float32)
    _, _, meta = build_cog._encode_radar_ptype_combo(
        requested_var="radar_ptype",
        normalized_var="radar_ptype",
        refl_values=refl,
        ptype_values={"crain": rain, "csnow": zeros, "cicep": zeros, "cfrzr": zeros},
    )
    assert meta["spec_key"] == "radar_ptype"
    assert meta["kind"] == "discrete"
    assert meta["units"] == "dBZ"
    assert meta["ptype_noinfo_fallback"] == "rain"
    assert meta["output_mode"] == "byte_alpha"


def test_encode_meta_precip_ptype_unchanged() -> None:
    prate = np.array([[0.001]], dtype=np.float32)
    zeros = np.zeros((1, 1), dtype=np.float32)
    _, meta = build_cog._encode_precip_ptype_blend(
        requested_var="precip_ptype",
        normalized_var="precip_ptype",
        prate_values=prate,
        ptype_values={"crain": zeros, "csnow": zeros, "cicep": zeros, "cfrzr": zeros},
    )
    assert meta["spec_key"] == "precip_ptype"
    assert meta["kind"] == "discrete"
    assert meta["units"] == "mm/hr"
    assert meta["encoding"] == "singleband_nodata0"
    assert meta["index_shift"] == 1
    assert meta["output_mode"] == "byte_singleband"
