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
    def __init__(self, date: datetime, model: str, product: str, fxx: int, **_: object):
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


def test_fetch_hrrr_passes_priority_to_herbie(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = "2026020716"
    run_dt = datetime.strptime(run, "%Y%m%d%H")
    target_dir = tmp_path / run_dt.strftime("%Y%m%d") / run_dt.strftime("%H")
    target_dir.mkdir(parents=True, exist_ok=True)
    source = target_dir / "random_download_name.grib2"
    source.write_bytes(b"GRIB")
    expected = target_dir / "hrrr.t16z.wrfsfcf00.t2m.grib2"
    seen_priorities: list[object] = []

    class _PriorityHerbie:
        def __init__(self, date: datetime, model: str, product: str, fxx: int, **kwargs: object):
            self.date = date
            self.model = model
            self.product = product
            self.fxx = fxx
            self.grib = "dummy.grib2"
            seen_priorities.append(kwargs.get("priority"))

        def download(self, save_dir: Path, search: str | None = None):
            del search
            assert save_dir == target_dir
            return source

    monkeypatch.setattr("app.services.hrrr_fetch.Herbie", _PriorityHerbie)
    monkeypatch.setattr("app.services.hrrr_fetch.TWF_HRRR_PRIORITY", "aws")
    monkeypatch.setattr("app.services.hrrr_fetch._subset_contains_required_variables", lambda *args, **kwargs: True)

    result = fetch_hrrr_grib(
        run=run,
        fh=0,
        model="hrrr",
        product="sfc",
        variable="tmp2m",
        cache_cfg=HRRRCacheConfig(base_dir=tmp_path, keep_runs=1),
    )

    assert result.path == expected
    assert expected.exists()
    assert seen_priorities
    assert seen_priorities[0] == ["aws"]
