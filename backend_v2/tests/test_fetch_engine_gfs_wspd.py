from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from fastapi import HTTPException

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


def test_gfs_radar_ptype_is_not_supported(
    monkeypatch,
    tmp_path: Path,
) -> None:
    day_dir = tmp_path / "20260206" / "06"
    day_dir.mkdir(parents=True, exist_ok=True)

    def fail_fetch_gfs_grib(**kwargs):
        del kwargs
        raise AssertionError("GFS fetch should not run for unknown GFS radar_ptype")

    monkeypatch.setattr(fetch_engine, "fetch_gfs_grib", fail_fetch_gfs_grib)

    with pytest.raises(HTTPException, match="Unknown variable"):
        fetch_engine.fetch_grib(
            model="gfs",
            run="latest",
            fh=0,
            var="radar_ptype",
            region="pnw",
        )


def test_gfs_precip_ptype_uses_prate_plus_ptype_bundle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    day_dir = tmp_path / "20260206" / "06"
    day_dir.mkdir(parents=True, exist_ok=True)
    seen: dict[str, object] = {}

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
        assert run == "latest"
        assert variable == "precip_ptype"
        seen["search_override"] = search_override
        seen["cache_key"] = cache_key
        seen["required_vars"] = required_vars
        return SimpleNamespace(
            path=day_dir / "gfs.t06z.pgrb2.0p25f00.precip_ptype.grib2",
            is_full_file=False,
        )

    monkeypatch.setattr(fetch_engine, "fetch_gfs_grib", fake_fetch_gfs_grib)

    result = fetch_engine.fetch_grib(
        model="gfs",
        run="latest",
        fh=0,
        var="precip_ptype",
        region="pnw",
    )

    assert result.not_ready_reason is None
    assert result.grib_path is not None
    assert result.grib_path.name.endswith(".precip_ptype.grib2")
    assert seen["cache_key"] == "precip_ptype"
    assert seen["required_vars"] == ["precip_ptype"]
    assert ":PRATE:surface:0 hour fcst:" in str(seen["search_override"])
    assert ":CRAIN:surface:0 hour fcst:" in str(seen["search_override"])
    assert ":CSNOW:surface:0 hour fcst:" in str(seen["search_override"])
    assert ":CICEP:surface:0 hour fcst:" in str(seen["search_override"])
    assert ":CFRZR:surface:0 hour fcst:" in str(seen["search_override"])


def test_gfs_precip_ptype_uses_instant_prate_search_for_fh24(
    monkeypatch,
    tmp_path: Path,
) -> None:
    day_dir = tmp_path / "20260206" / "06"
    day_dir.mkdir(parents=True, exist_ok=True)
    seen: dict[str, object] = {}

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
        assert run == "latest"
        assert variable == "precip_ptype"
        seen["search_override"] = search_override
        seen["cache_key"] = cache_key
        seen["required_vars"] = required_vars
        return SimpleNamespace(
            path=day_dir / "gfs.t06z.pgrb2.0p25f24.precip_ptype.grib2",
            is_full_file=False,
        )

    monkeypatch.setattr(fetch_engine, "fetch_gfs_grib", fake_fetch_gfs_grib)

    result = fetch_engine.fetch_grib(
        model="gfs",
        run="latest",
        fh=24,
        var="precip_ptype",
        region="pnw",
    )

    assert result.not_ready_reason is None
    assert result.grib_path is not None
    assert result.grib_path.name.endswith(".precip_ptype.grib2")
    assert seen["cache_key"] == "precip_ptype"
    assert seen["required_vars"] == ["precip_ptype"]
    assert ":PRATE:surface:24 hour fcst:" in str(seen["search_override"])
    assert ":CRAIN:surface:24 hour fcst:" in str(seen["search_override"])
    assert "hour ave fcst" not in str(seen["search_override"])


def test_gfs_precip_ptype_prefers_instant_fh_record_when_avg_also_exists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    day_dir = tmp_path / "20260206" / "06"
    day_dir.mkdir(parents=True, exist_ok=True)
    seen: dict[str, object] = {}
    inventory_records = [
        ":PRATE:surface:12 hour fcst:",
        ":PRATE:surface:6-12 hour ave fcst:",
    ]
    subset_path = day_dir / "gfs.t06z.pgrb2.0p25f12.precip_ptype.grib2"
    subset_path.write_bytes(b"GRIB")

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
        assert run == "latest"
        assert variable == "precip_ptype"
        # Simulate inventory containing both instantaneous and average PRATE records.
        assert ":PRATE:surface:12 hour fcst:" in inventory_records
        assert ":PRATE:surface:6-12 hour ave fcst:" in inventory_records
        seen["search_override"] = search_override
        seen["cache_key"] = cache_key
        seen["required_vars"] = required_vars
        return SimpleNamespace(
            path=subset_path,
            is_full_file=False,
        )

    monkeypatch.setattr(fetch_engine, "fetch_gfs_grib", fake_fetch_gfs_grib)

    result = fetch_engine.fetch_grib(
        model="gfs",
        run="latest",
        fh=12,
        var="precip_ptype",
        region="pnw",
    )

    assert result.not_ready_reason is None
    assert result.grib_path is not None
    assert result.grib_path.name.endswith(".precip_ptype.grib2")
    assert result.grib_path.exists()
    assert result.grib_path.stat().st_size > 0
    assert seen["cache_key"] == "precip_ptype"
    assert seen["required_vars"] == ["precip_ptype"]
    search = str(seen["search_override"])
    assert ":PRATE:surface:12 hour fcst:" in search
    assert ":CRAIN:surface:12 hour fcst:" in search
    assert ":CSNOW:surface:12 hour fcst:" in search
    assert ":CICEP:surface:12 hour fcst:" in search
    assert ":CFRZR:surface:12 hour fcst:" in search
    assert "hour ave fcst" not in search
