from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional, Tuple


BoundsWGS84 = Tuple[float, float, float, float]


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


def create_mbtiles(
    path: Path | str,
    *,
    minzoom: int,
    maxzoom: int,
    bounds_wgs84: BoundsWGS84,
) -> sqlite3.Connection:
    path = Path(path)
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    cursor = conn.cursor()

    cursor.execute(
        "CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT);"
    )
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);"
    )

    cursor.execute("DELETE FROM metadata;")
    cursor.execute("DELETE FROM tiles;")

    minlon, minlat, maxlon, maxlat = bounds_wgs84
    bounds_str = f"{minlon:.6f},{minlat:.6f},{maxlon:.6f},{maxlat:.6f}"

    metadata = [
        ("name", path.stem),
        ("format", "png"),
        ("minzoom", str(minzoom)),
        ("maxzoom", str(maxzoom)),
        ("bounds", bounds_str),
        ("type", "overlay"),
        ("version", "1"),
    ]
    cursor.executemany("INSERT INTO metadata (name, value) VALUES (?, ?);", metadata)
    conn.commit()

    return conn


def put_tile(conn: sqlite3.Connection, z: int, x: int, y: int, png_bytes: bytes) -> None:
    tms_y = xyz_to_tms_y(z, y)
    conn.execute(
        "INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?);",
        (z, x, tms_y, png_bytes),
    )


def finalize_mbtiles(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS tile_index on tiles (zoom_level, tile_column, tile_row);"
    )
    conn.commit()
