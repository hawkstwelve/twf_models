from __future__ import annotations

import os
import time
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

    monkeypatch.setenv("DATA_V2_ROOT", str(root))

    runs = list_runs("hrrr", "pnw")
    assert runs == ["20250204_12z", "20250203_18z"]
    assert resolve_run("hrrr", "pnw", "latest") == "20250204_12z"


def test_resolve_latest_mtime_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "data"
    run_a = _mkdir(root / "hrrr" / "pnw" / "runA")
    run_b = _mkdir(root / "hrrr" / "pnw" / "runB")

    now = time.time()
    os.utime(run_a, (now - 100, now - 100))
    os.utime(run_b, (now - 10, now - 10))

    monkeypatch.setenv("DATA_V2_ROOT", str(root))

    runs = list_runs("hrrr", "pnw")
    assert runs[0] == "runB"
    assert resolve_run("hrrr", "pnw", "latest") == "runB"
