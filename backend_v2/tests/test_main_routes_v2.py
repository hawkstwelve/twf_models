from __future__ import annotations

from app.main import app


def test_main_app_is_metadata_only() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/v2/models" in paths
    assert "/api/models" in paths
    assert "/tiles/{model}/{run}/{var}/{frame_id}.pmtiles" in paths
    assert "/manifests/{model}/latest.json" in paths
