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

import build_cog as _build_cog

main = _build_cog.main


def __getattr__(name: str):
    return getattr(_build_cog, name)


if __name__ == "__main__":
    raise SystemExit(main())
