from __future__ import annotations

from app.services.paths import default_gfs_cache_dir, default_hrrr_cache_dir


def test_default_hrrr_cache_dir_suffix() -> None:
    assert str(default_hrrr_cache_dir()).endswith("herbie_cache/hrrr/hrrr")


def test_default_gfs_cache_dir_suffix() -> None:
    assert str(default_gfs_cache_dir()).endswith("herbie_cache/gfs/gfs")
