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


def _touch(path: Path, content: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


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
    monkeypatch.setenv("OFFLINE_FRAME_IMAGE_SIZE_PX", "256")
    monkeypatch.setenv("OFFLINE_FRAME_IMAGE_WEBP_QUALITY", "75")
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
    _write_fake_cog(source_cog)
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
    assert (staging_root / "frames" / "000.pmtiles").read_bytes()[:7] == b"PMTiles"
    assert (staging_root / "frames" / "000.webp").exists()
    assert (staging_root / "meta" / "000.json").exists()
    assert (staging_root / "manifest.json").exists()
    assert frame_meta["contract_version"] == 1
    assert isinstance(frame_meta["contract_version"], int)
    assert frame_meta["zoom_max"] == 7
    assert frame_meta["url"] == f"/tiles/hrrr/{run}/tmp2m/000.pmtiles"
    assert frame_meta["frame_image_url"] == f"/frames/hrrr/{run}/tmp2m/000.webp"
    assert manifest["available_frames"] == 1
    assert manifest["frames"][0]["frame_id"] == "000"
    assert manifest["frames"][0]["frame_image_url"] == f"/frames/hrrr/{run}/tmp2m/000.webp"


def test_validate_staged_pmtiles_rejects_tiff_disguised_as_pmtiles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    offline_tiles = _reload_offline_tiles(monkeypatch, tmp_path)

    fake_pmtiles = tmp_path / "staging" / "hrrr" / "20260207_01z" / "tmp2m" / "frames" / "000.pmtiles"
    _touch(fake_pmtiles, b"II*\x00FAKECOGTIFF")
    validation_sidecar = fake_pmtiles.with_suffix(".tiles.json")
    validation_sidecar.write_text(
        json.dumps(
            {
                "tile_presence": {
                    "z0": {"present": True},
                    "z7": {"present": True},
                }
            }
        )
    )

    with pytest.raises(ValueError, match="produced GeoTIFF, not PMTiles"):
        offline_tiles.validate_staged_pmtiles(fake_pmtiles)
