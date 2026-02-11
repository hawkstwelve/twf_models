from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from app import config as config_module
from app.services import offline_tiles as offline_tiles_module


def _touch(path: Path, content: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _reload_offline_tiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(tmp_path / "data_v2"))
    monkeypatch.setenv("STAGING_ROOT", str(tmp_path / "staging"))
    monkeypatch.setenv("PUBLISH_ROOT", str(tmp_path / "published"))
    monkeypatch.setenv("MANIFEST_ROOT", str(tmp_path / "manifests"))
    monkeypatch.setenv("OFFLINE_TILES_ENABLED", "true")
    importlib.reload(config_module)
    return importlib.reload(offline_tiles_module)


def test_offline_builder_stages_frame_outputs_and_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    offline_tiles = _reload_offline_tiles(monkeypatch, tmp_path)

    data_root = tmp_path / "data_v2"
    run = "20260207_01z"
    source_cog = data_root / "hrrr" / "pnw" / run / "tmp2m" / "fh000.cog.tif"
    _touch(source_cog, b"II*\x00fake-cog")
    sidecar = {
        "model": "hrrr",
        "region": "pnw",
        "run": run,
        "var": "tmp2m",
        "fh": 0,
        "meta": {
            "units": "F",
            "output_mode": "byte_alpha",
        },
    }
    (source_cog.parent / "fh000.json").write_text(json.dumps(sidecar))

    frame_meta = offline_tiles.stage_single_frame(
        model="hrrr",
        region="pnw",
        run=run,
        var="tmp2m",
        fh=0,
    )
    manifest = offline_tiles.rebuild_staging_manifest("hrrr", run, "tmp2m")

    staging_root = tmp_path / "staging" / "hrrr" / run / "tmp2m"
    assert (staging_root / "frames" / "000.pmtiles").exists()
    assert (staging_root / "meta" / "000.json").exists()
    assert (staging_root / "manifest.json").exists()
    assert frame_meta["contract_version"] == 1
    assert isinstance(frame_meta["contract_version"], int)
    assert frame_meta["zoom_max"] == 7
    assert frame_meta["url"] == f"/tiles/hrrr/{run}/tmp2m/000.pmtiles"
    assert manifest["available_frames"] == 1
    assert manifest["frames"][0]["frame_id"] == "000"
