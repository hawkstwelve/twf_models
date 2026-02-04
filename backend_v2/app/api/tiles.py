from __future__ import annotations

import logging
import re
from io import BytesIO
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

from fastapi import APIRouter, HTTPException, Response

from app.services.colormaps_v2 import encode_to_byte_and_alpha, get_lut
from app.services.run_resolution import get_data_root, resolve_run

router = APIRouter(prefix="/tiles/v2", tags=["v2-tiles"])
logger = logging.getLogger(__name__)
SEGMENT_RE = re.compile(r"^[a-z0-9_-]+$")
ORIGIN_SHIFT = 20037508.342789244
TILE_SIZE = 256


def _tile_bounds_3857(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    res = (2 * ORIGIN_SHIFT) / (TILE_SIZE * (2**z))
    minx = x * TILE_SIZE * res - ORIGIN_SHIFT
    maxx = (x + 1) * TILE_SIZE * res - ORIGIN_SHIFT
    maxy = ORIGIN_SHIFT - y * TILE_SIZE * res
    miny = ORIGIN_SHIFT - (y + 1) * TILE_SIZE * res
    return minx, miny, maxx, maxy


@router.get("/{model}/{region}/{run}/{var}/{fh}/{z}/{x}/{y}.png")
def get_tile(
    model: str,
    region: str,
    run: str,
    var: str,
    fh: int,
    z: int,
    x: int,
    y: int,
) -> Response:
    for label, value in ("model", model), ("region", region), ("run", run), ("var", var):
        if not SEGMENT_RE.match(value):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {label} segment: must match ^[a-z0-9_-]+$",
            )

    resolved_run = resolve_run(model, region, run)
    root = get_data_root()
    cog_path = Path(root) / model / region / resolved_run / var / f"fh{fh:03d}.cog.tif"
    if not cog_path.exists():
        raise HTTPException(status_code=404, detail="Tile source not found")

    bounds = _tile_bounds_3857(x, y, z)
    try:
        with rasterio.open(cog_path) as src:
            window = from_bounds(*bounds, transform=src.transform)
            count = src.count
            dtype = np.dtype(src.dtypes[0])

            if count == 2:
                band1 = src.read(
                    1,
                    window=window,
                    out_shape=(TILE_SIZE, TILE_SIZE),
                    resampling=Resampling.nearest,
                    boundless=True,
                    fill_value=0,
                ).astype(np.uint8)
                band2 = src.read(
                    2,
                    window=window,
                    out_shape=(TILE_SIZE, TILE_SIZE),
                    resampling=Resampling.nearest,
                    boundless=True,
                    fill_value=0,
                ).astype(np.uint8)
                rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
                rgba[..., 0] = band1
                rgba[..., 1] = band1
                rgba[..., 2] = band1
                rgba[..., 3] = band2
            elif count == 4:
                bands = src.read(
                    [1, 2, 3, 4],
                    window=window,
                    out_shape=(4, TILE_SIZE, TILE_SIZE),
                    resampling=Resampling.nearest,
                    boundless=True,
                    fill_value=0,
                )
                rgba = np.moveaxis(bands, 0, -1).astype(np.uint8)
            elif count == 1:
                if dtype == np.uint8:
                    band = src.read(
                        1,
                        window=window,
                        out_shape=(TILE_SIZE, TILE_SIZE),
                        resampling=Resampling.nearest,
                        boundless=True,
                        fill_value=0,
                        masked=True,
                    )
                    data = np.asarray(band.filled(0), dtype=np.uint8)
                    alpha = np.where(np.ma.getmaskarray(band), 0, 255).astype(np.uint8)
                    rgba = np.stack([data, data, data, alpha], axis=-1)
                else:
                    band = src.read(
                        1,
                        window=window,
                        out_shape=(TILE_SIZE, TILE_SIZE),
                        resampling=Resampling.nearest,
                        boundless=True,
                        fill_value=np.nan,
                    )
                    byte_band, alpha_band, _ = encode_to_byte_and_alpha(band, var_key=var)
                    lut = get_lut(var)
                    rgba = lut[byte_band]
                    rgba[..., 3] = alpha_band
            else:
                raise RuntimeError(f"Unsupported band count: {count}")
    except Exception as exc:
        logger.exception(
            "Tile render failed model=%s region=%s run=%s var=%s fh=%s z=%s x=%s y=%s path=%s",
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
        return Response(
            content=f"Tile render error: {exc}",
            media_type="text/plain",
            status_code=500,
        )

    image = Image.fromarray(rgba.astype(np.uint8), mode="RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    tile_bytes = buffer.getvalue()

    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    try:
        stat = cog_path.stat()
    except OSError:
        stat = None
    if stat is not None:
        headers["ETag"] = f"\"{stat.st_mtime_ns}-{stat.st_size}-{var}-{fh}-{z}-{x}-{y}-{resolved_run}\""

    return Response(content=tile_bytes, media_type="image/png", headers=headers)
