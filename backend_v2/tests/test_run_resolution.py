from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.run_resolution import list_runs, resolve_run


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_resolve_latest_lexicographic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "data"
    _mkdir(root / "hrrr" / "pnw" / "20250203_18z")
    _mkdir(root / "hrrr" / "pnw" / "20250204_12z")

    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(root))

    runs = list_runs("hrrr", "pnw")
    assert runs == ["20250204_12z", "20250203_18z"]
    assert resolve_run("hrrr", "pnw", "latest") == "20250204_12z"


def test_resolve_latest_falls_back_to_scan_when_pointer_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "data"
    _mkdir(root / "hrrr" / "pnw" / "20250203_18z")
    _mkdir(root / "hrrr" / "pnw" / "20250204_12z")
    (root / "hrrr" / "pnw" / "LATEST.json").write_text(json.dumps({"run_id": "runB"}))

    monkeypatch.setenv("TWF_DATA_V2_ROOT", str(root))

    runs = list_runs("hrrr", "pnw")
    assert runs == ["20250204_12z", "20250203_18z"]
    assert resolve_run("hrrr", "pnw", "latest") == "20250204_12z"
