from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Response

from ..config import MBTILES_ROOT
from ..services.mbtiles import get_tile_bytes
from ..utils.pathing import safe_join

router = APIRouter(prefix="/tiles/v2", tags=["v2-tiles"])
SEGMENT_RE = re.compile(r"^[a-z0-9_-]+$")


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

    try:
        mbtiles_path = safe_join(MBTILES_ROOT, model, run, f"{var}.mbtiles")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    tile_bytes = get_tile_bytes(mbtiles_path, z, x, y)
    if tile_bytes is None:
        raise HTTPException(status_code=404, detail="Tile not found")

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
