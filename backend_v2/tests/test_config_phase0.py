from __future__ import annotations

import importlib
from pathlib import Path

from app import config as config_module


def test_phase0_offline_tiles_settings(monkeypatch) -> None:
    monkeypatch.setenv("OFFLINE_TILES_ENABLED", "true")
    monkeypatch.setenv("STAGING_ROOT", "/tmp/twf/staging")
    monkeypatch.setenv("PUBLISH_ROOT", "/tmp/twf/published")
    monkeypatch.setenv("MANIFEST_ROOT", "/tmp/twf/manifests")
    monkeypatch.setenv("OFFLINE_TILES_MAX_WORKERS", "12")
    monkeypatch.setenv("OFFLINE_TILES_INITIAL_GATE", "8")
    monkeypatch.setenv("OFFLINE_TILES_PUBLISH_DELTA", "0")
    monkeypatch.setenv("WRITE_LEGACY_MODEL_LATEST_ALIAS", "true")

    reloaded = importlib.reload(config_module)

    assert reloaded.settings.OFFLINE_TILES_ENABLED is True
    assert reloaded.settings.STAGING_ROOT == Path("/tmp/twf/staging").resolve()
    assert reloaded.settings.PUBLISH_ROOT == Path("/tmp/twf/published").resolve()
    assert reloaded.settings.MANIFEST_ROOT == Path("/tmp/twf/manifests").resolve()
    assert reloaded.settings.OFFLINE_TILES_MAX_WORKERS == 6
    assert reloaded.settings.OFFLINE_TILES_INITIAL_GATE == 8
    assert reloaded.settings.OFFLINE_TILES_PUBLISH_DELTA == 1
    assert reloaded.settings.WRITE_LEGACY_MODEL_LATEST_ALIAS is True


def test_phase0_metrics_are_defined() -> None:
    assert config_module.OFFLINE_TILE_BUILD_DURATION_SECONDS_METRIC
    assert config_module.OFFLINE_TILE_VALIDATION_RESULTS_TOTAL_METRIC
    assert config_module.OFFLINE_TILE_PUBLISH_POINTER_SWITCH_LATENCY_SECONDS_METRIC
