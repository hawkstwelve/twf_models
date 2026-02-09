from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add backend_v2 to path so app module can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))

from app.services.hrrr_fetch import fetch_hrrr_grib
from app.services.hrrr_runs import HRRRCacheConfig, resolve_hrrr_grib_path
from app.services.paths import default_hrrr_cache_dir
from app.services.variable_registry import herbie_search_for, normalize_api_variable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=str, default="latest")
    parser.add_argument("--fh", type=int, default=1)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--var", type=str, default=None)
    args = parser.parse_args()

    base_dir = args.cache_dir or default_hrrr_cache_dir()
    cfg = HRRRCacheConfig(base_dir=base_dir, keep_runs=1)

    if args.var:
        normalized = normalize_api_variable(args.var)
        search = herbie_search_for(args.var)
        print(f"Variable: {args.var} normalized={normalized} search={search or '(none)'}")

    try:
        result = fetch_hrrr_grib(run=args.run, fh=args.fh, variable=args.var, cache_cfg=cfg)
    except Exception as exc:
        print(str(exc))
        return 1

    if result.not_ready_reason:
        print(f"Upstream not ready: {result.not_ready_reason}")
        return 2
    if result.path is None:
        print("Fetch completed without GRIB path")
        return 1

    path = result.path
    print(f"Downloaded path: {path}")

    try:
        resolved = resolve_hrrr_grib_path(cfg, run=args.run, fh=args.fh)
    except Exception as exc:
        print(str(exc))
        return 1

    print(f"Resolved path: {resolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
