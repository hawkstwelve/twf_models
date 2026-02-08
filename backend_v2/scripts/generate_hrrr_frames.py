from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Add backend_v2 to path so app module can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))

from app.services.colormaps_v2 import VAR_SPECS
from app.services.hrrr_runs import HRRRCacheConfig, get_latest_cycle_dir
from app.services.paths import default_hrrr_cache_dir

logger = logging.getLogger(__name__)
RUN_RE = re.compile(r"^\d{8}_(\d{2})z$")
RUN_ID_RE = re.compile(r"^(?P<day>\d{8})_(?P<hour>\d{2})z$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate HRRR V2 COG frames for the latest run.")
    parser.add_argument("--cache-dir", type=str, default=None)
    parser.add_argument("--model", type=str, default="hrrr")
    parser.add_argument("--region", type=str, default="pnw")
    parser.add_argument("--out-root", type=str, default="/opt/twf_models/data/v2")
    parser.add_argument("--run", type=str, default="latest")
    parser.add_argument("--vars", type=str, default=None)
    parser.add_argument("--fh", type=str, default=None)
    parser.add_argument("--no-retention", action="store_true")
    return parser.parse_args()


def resolve_latest_run(cfg: HRRRCacheConfig) -> tuple[str, int]:
    cycle_dir = get_latest_cycle_dir(cfg)
    day_dir = cycle_dir.parent
    run_id = f"{day_dir.name}_{cycle_dir.name}z"
    cycle_hour = int(cycle_dir.name)
    return run_id, cycle_hour


def parse_run_id_datetime(value: str) -> datetime | None:
    match = RUN_ID_RE.match(value)
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
        return datetime(year, month, day_num, hour)
    except ValueError:
        return None


def parse_fh_arg(value: str) -> list[int]:
    text = value.strip()
    if not text:
        raise ValueError("--fh cannot be empty")
    if "-" in text:
        parts = [item.strip() for item in text.split("-") if item.strip()]
        if len(parts) != 2:
            raise ValueError(f"Invalid --fh range format: {value}")
        start, end = (int(parts[0]), int(parts[1]))
        if end < start:
            raise ValueError(f"Invalid --fh range (end < start): {value}")
        return list(range(start, end + 1))
    values = [int(item.strip()) for item in text.split(",") if item.strip()]
    if not values:
        raise ValueError(f"Invalid --fh list format: {value}")
    return sorted(set(values))


def parse_vars_arg(value: str) -> list[str]:
    items = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError("--vars cannot be empty")
    return items


def to_fetch_run(run_id: str) -> str:
    if run_id == "latest":
        return "latest"
    if RUN_RE.match(run_id):
        return run_id.replace("_", "")[:-1]
    if re.fullmatch(r"^\d{10}$", run_id):
        return run_id
    if re.fullmatch(r"^\d{8}$", run_id):
        return run_id
    raise ValueError(
        "Invalid run_id for fetch_hrrr_grib. Expected 'latest', YYYYMMDD_HHz, YYYYMMDDHH, or YYYYMMDD."
    )


def select_mvp_vars() -> list[str]:
    vars_available = list(VAR_SPECS.keys())
    if "tmp2m" not in VAR_SPECS:
        raise RuntimeError("VAR_SPECS missing required tmp2m")

    wind_like = next((key for key in vars_available if "wind" in key), None)
    if wind_like is None:
        logger.warning("No wind-like variable found in VAR_SPECS; selecting fallback")

    discrete_var = "radar_ptype" if "radar_ptype" in VAR_SPECS else None
    if discrete_var is None:
        discrete_var = next(
            (key for key, spec in VAR_SPECS.items() if spec.get("type") == "discrete"),
            None,
        )

    chosen = ["tmp2m"]
    if wind_like and wind_like not in chosen:
        chosen.append(wind_like)
    if discrete_var and discrete_var not in chosen:
        chosen.append(discrete_var)

    for key in vars_available:
        if len(chosen) >= 3:
            break
        if key not in chosen:
            chosen.append(key)

    if len(chosen) < 3:
        raise RuntimeError(f"Unable to select 3 MVP vars from VAR_SPECS (got {chosen})")

    return chosen[:3]


def _check_run_complete(run_dir: Path, vars_to_build: list[str], fhs: list[int]) -> tuple[bool, str | None]:
    for var in vars_to_build:
        var_dir = run_dir / var
        if not var_dir.is_dir():
            return False, f"missing var dir: {var_dir.name}"
        for fh in fhs:
            cog_path = var_dir / f"fh{fh:03d}.cog.tif"
            json_path = var_dir / f"fh{fh:03d}.json"
            if not cog_path.exists():
                return False, f"missing cog: {var_dir.name}/fh{fh:03d}.cog.tif"
            if not json_path.exists():
                return False, f"missing json: {var_dir.name}/fh{fh:03d}.json"
    return True, None


