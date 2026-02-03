from __future__ import annotations

import logging
import os
import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

router = APIRouter(prefix="/tiles/v2", tags=["v2-tiles"])
logger = logging.getLogger(__name__)
SEGMENT_RE = re.compile(r"^[a-z0-9_-]+$")
MBTILES_ENV = "TWF_V2_MBTILES_PATH"


@router.get("/{model}/{run}/{var}/{fh}/{z}/{x}/{y}.png")
def get_tile(
    model: str,
    run: str,
    var: str,
    fh: str,
    z: int,
    x: int,
    y: int,
) -> Response:
    for label, value in ("model", model), ("run", run), ("var", var), ("fh", fh):
        if not SEGMENT_RE.match(value):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {label} segment: must match ^[a-z0-9_-]+$",
            )

    env_value = os.environ.get(MBTILES_ENV)
    if not env_value:
        raise HTTPException(
            status_code=500,
            detail=f"{MBTILES_ENV} not set or MBTiles not found: {env_value or ''}",
        )
    mbtiles_path = Path(env_value)
    if not mbtiles_path.exists():
        raise HTTPException(
            status_code=500,
            detail=f"{MBTILES_ENV} not set or MBTiles not found: {mbtiles_path}",
        )

    tms_y = (1 << z) - 1 - y

    try:
        with sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 1",
                (z, x, tms_y),
            ).fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"MBTiles read error: {exc}") from exc

    found = bool(row and row[0])
    logger.warning(
        "MBTiles lookup path=%s z=%s x=%s y=%s tms_y=%s found=%s",
        mbtiles_path,
        z,
        x,
        y,
        tms_y,
        found,
    )

    if not found:
        raise HTTPException(status_code=404, detail="Tile not found")

    tile_bytes = row[0]

    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    try:
        stat = mbtiles_path.stat()
    except OSError:
        stat = None
    if stat is not None:
        headers["ETag"] = f"\"{stat.st_mtime_ns}-{stat.st_size}\""

    return Response(
        content=tile_bytes,
        media_type="image/png",
        headers=headers,
    )
