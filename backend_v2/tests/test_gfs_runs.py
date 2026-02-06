from __future__ import annotations

from pathlib import Path

from app.services.gfs_runs import (
    GFSCacheConfig,
    enforce_cycle_retention,
    list_cycle_dirs,
    parse_cycle_dir_name,
    parse_run_dir_name,
    resolve_gfs_grib_path,
)


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_parse_helpers() -> None:
    assert parse_run_dir_name("20260206") is not None
    assert parse_run_dir_name("2026-02-06") is None
    assert parse_cycle_dir_name("00") == 0
    assert parse_cycle_dir_name("23") == 23
    assert parse_cycle_dir_name("24") is None


def test_list_cycle_dirs_and_resolve_latest(tmp_path: Path) -> None:
    base = tmp_path / "gfs"
    latest_cycle = _mkdir(base / "20260206" / "00")
    _mkdir(base / "20260205" / "18")
    grib = latest_cycle / "gfs.t00z.pgrb2.0p25f00.t2m.grib2"
    grib.write_bytes(b"GRIB")

    cfg = GFSCacheConfig(base_dir=base, keep_runs=1)
    cycles = list_cycle_dirs(cfg)
    assert cycles[0] == latest_cycle

    resolved = resolve_gfs_grib_path(cfg, run="latest", fh=0)
    assert resolved == grib


def test_enforce_cycle_retention(tmp_path: Path) -> None:
    base = tmp_path / "gfs"
    keep_cycle = _mkdir(base / "20260206" / "00")
    old_cycle = _mkdir(base / "20260205" / "18")
    (keep_cycle / "keep.grib2").write_bytes(b"GRIB")
    (old_cycle / "old.grib2").write_bytes(b"GRIB")

    cfg = GFSCacheConfig(base_dir=base, keep_runs=1)
    summary = enforce_cycle_retention(cfg)

    assert summary["kept_cycles"] == 1
    assert summary["deleted_cycles"] == 1
    assert keep_cycle.exists()
    assert not old_cycle.exists()
