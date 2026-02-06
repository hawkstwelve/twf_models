from __future__ import annotations

import numpy as np
import xarray as xr

from app.models.base import VarSelectors, VarSpec
from scripts.build_cog_v2 import _encode_with_nodata
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
        if backend_kwargs is None:
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
    assert calls[0] is None
    assert calls[1] == {"filter_by_keys": {"stepType": "instant"}}


def test_open_cfgrib_dataset_uses_selector_filter_keys(monkeypatch) -> None:
    calls: list[dict | None] = []

    def fake_open_dataset(path, *, engine=None, backend_kwargs=None):
        del path
        assert engine == "cfgrib"
        calls.append(backend_kwargs)
        if backend_kwargs is None:
            raise Exception("multiple values for key 'typeOfLevel'")
        return "ok"

    monkeypatch.setattr(build_cog_v2.xr, "open_dataset", fake_open_dataset)
    spec = VarSpec(
        id="tmp2m",
        name="2m Temp",
        selectors=VarSelectors(filter_by_keys={"typeOfLevel": "heightAboveGround", "level": "2"}),
    )
    result = build_cog_v2._open_cfgrib_dataset("/tmp/fake.grib2", spec)
    assert result == "ok"
    assert calls[1] == {
        "filter_by_keys": {
            "typeOfLevel": "heightAboveGround",
            "level": 2,
        }
    }
