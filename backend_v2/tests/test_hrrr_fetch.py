from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.services.hrrr_fetch import fetch_hrrr_grib
from app.services.hrrr_runs import HRRRCacheConfig


class _Fake404Response:
    status_code = 404


class _FakeHTTPError(Exception):
    def __init__(self):
        super().__init__("404 Client Error")
        self.response = _Fake404Response()


class _FakeHerbie:
    def __init__(self, date: datetime, model: str, product: str, fxx: int):
        self.date = date
        self.model = model
        self.product = product
        self.fxx = fxx
        self.grib = None

    def download(self, save_dir: Path, search: str | None = None):
        del save_dir, search
        raise _FakeHTTPError()


def test_fetch_hrrr_404_is_not_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.services.hrrr_fetch.Herbie", _FakeHerbie)

    result = fetch_hrrr_grib(
        run="20260207_16",
        fh=18,
        model="hrrr",
        product="sfc",
        variable="tmp2m",
        cache_cfg=HRRRCacheConfig(base_dir=tmp_path, keep_runs=1),
    )

    assert result.path is None
    assert result.not_ready_reason is not None
    assert "404" in result.not_ready_reason
