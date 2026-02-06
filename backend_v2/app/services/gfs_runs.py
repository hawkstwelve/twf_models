from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .paths import default_gfs_cache_dir

logger = logging.getLogger(__name__)

RUN_DIR_RE = re.compile(r"^(\d{8})$")
CYCLE_DIR_RE = re.compile(r"^(\d{2})$")
RUN_WITH_HOUR_RE = re.compile(r"^(\d{8})(?:[T_]?)(\d{2})$")


@dataclass(frozen=True)
class GFSCacheConfig:
    base_dir: Path = field(default_factory=default_gfs_cache_dir)
    keep_runs: int = 1


def parse_run_dir_name(name: str) -> date | None:
    match = RUN_DIR_RE.match(name)
    if not match:
        return None
    ymd = match.group(1)
    try:
        return date(int(ymd[0:4]), int(ymd[4:6]), int(ymd[6:8]))
    except ValueError:
        return None


def parse_cycle_dir_name(name: str) -> int | None:
    match = CYCLE_DIR_RE.match(name)
    if not match:
        return None
    hour = int(match.group(1))
    if 0 <= hour <= 23:
        return hour
    return None


def _parse_run_string(run: str) -> tuple[str, str | None]:
    if run.lower() == "latest":
        return "latest", None
    match = RUN_WITH_HOUR_RE.match(run)
    if match:
        return match.group(1), match.group(2)
    match = RUN_DIR_RE.match(run)
    if match:
        return match.group(1), None
    raise ValueError(
        "Run format must be 'latest' or YYYYMMDD or YYYYMMDDhh or YYYYMMDD_hh or YYYYMMDDThh"
    )


def list_day_dirs(cfg: GFSCacheConfig) -> list[Path]:
    if not cfg.base_dir.exists():
        return []
    day_dirs: list[tuple[date, Path]] = []
    for entry in cfg.base_dir.iterdir():
        if not entry.is_dir():
            continue
        parsed = parse_run_dir_name(entry.name)
        if parsed is None:
            continue
        day_dirs.append((parsed, entry))
    day_dirs.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in day_dirs]


def list_cycle_dirs_for_day(day_dir: Path) -> list[Path]:
    cycle_dirs: list[tuple[int, Path]] = []
    if not day_dir.exists():
        return []
    for entry in day_dir.iterdir():
        if not entry.is_dir():
            continue
        hour = parse_cycle_dir_name(entry.name)
        if hour is None:
            continue
        cycle_dirs.append((hour, entry))
    cycle_dirs.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in cycle_dirs]


def list_cycle_dirs(cfg: GFSCacheConfig) -> list[Path]:
    cycles: list[tuple[datetime, Path]] = []
    for day_dir in list_day_dirs(cfg):
        parsed_day = parse_run_dir_name(day_dir.name)
        if parsed_day is None:
            continue
        for cycle_dir in list_cycle_dirs_for_day(day_dir):
            hour = parse_cycle_dir_name(cycle_dir.name)
            if hour is None:
                continue
            dt = datetime(parsed_day.year, parsed_day.month, parsed_day.day, hour)
            cycles.append((dt, cycle_dir))
    cycles.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in cycles]


def get_latest_cycle_dir(cfg: GFSCacheConfig) -> Path:
    cycles = list_cycle_dirs(cfg)
    if not cycles:
        raise FileNotFoundError(f"No GFS cycle directories found in {cfg.base_dir}")
    return cycles[0]


def _collect_grib_candidates(run_dir: Path) -> list[Path]:
    return [p for p in run_dir.iterdir() if p.is_file() and p.suffix == ".grib2"]


def resolve_gfs_grib_path(cfg: GFSCacheConfig, run: str, fh: int) -> Path:
    run_key, hour = _parse_run_string(run)

    if run_key == "latest":
        cycle_dir = get_latest_cycle_dir(cfg)
    else:
        day_dir = cfg.base_dir / run_key
        if not day_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {day_dir}")
        if hour is None:
            cycle_dirs = list_cycle_dirs_for_day(day_dir)
            if not cycle_dirs:
                raise FileNotFoundError(f"No cycle directories found in {day_dir}")
            cycle_dir = cycle_dirs[0]
        else:
            cycle_dir = day_dir / hour
            if not cycle_dir.exists():
                raise FileNotFoundError(f"Cycle directory not found: {cycle_dir}")

    fh_token = f"f{fh:02d}"
    hour_token = f"t{cycle_dir.name}z"
    strict_fh = re.compile(rf"{fh_token}(?!\d)")

    candidates = _collect_grib_candidates(cycle_dir)
    matches: list[Path] = []
    for path in candidates:
        name = path.name.lower()
        if strict_fh.search(name):
            if hour is None or hour_token in name or hour_token not in name:
                matches.append(path)

    if hour is not None:
        hour_matches = [p for p in matches if hour_token in p.name.lower()]
        if hour_matches:
            matches = hour_matches

    if not matches:
        candidate_names = "\n".join(sorted(str(p) for p in candidates))
        hour_msg = f" and hour={hour}" if hour is not None else ""
        raise FileNotFoundError(
            "No GRIB2 file found for "
            f"run={run_key}{hour_msg}, fh={fh:02d} in {cycle_dir}\n"
            f"Searched for token: {fh_token}\n"
            f"Candidates:\n{candidate_names if candidate_names else '  (none)'}"
        )

    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


def _count_files(paths: Iterable[Path]) -> int:
    total = 0
    for path in paths:
        if path.is_dir():
            total += sum(1 for _ in path.rglob("*") if _.is_file())
        elif path.is_file():
            total += 1
    return total


def _is_under_base(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def enforce_cycle_retention(cfg: GFSCacheConfig) -> dict[str, int]:
    cycle_dirs = list_cycle_dirs(cfg)
    if not cycle_dirs:
        raise FileNotFoundError(f"No GFS cycle directories found in {cfg.base_dir}")

    keep = max(1, cfg.keep_runs)
    keep_dirs = cycle_dirs[:keep]
    delete_dirs = cycle_dirs[keep:]

    deleted_files = _count_files(delete_dirs)
    deleted_cycles = len(delete_dirs)
    deleted_day_dirs = 0

    for cycle_dir in delete_dirs:
        if not _is_under_base(cycle_dir, cfg.base_dir):
            raise RuntimeError(f"Refusing to delete outside base dir: {cycle_dir}")
        logger.info("Deleting GFS cycle directory: %s", cycle_dir)
        shutil.rmtree(cycle_dir)

        parent_day = cycle_dir.parent
        if parent_day.exists() and not any(parent_day.iterdir()):
            if _is_under_base(parent_day, cfg.base_dir):
                logger.info("Deleting empty day directory: %s", parent_day)
                parent_day.rmdir()
                deleted_day_dirs += 1

    return {
        "kept_cycles": len(keep_dirs),
        "deleted_cycles": deleted_cycles,
        "deleted_files": deleted_files,
        "deleted_day_dirs": deleted_day_dirs,
    }


def enforce_latest_run_only(cfg: GFSCacheConfig) -> dict[str, int]:
    return enforce_cycle_retention(cfg)
