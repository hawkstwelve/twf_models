from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add backend_v2 to path so app module can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))

from app.services.hrrr_runs import HRRRCacheConfig, list_cycle_dirs
from app.services.paths import default_hrrr_cache_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=None)
    args = parser.parse_args()

    base_dir = args.cache_dir or default_hrrr_cache_dir()
    cfg = HRRRCacheConfig(base_dir=base_dir, keep_runs=1)

    cycle_dirs = list_cycle_dirs(cfg)
    if not cycle_dirs:
        print(f"No HRRR cycle directories found in {base_dir}")
        return 2

    print("Latest cycles:")
    for path in cycle_dirs[:10]:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
