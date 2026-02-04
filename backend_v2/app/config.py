from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MBTILES_ROOT = Path(
    os.environ.get("TWF_MBTILES_ROOT", "/var/lib/twf-models/mbtiles")
).resolve()


@dataclass(frozen=True)
class Settings:
    DATA_V2_ROOT: Path = Path(os.environ.get("TWF_DATA_V2_ROOT", "/opt/twf_models/data/v2")).resolve()


settings = Settings()
