from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

import os
print("LOADED tiles_mbtiles:", __file__)
print("TWF_V2_MBTILES_PATH in process:", os.getenv("TWF_V2_MBTILES_PATH"))

from ..config import MBTILES_ROOT
from ..utils.pathing import safe_join

router = APIRouter(prefix="/tiles/v2", tags=["v2-tiles"])
logger = logging.getLogger(__name__)

MBTILES_ENV = "TWF_V2_MBTILES_PATH"


@router.get("/{model}/{run}/{var}/{fh}/{z}/{x}/{y}.png")
def get_hrrr_tile(
    model: str,
    run: str,
    var: str,
    fh: str,
    z: int,
    x: int,
    y: int,
) -> Response:
    env_path = os.getenv(MBTILES_ENV)
    if env_path:
        mbtiles_path = Path(env_path)
        env_override = True
    else:
        env_override = False
        try:
            mbtiles_path = safe_join(MBTILES_ROOT, model, run, f"{var}.mbtiles")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    tms_y = (1 << z) - 1 - y
    exists = mbtiles_path.exists()
    logger.warning("MBTiles resolved path=%s exists=%s", mbtiles_path.resolve(), exists)

    if not exists:
        if env_override:
            raise HTTPException(status_code=500, detail=f"MBTiles not found: {mbtiles_path}")
        raise HTTPException(status_code=404, detail="Tile not found")

    try:
        with sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 1",
                (z, x, tms_y),
            ).fetchone()
            if not row or not row[0]:
                row = conn.execute(
                    "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 1",
                    (z, x, y),
                ).fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"MBTiles read error: {exc}") from exc

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="Tile not found")

    return Response(content=row[0], media_type="image/png")
