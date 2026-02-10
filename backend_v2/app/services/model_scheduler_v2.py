from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from app.models import get_model
from app.services.fetch_engine import fetch_grib

logger = logging.getLogger(__name__)

RUN_ID_RE = re.compile(r"^(?P<day>\d{8})_(?P<hour>\d{2})z$")
DEFAULT_DATA_ROOT = Path("/opt/twf_models/data/v2")
PRIMARY_VAR_DEFAULT = "tmp2m"
VAR_DEFAULTS = "tmp2m,wspd10m"
PROBE_INTERVAL_SECONDS = 90
RATE_LIMIT_SECONDS = 300
CACHE_TTL_SECONDS = 7200
RELEASE_WINDOW_START_MINUTE = 0
RELEASE_WINDOW_END_MINUTE = 20
RELEASE_POLL_SECONDS = 60
QUIET_POLL_SECONDS = 600
BUSY_POLL_SECONDS = 60
BACKOFF_INITIAL_SECONDS = 60
BACKOFF_MAX_SECONDS = 600
SLEEP_JITTER_RATIO = 0.1

COMPONENT_ONLY_VARS_BY_MODEL: dict[str, set[str]] = {
    "gfs": {"10u", "10v", "crain", "csnow", "cicep", "cfrzr"},
}


class RunResolutionError(RuntimeError):
    pass


class ConfigError(RuntimeError):
    pass


class UpstreamNotReady(RuntimeError):
    pass


_UPSTREAM_LOG_CACHE: dict[tuple[str, str], dict[str, object]] = {}


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def parse_vars(value: str) -> list[str]:
    items = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError("--vars cannot be empty")
    return items


def _parse_run_id_datetime(run_id: str) -> datetime | None:
    match = RUN_ID_RE.match(run_id)
    if not match:
        return None
    day = match.group("day")
    hour_text = match.group("hour")
    try:
        year = int(day[0:4])
        month = int(day[4:6])
        day_num = int(day[6:8])
        hour = int(hour_text)
        if not (0 <= hour <= 23):
            return None
        return datetime(year, month, day_num, hour, tzinfo=timezone.utc)
    except ValueError:
        return None


