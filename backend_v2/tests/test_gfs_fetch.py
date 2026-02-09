from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import requests

from app.services import gfs_fetch
from app.services.herbie_priority import DEFAULT_HERBIE_PRIORITY, parse_herbie_priority


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

    seen_priorities: list[object] = []

    class _DownloadHerbie(_DummyHerbie):
        def __init__(self, date: datetime, **kwargs: object) -> None:
            super().__init__(date, **kwargs)
            seen_priorities.append(kwargs.get("priority"))

        def download(self, _search: str, save_dir: Path):
            assert save_dir == target_dir
            return source

    monkeypatch.setattr(gfs_fetch, "Herbie", _DownloadHerbie)
    monkeypatch.setattr(
        gfs_fetch,
        "_subset_contains_required_variables",
        lambda *args, **kwargs: (True, ["tmp2m"], []),
    )

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
    assert seen_priorities
    assert seen_priorities[0] == parse_herbie_priority(DEFAULT_HERBIE_PRIORITY)


def test_parse_run_datetime_accepts_scheduler_run_id() -> None:
    parsed = gfs_fetch._parse_run_datetime("20260206_06z")
    assert parsed is not None
    assert parsed.strftime("%Y%m%d%H") == "2026020606"


def test_fetch_timeout_returns_not_ready_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = "2026020600"

    class _TimeoutHerbie(_DummyHerbie):
        def download(self, _search: str, save_dir: Path):
            del save_dir
            raise requests.exceptions.ReadTimeout("upstream timeout")

    monkeypatch.setattr(gfs_fetch, "Herbie", _TimeoutHerbie)

    result = gfs_fetch.fetch_gfs_grib(
        run=run,
        fh=0,
        model="gfs",
        product="pgrb2.0p25",
        variable="t2m",
        search_override=":TMP:2 m above ground:",
        cache_dir=tmp_path,
    )

    assert result.path is None
    assert result.not_ready_reason is not None


def test_parse_herbie_priority_defaults_when_missing() -> None:
    assert parse_herbie_priority(None) == DEFAULT_HERBIE_PRIORITY.split(",")


def test_parse_herbie_priority_single_source() -> None:
    assert parse_herbie_priority("aws") == ["aws"]


def test_latest_probe_uses_six_hour_cycles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen_dates: list[datetime] = []

    class _FixedDateTime(datetime):
        @classmethod
        def utcnow(cls) -> datetime:
            return cls(2026, 2, 9, 23, 12, 0)

    class _ProbeHerbie(_DummyHerbie):
        def __init__(self, date: datetime, **kwargs: object) -> None:
            super().__init__(date, **kwargs)
            seen_dates.append(date)
            self.grib = "dummy.grib2" if date.hour == 18 else None

        def download(self, _search: str, save_dir: Path):
            run_dt = self.date
            target_dir = save_dir / run_dt.strftime("%Y%m%d") / run_dt.strftime("%H")
            target_dir.mkdir(parents=True, exist_ok=True)
            source = target_dir / "random_download_name.grib2"
            source.write_bytes(b"GRIB")
            return source

    monkeypatch.setattr(gfs_fetch, "datetime", _FixedDateTime)
    monkeypatch.setattr(gfs_fetch, "Herbie", _ProbeHerbie)
    monkeypatch.setattr(
        gfs_fetch,
        "_subset_contains_required_variables",
        lambda *args, **kwargs: (True, ["tmp2m"], []),
    )

    result = gfs_fetch.fetch_gfs_grib(
        run="latest",
        fh=0,
        model="gfs",
        product="pgrb2.0p25",
        variable="t2m",
        search_override=":TMP:2 m above ground:",
        cache_dir=tmp_path,
        lookback_hours=12,
    )

    assert result.path is not None
    assert seen_dates
    assert seen_dates[0].hour == 18
    assert all(dt.hour in {0, 6, 12, 18} for dt in seen_dates)
