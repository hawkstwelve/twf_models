from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from ..config import MBTILES_ROOT
from ..utils.pathing import safe_join

router = APIRouter(prefix="/tiles/v2", tags=["v2-tiles"])
logger = logging.getLogger(__name__)


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
    try:
        mbtiles_path = safe_join(MBTILES_ROOT, model, run, f"{var}.mbtiles")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    tms_y = (1 << z) - 1 - y
    stat = None
    if mbtiles_path.exists():
        try:
            stat = mbtiles_path.stat()
        except OSError:
            stat = None

    logger.warning(
        "MBTiles resolved path=%s exists=%s size=%s mtime=%s z=%s x=%s y=%s tms_y=%s",
        mbtiles_path.resolve(),
        mbtiles_path.exists(),
        stat.st_size if stat else None,
        stat.st_mtime if stat else None,
        z,
        x,
        y,
        tms_y,
    )

    if not mbtiles_path.exists():
        raise HTTPException(status_code=404, detail="Tile not found")

    counts = {
        "total": None,
        "zx": None,
        "zxtms": None,
        "zxy": None,
    }

    try:
        with sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True) as conn:
            counts["total"] = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
            counts["zx"] = conn.execute(
                "SELECT COUNT(*) FROM tiles WHERE zoom_level=? AND tile_column=?",
                (z, x),
            ).fetchone()[0]
            counts["zxtms"] = conn.execute(
                "SELECT COUNT(*) FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, x, tms_y),
            ).fetchone()[0]
            counts["zxy"] = conn.execute(
                "SELECT COUNT(*) FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, x, y),
            ).fetchone()[0]

            row = conn.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 1",
                (z, x, tms_y),
            ).fetchone()
            used_row = "tms"
            if not row or not row[0]:
                row = conn.execute(
                    "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 1",
                    (z, x, y),
                ).fetchone()
                used_row = "xyz"
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"MBTiles read error: {exc}") from exc

    logger.warning(
        "MBTiles counts total=%s zx=%s zxtms=%s zxy=%s used=%s found=%s",
        counts["total"],
        counts["zx"],
        counts["zxtms"],
        counts["zxy"],
        used_row,
        bool(row and row[0]),
    )

    if not row or not row[0]:
        detail = (
            "Tile not found: "
            f"path={mbtiles_path} z={z} x={x} y={y} tms_y={tms_y} "
            f"count_total={counts['total']} count_zx={counts['zx']} "
            f"count_zxtms={counts['zxtms']} count_zxy={counts['zxy']}"
        )
        raise HTTPException(status_code=404, detail=detail)

    return Response(content=row[0], media_type="image/png")
