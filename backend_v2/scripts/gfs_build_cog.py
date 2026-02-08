from __future__ import annotations

import sys
from pathlib import Path

# Compatibility shim. Canonical builder now lives in build_cog.py.
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from build_cog import (
    _coerce_run_id,
    _infer_spacing,
    _latlon_axes_from_grib_attrs,
    _normalize_latlon_dataarray,
    _resolve_radar_blend_component_paths,
    main as _build_cog_main,
)


def _strip_legacy_product_flag(argv: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--product":
            i += 2
            continue
        if arg.startswith("--product="):
            i += 1
            continue
        out.append(arg)
        i += 1
    return out


def main() -> int:
    sys.argv = _strip_legacy_product_flag(sys.argv)
    return _build_cog_main()


if __name__ == "__main__":
    raise SystemExit(main())
