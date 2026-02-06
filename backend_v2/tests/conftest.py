from __future__ import annotations

import sys
from pathlib import Path


_BACKEND_V2_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_V2_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_ROOT))
