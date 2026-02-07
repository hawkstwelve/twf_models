from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.services import fetch_engine


def test_wspd10m_latest_reuses_resolved_run_for_second_component(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    seen: dict[str, object] = {}
    day_dir = tmp_path / "20260206" / "06"
    day_dir.mkdir(parents=True, exist_ok=True)

    def fake_fetch_gfs_grib(
        *,
        run: str,
        variable: str | None = None,
        search_override: str | None = None,
        cache_key: str | None = None,
        required_vars: list[str] | None = None,
        **kwargs,
    ):
        del kwargs
        calls.append(run)
        seen["search_override"] = search_override
        seen["cache_key"] = cache_key
        seen["required_vars"] = required_vars
        suffix = cache_key or variable or "var"
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
    assert result.component_paths is None
    assert result.grib_path is not None
    assert result.grib_path.name.endswith(".wspd10m.grib2")
    assert calls == ["latest"]
    assert seen["cache_key"] == "wspd10m"
    assert seen["required_vars"] == ["10u", "10v"]
    assert ":UGRD:10 m above ground:" in str(seen["search_override"])
    assert ":VGRD:10 m above ground:" in str(seen["search_override"])


def test_wspd10m_explicit_run_is_reused_for_both_components(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    seen: dict[str, object] = {}
    day_dir = tmp_path / "20260206" / "06"
    day_dir.mkdir(parents=True, exist_ok=True)

    def fake_fetch_gfs_grib(
        *,
        run: str,
        variable: str | None = None,
        search_override: str | None = None,
        cache_key: str | None = None,
        required_vars: list[str] | None = None,
        **kwargs,
    ):
        del kwargs
        calls.append(run)
        seen["search_override"] = search_override
        seen["cache_key"] = cache_key
        seen["required_vars"] = required_vars
        suffix = cache_key or variable or "var"
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
    assert result.component_paths is None
    assert result.grib_path is not None
    assert result.grib_path.name.endswith(".wspd10m.grib2")
    assert calls == ["20260206_06"]
    assert seen["cache_key"] == "wspd10m"
    assert seen["required_vars"] == ["10u", "10v"]
    assert ":UGRD:10 m above ground:" in str(seen["search_override"])
    assert ":VGRD:10 m above ground:" in str(seen["search_override"])


def test_radar_ptype_combo_latest_reuses_resolved_run_for_all_components(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str | None]] = []
    seen: dict[str, object] = {}
    day_dir = tmp_path / "20260206" / "06"
    day_dir.mkdir(parents=True, exist_ok=True)

    def fake_fetch_gfs_grib(
        *,
        run: str,
        variable: str | None = None,
        search_override: str | None = None,
        cache_key: str | None = None,
        required_vars: list[str] | None = None,
        **kwargs,
    ):
        del kwargs
        calls.append((run, variable))
        seen["search_override"] = search_override
        seen["cache_key"] = cache_key
        seen["required_vars"] = required_vars
        suffix = cache_key or variable or "var"
        return SimpleNamespace(
            path=day_dir / f"gfs.t06z.pgrb2.0p25f00.{suffix}.grib2",
            is_full_file=False,
        )

    monkeypatch.setattr(fetch_engine, "fetch_gfs_grib", fake_fetch_gfs_grib)

    result = fetch_engine.fetch_grib(
        model="gfs",
        run="latest",
        fh=0,
        var="radar_ptype",
        region="pnw",
    )

    assert result.not_ready_reason is None
    assert result.component_paths is None
    assert result.grib_path is not None
    assert result.grib_path.name.endswith(".radar_ptype.grib2")
    assert calls == [("latest", "radar_ptype")]
    assert seen["cache_key"] == "radar_ptype"
    assert seen["required_vars"] == ["refc", "crain", "csnow", "cicep", "cfrzr"]
    assert ":REFC:" in str(seen["search_override"])
    assert ":CRAIN:surface:" in str(seen["search_override"])
