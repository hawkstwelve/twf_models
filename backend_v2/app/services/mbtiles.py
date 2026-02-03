from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


def xyz_to_tms_y(z: int, y: int) -> int:
    return (1 << z) - 1 - y


def get_tile_bytes(mbtiles_path: Path, z: int, x: int, y: int) -> Optional[bytes]:
    if not mbtiles_path.is_file():
        return None

    tms_y = xyz_to_tms_y(z, y)

    try:
        with sqlite3.connect(mbtiles_path) as connection:
            cursor = connection.execute(
                """
                SELECT tile_data
                FROM tiles
                WHERE zoom_level = ?
                  AND tile_column = ?
                  AND tile_row = ?
                LIMIT 1
                """,
                (z, x, tms_y),
            )
            row = cursor.fetchone()
    except sqlite3.Error:
        return None

    if row is None:
        return None

    return row[0]
