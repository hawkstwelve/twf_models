from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from herbie import Herbie

from .hrrr_runs import HRRRCacheConfig, enforce_cycle_retention
from .paths import default_hrrr_cache_dir
from .variable_registry import herbie_search_for, normalize_api_variable

logger = logging.getLogger(__name__)


def _parse_run_datetime(run: str) -> datetime | None:
    if run.lower() == "latest":
        return None
    for fmt in ("%Y%m%d%H", "%Y%m%d_%H", "%Y%m%dT%H"):
        try:
            return datetime.strptime(run, fmt)
        except ValueError:
            continue
    if len(run) == 8 and run.isdigit():
        return datetime.strptime(run + "00", "%Y%m%d%H")
    raise ValueError("Run format must be 'latest' or YYYYMMDD or YYYYMMDDhh")


def _cache_dir_for_run(base_dir: Path, run_dt: datetime) -> Path:
    return base_dir / run_dt.strftime("%Y%m%d") / run_dt.strftime("%H")


def fetch_hrrr_grib(
    *,
    run: str,
    fh: int,
    product: str = "sfc",
    model: str = "hrrr",
    variable: str | None = None,
    cache_cfg: HRRRCacheConfig | None = None,
) -> Path:
    cfg = cache_cfg or HRRRCacheConfig(base_dir=default_hrrr_cache_dir(), keep_runs=1)
    run_dt = _parse_run_datetime(run)

    normalized_var = normalize_api_variable(variable) if variable else None
    if variable == "wspd10m":
        normalized_var = "wspd10m"
        search = herbie_search_for("wspd10m")
    else:
        search = herbie_search_for(variable) if variable else None

    logger.info(
        "Fetching HRRR GRIB: run=%s fh=%02d model=%s product=%s variable=%s search=%s",
        run,
        fh,
        model,
        product,
        normalized_var or "full",
        search or "(none)",
    )

    if run_dt is None:
        now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)

        herbie = None
        for i in range(0, 12):
            candidate = now - timedelta(hours=i)
            H = Herbie(candidate, model=model, product=product, fxx=fh)
            if H.grib:
                herbie = H
                run_dt = H.date
                break

        if herbie is None or run_dt is None:
            raise RuntimeError("Could not resolve latest HRRR cycle in the last 12 hours")
    else:
        herbie = Herbie(run_dt, model=model, product=product, fxx=fh)

    target_dir = _cache_dir_for_run(cfg.base_dir, run_dt)
    target_dir.mkdir(parents=True, exist_ok=True)

    suffix = normalized_var or "full"
    expected_filename = f"{model}.t{run_dt:%H}z.wrfsfcf{fh:02d}.{suffix}.grib2"
    expected_path = target_dir / expected_filename

    if expected_path.exists() and expected_path.stat().st_size > 0:
        logger.info("Using cached GRIB: %s", expected_path)
        return expected_path

    try:
        if search:
            downloaded = herbie.download(save_dir=target_dir, search=search)
        else:
            downloaded = herbie.download(save_dir=target_dir)
    except Exception as exc:
        raise RuntimeError(f"Herbie download failed: {exc}") from exc

    if isinstance(downloaded, (list, tuple)):
        downloaded = downloaded[0] if downloaded else None

    if downloaded is None:
        raise FileNotFoundError("Herbie did not return a GRIB2 path")

    path = Path(downloaded)
    if not path.exists():
        candidates = list(target_dir.rglob("*.grib2"))
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            path = candidates[0]
        else:
            raise FileNotFoundError(f"Downloaded GRIB2 not found: {path}")

    if path.stat().st_size == 0:
        try:
            path.unlink()
        except OSError:
            pass
        raise RuntimeError(f"Downloaded GRIB2 is empty: {path}")

    if path.resolve() != expected_path.resolve():
        logger.info("Moving GRIB into cache layout: %s -> %s", path, expected_path)
        try:
            path.replace(expected_path)
        except OSError:
            shutil.move(str(path), str(expected_path))

        parent = path.parent
        while parent != target_dir and parent.exists():
            if any(parent.iterdir()):
                break
            parent.rmdir()
            parent = parent.parent

    if not expected_path.exists() or expected_path.stat().st_size == 0:
        raise RuntimeError(f"Expected GRIB2 not found after download: {expected_path}")

    logger.info("Cached GRIB: %s", expected_path)
    return expected_path


def ensure_latest_cycles(*, keep_cycles: int, cache_cfg: HRRRCacheConfig | None = None) -> dict[str, int]:
    cfg = cache_cfg or HRRRCacheConfig(base_dir=default_hrrr_cache_dir(), keep_runs=keep_cycles)
    return enforce_cycle_retention(cfg)
