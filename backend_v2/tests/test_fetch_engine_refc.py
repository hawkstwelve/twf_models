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
    seen: dict[str, object] = {}

    def fake_fetch_hrrr_grib(
        *,
        run: str,
        variable: str | None = None,
        search_override: str | None = None,
        cache_key: str | None = None,
        required_vars: list[str] | None = None,
        **kwargs,
    ):
        del kwargs
        assert run == "latest"
        assert variable == "refc"
        seen["search_override"] = search_override
        seen["cache_key"] = cache_key
        seen["required_vars"] = required_vars
        return SimpleNamespace(
            path=day_dir / "hrrr.t06z.wrfsfcf00.radar_ptype.grib2",
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
    assert result.grib_path.name.endswith(".radar_ptype.grib2")
    assert seen["cache_key"] == "radar_ptype"
    assert seen["required_vars"] == ["refc"]
    assert isinstance(seen["search_override"], str)
    assert ":REFC:" in str(seen["search_override"])
    assert ":CRAIN:surface:" in str(seen["search_override"])


def test_fetch_grib_hrrr_radar_ptype_combo_components(monkeypatch, tmp_path: Path) -> None:
    day_dir = tmp_path / "20260206" / "15"
    day_dir.mkdir(parents=True, exist_ok=True)
    calls: list[tuple[str, str | None, str | None, tuple[str, ...]]] = []

    def fake_fetch_hrrr_grib(
        *,
        run: str,
        variable: str | None = None,
        search_override: str | None = None,
        cache_key: str | None = None,
        required_vars: list[str] | None = None,
        **kwargs,
    ):
        del kwargs
        calls.append((run, variable, cache_key, tuple(required_vars or [])))
        assert isinstance(search_override, str)
        assert ":REFC:" in search_override
        assert ":CRAIN:surface:" in search_override
        return SimpleNamespace(
            path=day_dir / "hrrr.t15z.wrfsfcf00.radar_ptype.grib2",
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
    assert result.component_paths is None
    assert result.grib_path is not None
    assert result.grib_path.name.endswith(".radar_ptype.grib2")
    assert calls == [
        ("latest", "radar_ptype", "radar_ptype", ("refc", "crain", "csnow", "cicep", "cfrzr"))
    ]


def test_fetch_grib_hrrr_wspd10m_uses_uv_bundle(monkeypatch, tmp_path: Path) -> None:
    day_dir = tmp_path / "20260206" / "18"
    day_dir.mkdir(parents=True, exist_ok=True)
    seen: dict[str, object] = {}

    def fake_fetch_hrrr_grib(
        *,
        run: str,
        variable: str | None = None,
        search_override: str | None = None,
        cache_key: str | None = None,
        required_vars: list[str] | None = None,
        **kwargs,
    ):
        del kwargs
        assert run == "latest"
        assert variable == "wspd10m"
        seen["search_override"] = search_override
        seen["cache_key"] = cache_key
        seen["required_vars"] = required_vars
        return SimpleNamespace(
            path=day_dir / "hrrr.t18z.wrfsfcf06.wspd10m.grib2",
            is_full_file=False,
        )

    monkeypatch.setattr(fetch_engine, "fetch_hrrr_grib", fake_fetch_hrrr_grib)

    result = fetch_engine.fetch_grib(
        model="hrrr",
        run="latest",
        fh=6,
        var="wspd10m",
        region="pnw",
    )

    assert result.not_ready_reason is None
    assert result.grib_path is not None
    assert result.grib_path.name.endswith(".wspd10m.grib2")
    assert seen["cache_key"] == "wspd10m"
    assert seen["required_vars"] == ["10u", "10v"]
    assert ":UGRD:10 m above ground:" in str(seen["search_override"])
    assert ":VGRD:10 m above ground:" in str(seen["search_override"])
