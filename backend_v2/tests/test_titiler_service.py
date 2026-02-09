from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

from titiler_service import main as titiler_main


class _FakeImageData:
    def __init__(self, data: np.ndarray, mask: np.ndarray | None = None):
        self.data = data
        self.mask = mask


class _FakeCOGReader:
    def __init__(self, path: str):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def tile(self, x: int, y: int, z: int, tilesize: int = 256) -> _FakeImageData:
        del x, y, z, tilesize
        band1 = np.array([[0, 255], [10, 20]], dtype=np.uint8)
        band2 = np.array([[255, 255], [128, 64]], dtype=np.uint8)
        data = np.stack([band1, band2], axis=0)
        mask = np.array([[255, 255], [255, 255]], dtype=np.uint8)
        return _FakeImageData(data=data, mask=mask)


def _touch_cog(tmp_path: Path) -> Path:
    cog_path = tmp_path / "hrrr" / "pnw" / "20260207_19z" / "tmp2m" / "fh000.cog.tif"
    cog_path.parent.mkdir(parents=True, exist_ok=True)
    cog_path.write_bytes(b"fake-cog")
    return cog_path


def test_titiler_tile_route_renders_png(monkeypatch, tmp_path: Path) -> None:
    _touch_cog(tmp_path)
    monkeypatch.setattr(titiler_main, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(titiler_main, "resolve_run", lambda model, region, run: "20260207_19z")
    monkeypatch.setattr(titiler_main, "COGReader", _FakeCOGReader)

    response = titiler_main.tile_canonical(
        model="hrrr",
        region="pnw",
        run="latest",
        var="tmp2m",
        fh=0,
        z=6,
        x=10,
        y=22,
    )
    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert "immutable" in response.headers["cache-control"]
    assert "etag" in response.headers

    img = Image.open(io.BytesIO(response.body))
    arr = np.asarray(img)
    assert arr.shape == (2, 2, 4)
    # Byte value 255 should force transparency regardless of band2 alpha.
    assert int(arr[0, 1, 3]) == 0


def test_titiler_legacy_v2_path_renders_png(monkeypatch, tmp_path: Path) -> None:
    _touch_cog(tmp_path)
    monkeypatch.setattr(titiler_main, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(titiler_main, "resolve_run", lambda model, region, run: "20260207_19z")
    monkeypatch.setattr(titiler_main, "COGReader", _FakeCOGReader)

    response = titiler_main.tile_legacy_v2_compat(
        model="hrrr",
        region="pnw",
        run="latest",
        var="tmp2m",
        fh=0,
        z=6,
        x=10,
        y=22,
    )
    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert "immutable" in response.headers["cache-control"]


def test_titiler_invalid_segment_rejected(monkeypatch, tmp_path: Path) -> None:
    _touch_cog(tmp_path)
    monkeypatch.setattr(titiler_main, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(titiler_main, "resolve_run", lambda model, region, run: "20260207_19z")
    monkeypatch.setattr(titiler_main, "COGReader", _FakeCOGReader)

    with pytest.raises(HTTPException) as exc:
        titiler_main.tile_canonical(
            model="HRRR!",
            region="pnw",
            run="latest",
            var="tmp2m",
            fh=0,
            z=6,
            x=10,
            y=22,
        )
    assert exc.value.status_code == 400


def test_titiler_missing_dependency_returns_503(monkeypatch, tmp_path: Path) -> None:
    _touch_cog(tmp_path)
    monkeypatch.setattr(titiler_main, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(titiler_main, "resolve_run", lambda model, region, run: "20260207_19z")
    monkeypatch.setattr(titiler_main, "COGReader", None)

    with pytest.raises(HTTPException) as exc:
        titiler_main.tile_canonical(
            model="hrrr",
            region="pnw",
            run="latest",
            var="tmp2m",
            fh=0,
            z=6,
            x=10,
            y=22,
        )
    assert exc.value.status_code == 503


def test_titiler_missing_source_returns_204(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(titiler_main, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(titiler_main, "resolve_run", lambda model, region, run: "20260207_19z")

    response = titiler_main.tile_canonical(
        model="hrrr",
        region="pnw",
        run="latest",
        var="tmp2m",
        fh=0,
        z=6,
        x=10,
        y=22,
    )

    assert response.status_code == 204
    assert response.headers["cache-control"].startswith("public, max-age=15")


def test_titiler_missing_asset_during_render_returns_204(monkeypatch, tmp_path: Path) -> None:
    _touch_cog(tmp_path)
    monkeypatch.setattr(titiler_main, "get_data_root", lambda: tmp_path)
    monkeypatch.setattr(titiler_main, "resolve_run", lambda model, region, run: "20260207_19z")
    monkeypatch.setattr(
        titiler_main,
        "_render_tile_png",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing asset")),
    )

    response = titiler_main.tile_canonical(
        model="hrrr",
        region="pnw",
        run="latest",
        var="tmp2m",
        fh=0,
        z=6,
        x=10,
        y=22,
    )

    assert response.status_code == 204
