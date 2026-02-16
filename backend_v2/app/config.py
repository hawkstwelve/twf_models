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
    STAGING_ROOT: Path = Path(os.environ.get("STAGING_ROOT", "/data/staging")).resolve()
    PUBLISH_ROOT: Path = Path(os.environ.get("PUBLISH_ROOT", "/data/published")).resolve()
    MANIFEST_ROOT: Path = Path(os.environ.get("MANIFEST_ROOT", "/opt/twf_models/data/manifests")).resolve()
    OFFLINE_TILES_MAX_WORKERS: int = _env_int("OFFLINE_TILES_MAX_WORKERS", default=4, minimum=1, maximum=6)
    OFFLINE_TILES_INITIAL_GATE: int = _env_int("OFFLINE_TILES_INITIAL_GATE", default=6)
    OFFLINE_TILES_PUBLISH_DELTA: int = _env_int("OFFLINE_TILES_PUBLISH_DELTA", default=6, minimum=1)
    OFFLINE_FRAME_IMAGES_ENABLED: bool = _env_bool("OFFLINE_FRAME_IMAGES_ENABLED", default=True)
    OFFLINE_FRAME_IMAGE_SIZE_PX: int = _env_int("OFFLINE_FRAME_IMAGE_SIZE_PX", default=2048, minimum=256, maximum=4096)
    OFFLINE_FRAME_IMAGE_WEBP_QUALITY: int = _env_int(
        "OFFLINE_FRAME_IMAGE_WEBP_QUALITY",
        default=90,
        minimum=1,
        maximum=100,
    )
    WRITE_LEGACY_MODEL_LATEST_ALIAS: bool = _env_bool("WRITE_LEGACY_MODEL_LATEST_ALIAS", default=False)


settings = Settings()
