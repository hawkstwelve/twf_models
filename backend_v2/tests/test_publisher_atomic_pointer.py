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


def _write_source(root: Path, *, run: str, fh: int) -> None:
    frame_id = f"{fh:03d}"
    source_cog = root / "hrrr" / "pnw" / run / "tmp2m" / f"fh{frame_id}.cog.tif"
    _touch(source_cog, b"II*\x00fake-cog")
    payload = {
        "model": "hrrr",
        "region": "pnw",
        "run": run,
        "var": "tmp2m",
        "fh": fh,
        "meta": {"units": "F", "output_mode": "byte_alpha"},
    }
    (source_cog.parent / f"fh{frame_id}.json").write_text(json.dumps(payload))


def test_publisher_updates_latest_pointer_atomically_and_supports_rollback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    offline_tiles = _reload_offline_tiles(monkeypatch, tmp_path)
    data_root = tmp_path / "data_v2"

    run1 = "20260207_01z"
    for fh in range(0, 6):
        _write_source(data_root, run=run1, fh=fh)
        offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run1, var="tmp2m", fh=fh)
        offline_tiles.publish_from_staging(model="hrrr", run=run1, var="tmp2m")

    published_manifest = tmp_path / "published" / "hrrr" / run1 / "tmp2m" / "manifest.json"
    assert published_manifest.exists()
    assert published_manifest.is_symlink()
    latest_path = tmp_path / "manifests" / "hrrr" / "latest.json"
    assert latest_path.exists()
    snapshot_run1 = latest_path.read_text()

    run2 = "20260207_02z"
    for fh in range(0, 6):
        _write_source(data_root, run=run2, fh=fh)
        offline_tiles.stage_single_frame(model="hrrr", region="pnw", run=run2, var="tmp2m", fh=fh)
        offline_tiles.publish_from_staging(model="hrrr", run=run2, var="tmp2m")

    latest_after_run2 = json.loads(latest_path.read_text())
    assert latest_after_run2["run"] == run2

    rollback_tmp = latest_path.with_suffix(".json.rollback.tmp")
    rollback_tmp.write_text(snapshot_run1)
    rollback_tmp.replace(latest_path)

    rolled_back = json.loads(latest_path.read_text())
    assert rolled_back["run"] == run1
