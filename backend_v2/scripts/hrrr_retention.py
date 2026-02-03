from __future__ import annotations

import argparse
from pathlib import Path

from app.services.hrrr_runs import HRRRCacheConfig, enforce_cycle_retention, list_cycle_dirs
from app.services.paths import default_hrrr_cache_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--keep-runs", type=int, default=1)
    parser.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args()

    base_dir = args.cache_dir or default_hrrr_cache_dir()
    cfg = HRRRCacheConfig(base_dir=base_dir, keep_runs=args.keep_runs)

    run_dirs = list_cycle_dirs(cfg)
    if not run_dirs:
        print(f"No HRRR cycle directories found in {base_dir}")
        return 2

    keep = max(1, args.keep_runs)
    keep_dirs = run_dirs[:keep]
    delete_dirs = run_dirs[keep:]

    print(f"Base dir: {base_dir}")
    print(f"Keep runs: {keep}")
    print("Keep cycles:")
    for path in keep_dirs:
        print(f"  {path}")
    print("Delete cycles:")
    for path in delete_dirs:
        print(f"  {path}")

    if not args.apply:
        print("Dry run only. Use --apply to delete.")
        return 0

    summary = enforce_cycle_retention(cfg)
    print(
        "Deleted cycles: {deleted_cycles}, deleted files: {deleted_files}, deleted day dirs: {deleted_day_dirs}, kept cycles: {kept_cycles}".format(
            **summary
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
