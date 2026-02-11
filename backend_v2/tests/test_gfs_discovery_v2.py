from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from app import config as config_module
from app.services import discovery_v2
from app.services import offline_tiles as offline_tiles_module


def _touch(path: Path, content: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_source_frame(root: Path, *, model: str, region: str, run: str, var: str, fh: int) -> None:
    frame_id = f"{fh:03d}"
    _touch(root / model / region / run / var / f"fh{frame_id}.cog.tif", b"II*\x00cog")
    sidecar = {
        "model": model,
        "region": region,
        "run": run,
        "var": var,
        "fh": fh,
        "meta": {"units": "F", "output_mode": "byte_alpha"},
    }
    (root / model / region / run / var / f"fh{frame_id}.json").write_text(json.dumps(sidecar))


def _reload_modules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(tmp_path / "data_v2"))
    monkeypatch.setenv("STAGING_ROOT", str(tmp_path / "staging"))
    monkeypatch.setenv("PUBLISH_ROOT", str(tmp_path / "published"))
    monkeypatch.setenv("MANIFEST_ROOT", str(tmp_path / "manifests"))
    monkeypatch.setenv("OFFLINE_TILES_ENABLED", "true")
    importlib.reload(config_module)
    offline_tiles = importlib.reload(offline_tiles_module)
    discovery = importlib.reload(discovery_v2)
    discovery._CACHE.clear()
    return offline_tiles, discovery


def test_gfs_discovery_reads_published_manifests_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    offline_tiles, discovery = _reload_modules(monkeypatch, tmp_path)
    data_root = tmp_path / "data_v2"
    run = "20260206_06z"
    for fh in range(0, 36, 6):
        _write_source_frame(data_root, model="gfs", region="pnw", run=run, var="tmp2m", fh=fh)
        offline_tiles.stage_single_frame(model="gfs", region="pnw", run=run, var="tmp2m", fh=fh)
        offline_tiles.publish_from_staging(model="gfs", run=run, var="tmp2m")

    models = discovery.list_models()
    assert any(row["id"] == "gfs" for row in models)
    assert discovery.list_runs("gfs", "pnw") == [run]
    assert discovery.list_vars("gfs", "pnw", "latest") == ["tmp2m"]

    frames = discovery.list_frames("gfs", "pnw", "latest", "tmp2m")
    assert [row["fh"] for row in frames] == [0, 6, 12, 18, 24, 30]
    assert frames[0]["url"] == "/tiles/gfs/20260206_06z/tmp2m/000.pmtiles"


def test_gfs_discovery_does_not_leak_staging_only_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    offline_tiles, discovery = _reload_modules(monkeypatch, tmp_path)
    data_root = tmp_path / "data_v2"

    published_run = "20260206_06z"
    for fh in range(0, 36, 6):
        _write_source_frame(data_root, model="gfs", region="pnw", run=published_run, var="tmp2m", fh=fh)
        offline_tiles.stage_single_frame(model="gfs", region="pnw", run=published_run, var="tmp2m", fh=fh)
        offline_tiles.publish_from_staging(model="gfs", run=published_run, var="tmp2m")

    staging_only_run = "20260206_12z"
    for fh in (0, 6, 12):
        _write_source_frame(data_root, model="gfs", region="pnw", run=staging_only_run, var="tmp2m", fh=fh)
        offline_tiles.stage_single_frame(model="gfs", region="pnw", run=staging_only_run, var="tmp2m", fh=fh)
    # Never published: < gate

    runs = discovery.list_runs("gfs", "pnw")
    assert runs == [published_run]
