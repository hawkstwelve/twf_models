from __future__ import annotations

import importlib
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app import config as config_module
from app.api import offline as offline_api_module
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


def _write_source(root: Path, *, model: str, run: str, fh: int) -> None:
    frame_id = f"{fh:03d}"
    source_cog = root / model / "pnw" / run / "tmp2m" / f"fh{frame_id}.cog.tif"
    _write_fake_cog(source_cog)
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
    monkeypatch.setenv("OFFLINE_FRAME_IMAGE_SIZE_PX", "256")
    monkeypatch.setenv("OFFLINE_FRAME_IMAGE_WEBP_QUALITY", "75")
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
