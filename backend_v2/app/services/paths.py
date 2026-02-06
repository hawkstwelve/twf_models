from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "backend_v2").is_dir():
            return parent
    raise FileNotFoundError("Could not locate repo root containing backend_v2")


def default_hrrr_cache_dir() -> Path:
    return repo_root() / "herbie_cache" / "hrrr" / "hrrr"


def default_gfs_cache_dir() -> Path:
    return repo_root() / "herbie_cache" / "gfs" / "gfs"
