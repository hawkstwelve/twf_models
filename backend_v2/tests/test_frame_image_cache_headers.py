from __future__ import annotations

import importlib
from pathlib import Path

from app import config as config_module
import app.main as main_module


def _reload_app_with_publish_root(monkeypatch, publish_root: Path):
    monkeypatch.setenv("PUBLISH_ROOT", str(publish_root))
    importlib.reload(config_module)
    return importlib.reload(main_module)


def test_frame_image_cache_headers_for_versioned_and_legacy_urls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run = "20260207_01z"
    frame_path = tmp_path / "hrrr" / run / "tmp2m" / "frames" / "000.webp"
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    frame_path.write_bytes(b"RIFF\x1a\x00\x00\x00WEBPVP8 ")

    main = _reload_app_with_publish_root(monkeypatch, tmp_path)

    legacy = main.get_frame_image(model="hrrr", run=run, var="tmp2m", frame_id="000", v=None)
    assert legacy.status_code == 200
    assert legacy.headers.get("cache-control") == "public, max-age=31536000, immutable"

    versioned = main.get_frame_image(model="hrrr", run=run, var="tmp2m", frame_id="000", v="abcdef1234567890")
    assert versioned.status_code == 200
    assert versioned.headers.get("cache-control") == "public, max-age=31536000, immutable"
