from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import discovery_v2


def _touch(path: Path, content: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_gfs_discovery_lists_runs_vars_and_frames(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "data"
    newer = root / "gfs" / "pnw" / "20260206_06z"
    older = root / "gfs" / "pnw" / "20260206_00z"

    _touch(newer / "tmp2m" / "fh000.cog.tif", b"II*\x00valid")
    _touch(newer / "tmp2m" / "fh006.cog.tif", b"II*\x00valid")
    _touch(newer / "wspd10m" / "fh000.cog.tif", b"II*\x00valid")
    _touch(newer / "precip_ptype" / "fh006.cog.tif", b"II*\x00valid")
    _touch(older / "tmp2m" / "fh000.cog.tif", b"II*\x00valid")
    (root / "gfs" / "pnw" / "LATEST.json").write_text(
        json.dumps({"run_id": "20260206_06z"})
    )

    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(root))
    discovery_v2._CACHE.clear()

    runs = discovery_v2.list_runs("gfs", "pnw")
    assert runs == ["20260206_06z", "20260206_00z"]

    vars_latest = discovery_v2.list_vars("gfs", "pnw", "latest")
    assert vars_latest == ["precip_ptype", "tmp2m", "wspd10m"]

    frames = discovery_v2.list_frames("gfs", "pnw", "latest", "tmp2m")
    assert [row["fh"] for row in frames] == [0, 6]
    assert all(row["run"] == "20260206_06z" for row in frames)
    assert frames[0]["tile_url_template"] == "/tiles/v2/gfs/pnw/20260206_06z/tmp2m/0/{z}/{x}/{y}.png"
    assert frames[1]["tile_url_template"] == "/tiles/v2/gfs/pnw/20260206_06z/tmp2m/6/{z}/{x}/{y}.png"


def test_gfs_discovery_ignores_invalid_cog_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "data"
    run_dir = root / "gfs" / "pnw" / "20260206_06z" / "tmp2m"
    _touch(run_dir / "fh000.cog.tif", b"not-a-tiff")
    _touch(run_dir / "fh006.cog.tif", b"II*\x00valid")
    (root / "gfs" / "pnw" / "LATEST.json").write_text(json.dumps({"run_id": "20260206_06z"}))

    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(root))
    discovery_v2._CACHE.clear()

    frames = discovery_v2.list_frames("gfs", "pnw", "latest", "tmp2m")
    assert [row["fh"] for row in frames] == [6]


def test_discovery_filters_gfs_radar_ptype_but_keeps_hrrr(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "data"
    run_id = "20260206_06z"

    _touch(root / "gfs" / "pnw" / run_id / "tmp2m" / "fh000.cog.tif", b"II*\x00valid")
    _touch(root / "gfs" / "pnw" / run_id / "radar_ptype" / "fh000.cog.tif", b"II*\x00valid")
    _touch(root / "hrrr" / "pnw" / run_id / "tmp2m" / "fh000.cog.tif", b"II*\x00valid")
    _touch(root / "hrrr" / "pnw" / run_id / "radar_ptype" / "fh000.cog.tif", b"II*\x00valid")
    (root / "gfs" / "pnw" / "LATEST.json").write_text(json.dumps({"run_id": run_id}))
    (root / "hrrr" / "pnw" / "LATEST.json").write_text(json.dumps({"run_id": run_id}))

    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(root))
    discovery_v2._CACHE.clear()

    gfs_vars = discovery_v2.list_vars("gfs", "pnw", run_id)
    assert "tmp2m" in gfs_vars
    assert "radar_ptype" not in gfs_vars

    hrrr_vars = discovery_v2.list_vars("hrrr", "pnw", run_id)
    assert "radar_ptype" in hrrr_vars

    gfs_radar_frames = discovery_v2.list_frames("gfs", "pnw", run_id, "radar_ptype")
    assert gfs_radar_frames == []

    hrrr_radar_frames = discovery_v2.list_frames("hrrr", "pnw", run_id, "radar_ptype")
    assert [row["fh"] for row in hrrr_radar_frames] == [0]


def test_discovery_includes_gfs_precip_ptype_but_excludes_hrrr_precip_ptype(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    run_id = "20260206_06z"

    _touch(root / "gfs" / "pnw" / run_id / "precip_ptype" / "fh006.cog.tif", b"II*\x00valid")
    _touch(root / "hrrr" / "pnw" / run_id / "precip_ptype" / "fh006.cog.tif", b"II*\x00valid")
    (root / "gfs" / "pnw" / "LATEST.json").write_text(json.dumps({"run_id": run_id}))
    (root / "hrrr" / "pnw" / "LATEST.json").write_text(json.dumps({"run_id": run_id}))

    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(root))
    discovery_v2._CACHE.clear()

    gfs_vars = discovery_v2.list_vars("gfs", "pnw", run_id)
    assert "precip_ptype" in gfs_vars

    hrrr_vars = discovery_v2.list_vars("hrrr", "pnw", run_id)
    assert "precip_ptype" not in hrrr_vars


def test_discovery_gfs_precip_ptype_frames_require_fh6_and_6_hour_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    run_id = "20260206_06z"
    var_root = root / "gfs" / "pnw" / run_id / "precip_ptype"

    _touch(var_root / "fh000.cog.tif", b"II*\x00valid")
    _touch(var_root / "fh003.cog.tif", b"II*\x00valid")
    _touch(var_root / "fh006.cog.tif", b"II*\x00valid")
    _touch(var_root / "fh009.cog.tif", b"II*\x00valid")
    _touch(var_root / "fh012.cog.tif", b"II*\x00valid")
    (root / "gfs" / "pnw" / "LATEST.json").write_text(json.dumps({"run_id": run_id}))

    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(root))
    discovery_v2._CACHE.clear()

    frames = discovery_v2.list_frames("gfs", "pnw", run_id, "precip_ptype")
    assert [row["fh"] for row in frames] == [6, 12]
