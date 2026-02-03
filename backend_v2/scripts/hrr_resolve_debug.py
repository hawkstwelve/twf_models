from __future__ import annotations

import warnings

from backend_v2.scripts.hrrr_resolve_debug import main


if __name__ == "__main__":
    warnings.warn(
        "hrr_resolve_debug.py is deprecated; use hrrr_resolve_debug.py",
        DeprecationWarning,
    )
    raise SystemExit(main())
