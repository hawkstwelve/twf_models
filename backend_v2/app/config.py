from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MBTILES_ROOT = Path(
    os.environ.get("TWF_MBTILES_ROOT", "/var/lib/twf-models/mbtiles")
).resolve()

OFFLINE_TILE_BUILD_DURATION_SECONDS_METRIC = "twf_offline_tile_build_duration_seconds"
OFFLINE_TILE_VALIDATION_RESULTS_TOTAL_METRIC = "twf_offline_tile_validation_results_total"
OFFLINE_TILE_PUBLISH_POINTER_SWITCH_LATENCY_SECONDS_METRIC = (
    "twf_offline_tile_publish_pointer_switch_latency_seconds"
)


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, *, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError:
            value = default
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


@dataclass(frozen=True)
class Settings:
    DATA_V2_ROOT: Path = Path(os.environ.get("TWF_DATA_V2_ROOT", "/opt/twf_models/data/v2")).resolve()
    OFFLINE_TILES_ENABLED: bool = _env_bool("OFFLINE_TILES_ENABLED", default=False)
    STAGING_ROOT: Path = Path(os.environ.get("STAGING_ROOT", "/opt/twf_models/data/staging")).resolve()
    PUBLISH_ROOT: Path = Path(os.environ.get("PUBLISH_ROOT", "/opt/twf_models/data/published")).resolve()
    MANIFEST_ROOT: Path = Path(os.environ.get("MANIFEST_ROOT", "/opt/twf_models/data/manifests")).resolve()
    OFFLINE_TILES_MAX_WORKERS: int = _env_int("OFFLINE_TILES_MAX_WORKERS", default=4, minimum=1, maximum=6)
    RUNTIME_TILE_SUNSET_AT: str | None = os.environ.get("RUNTIME_TILE_SUNSET_AT", "").strip() or None
    WRITE_LEGACY_MODEL_LATEST_ALIAS: bool = _env_bool("WRITE_LEGACY_MODEL_LATEST_ALIAS", default=False)
    APP_ENV: str = os.environ.get("APP_ENV", "development").strip().lower() or "development"
    RUNTIME_TILES_SOFT_DISABLE_PROD: bool = _env_bool("RUNTIME_TILES_SOFT_DISABLE_PROD", default=False)


settings = Settings()
