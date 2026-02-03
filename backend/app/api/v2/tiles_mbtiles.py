from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

router = APIRouter(prefix="/v2/tiles", tags=["v2-tiles"])
logger = logging.getLogger(__name__)

MBTILES_ENV = "TWF_V2_MBTILES_PATH"
MBTILES_DEFAULT = "/opt/twf_models/mbtiles/hrrr_latest.mbtiles"


@router.get("/hrrr/{z}/{x}/{y}.png")
async def get_hrrr_tile(z: int, x: int, y: int) -> Response:
    mbtiles_path = Path(os.getenv(MBTILES_ENV, MBTILES_DEFAULT))
    if not mbtiles_path.exists():
        raise HTTPException(status_code=500, detail=f"MBTiles not found: {mbtiles_path}")

    tms_y = (1 << z) - 1 - y
    logger.debug("MBTiles path: %s", mbtiles_path)
    logger.debug("Request XYZ: z=%s x=%s y=%s", z, x, y)
    logger.debug("Computed TMS y: %s", tms_y)
    params = (z, x, tms_y)
    logger.debug("SQL params: %s", params)

    try:
        conn = sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 1",
                params,
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"MBTiles read error: {exc}") from exc

    logger.debug("Tile row found: %s", bool(row))

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="Tile not found")

    return Response(content=row[0], media_type="image/png")


# Quick local test:
# curl -sS http://127.0.0.1:PORT/v2/tiles/hrrr/5/4/10.png -o /tmp/tile.png
