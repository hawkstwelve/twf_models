from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.services import fetch_engine


def test_fetch_grib_gfs_refc_generic_path(monkeypatch, tmp_path: Path) -> None:
    day_dir = tmp_path / "20260206" / "06"
    day_dir.mkdir(parents=True, exist_ok=True)

    def fake_fetch_gfs_grib(*, run: str, variable: str | None = None, **kwargs):
        del kwargs
        assert run == "latest"
        assert variable == "refc"
        return SimpleNamespace(
            path=day_dir / "gfs.t06z.pgrb2.0p25f00.refc.grib2",
            is_full_file=False,
        )

    monkeypatch.setattr(fetch_engine, "fetch_gfs_grib", fake_fetch_gfs_grib)

    result = fetch_engine.fetch_grib(
        model="gfs",
        run="latest",
        fh=0,
        var="refc",
        region="pnw",
    )

    assert result.not_ready_reason is None
    assert result.grib_path is not None
    assert result.grib_path.name.endswith(".refc.grib2")


def test_fetch_grib_hrrr_refc_generic_path(monkeypatch, tmp_path: Path) -> None:
    day_dir = tmp_path / "20260206" / "06"
    day_dir.mkdir(parents=True, exist_ok=True)

    def fake_fetch_hrrr_grib(*, run: str, variable: str | None = None, **kwargs):
        del kwargs
        assert run == "latest"
        assert variable == "refc"
        return SimpleNamespace(
            path=day_dir / "hrrr.t06z.wrfsfcf00.refc.grib2",
            is_full_file=False,
        )

    monkeypatch.setattr(fetch_engine, "fetch_hrrr_grib", fake_fetch_hrrr_grib)

    result = fetch_engine.fetch_grib(
        model="hrrr",
        run="latest",
        fh=0,
        var="refc",
        region="pnw",
    )

    assert result.not_ready_reason is None
    assert result.grib_path is not None
    assert result.grib_path.name.endswith(".refc.grib2")


def test_fetch_grib_hrrr_radar_ptype_combo_components(monkeypatch, tmp_path: Path) -> None:
    day_dir = tmp_path / "20260206" / "15"
    day_dir.mkdir(parents=True, exist_ok=True)
    calls: list[tuple[str, str | None]] = []

    def fake_fetch_hrrr_grib(*, run: str, variable: str | None = None, **kwargs):
        del kwargs
        calls.append((run, variable))
        suffix = variable or "var"
        return SimpleNamespace(
            path=day_dir / f"hrrr.t15z.wrfsfcf00.{suffix}.grib2",
            is_full_file=False,
        )

    monkeypatch.setattr(fetch_engine, "fetch_hrrr_grib", fake_fetch_hrrr_grib)

    result = fetch_engine.fetch_grib(
        model="hrrr",
        run="latest",
        fh=0,
        var="radar_ptype",
        region="pnw",
    )

    assert result.not_ready_reason is None
    assert result.component_paths is not None
    assert calls == [
        ("latest", "refc"),
        ("latest", "crain"),
        ("latest", "csnow"),
        ("latest", "cicep"),
        ("latest", "cfrzr"),
    ]