def _derive_run_id_from_grib_path(path: Path) -> tuple[str, int] | None:
    day = None
    hour_dir = None
    hour_file = None

    if re.fullmatch(r"\d{2}", path.parent.name):
        hour_dir = path.parent.name

    for part in reversed(path.parts):
        if re.fullmatch(r"\d{8}", part):
            try:
                datetime.strptime(part, "%Y%m%d")
            except ValueError:
                logger.debug("Invalid day token in GRIB path: %s", path)
                return None
            day = part
            break

    match = re.search(r"\.t(\d{2})z", path.name)
    if match:
        hour_file = match.group(1)

    def _validate_hour(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            hour_val = int(value)
        except ValueError:
            return None
        if 0 <= hour_val <= 23:
            return hour_val
        return None

    hour_dir_val = _validate_hour(hour_dir)
    hour_file_val = _validate_hour(hour_file)

    if hour_dir_val is not None and hour_file_val is not None and hour_dir_val != hour_file_val:
        logger.warning(
            "GRIB path hour mismatch (dir=%s file=%s raw_dir=%s raw_file=%s); preferring filename: %s",
            hour_dir_val,
            hour_file_val,
            hour_dir,
            hour_file,
            path,
        )

    hour_val = hour_file_val if hour_file_val is not None else hour_dir_val

    if day and hour_val is not None:
        return f"{day}_{hour_val:02d}z", hour_val

    logger.debug("Failed to derive run_id from GRIB path: %s", path)
    return None


def _resolve_latest_run(model: str, region: str, primary_var: str) -> tuple[str, int]:
    fetch_result = fetch_grib(model=model, run="latest", fh=0, var=primary_var, region=region)
    if fetch_result.not_ready_reason:
        raise UpstreamNotReady(fetch_result.not_ready_reason)
    if fetch_result.grib_path is None:
        raise UpstreamNotReady("Latest run fetch returned no GRIB path")
    derived = _derive_run_id_from_grib_path(fetch_result.grib_path)
    if derived is None:
        raise RunResolutionError(f"Unable to derive run_id from GRIB path: {fetch_result.grib_path}")
    return derived


def _probe_latest_run(model: str, region: str, primary_var: str) -> tuple[str, int] | None:
    try:
        return _resolve_latest_run(model, region, primary_var)
    except Exception as exc:
        if isinstance(exc, UpstreamNotReady):
            logger.warning("Latest run not ready yet: %s", exc)
            return None
        if isinstance(exc, ConfigError):
            logger.error("Scheduler configuration error: %s", exc)
            raise
        logger.error("Latest run discovery failed: %s", exc)
        return None


def _data_root() -> Path:
    return Path(os.getenv("TWF_DATA_V2_ROOT", str(DEFAULT_DATA_ROOT)))


def _workers() -> int:
    raw = os.getenv("TWF_V2_WORKERS", "4").strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid TWF_V2_WORKERS=%s; using default 4", raw)
        return 4
    if value < 1:
        logger.warning("Invalid TWF_V2_WORKERS=%s; using default 4", raw)
        return 4
    return value


def _build_script_path_for_model(model_id: str) -> Path:
    backend_v2_dir = Path(__file__).resolve().parents[2]
    return backend_v2_dir / "scripts" / "build_cog.py"


def _resolve_regions_for_cli(model_id: str, out_root: Path, region: str | None) -> list[str]:
    if region:
        return [region]

    model_root = out_root / model_id
    if not model_root.exists() or not model_root.is_dir():
        raise ConfigError(f"--region is required. Model data root not found: {model_root}")
    regions = sorted(p.name for p in model_root.iterdir() if p.is_dir())
    if not regions:
        raise ConfigError(f"--region is required. Found regions: (none)")
    return [
        _raise_region_required(regions)
    ]


def _raise_region_required(regions: list[str]) -> str:
    joined = ",".join(regions)
    raise ConfigError(f"--region is required. Found regions: {joined}")


def _task_output_path(
    out_root: Path,
    model: str,
    region: str,
    run_id: str,
    var: str,
    fh: int,
) -> Path:
    return out_root / model / region / run_id / var / f"fh{fh:03d}.cog.tif"


def _latest_pointer_path(out_root: Path, model: str, region: str) -> Path:
    return out_root / model / region / "LATEST.json"


def _read_latest_pointer(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read LATEST.json: %s", exc)
        return None
    run_id = payload.get("run_id")
    if isinstance(run_id, str):
        return run_id
    return None


def _write_latest_pointer(path: Path, run_id: str) -> None:
    run_dt = _parse_run_id_datetime(run_id)
    if run_dt is None:
        raise RunResolutionError(f"Invalid run_id for LATEST.json: {run_id}")
    cycle_utc = run_dt.strftime("%Y-%m-%dT%H:00:00Z")
    updated_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "run_id": run_id,
        "cycle_utc": cycle_utc,
        "updated_utc": updated_utc,
        "source": "scheduler_v2",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp_path.replace(path)


def _should_promote_latest(
    out_root: Path,
    model: str,
    region: str,
    run_id: str,
    primary_vars: Iterable[str],
    fhs: Iterable[int] | None = None,
) -> bool:
    targets = list(fhs) if fhs is not None else [0, 1, 2]
    for var in primary_vars:
        for fh in targets:
            path = _task_output_path(out_root, model, region, run_id, var, fh)
            if path.exists():
                return True
    return False


def _promotion_fhs_for_cycle(plugin, cycle_hour: int | None) -> list[int]:
    if cycle_hour is None:
        return [0, 1, 2]
    try:
        fhs = list(plugin.target_fhs(cycle_hour))
    except Exception:
        return [0, 1, 2]
    if not fhs:
        return [0, 1, 2]
    return fhs[: min(3, len(fhs))]


def _scheduled_targets_for_cycle(
    plugin,
    vars_to_build: Iterable[str],
    cycle_hour: int,
) -> list[tuple[str, int]]:
    try:
        base_fhs = list(plugin.target_fhs(cycle_hour))
    except Exception:
        return []

    model_id = str(getattr(plugin, "id", "")).lower()
    targets: list[tuple[str, int]] = []
    for var in vars_to_build:
        normalized_var = plugin.normalize_var_id(var)
        # Guard enqueueing against unsupported shared/global vars.
        if plugin.get_var(normalized_var) is None:
            continue
        min_fh = 6 if model_id == "gfs" and normalized_var == "qpf6h" else 0
        for fh in base_fhs:
            if fh < min_fh:
                continue
            targets.append((normalized_var, fh))
    return targets


def _vars_to_schedule(plugin) -> list[str]:
    model_id = str(getattr(plugin, "id", "")).lower()
    excluded = COMPONENT_ONLY_VARS_BY_MODEL.get(model_id, set())
    scheduled: list[str] = []
    for var_id, var_spec in plugin.vars.items():
        normalized_var = plugin.normalize_var_id(var_id)
        if plugin.get_var(normalized_var) is None:
            continue
        if not (bool(getattr(var_spec, "primary", False)) or bool(getattr(var_spec, "derived", False))):
            continue
        if normalized_var in excluded:
            continue
        scheduled.append(normalized_var)
    return _dedupe_preserve_order(scheduled)


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _enforce_output_retention(
    out_root: Path,
    model: str,
    region: str,
    latest_pointer_run: str | None,
    newest_run: str | None,
    active_run: str | None,
) -> None:
    root = out_root / model / region
    if not root.exists():
        return

    runs: list[tuple[datetime, Path]] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        run_dt = _parse_run_id_datetime(entry.name)
        if run_dt is None:
            continue
        runs.append((run_dt, entry))

    if not runs:
        return

    runs.sort(key=lambda item: item[0], reverse=True)
    keep_names = {p.name for _, p in runs[:2]}
    if latest_pointer_run:
        keep_names.add(latest_pointer_run)
    if newest_run:
        keep_names.add(newest_run)
    if active_run:
        keep_names.add(active_run)

    for run_dt, entry in runs:
        if entry.name in keep_names:
            continue
        if not _is_under_root(entry, root):
            logger.warning("Skipping retention delete outside root: %s", entry)
            continue
        logger.info("Removing old run dir: %s", entry)
        shutil.rmtree(entry, ignore_errors=True)


def _run_build_task(task: dict) -> dict:
    cmd = [
        sys.executable,
        task["script"],
        "--run",
        task["run_id"],
        "--fh",
        str(task["fh"]),
        "--var",
        task["var"],
        "--model",
        task["model"],
        "--region",
        task["region"],
        "--out-root",
        task["out_root"],
    ]
    env = os.environ.copy()
    backend_v2_dir = str(Path(task["script"]).resolve().parents[1])
    env["PYTHONPATH"] = os.pathsep.join(
        [backend_v2_dir, env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    return {
        "run_id": task["run_id"],
        "var": task["var"],
        "fh": task["fh"],
        "returncode": result.returncode,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
    }


def _summarize_loop(
    run_id: str,
    completed: int,
    total: int,
    pending: int,
    newest_run: str | None,
    latest_pointer: str | None,
) -> None:
    logger.info(
        "Loop summary: run=%s completed=%s/%s pending=%s newest=%s latest=%s",
        run_id,
        completed,
        total,
        pending,
        newest_run or "none",
        latest_pointer or "none",
    )


def _should_abandon_run(active_run: str, newest_run: str, now_utc: datetime) -> bool:
    if active_run == newest_run:
        return False
    active_dt = _parse_run_id_datetime(active_run)
    newest_dt = _parse_run_id_datetime(newest_run)
    if active_dt is None or newest_dt is None:
        return True
    if newest_dt <= active_dt:
        return False
    if now_utc - active_dt >= timedelta(hours=2):
        return True
    return False


def in_release_window(now_utc: datetime) -> bool:
    minute = now_utc.minute
    return RELEASE_WINDOW_START_MINUTE <= minute <= RELEASE_WINDOW_END_MINUTE


def compute_sleep_seconds(
    now_utc: datetime,
    *,
    caught_up: bool,
    pending: int,
    latest_missing: bool,
    latest_missing_backoff: int,
) -> tuple[int, str]:
    if pending > 0:
        return BUSY_POLL_SECONDS, "busy"
    if latest_missing:
        return latest_missing_backoff, "backoff"
    if in_release_window(now_utc):
        return RELEASE_POLL_SECONDS, "release"
    return QUIET_POLL_SECONDS, "quiet"


def _apply_sleep_jitter(seconds: int) -> float:
    if seconds <= 0:
        return 0.0
    delta = seconds * SLEEP_JITTER_RATIO
    jittered = seconds + random.uniform(-delta, delta)
    return max(1.0, jittered)


def _normalize_reason(text: str | None) -> str:
    if not text:
        return "unknown"

    # Try to stabilize "Upstream not ready" errors by extracting the value after "reason=".
    # Herbie/our wrappers often embed var/run/fh in the first line; we only want the actual cause.
    match = re.search(r"reason=([^\n\r]*)", text)
    if match:
        candidate = match.group(1).strip()
        if candidate:
            return candidate

    # Fall back to the first non-empty line.
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line

    return "unknown"


def _prune_upstream_log_cache(now_ts: float) -> None:
    expired = [key for key, entry in _UPSTREAM_LOG_CACHE.items() if now_ts - entry["last_seen_ts"] > CACHE_TTL_SECONDS]
    for key in expired:
        _UPSTREAM_LOG_CACHE.pop(key, None)


def run_scheduler(
    *,
    model: str,
    region: str,
    vars: list[str],
    primary_vars: list[str],
    out_root: Path | None = None,
    workers: int | None = None,
) -> int:
    out_root = out_root or _data_root()
    try:
        plugin = get_model(model)
    except Exception as exc:
        raise ConfigError(f"Unknown model: {model}") from exc
    if plugin.get_region(region) is None:
        raise ConfigError(f"Unknown region: {region}")
    script_path = _build_script_path_for_model(model)
    if not script_path.exists():
        raise ConfigError(f"Build script not found for model={model}: {script_path}")
    vars_to_build = _vars_to_schedule(plugin)
    primary_vars = _dedupe_preserve_order(
        [
            plugin.normalize_var_id(v)
            for v in primary_vars
            if plugin.get_var(plugin.normalize_var_id(v)) is not None
        ]
    )
    if not vars_to_build:
        raise ConfigError(f"No supported vars to schedule for model={model}; requested={vars}")
    probe_var = primary_vars[0] if primary_vars else plugin.normalize_var_id(PRIMARY_VAR_DEFAULT)
    latest_path = _latest_pointer_path(out_root, model, region)

    max_workers = workers if workers is not None else _workers()
    active_run_id: str | None = None
    active_cycle_hour: int | None = None
    newest_run_id: str | None = None
    newest_cycle_hour: int | None = None
    last_probe_ts = 0.0
    latest_missing_backoff = BACKOFF_INITIAL_SECONDS
    latest_missing = False
    last_sleep_policy: tuple[str, bool, int, bool, int] | None = None
    not_ready_backoff: dict[tuple[str, str, int], int] = {}
    not_ready_retry_at: dict[tuple[str, str, int], float] = {}

    logger.info("Scheduler starting: model=%s region=%s vars=%s", model, region, vars_to_build)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        while True:
            now_ts = time.time()
            now_utc = datetime.now(timezone.utc)
            probe_interval = RELEASE_POLL_SECONDS if in_release_window(now_utc) else QUIET_POLL_SECONDS
            if latest_missing:
                probe_interval = max(probe_interval, latest_missing_backoff)
            should_probe = active_run_id is None or (now_ts - last_probe_ts >= probe_interval)
            if should_probe:
                newest = _probe_latest_run(model, region, probe_var)
                last_probe_ts = now_ts
                if newest is None:
                    latest_missing = True
                    latest_missing_backoff = min(
                        BACKOFF_MAX_SECONDS,
                        max(latest_missing_backoff * 2, BACKOFF_INITIAL_SECONDS),
                    )
                    if active_run_id is None:
                        base_sleep, window_label = compute_sleep_seconds(
                            now_utc,
                            caught_up=False,
                            pending=0,
                            latest_missing=True,
                            latest_missing_backoff=latest_missing_backoff,
                        )
                        sleep_seconds = _apply_sleep_jitter(base_sleep)
                        policy_key = (window_label, False, 0, True, base_sleep)
                        if policy_key != last_sleep_policy:
                            logger.info(
                                "Sleep policy: window=%s caught_up=%s pending=%s sleep=%.0fs",
                                window_label,
                                False,
                                0,
                                sleep_seconds,
                            )
                            last_sleep_policy = policy_key
                        logger.info("No runs available yet for model=%s; sleeping", model)
                        time.sleep(sleep_seconds)
                        continue
                else:
                    newest_run_id, newest_cycle_hour = newest
                    latest_missing = False
                    latest_missing_backoff = BACKOFF_INITIAL_SECONDS
            elif newest_run_id is None and active_run_id is not None:
                newest_run_id = active_run_id
                newest_cycle_hour = active_cycle_hour

            if newest_run_id is None or newest_cycle_hour is None:
                base_sleep, window_label = compute_sleep_seconds(
                    now_utc,
                    caught_up=False,
                    pending=0,
                    latest_missing=True,
                    latest_missing_backoff=latest_missing_backoff,
                )
                sleep_seconds = _apply_sleep_jitter(base_sleep)
                policy_key = (window_label, False, 0, True, base_sleep)
                if policy_key != last_sleep_policy:
                    logger.info(
                        "Sleep policy: window=%s caught_up=%s pending=%s sleep=%.0fs",
                        window_label,
                        False,
                        0,
                        sleep_seconds,
                    )
                    last_sleep_policy = policy_key
                logger.info("No runs available yet for model=%s; sleeping", model)
                time.sleep(sleep_seconds)
                continue

            if active_run_id is None:
                active_run_id = newest_run_id
                active_cycle_hour = newest_cycle_hour
            elif newest_run_id != active_run_id:
                if _should_abandon_run(active_run_id, newest_run_id, now_utc):
                    logger.info("Switching to newer run: %s -> %s", active_run_id, newest_run_id)
                    not_ready_backoff.clear()
                    not_ready_retry_at.clear()
                    active_run_id = newest_run_id
                    active_cycle_hour = newest_cycle_hour
                elif active_cycle_hour is None:
                    match = RUN_ID_RE.match(active_run_id)
                    if match:
                        active_cycle_hour = int(match.group("hour"))
                    else:
                        logger.warning("Invalid active run id: %s; switching to newest", active_run_id)
                        not_ready_backoff.clear()
                        not_ready_retry_at.clear()
                        active_run_id = newest_run_id
                        active_cycle_hour = newest_cycle_hour

            if active_run_id is None or active_cycle_hour is None:
                base_sleep, window_label = compute_sleep_seconds(
                    now_utc,
                    caught_up=False,
                    pending=0,
                    latest_missing=latest_missing,
                    latest_missing_backoff=latest_missing_backoff,
                )
                sleep_seconds = _apply_sleep_jitter(base_sleep)
                policy_key = (window_label, False, 0, latest_missing, base_sleep)
                if policy_key != last_sleep_policy:
                    logger.info(
                        "Sleep policy: window=%s caught_up=%s pending=%s sleep=%.0fs",
                        window_label,
                        False,
                        0,
                        sleep_seconds,
                    )
                    last_sleep_policy = policy_key
                logger.info("No active run resolved; sleeping")
                time.sleep(sleep_seconds)
                continue

            scheduled_targets = _scheduled_targets_for_cycle(plugin, vars_to_build, active_cycle_hour)
            total = len(scheduled_targets)
            pending: list[tuple[str, int]] = []
            completed = 0

            for var, fh in scheduled_targets:
                out_path = _task_output_path(out_root, model, region, active_run_id, var, fh)
                if out_path.exists():
                    completed += 1
                else:
                    pending.append((var, fh))

            if not pending and active_run_id != newest_run_id:
                active_run_id = newest_run_id
                active_cycle_hour = newest_cycle_hour
                scheduled_targets = _scheduled_targets_for_cycle(plugin, vars_to_build, active_cycle_hour)
                total = len(scheduled_targets)
                pending = []
                completed = 0
                for var, fh in scheduled_targets:
                    out_path = _task_output_path(out_root, model, region, active_run_id, var, fh)
                    if out_path.exists():
                        completed += 1
                    else:
                        pending.append((var, fh))

            latest_pointer_run = _read_latest_pointer(latest_path)
            newest_promotion_fhs = _promotion_fhs_for_cycle(plugin, newest_cycle_hour)
            active_promotion_fhs = _promotion_fhs_for_cycle(plugin, active_cycle_hour)

            if _should_promote_latest(
                out_root,
                model,
                region,
                newest_run_id,
                primary_vars,
                fhs=newest_promotion_fhs,
            ):
                if latest_pointer_run != newest_run_id:
                    _write_latest_pointer(latest_path, newest_run_id)
                    latest_pointer_run = newest_run_id
            elif _should_promote_latest(
                out_root,
                model,
                region,
                active_run_id,
                primary_vars,
                fhs=active_promotion_fhs,
            ):
                if latest_pointer_run != active_run_id:
                    _write_latest_pointer(latest_path, active_run_id)
                    latest_pointer_run = active_run_id

            _summarize_loop(active_run_id, completed, total, len(pending), newest_run_id, latest_pointer_run)

            loop_not_ready: dict[tuple[str, str], dict[str, set[int] | set[str]]] = {}
            pending_ready_count = len(pending)
            pending_retry_in_seconds: int | None = None

            if pending:
                primary_set = set(primary_vars)
                now_for_filter = time.time()
                ready_pending: list[tuple[str, int]] = []
                for var, fh in pending:
                    key = (active_run_id, var, fh)
                    retry_at = not_ready_retry_at.get(key, 0.0)
                    if retry_at > now_for_filter:
                        wait_seconds = int(max(1.0, retry_at - now_for_filter))
                        if pending_retry_in_seconds is None or wait_seconds < pending_retry_in_seconds:
                            pending_retry_in_seconds = wait_seconds
                        continue
                    ready_pending.append((var, fh))

                pending_ready_count = len(ready_pending)
                ready_pending.sort(key=lambda item: (item[1], 0 if item[0] in primary_set else 1, item[0]))
                batch_size = min(len(ready_pending), max_workers * 2)
                batch = ready_pending[:batch_size]
                tasks = []
                for var, fh in batch:
                    tasks.append(
                        {
                            "script": str(script_path),
                            "run_id": active_run_id,
                            "fh": fh,
                            "var": var,
                            "model": model,
                            "region": region,
                            "out_root": str(out_root),
                        }
                    )
                    logger.info("Queue build: run=%s var=%s fh=%s", active_run_id, var, fh)

                futures = [executor.submit(_run_build_task, task) for task in tasks]
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    if result["returncode"] == 0:
                        state_key = (result["run_id"], result["var"], int(result["fh"]))
                        not_ready_backoff.pop(state_key, None)
                        not_ready_retry_at.pop(state_key, None)
                        logger.info(
                            "Build success: run=%s var=%s fh=%s",
                            result["run_id"],
                            result["var"],
                            result["fh"],
                        )
                    else:
                        combined = f"{result['stderr']}\n{result['stdout']}"
                        is_retryable = result["returncode"] == 2
                        if is_retryable:
                            reason = _normalize_reason(combined) if combined.strip() else "returncode 2"
                            key = (result["run_id"], reason)
                            entry = loop_not_ready.setdefault(key, {"fhs": set(), "vars": set()})
                            entry["fhs"].add(result["fh"])
                            entry["vars"].add(result["var"])
                            state_key = (result["run_id"], result["var"], int(result["fh"]))
                            current = not_ready_backoff.get(state_key, 0)
                            next_backoff = (
                                BACKOFF_INITIAL_SECONDS
                                if current <= 0
                                else min(BACKOFF_MAX_SECONDS, current * 2)
                            )
                            jittered_backoff = int(_apply_sleep_jitter(next_backoff))
                            not_ready_backoff[state_key] = next_backoff
                            not_ready_retry_at[state_key] = time.time() + max(1, jittered_backoff)
                        else:
                            logger.error(
                                "Build failed: run=%s var=%s fh=%s code=%s stderr=%s",
                                result["run_id"],
                                result["var"],
                                result["fh"],
                                result["returncode"],
                                result["stderr"],
                            )

            now_ts = time.time()
            _prune_upstream_log_cache(now_ts)
            for (run_id, reason), summary in loop_not_ready.items():
                cache_key = (run_id, reason)
                cache_entry = _UPSTREAM_LOG_CACHE.get(cache_key)
                last_logged_ts = cache_entry["last_logged_ts"] if cache_entry else 0.0
                if now_ts - last_logged_ts < RATE_LIMIT_SECONDS:
                    if cache_entry:
                        cache_entry["last_seen_ts"] = now_ts
                    continue
                fhs_list = sorted(summary["fhs"])
                vars_list = sorted(summary["vars"])
                logger.info(
                    "Upstream not ready: run=%s reason=%s fhs=%s vars=%s count_fh=%s",
                    run_id,
                    reason,
                    fhs_list,
                    vars_list,
                    len(fhs_list),
                )
                _UPSTREAM_LOG_CACHE[cache_key] = {
                    "last_logged_ts": now_ts,
                    "last_seen_ts": now_ts,
                }

            _enforce_output_retention(
                out_root,
                model,
                region,
                latest_pointer_run,
                newest_run_id,
                active_run_id,
            )

            caught_up = len(pending) == 0 and completed == total and active_run_id == newest_run_id
            base_sleep, window_label = compute_sleep_seconds(
                now_utc,
                caught_up=caught_up,
                pending=pending_ready_count,
                latest_missing=latest_missing,
                latest_missing_backoff=latest_missing_backoff,
            )
            if pending_ready_count == 0 and pending_retry_in_seconds is not None:
                base_sleep = min(base_sleep, pending_retry_in_seconds)
            sleep_seconds = _apply_sleep_jitter(base_sleep)
            policy_key = (window_label, caught_up, pending_ready_count, latest_missing, base_sleep)
            if policy_key != last_sleep_policy:
                logger.info(
                    "Sleep policy: window=%s caught_up=%s pending=%s sleep=%.0fs",
                    window_label,
                    caught_up,
                    pending_ready_count,
                    sleep_seconds,
                )
                last_sleep_policy = policy_key
            time.sleep(sleep_seconds)


def run_self_test() -> int:
    samples = [
        "/data/hrrr/20250205/21/hrrr.t21z.wrfsfcf00.tmp2m.grib2",
        "/data/hrrr/20250205/21/hrrr.t22z.wrfsfcf00.tmp2m.grib2",
        "/data/hrrr/20250230/21/hrrr.t21z.wrfsfcf00.tmp2m.grib2",
        "/data/hrrr/20250205/99/hrrr.t21z.wrfsfcf00.tmp2m.grib2",
        "/data/hrrr/20250205/21/hrrr.wrfsfcf00.tmp2m.grib2",
    ]
    for sample in samples:
        path = Path(sample)
        print(f"{sample} -> {_derive_run_id_from_grib_path(path)}")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the V2 model scheduler.")
    parser.add_argument("--model", type=str, required=True)
    parser.add_argument("--region", type=str, default=None)
    parser.add_argument("--vars", type=str, default=VAR_DEFAULTS)
    parser.add_argument("--primary-vars", type=str, default=PRIMARY_VAR_DEFAULT)
    parser.add_argument("--data-root", type=str, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    if args.self_test:
        return run_self_test()

    out_root = Path(args.data_root).resolve() if args.data_root else _data_root()

    try:
        region_list = _resolve_regions_for_cli(args.model, out_root, args.region)
    except (ConfigError, RunResolutionError) as exc:
        logger.error("Scheduler configuration error: %s", exc)
        return 1

    vars_list = parse_vars(args.vars)
    primary_list = parse_vars(args.primary_vars)

    region = region_list[0]
    try:
        return run_scheduler(
            model=args.model,
            region=region,
            vars=vars_list,
            primary_vars=primary_list,
            out_root=out_root,
            workers=args.workers,
        )
    except (ConfigError, RunResolutionError) as exc:
        logger.error("Scheduler failed for region=%s: %s", region, exc)
        return 1
    except KeyboardInterrupt:
        logger.info("Scheduler shutdown requested")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
