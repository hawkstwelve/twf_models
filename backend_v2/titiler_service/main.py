from __future__ import annotations

import logging
import re
from io import BytesIO
from pathlib import Path

import numpy as np
from fastapi import APIRouter, FastAPI, HTTPException, Response
from PIL import Image

from app.services.colormaps_v2 import encode_to_byte_and_alpha, get_lut
from app.services.run_resolution import get_data_root, resolve_run

try:
    from rio_tiler.io import COGReader  # type: ignore
except Exception:  # pragma: no cover - dependency availability is environment-specific
    COGReader = None


logger = logging.getLogger(__name__)

SEGMENT_RE = re.compile(r"^[a-z0-9_-]+$")
TILE_CACHE_SECONDS = 31_536_000

app = FastAPI(
    title="TWF TiTiler Service (V2)",
    version="0.1.0",
)

router = APIRouter(tags=["titiler"])


def _ensure_segment(label: str, value: str) -> None:
    if not SEGMENT_RE.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label} segment: must match ^[a-z0-9_-]+$",
        )


def _resolve_cog_path(model: str, region: str, run: str, var: str, fh: int) -> tuple[Path, str]:
    resolved_run = resolve_run(model, region, run)
    cog_path = Path(get_data_root()) / model / region / resolved_run / var / f"fh{fh:03d}.cog.tif"
    if not cog_path.exists():
        raise HTTPException(status_code=404, detail="Tile source not found")
    return cog_path, resolved_run


def _image_data_to_rgba(image_data, var_key: str) -> np.ndarray:
    data = np.asarray(image_data.data)
    if data.ndim != 3:
        raise RuntimeError(f"Unexpected tile data shape: {data.shape}")

    count = int(data.shape[0])
    mask = getattr(image_data, "mask", None)
    mask_array = np.asarray(mask) if mask is not None else None

    if count == 2:
        band1 = data[0].astype(np.uint8)
        band2 = data[1].astype(np.uint8)
        lut = get_lut(var_key)
        rgba = lut[band1]
        alpha = np.where(band1 == 255, 0, band2).astype(np.uint8)
        if mask_array is not None:
            alpha = np.where(mask_array > 0, alpha, 0).astype(np.uint8)
        rgba[..., 3] = alpha
        return rgba

    if count == 4:
        rgba = np.moveaxis(data[:4], 0, -1).astype(np.uint8)
        if mask_array is not None:
            rgba[..., 3] = np.where(mask_array > 0, rgba[..., 3], 0).astype(np.uint8)
        return rgba

    if count == 1:
        band = data[0]
        lut = get_lut(var_key)
        if band.dtype == np.uint8:
            byte_band = band.astype(np.uint8)
            alpha = np.where(byte_band == 255, 0, 255).astype(np.uint8)
            if mask_array is not None:
                alpha = np.where(mask_array > 0, alpha, 0).astype(np.uint8)
        else:
            byte_band, alpha, _ = encode_to_byte_and_alpha(
                band.astype(np.float32),
                var_key=var_key,
            )
        rgba = lut[byte_band]
        rgba[..., 3] = alpha
        return rgba

    raise RuntimeError(f"Unsupported band count for tile rendering: {count}")


def _render_tile_png(cog_path: Path, *, var_key: str, z: int, x: int, y: int) -> bytes:
    if COGReader is None:
        raise RuntimeError("rio-tiler is not installed in this environment")

    with COGReader(str(cog_path)) as cog:
        image_data = cog.tile(x, y, z, tilesize=256)
    rgba = _image_data_to_rgba(image_data, var_key)
    image = Image.fromarray(rgba, mode="RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _tile_response(
    *,
    model: str,
    region: str,
    run: str,
    var: str,
    fh: int,
    z: int,
    x: int,
    y: int,
) -> Response:
    for label, value in (("model", model), ("region", region), ("run", run), ("var", var)):
        _ensure_segment(label, value)

    cog_path, resolved_run = _resolve_cog_path(model, region, run, var, fh)

    try:
        tile_bytes = _render_tile_png(cog_path, var_key=var, z=z, x=x, y=y)
    except RuntimeError as exc:
        # Missing rio-tiler dependency should be explicit for ops triage.
        if "rio-tiler is not installed" in str(exc):
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail=f"Tile render error: {exc}") from exc
    except Exception as exc:
        logger.exception(
            "TiTiler render failed model=%s region=%s run=%s var=%s fh=%s z=%s x=%s y=%s path=%s",
            model,
            region,
            resolved_run,
            var,
            fh,
            z,
            x,
            y,
            cog_path,
        )
        raise HTTPException(status_code=500, detail=f"Tile render error: {exc}") from exc

    headers = {
        "Cache-Control": f"public, max-age={TILE_CACHE_SECONDS}, immutable",
    }
    try:
        stat = cog_path.stat()
    except OSError:
        stat = None
    if stat is not None:
        headers["ETag"] = f"\"{stat.st_mtime_ns}-{stat.st_size}-{var}-{fh}-{z}-{x}-{y}-{resolved_run}\""

    return Response(content=tile_bytes, media_type="image/png", headers=headers)


@router.get("/tiles/{model}/{region}/{run}/{var}/{fh}/{z}/{x}/{y}.png")
def tile_canonical(
    model: str,
    region: str,
    run: str,
    var: str,
    fh: int,
    z: int,
    x: int,
    y: int,
) -> Response:
    return _tile_response(model=model, region=region, run=run, var=var, fh=fh, z=z, x=x, y=y)


@router.get("/tiles-titiler/{model}/{region}/{run}/{var}/{fh}/{z}/{x}/{y}.png")
def tile_parallel_path(
    model: str,
    region: str,
    run: str,
    var: str,
    fh: int,
    z: int,
    x: int,
    y: int,
) -> Response:
    # Temporary shadow-validation route namespace.
    return _tile_response(model=model, region=region, run=run, var=var, fh=fh, z=z, x=x, y=y)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(router)

