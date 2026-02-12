from __future__ import annotations

import importlib
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app import config as config_module
from app.services import offline_tiles as offline_tiles_module


def _write_fake_cog(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width = 64
    height = 64
    transform = from_origin(-13_000_000.0, 6_000_000.0, 50_000.0, 50_000.0)
    band1 = np.full((height, width), 10, dtype=np.uint8)
    band2 = np.full((height, width), 255, dtype=np.uint8)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=2,
        dtype="uint8",
        crs="EPSG:3857",
        transform=transform,
        tiled=True,
        blockxsize=32,
        blockysize=32,
        compress="deflate",
    ) as dataset:
        dataset.write(band1, 1)
        dataset.write(band2, 2)


def _reload_offline_tiles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(tmp_path / "data_v2"))
    monkeypatch.setenv("STAGING_ROOT", str(tmp_path / "staging"))
    monkeypatch.setenv("PUBLISH_ROOT", str(tmp_path / "published"))
    monkeypatch.setenv("MANIFEST_ROOT", str(tmp_path / "manifests"))
    monkeypatch.setenv("OFFLINE_TILES_ENABLED", "true")
    importlib.reload(config_module)
    return importlib.reload(offline_tiles_module)


def _write_source(root: Path, *, run: str, fh: int) -> None:
    frame_id = f"{fh:03d}"
    source_cog = root / "hrrr" / "pnw" / run / "tmp2m" / f"fh{frame_id}.cog.tif"
    _write_fake_cog(source_cog)
    payload = {
        "model": "hrrr",
        "region": "pnw",
        "run": run,
        "var": "tmp2m",
        "fh": fh,
        "meta": {"units": "F", "output_mode": "byte_alpha"},
    }
    (source_cog.parent / f"fh{frame_id}.json").write_text(json.dumps(payload))


def test_progressive_publish_gate_and_batching(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    offline_tiles = _reload_offline_tiles(monkeypatch, tmp_path)
    data_root = tmp_path / "data_v2"
    run = "20260207_01z"  # HRRR non-synoptic cycle => expected_frames=19

    for fh in range(0, 5):
        _write_source(data_root, run=run, fh=fh)
        offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=fh)
        result = offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")
        assert result["published"] is False
        assert result["reason"] == "gate_not_met"

    _write_source(data_root, run=run, fh=5)
    offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=5)
    at_gate = offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")
    assert at_gate["published"] is True
    assert at_gate["published_frames"] == 6

    for fh in range(6, 11):
        _write_source(data_root, run=run, fh=fh)
        offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=fh)
        result = offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")
        assert result["published"] is False
        assert result["reason"] == "batch_threshold_not_met"
        assert result["published_frames"] == 6

    _write_source(data_root, run=run, fh=11)
    offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=11)
    second_batch = offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")
    assert second_batch["published"] is True
    assert second_batch["published_frames"] == 12

    for fh in range(12, 18):
        _write_source(data_root, run=run, fh=fh)
        offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=fh)
        offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")

    _write_source(data_root, run=run, fh=18)
    offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=18)
    completed = offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")
    assert completed["published"] is True
    assert completed["published_frames"] == 19
    assert completed["expected_frames"] == 19
