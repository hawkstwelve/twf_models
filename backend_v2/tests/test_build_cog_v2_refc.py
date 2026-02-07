from __future__ import annotations

import numpy as np
import xarray as xr

from app.models.base import VarSelectors, VarSpec
from scripts.build_cog_v2 import _encode_radar_ptype_combo, _encode_with_nodata, resolve_target_grid_meters
from scripts import build_cog_v2


def test_encode_with_nodata_refc_masks_sub_threshold() -> None:
    values = np.array([[0.0, 5.0], [10.0, 20.0]], dtype=np.float32)
    da = xr.DataArray(values, dims=("y", "x"), name="refc")

    byte_band, alpha, meta, _, _, _ = _encode_with_nodata(
        values,
        requested_var="refc",
        normalized_var="refc",
        da=da,
        allow_range_fallback=False,
    )

    assert meta["kind"] == "discrete"
    assert int(alpha[0, 0]) == 0
    assert int(alpha[0, 1]) == 0
    assert int(alpha[1, 0]) == 255
    assert int(alpha[1, 1]) == 255
    # first visible threshold should map to first color bin
    assert int(byte_band[1, 0]) == 0


def test_open_cfgrib_dataset_retries_step_type(monkeypatch) -> None:
    calls: list[dict | None] = []

    def fake_open_dataset(path, *, engine=None, backend_kwargs=None):
        del path
        assert engine == "cfgrib"
        calls.append(backend_kwargs)
        if backend_kwargs == {"indexpath": ""}:
            raise Exception(
                "multiple values for unique key, try re-open the file with one of: "
                "filter_by_keys={'stepType': 'instant'}"
            )
        if backend_kwargs.get("filter_by_keys", {}).get("stepType") == "instant":
            return "ok"
        raise Exception("still failing")

    monkeypatch.setattr(build_cog_v2.xr, "open_dataset", fake_open_dataset)
    spec = VarSpec(id="crain", name="Categorical Rain", selectors=VarSelectors())
    result = build_cog_v2._open_cfgrib_dataset("/tmp/fake.grib2", spec)
    assert result == "ok"
    assert calls[0] == {"indexpath": ""}
    assert calls[1] == {"filter_by_keys": {"stepType": "instant"}, "indexpath": ""}


def test_open_cfgrib_dataset_uses_selector_filter_keys(monkeypatch) -> None:
    calls: list[dict | None] = []

    def fake_open_dataset(path, *, engine=None, backend_kwargs=None):
        del path
        assert engine == "cfgrib"
        calls.append(backend_kwargs)
        return "ok"

    monkeypatch.setattr(build_cog_v2.xr, "open_dataset", fake_open_dataset)
    spec = VarSpec(
        id="tmp2m",
        name="2m Temp",
        selectors=VarSelectors(filter_by_keys={"typeOfLevel": "heightAboveGround", "level": "2"}),
    )
    result = build_cog_v2._open_cfgrib_dataset("/tmp/fake.grib2", spec)
    assert result == "ok"
    assert calls[0] == {
        "filter_by_keys": {
            "typeOfLevel": "heightAboveGround",
            "level": 2,
        },
        "indexpath": "",
    }


