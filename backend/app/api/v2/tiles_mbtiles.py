from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

router = APIRouter(prefix="/v2/tiles", tags=["v2-tiles"])

MBTILES_ENV = "TWF_V2_MBTILES_PATH"
MBTILES_DEFAULT = "/opt/twf_models/mbtiles/hrrr_latest.mbtiles"


@router.get("/hrrr/{z}/{x}/{y}.png")
async def get_hrrr_tile(z: int, x: int, y: int) -> Response:
    mbtiles_path = Path(os.getenv(MBTILES_ENV, MBTILES_DEFAULT))
    if not mbtiles_path.exists():
        raise HTTPException(status_code=500, detail=f"MBTiles not found: {mbtiles_path}")

    tms_y = (1 << z) - 1 - y

    try:
        conn = sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 1",
                (z, x, tms_y),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"MBTiles read error: {exc}") from exc

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="Tile not found")

    return Response(content=row[0], media_type="image/png")


# Quick local test:
# curl -sS http://127.0.0.1:PORT/v2/tiles/hrrr/5/4/10.png -o /tmp/tile.png
