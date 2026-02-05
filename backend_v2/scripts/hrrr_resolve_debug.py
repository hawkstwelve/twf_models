from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add backend_v2 to path so app module can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))

from app.services.hrrr_runs import HRRRCacheConfig, list_cycle_dirs, resolve_hrrr_grib_path
from app.services.paths import default_hrrr_cache_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--run", type=str, default="latest")
    parser.add_argument("--fh", type=int, default=1)
    args = parser.parse_args()

    base_dir = args.cache_dir or default_hrrr_cache_dir()
    cfg = HRRRCacheConfig(base_dir=base_dir, keep_runs=1)

    run_dirs = list_cycle_dirs(cfg)
    print(f"Base dir: {base_dir}")
    if not run_dirs:
        print("No run dirs found.")
        return 2

    print("Cycle dirs (newest first):")
    for path in run_dirs:
        print(f"  {path}")

    try:
        resolved = resolve_hrrr_grib_path(cfg, run=args.run, fh=args.fh)
    except Exception as exc:
        print(str(exc))
        return 1

    print(f"Resolved GRIB path: {resolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
