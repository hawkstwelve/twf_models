from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.services import fetch_engine


def test_wspd10m_latest_reuses_resolved_run_for_second_component(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    day_dir = tmp_path / "20260206" / "06"
    day_dir.mkdir(parents=True, exist_ok=True)

    def fake_fetch_gfs_grib(*, run: str, variable: str | None = None, **kwargs):
        del kwargs
        calls.append(run)
        suffix = variable or "var"
        return SimpleNamespace(
            path=day_dir / f"gfs.t06z.pgrb2.0p25f00.{suffix}.grib2",
            is_full_file=False,
        )

    monkeypatch.setattr(fetch_engine, "fetch_gfs_grib", fake_fetch_gfs_grib)

    result = fetch_engine.fetch_grib(
        model="gfs",
        run="latest",
        fh=0,
        var="wspd10m",
        region="pnw",
    )

    assert result.not_ready_reason is None
    assert result.component_paths is not None
    assert calls == ["latest", "20260206_06"]


def test_wspd10m_explicit_run_is_reused_for_both_components(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    day_dir = tmp_path / "20260206" / "06"
    day_dir.mkdir(parents=True, exist_ok=True)

    def fake_fetch_gfs_grib(*, run: str, variable: str | None = None, **kwargs):
        del kwargs
        calls.append(run)
        suffix = variable or "var"
        return SimpleNamespace(
            path=day_dir / f"gfs.t06z.pgrb2.0p25f00.{suffix}.grib2",
            is_full_file=False,
        )

    monkeypatch.setattr(fetch_engine, "fetch_gfs_grib", fake_fetch_gfs_grib)

    result = fetch_engine.fetch_grib(
        model="gfs",
        run="20260206_06",
        fh=0,
        var="wspd10m",
        region="pnw",
    )

    assert result.not_ready_reason is None
    assert result.component_paths is not None
    assert calls == ["20260206_06", "20260206_06"]
