from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from app import config as config_module
from app.api import offline as offline_api_module
from app.services import offline_tiles as offline_tiles_module


def _touch(path: Path, content: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_source(root: Path, *, model: str, run: str, fh: int) -> None:
    frame_id = f"{fh:03d}"
    source_cog = root / model / "pnw" / run / "tmp2m" / f"fh{frame_id}.cog.tif"
    _touch(source_cog, b"II*\x00fake-cog")
    payload = {
        "model": model,
        "region": "pnw",
        "run": run,
        "var": "tmp2m",
        "fh": fh,
        "meta": {"units": "F", "output_mode": "byte_alpha"},
    }
    (source_cog.parent / f"fh{frame_id}.json").write_text(json.dumps(payload))


def _reload_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(tmp_path / "data_v2"))
    monkeypatch.setenv("STAGING_ROOT", str(tmp_path / "staging"))
    monkeypatch.setenv("PUBLISH_ROOT", str(tmp_path / "published"))
    monkeypatch.setenv("MANIFEST_ROOT", str(tmp_path / "manifests"))
    monkeypatch.setenv("OFFLINE_TILES_ENABLED", "true")
    importlib.reload(config_module)
    offline_tiles = importlib.reload(offline_tiles_module)
    offline_api = importlib.reload(offline_api_module)
    return offline_tiles, offline_api


def test_discovery_endpoints_are_published_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    offline_tiles, offline_api = _reload_app(monkeypatch, tmp_path)
    data_root = tmp_path / "data_v2"

    published_run = "20260207_01z"
    for fh in range(0, 6):
        _write_source(data_root, model="hrrr", run=published_run, fh=fh)
        offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=published_run, var="tmp2m", fh=fh)
        offline_tiles.publish_from_staging(model="hrrr", run=published_run, var="tmp2m")

    staging_only_run = "20260207_02z"
    for fh in range(0, 5):
        _write_source(data_root, model="hrrr", run=staging_only_run, fh=fh)
        offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=staging_only_run, var="tmp2m", fh=fh)
    # Not published (< gate), should not appear in discovery.

    models = offline_api.list_models()
    assert any(item["id"] == "hrrr" for item in models)

    runs = offline_api.list_runs(model="hrrr")
    assert runs == [published_run]

    vars_response = offline_api.list_vars(model="hrrr", run="latest")
    assert vars_response == ["tmp2m"]

    payload = offline_api.get_run_manifest(model="hrrr", run="latest")
    assert payload["run"] == published_run
    assert "tmp2m" in payload["variables"]
