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


def _reload_offline_tiles_with_publish_delta(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    publish_delta: int,
):
    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(tmp_path / "data_v2"))
    monkeypatch.setenv("STAGING_ROOT", str(tmp_path / "staging"))
    monkeypatch.setenv("PUBLISH_ROOT", str(tmp_path / "published"))
    monkeypatch.setenv("MANIFEST_ROOT", str(tmp_path / "manifests"))
    monkeypatch.setenv("OFFLINE_TILES_ENABLED", "true")
    monkeypatch.setenv("OFFLINE_TILES_INITIAL_GATE", "6")
    monkeypatch.setenv("OFFLINE_TILES_PUBLISH_DELTA", str(publish_delta))
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


@pytest.mark.parametrize("publish_delta", [6, 2])
def test_progressive_publish_gate_and_batching(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    publish_delta: int,
) -> None:
    offline_tiles = _reload_offline_tiles_with_publish_delta(
        monkeypatch,
        tmp_path,
        publish_delta=publish_delta,
    )
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

    next_publish_fh = 6 + publish_delta - 1
    for fh in range(6, next_publish_fh):
        _write_source(data_root, run=run, fh=fh)
        offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=fh)
        result = offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")
        assert result["published"] is False
        assert result["reason"] == "batch_threshold_not_met"
        assert result["published_frames"] == 6

    _write_source(data_root, run=run, fh=next_publish_fh)
    offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=next_publish_fh)
    second_batch = offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")
    assert second_batch["published"] is True
    assert second_batch["published_frames"] == 6 + publish_delta

    for fh in range(next_publish_fh + 1, 18):
        _write_source(data_root, run=run, fh=fh)
        offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=fh)
        offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")

    _write_source(data_root, run=run, fh=18)
    offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=18)
    completed = offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")
    assert completed["published"] is True
    assert completed["published_frames"] == 19
    assert completed["expected_frames"] == 19


def test_progressive_publish_with_delta_one_advances_one_frame_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    offline_tiles = _reload_offline_tiles_with_publish_delta(
        monkeypatch,
        tmp_path,
        publish_delta=1,
    )
    data_root = tmp_path / "data_v2"
    run = "20260207_01z"

    for fh in range(0, 6):
        _write_source(data_root, run=run, fh=fh)
        offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=fh)
    at_gate = offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")
    assert at_gate["published"] is True
    assert at_gate["published_frames"] == 6

    _write_source(data_root, run=run, fh=6)
    offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=6)
    after_fh6 = offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")
    assert after_fh6["published"] is True
    assert after_fh6["published_frames"] == 7

    _write_source(data_root, run=run, fh=7)
    offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run, var="tmp2m", fh=7)
    after_fh7 = offline_tiles.publish_from_staging(model="hrrr", run=run, var="tmp2m")
    assert after_fh7["published"] is True
    assert after_fh7["published_frames"] == 8
