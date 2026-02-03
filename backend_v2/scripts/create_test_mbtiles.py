from __future__ import annotations

import argparse
import base64
import os
import sqlite3
from pathlib import Path

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/wwA"
    "AgEB/2xZfQAAAABJRU5ErkJggg=="
)

MBTILES_ROOT = Path(
    os.environ.get("TWF_MBTILES_ROOT", "/var/lib/twf-models/mbtiles")
).resolve()


def build_mbtiles(path: Path, z: int, x: int, y: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS tile_index ON tiles (zoom_level, tile_column, tile_row)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)",
            ("format", "png"),
        )
        connection.execute(
            "INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
            (z, x, y, PNG_1X1),
        )
        connection.commit()


def xyz_to_tms_y(z: int, y: int) -> int:
    return (1 << z) - 1 - y


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--z", type=int, default=5)
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=0)
    parser.add_argument("--xyz", action="store_true", help="Interpret y as XYZ and convert to TMS")
    args = parser.parse_args()

    tile_y = xyz_to_tms_y(args.z, args.y) if args.xyz else args.y
    mbtiles_path = MBTILES_ROOT / "hrrr" / "testrun" / "tmp2m.mbtiles"
    build_mbtiles(mbtiles_path, args.z, args.x, tile_y)


if __name__ == "__main__":
    main()
