from __future__ import annotations

import os
from pathlib import Path

MBTILES_ROOT = Path(
    os.environ.get("TWF_MBTILES_ROOT", "/var/lib/twf-models/mbtiles")
).resolve()
