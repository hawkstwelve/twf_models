from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from herbie import Herbie

from app.services.paths import repo_root

logger = logging.getLogger(__name__)

IDX_FALLBACK_RATE_SECONDS = 300
_IDX_FALLBACK_LOG_CACHE: dict[tuple[str, int], float] = {}


class UpstreamNotReady(RuntimeError):
    pass


@dataclass(frozen=True)
class GribFetchResult:
    path: Path
    is_full_file: bool = False

    def __fspath__(self) -> str:
        return str(self.path)

    def __getattr__(self, name: str):
        return getattr(self.path, name)


def default_gfs_cache_dir() -> Path:
    return repo_root() / "herbie_cache" / "gfs" / "gfs"


def _is_readable_grib(path: Path) -> bool:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return False
        with path.open("rb") as handle:
            return bool(handle.read(4))
    except OSError:
        return False


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


def _is_idx_missing_message(message: str) -> bool:
    text = message.lower()
    patterns = [
        "no index file was found",
        "index_as_dataframe",
        "inventory not found",
        "no inventory",
        "download the full file first",
        "index not ready",
        "idx missing",
    ]
    return any(pattern in text for pattern in patterns)


def _log_idx_missing(run_id: str, fh: int) -> None:
    now_ts = time.time()
    key = (run_id, fh)
    last_ts = _IDX_FALLBACK_LOG_CACHE.get(key, 0.0)
    if now_ts - last_ts < IDX_FALLBACK_RATE_SECONDS:
        return
    _IDX_FALLBACK_LOG_CACHE[key] = now_ts
    logger.info("IDX missing; deferring subset: run=%s fh=%02d", run_id, fh)


def fetch_gfs_grib(
    *,
    run: str,
    fh: int,
    product: str = "pgrb2.0p25",
    model: str = "gfs",
    variable: str | None = None,
    search_override: str | None = None,
    cache_dir: Path | None = None,
) -> GribFetchResult:
    base_dir = cache_dir or default_gfs_cache_dir()
    run_dt = _parse_run_datetime(run)

    search = search_override
    if not search:
        raise UpstreamNotReady("Subset search required for GFS fetch")

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
            raise UpstreamNotReady("Could not resolve latest GFS cycle in the last 12 hours")
    else:
        herbie = Herbie(run_dt, model=model, product=product, fxx=fh)

    target_dir = _cache_dir_for_run(base_dir, run_dt)
    target_dir.mkdir(parents=True, exist_ok=True)

    expected_suffix = variable or "subset"
    expected_filename = f"{model}.t{run_dt:%H}z.{product}f{fh:02d}.{expected_suffix}.grib2"
    expected_path = target_dir / expected_filename

    if expected_path.exists() and _is_readable_grib(expected_path):
        logger.info("Using cached GFS GRIB: %s", expected_path)
        return GribFetchResult(path=expected_path, is_full_file=False)

    logger.info(
        "Fetching GFS GRIB: run=%s fh=%02d model=%s product=%s variable=%s search=%s",
        run,
        fh,
        model,
        product,
        variable or "subset",
        search,
    )

    try:
        downloaded = herbie.download(search, save_dir=target_dir)
    except Exception as exc:
        message = str(exc)
        if _is_idx_missing_message(message):
            _log_idx_missing(run_dt.strftime("%Y%m%d_%Hz"), fh)
            raise UpstreamNotReady("Index not ready for requested GFS GRIB") from exc
        raise RuntimeError(f"Herbie download failed: {exc}") from exc

    if isinstance(downloaded, (list, tuple)):
        downloaded = downloaded[0] if downloaded else None

    if downloaded is None:
        raise UpstreamNotReady("Herbie did not return a GRIB2 path")

    path = Path(downloaded)
    if not path.exists():
        candidates = list(target_dir.rglob("*.grib2"))
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            path = candidates[0]
        else:
            raise UpstreamNotReady(f"Downloaded GRIB2 not found: {path}")

    if path.stat().st_size == 0:
        try:
            path.unlink()
        except OSError:
            pass
        raise UpstreamNotReady(f"Downloaded GRIB2 is empty: {path}")

    if path.resolve() != expected_path.resolve():
        logger.info("Moving GRIB into cache layout: %s -> %s", path, expected_path)
        try:
            path.replace(expected_path)
        except OSError:
            shutil.move(str(path), str(expected_path))

    return GribFetchResult(path=expected_path, is_full_file=False)


def is_upstream_not_ready(exc: BaseException) -> bool:
    return isinstance(exc, UpstreamNotReady)
