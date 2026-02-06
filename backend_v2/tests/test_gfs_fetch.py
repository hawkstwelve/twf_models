from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.services import gfs_fetch


class _DummyHerbie:
    def __init__(self, date: datetime, **_: object) -> None:
        self.date = date
        self.grib = "dummy.grib2"

    def download(self, _search: str, save_dir: Path):  # pragma: no cover - behavior set in tests
        raise NotImplementedError


def test_fetch_refuses_overwrite_when_expected_unreadable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = "2026020600"
    run_dt = datetime.strptime(run, "%Y%m%d%H")
    target_dir = tmp_path / run_dt.strftime("%Y%m%d") / run_dt.strftime("%H")
    target_dir.mkdir(parents=True, exist_ok=True)
    expected = target_dir / "gfs.t00z.pgrb2.0p25f00.t2m.grib2"
    expected.write_bytes(b"")

    monkeypatch.setattr(gfs_fetch, "Herbie", _DummyHerbie)

    with pytest.raises(RuntimeError, match="Immutable cache conflict"):
        gfs_fetch.fetch_gfs_grib(
            run=run,
            fh=0,
            model="gfs",
            product="pgrb2.0p25",
            variable="t2m",
            search_override=":TMP:2 m above ground:",
            cache_dir=tmp_path,
        )


def test_fetch_moves_download_into_deterministic_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = "2026020600"
    run_dt = datetime.strptime(run, "%Y%m%d%H")
    target_dir = tmp_path / run_dt.strftime("%Y%m%d") / run_dt.strftime("%H")
    target_dir.mkdir(parents=True, exist_ok=True)
    source = target_dir / "random_download_name.grib2"
    source.write_bytes(b"GRIB")
    expected = target_dir / "gfs.t00z.pgrb2.0p25f00.t2m.grib2"

    class _DownloadHerbie(_DummyHerbie):
        def download(self, _search: str, save_dir: Path):
            assert save_dir == target_dir
            return source

    monkeypatch.setattr(gfs_fetch, "Herbie", _DownloadHerbie)

    result = gfs_fetch.fetch_gfs_grib(
        run=run,
        fh=0,
        model="gfs",
        product="pgrb2.0p25",
        variable="t2m",
        search_override=":TMP:2 m above ground:",
        cache_dir=tmp_path,
    )

    assert result.path == expected
    assert expected.exists()
    assert not source.exists()


def test_parse_run_datetime_accepts_scheduler_run_id() -> None:
    parsed = gfs_fetch._parse_run_datetime("20260206_06z")
    assert parsed is not None
    assert parsed.strftime("%Y%m%d%H") == "2026020606"