def test_encode_radar_ptype_combo_masks_no_ptype() -> None:
    refl = np.array([[20.0, 20.0], [20.0, np.nan]], dtype=np.float32)
    rain = np.array([[1.0, 0.0], [0.0, 0.0]], dtype=np.float32)
    snow = np.array([[0.0, 1.0], [0.0, 0.0]], dtype=np.float32)
    sleet = np.array([[0.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    frzr = np.zeros((2, 2), dtype=np.float32)

    byte_band, alpha, meta = _encode_radar_ptype_combo(
        requested_var="radar_ptype",
        normalized_var="radar_ptype",
        refl_values=refl,
        ptype_values={
            "crain": rain,
            "csnow": snow,
            "cicep": sleet,
            "cfrzr": frzr,
        },
    )

    assert meta["spec_key"] == "radar_ptype"
    assert int(alpha[0, 0]) == 255
    assert int(alpha[0, 1]) == 255
    assert int(alpha[1, 0]) == 255
    assert int(alpha[1, 1]) == 0
    assert int(byte_band[1, 1]) == 255


def test_encode_radar_ptype_combo_prefers_dominant_component() -> None:
    refl = np.array([[30.0]], dtype=np.float32)
    rain = np.array([[0.4]], dtype=np.float32)
    snow = np.array([[0.8]], dtype=np.float32)
    sleet = np.array([[0.1]], dtype=np.float32)
    frzr = np.array([[0.2]], dtype=np.float32)

    byte_band, alpha, meta = _encode_radar_ptype_combo(
        requested_var="radar_ptype",
        normalized_var="radar_ptype",
        refl_values=refl,
        ptype_values={
            "crain": rain,
            "csnow": snow,
            "cicep": sleet,
            "cfrzr": frzr,
        },
    )

    assert int(alpha[0, 0]) == 255
    snow_offset = int(meta["ptype_breaks"]["snow"]["offset"])
    frzr_offset = int(meta["ptype_breaks"]["frzr"]["offset"])
    pixel = int(byte_band[0, 0])
    assert snow_offset <= pixel < frzr_offset


def test_encode_radar_ptype_combo_uses_argmax_threshold() -> None:
    refl = np.array([[30.0]], dtype=np.float32)
    # All masks below threshold should fall back to rain colorization.
    rain = np.array([[0.05]], dtype=np.float32)
    snow = np.array([[0.06]], dtype=np.float32)
    sleet = np.array([[0.07]], dtype=np.float32)
    frzr = np.array([[0.08]], dtype=np.float32)

    byte_band, alpha, meta = _encode_radar_ptype_combo(
        requested_var="radar_ptype",
        normalized_var="radar_ptype",
        refl_values=refl,
        ptype_values={
            "crain": rain,
            "csnow": snow,
            "cicep": sleet,
            "cfrzr": frzr,
        },
    )

    assert int(alpha[0, 0]) == 255
    assert int(byte_band[0, 0]) != 255
    assert meta["ptype_blend"] == "winner_argmax_threshold"
    assert float(meta["ptype_threshold"]) == 0.10
    assert float(meta["refl_min_dbz"]) == 10.0
    assert meta["ptype_noinfo_fallback"] == "rain"


def test_encode_radar_ptype_combo_auto_scales_percent_inputs() -> None:
    refl = np.array([[30.0]], dtype=np.float32)
    rain = np.array([[0.0]], dtype=np.float32)
    snow = np.array([[100.0]], dtype=np.float32)
    sleet = np.array([[0.0]], dtype=np.float32)
    frzr = np.array([[0.0]], dtype=np.float32)

    byte_band, alpha, meta = _encode_radar_ptype_combo(
        requested_var="radar_ptype",
        normalized_var="radar_ptype",
        refl_values=refl,
        ptype_values={
            "crain": rain,
            "csnow": snow,
            "cicep": sleet,
            "cfrzr": frzr,
        },
    )

    assert int(alpha[0, 0]) == 255
    snow_offset = int(meta["ptype_breaks"]["snow"]["offset"])
    frzr_offset = int(meta["ptype_breaks"]["frzr"]["offset"])
    pixel = int(byte_band[0, 0])
    assert snow_offset <= pixel < frzr_offset
    assert meta["ptype_scale"]["snow"] == "percent_to_fraction"


def test_resolve_target_grid_meters_defaults(monkeypatch) -> None:
    monkeypatch.delenv("TWF_TARGET_GRID_METERS", raising=False)
    monkeypatch.delenv("TWF_TARGET_GRID_METERS_HRRR", raising=False)
    monkeypatch.delenv("TWF_TARGET_GRID_METERS_GFS", raising=False)
    monkeypatch.delenv("TWF_TARGET_GRID_METERS_ECMWF", raising=False)
    monkeypatch.delenv("TWF_TARGET_GRID_METERS_GFS_PNW", raising=False)
    monkeypatch.delenv("TWF_TARGET_GRID_METERS_GFS_CONUS", raising=False)

    assert resolve_target_grid_meters("hrrr", "pnw") == (3000.0, 3000.0)
    assert resolve_target_grid_meters("gfs", "pnw") == (25000.0, 25000.0)
    assert resolve_target_grid_meters("gfs", "conus") == (25000.0, 25000.0)
    assert resolve_target_grid_meters("ecmwf", "pnw") == (9000.0, 9000.0)


def test_resolve_target_grid_meters_override_precedence(monkeypatch) -> None:
    monkeypatch.setenv("TWF_TARGET_GRID_METERS_GFS", "20000")
    monkeypatch.setenv("TWF_TARGET_GRID_METERS_GFS_PNW", "22000")
    monkeypatch.setenv("TWF_TARGET_GRID_METERS", "18000")
    assert resolve_target_grid_meters("gfs", "pnw") == (18000.0, 18000.0)

    monkeypatch.delenv("TWF_TARGET_GRID_METERS", raising=False)
    assert resolve_target_grid_meters("gfs", "pnw") == (22000.0, 22000.0)

    monkeypatch.delenv("TWF_TARGET_GRID_METERS_GFS_PNW", raising=False)
    assert resolve_target_grid_meters("gfs", "pnw") == (20000.0, 20000.0)
