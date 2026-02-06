from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import run_resolution


def _touch(path: Path, content: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_gfs_resolve_latest_uses_latest_pointer_when_run_has_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "data"
    run_id = "20260206_06z"
    _touch(root / "gfs" / "pnw" / run_id / "tmp2m" / "fh000.cog.tif", b"COG")
    (root / "gfs" / "pnw" / "LATEST.json").write_text(json.dumps({"run_id": run_id}))

    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(root))
    assert run_resolution.resolve_run("gfs", "pnw", "latest") == run_id


def test_gfs_resolve_latest_falls_back_when_pointer_run_missing_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "data"
    bad_pointer_run = "20260206_06z"
    good_run = "20260206_00z"
    _touch(root / "gfs" / "pnw" / good_run / "tmp2m" / "fh000.cog.tif", b"COG")
    (root / "gfs" / "pnw" / "LATEST.json").write_text(json.dumps({"run_id": bad_pointer_run}))

    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(root))
    assert run_resolution.resolve_run("gfs", "pnw", "latest") == good_run
