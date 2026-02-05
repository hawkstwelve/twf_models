from __future__ import annotations

import os
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from herbie import Herbie

from .hrrr_runs import HRRRCacheConfig, enforce_cycle_retention
from .paths import default_hrrr_cache_dir
from .variable_registry import herbie_search_for, normalize_api_variable

logger = logging.getLogger(__name__)

ALLOW_FULL_GRIB_FALLBACK = os.environ.get("TWF_ALLOW_FULL_GRIB_FALLBACK", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
FULL_GRIB_MAX_BYTES = int(os.environ.get("TWF_FULL_GRIB_MAX_BYTES", str(2 * 1024 * 1024 * 1024)))
FULL_GRIB_MAX_SECONDS = int(os.environ.get("TWF_FULL_GRIB_MAX_SECONDS", "900"))

IDX_FALLBACK_RATE_SECONDS = 300
IDX_FALLBACK_CACHE_TTL_SECONDS = 7200
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


def is_upstream_not_ready_message(message: str) -> bool:
    text = message.lower()
    patterns = [
        "upstream not ready",
        "grib2 file not found",
        "herbie did not return a grib2 path",
        "could not resolve latest hrrr cycle",
    ]
    return any(pattern in text for pattern in patterns)


def is_idx_missing_message(message: str) -> bool:
    text = message.lower()
    patterns = [
        "no index file was found",
        "index_as_dataframe",
        "inventory not found",
        "no inventory",
        "download the full file first",
    ]
    return any(pattern in text for pattern in patterns)


def is_upstream_not_ready(exc: BaseException) -> bool:
    if isinstance(exc, UpstreamNotReady):
        return True
    return is_upstream_not_ready_message(str(exc))


def _idx_path(herbie: Herbie) -> Path | None:
    try:
        idx = herbie.idx
    except Exception:
        return None
    if idx is None:
        return None
    return Path(idx)


def has_idx(herbie: Herbie) -> bool:
    idx_path = _idx_path(herbie)
    if idx_path is None:
        return False
    return idx_path.exists()


def _delete_cfgrib_index_files(grib_path: Path) -> None:
    """Delete cfgrib-generated index files for this GRIB to avoid stale/collision issues."""
    try:
        parent = grib_path.parent
        # cfgrib typically writes: <grib>.{hash}.idx
        for idx_file in parent.glob(grib_path.name + ".*.idx"):
            try:
                idx_file.unlink()
            except OSError:
                pass
    except Exception:
        # Never fail the pipeline due to cleanup
        pass


# --- wgrib2 helpers ---

def _wgrib2_available() -> bool:
    return shutil.which("wgrib2") is not None


if ALLOW_FULL_GRIB_FALLBACK and not _wgrib2_available():
    logger.warning(
        "Full GRIB fallback requested but wgrib2 not found; disabling fallback."
    )
    ALLOW_FULL_GRIB_FALLBACK = False


def _extract_grib_with_wgrib2(*, src: Path, search: str, dst: Path) -> None:
    """Extract a subset GRIB using wgrib2 -match into dst."""
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temp file and atomically replace to avoid readers seeing partial output.
    tmp_dst = dst.with_name(dst.name + ".tmp")

    # Remove any stale/partial outputs (including stale cfgrib idx files)
    for p in (dst, tmp_dst):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
        _delete_cfgrib_index_files(p)

    cmd = [
        "wgrib2",
        str(src),
        "-match",
        search,
        "-grib",
        str(tmp_dst),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # Best-effort cleanup
        try:
            if tmp_dst.exists():
                tmp_dst.unlink()
        except OSError:
            pass
        raise RuntimeError(
            f"wgrib2 extract failed (code={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
        )

    if not tmp_dst.exists() or tmp_dst.stat().st_size == 0:
        raise RuntimeError(f"wgrib2 extract produced empty output: {tmp_dst}")

    # Optional sanity check: if the subset is unexpectedly huge, the match is too broad.
    # (A single-field subset should be far smaller than a full HRRR file.)
    if tmp_dst.stat().st_size > 50 * 1024 * 1024:
        raise RuntimeError(
            f"wgrib2 subset appears too large ({tmp_dst.stat().st_size} bytes); match likely too broad: {search}"
        )

    os.replace(tmp_dst, dst)
    _delete_cfgrib_index_files(dst)


def _format_run_id(run_dt: datetime | None, run: str) -> str:
    if run_dt is None:
        return run
    return run_dt.strftime("%Y%m%d_%Hz")


def _prune_idx_fallback_cache(now_ts: float) -> None:
    expired = [
        key for key, ts in _IDX_FALLBACK_LOG_CACHE.items()
        if now_ts - ts > IDX_FALLBACK_CACHE_TTL_SECONDS
    ]
    for key in expired:
        _IDX_FALLBACK_LOG_CACHE.pop(key, None)


def _log_idx_fallback(run_id: str, fh: int) -> None:
    now_ts = time.time()
    _prune_idx_fallback_cache(now_ts)
    key = (run_id, fh)
    last_ts = _IDX_FALLBACK_LOG_CACHE.get(key, 0.0)
    if now_ts - last_ts < IDX_FALLBACK_RATE_SECONDS:
        return
    _IDX_FALLBACK_LOG_CACHE[key] = now_ts
    logger.info("IDX missing; falling back to full download: run=%s fh=%02d", run_id, fh)


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
) -> GribFetchResult:
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
            raise UpstreamNotReady("Could not resolve latest HRRR cycle in the last 12 hours")
    else:
        herbie = Herbie(run_dt, model=model, product=product, fxx=fh)

    target_dir = _cache_dir_for_run(cfg.base_dir, run_dt)
    target_dir.mkdir(parents=True, exist_ok=True)

    want_subset = bool(search)
    expected_suffix = normalized_var or "full"
    expected_filename = f"{model}.t{run_dt:%H}z.wrf{product}f{fh:02d}.{expected_suffix}.grib2"
    expected_path = target_dir / expected_filename
    expected_full_filename = f"{model}.t{run_dt:%H}z.wrf{product}f{fh:02d}.full.grib2"
    expected_full_path = target_dir / expected_full_filename

    run_id = _format_run_id(run_dt, run)
    use_full_download = False

    # If we want a subset file but Herbie has no IDX, Herbie can't do a remote subset.
    # In that case, download the full GRIB and (if possible) locally extract the subset
    # so downstream code still receives a single-variable GRIB.
    if expected_path.exists():
        if expected_path.stat().st_size == 0:
            try:
                expected_path.unlink()
            except OSError:
                pass
        else:
            _delete_cfgrib_index_files(expected_path)
            logger.info("Using cached GRIB: %s", expected_path)
            return GribFetchResult(path=expected_path, is_full_file=expected_suffix == "full")

    download_start = time.time()
    try:
        downloaded_full = False
        if search and not use_full_download:
            downloaded = herbie.download(save_dir=target_dir, search=search)
        else:
            downloaded_full = True
            downloaded = herbie.download(save_dir=target_dir)
    except Exception as exc:
        message = str(exc)
        if search and is_idx_missing_message(message):
            if not ALLOW_FULL_GRIB_FALLBACK:
                raise UpstreamNotReady("Index not ready for requested HRRR GRIB") from exc
            _log_idx_fallback(run_id, fh)
            herbie = Herbie(run_dt, model=model, product=product, fxx=fh)
            downloaded_full = True
            try:
                downloaded = herbie.download(save_dir=target_dir)
            except Exception as inner_exc:
                inner_message = str(inner_exc)
                if is_upstream_not_ready_message(inner_message):
                    raise UpstreamNotReady(inner_message) from inner_exc
                raise RuntimeError(f"Herbie download failed: {inner_exc}") from inner_exc
        elif is_upstream_not_ready_message(message):
            raise UpstreamNotReady(message) from exc
        else:
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

    if use_full_download:
        elapsed = time.time() - download_start
        if elapsed > FULL_GRIB_MAX_SECONDS:
            raise RuntimeError(f"Full GRIB download exceeded max time ({elapsed:.0f}s)")
        if path.stat().st_size > FULL_GRIB_MAX_BYTES:
            raise RuntimeError(
                f"Full GRIB download exceeded max size ({path.stat().st_size} bytes)"
            )

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

        _delete_cfgrib_index_files(expected_path)

        parent = path.parent
        while parent != target_dir and parent.exists():
            if any(parent.iterdir()):
                break
            parent.rmdir()
            parent = parent.parent

    if not expected_path.exists() or expected_path.stat().st_size == 0:
        raise UpstreamNotReady(f"Expected GRIB2 not found after download: {expected_path}")

    _delete_cfgrib_index_files(expected_path)
    logger.info("Cached GRIB: %s", expected_path)
    return GribFetchResult(path=expected_path, is_full_file=expected_suffix == "full")


def ensure_latest_cycles(*, keep_cycles: int, cache_cfg: HRRRCacheConfig | None = None) -> dict[str, int]:
    cfg = cache_cfg or HRRRCacheConfig(base_dir=default_hrrr_cache_dir(), keep_runs=keep_cycles)
    return enforce_cycle_retention(cfg)