def build_frames(
    *,
    script_path: Path,
    run_id: str,
    fetch_run: str,
    fhs: list[int],
    vars_to_build: list[str],
    args: argparse.Namespace,
) -> list[dict]:
    failures: list[dict] = []
    for var in vars_to_build:
        for fh in fhs:
            cmd = [
                sys.executable,
                str(script_path),
                "--run",
                fetch_run,
                "--fh",
                str(fh),
                "--var",
                var,
                "--model",
                args.model,
                "--region",
                args.region,
                "--out-root",
                args.out_root,
            ]
            if args.cache_dir:
                cmd.extend(["--cache-dir", args.cache_dir])

            logger.info("Building COG: var=%s fh=%s", var, fh)
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                logger.error(
                    "Failed COG build: var=%s fh=%s code=%s stderr=%s",
                    var,
                    fh,
                    result.returncode,
                    (result.stderr or "").strip(),
                )
                failures.append(
                    {
                        "var": var,
                        "fh": fh,
                        "code": result.returncode,
                        "stderr": (result.stderr or "").strip(),
                    }
                )
            else:
                out_dir = Path(args.out_root) / args.model / args.region / run_id / var
                cog_path = out_dir / f"fh{fh:03d}.cog.tif"
                json_path = out_dir / f"fh{fh:03d}.json"
                if not cog_path.exists() or not json_path.exists():
                    logger.error(
                        "COG build missing outputs: var=%s fh=%s run=%s cog=%s json=%s",
                        var,
                        fh,
                        run_id,
                        cog_path,
                        json_path,
                    )
                    failures.append(
                        {
                            "var": var,
                            "fh": fh,
                            "code": "missing-output",
                            "stderr": f"Expected outputs not found: {cog_path}, {json_path}",
                        }
                    )
                else:
                    logger.info("Success: var=%s fh=%s run=%s path=%s", var, fh, run_id, cog_path)

    return failures


def enforce_latest_run_retention(
    *,
    out_root: Path,
    model: str,
    region: str,
    keep_run: str,
    expected_vars: list[str],
    expected_fhs: list[int],
) -> None:
    root = out_root / model / region
    if not root.exists():
        return

    parsed_runs: list[tuple[datetime, Path]] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        run_dt = parse_run_id_datetime(entry.name)
        if run_dt is None:
            logger.warning("Skipping run dir with invalid name: %s", entry.name)
            continue
        complete, reason = _check_run_complete(entry, expected_vars, expected_fhs)
        if not complete:
            logger.warning("Skipping incomplete run dir: %s (%s)", entry.name, reason)
            continue
        parsed_runs.append((run_dt, entry))

    if not parsed_runs:
        logger.warning("No complete run dirs found under %s; retention skipped", root)
        return

    parsed_runs.sort(key=lambda item: item[0], reverse=True)
    latest_dt, latest_dir = parsed_runs[0]
    keep_names = {keep_run, latest_dir.name}
    if keep_run != latest_dir.name:
        logger.warning(
            "Latest complete run differs from keep_run; keeping both: keep_run=%s latest=%s",
            keep_run,
            latest_dir.name,
        )

    for run_dt, entry in parsed_runs:
        if entry.name in keep_names:
            continue
        if run_dt > latest_dt:
            logger.warning("Refusing to delete newer run dir: %s", entry.name)
            continue
        logger.info("Removing old run dir: %s", entry)
        shutil.rmtree(entry, ignore_errors=True)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()

    cache_dir = Path(args.cache_dir) if args.cache_dir else default_hrrr_cache_dir()
    cfg = HRRRCacheConfig(base_dir=cache_dir, keep_runs=1)

    if args.run == "latest":
        try:
            run_id, cycle_hour = resolve_latest_run(cfg)
        except Exception as exc:
            logger.error("Failed to resolve latest HRRR run: %s", exc)
            return 1
    else:
        match = RUN_RE.match(args.run)
        if not match:
            logger.error("Invalid --run format (expected YYYYMMDD_HHz): %s", args.run)
            return 1
        run_id = args.run
        cycle_hour = int(match.group(1))
        out_dir = Path(args.out_root) / args.model / args.region / run_id
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("Failed to prepare output dir %s: %s", out_dir, exc)
            return 1

    if args.fh:
        try:
            fhs = parse_fh_arg(args.fh)
        except ValueError as exc:
            logger.error("Invalid --fh value: %s", exc)
            return 1
    else:
        if cycle_hour in {0, 6, 12, 18}:
            fhs = list(range(0, 49))
        else:
            fhs = list(range(0, 19))

    if args.vars:
        try:
            vars_to_build = parse_vars_arg(args.vars)
        except ValueError as exc:
            logger.error("Invalid --vars value: %s", exc)
            return 1
        missing = [var for var in vars_to_build if var not in VAR_SPECS]
        if missing:
            logger.error("Unknown vars in --vars: %s", ", ".join(missing))
            return 1
    else:
        vars_to_build = select_mvp_vars()
    logger.info("Run: %s (cycle=%02d) fhs=%s vars=%s", run_id, cycle_hour, fhs[-1], vars_to_build)

    try:
        fetch_run = to_fetch_run(run_id)
    except ValueError as exc:
        logger.error(str(exc))
        return 1
    logger.info("Using fetch_run=%s for run_id=%s", fetch_run, run_id)

    script_path = Path(__file__).resolve().parent / "build_cog.py"
    failures = build_frames(
        script_path=script_path,
        run_id=run_id,
        fetch_run=fetch_run,
        fhs=fhs,
        vars_to_build=vars_to_build,
        args=args,
    )

    if not args.no_retention:
        enforce_latest_run_retention(
            out_root=Path(args.out_root),
            model=args.model,
            region=args.region,
            keep_run=run_id,
            expected_vars=vars_to_build,
            expected_fhs=fhs,
        )

    if failures:
        logger.warning("Completed with %s failures", len(failures))
        for failure in failures:
            logger.warning("Failure: var=%s fh=%s code=%s", failure["var"], failure["fh"], failure["code"])
        return 2

    logger.info("All frames built successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
