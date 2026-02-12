#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from io import BytesIO
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.windows import from_bounds

_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))

from app.services.colormaps_v2 import get_lut

WEB_MERCATOR_HALF_WORLD = 20037508.342789244
WEB_MERCATOR_WORLD_SPAN = WEB_MERCATOR_HALF_WORLD * 2.0
WEB_MERCATOR_TILE_SIZE = 256


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _tile_bounds_mercator(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    tiles_per_axis = 1 << z
    tile_span = WEB_MERCATOR_WORLD_SPAN / tiles_per_axis
    left = -WEB_MERCATOR_HALF_WORLD + x * tile_span
    right = left + tile_span
    top = WEB_MERCATOR_HALF_WORLD - y * tile_span
    bottom = top - tile_span
    return left, bottom, right, top


def _tile_range_for_bounds(bounds: tuple[float, float, float, float], z: int) -> tuple[int, int, int, int] | None:
    left, bottom, right, top = bounds
    if right <= left or top <= bottom:
        return None

    tiles_per_axis = 1 << z
    tile_span = WEB_MERCATOR_WORLD_SPAN / tiles_per_axis

    epsilon = 1e-9
    x_min = int(math.floor((left + WEB_MERCATOR_HALF_WORLD) / tile_span))
    x_max = int(math.floor(((right - epsilon) + WEB_MERCATOR_HALF_WORLD) / tile_span))
    y_min = int(math.floor((WEB_MERCATOR_HALF_WORLD - top) / tile_span))
    y_max = int(math.floor((WEB_MERCATOR_HALF_WORLD - (bottom + epsilon)) / tile_span))

    max_index = tiles_per_axis - 1
    x_min = _clamp(x_min, 0, max_index)
    x_max = _clamp(x_max, 0, max_index)
    y_min = _clamp(y_min, 0, max_index)
    y_max = _clamp(y_max, 0, max_index)

    if x_min > x_max or y_min > y_max:
        return None
    return x_min, x_max, y_min, y_max


def _mercator_bounds_to_wgs84(bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    left, bottom, right, top = bounds
    left = max(-WEB_MERCATOR_HALF_WORLD, min(WEB_MERCATOR_HALF_WORLD, left))
    right = max(-WEB_MERCATOR_HALF_WORLD, min(WEB_MERCATOR_HALF_WORLD, right))
    bottom = max(-WEB_MERCATOR_HALF_WORLD, min(WEB_MERCATOR_HALF_WORLD, bottom))
    top = max(-WEB_MERCATOR_HALF_WORLD, min(WEB_MERCATOR_HALF_WORLD, top))

    transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    min_lon, min_lat = transformer.transform(left, bottom)
    max_lon, max_lat = transformer.transform(right, top)
    return min(min_lon, max_lon), min(min_lat, max_lat), max(min_lon, max_lon), max(min_lat, max_lat)


def _tile_rgba_from_bands(tile_data: np.ndarray, var_key: str) -> np.ndarray:
    if tile_data.ndim != 3:
        raise RuntimeError(f"Expected 3D tile data (bands,y,x), got shape={tile_data.shape}")

    band_count = int(tile_data.shape[0])
    if band_count >= 4:
        return np.moveaxis(tile_data[:4], 0, -1).astype(np.uint8)

    if band_count == 2:
        band1 = tile_data[0].astype(np.uint8)
        band2 = tile_data[1].astype(np.uint8)
        lut = get_lut(var_key)
        rgba = lut[band1]
        alpha = np.where(band1 == 255, 0, band2).astype(np.uint8)
        rgba[..., 3] = alpha
        return rgba

    if band_count == 1:
        band = tile_data[0].astype(np.uint8)
        lut = get_lut(var_key)
        if var_key == "precip_ptype":
            palette_index = np.where(band == 0, 0, band - 1).astype(np.uint8)
            rgba = lut[palette_index]
            alpha = np.where(band == 0, 0, 255).astype(np.uint8)
        else:
            rgba = lut[band]
            alpha = np.where(band == 255, 0, 255).astype(np.uint8)
        rgba[..., 3] = alpha
        return rgba

    raise RuntimeError(f"Unsupported source band count for PMTiles conversion: {band_count}")


def _png_bytes(rgba: np.ndarray) -> bytes:
    image = Image.fromarray(rgba, mode="RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_pmtiles(
    *,
    src_path: Path,
    dst_path: Path,
    var_key: str,
    zoom_min: int,
    zoom_max: int,
    validation_json_path: Path | None,
) -> None:
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    z0_sample: dict[str, int | bool] | None = None
    z7_sample: dict[str, int | bool] | None = None
    tile_count = 0

    with dst_path.open("wb") as fp:
        writer = Writer(fp)
        with rasterio.open(src_path) as src:
            with WarpedVRT(src, crs="EPSG:3857", resampling=Resampling.nearest) as vrt:
                for z in range(zoom_min, zoom_max + 1):
                    tile_range = _tile_range_for_bounds(vrt.bounds, z)
                    if tile_range is None:
                        continue
                    x_min, x_max, y_min, y_max = tile_range
                    for x in range(x_min, x_max + 1):
                        for y in range(y_min, y_max + 1):
                            left, bottom, right, top = _tile_bounds_mercator(z, x, y)
                            window = from_bounds(left, bottom, right, top, transform=vrt.transform)
                            tile_data = vrt.read(
                                window=window,
                                out_shape=(vrt.count, WEB_MERCATOR_TILE_SIZE, WEB_MERCATOR_TILE_SIZE),
                                resampling=Resampling.nearest,
                            ).astype(np.uint8, copy=False)
                            rgba = _tile_rgba_from_bands(tile_data, var_key)
                            writer.write_tile(zxy_to_tileid(z, x, y), _png_bytes(rgba))
                            tile_count += 1
                            if z == 0 and z0_sample is None:
                                z0_sample = {"z": z, "x": x, "y": y, "present": True}
                            if z == 7 and z7_sample is None:
                                z7_sample = {"z": z, "x": x, "y": y, "present": True}

                if tile_count == 0:
                    raise RuntimeError(f"No tiles generated from source raster: {src_path}")

                min_lon, min_lat, max_lon, max_lat = _mercator_bounds_to_wgs84(vrt.bounds)
                center_lon = (min_lon + max_lon) / 2.0
                center_lat = (min_lat + max_lat) / 2.0
                header = {
                    "version": 3,
                    "tile_compression": Compression.NONE,
                    "tile_type": TileType.PNG,
                    "min_zoom": zoom_min,
                    "max_zoom": zoom_max,
                    "min_lon_e7": int(min_lon * 10_000_000),
                    "min_lat_e7": int(min_lat * 10_000_000),
                    "max_lon_e7": int(max_lon * 10_000_000),
                    "max_lat_e7": int(max_lat * 10_000_000),
                    "center_zoom": zoom_min,
                    "center_lon_e7": int(center_lon * 10_000_000),
                    "center_lat_e7": int(center_lat * 10_000_000),
                }
                metadata = {
                    "name": src_path.stem,
                    "format": "png",
                    "type": "overlay",
                    "minzoom": zoom_min,
                    "maxzoom": zoom_max,
                    "bounds": [min_lon, min_lat, max_lon, max_lat],
                }
                writer.finalize(header, metadata)

    if validation_json_path is not None:
        validation_json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tile_presence": {
                "z0": z0_sample or {"present": False},
                "z7": z7_sample or {"present": False},
            },
            "tile_count": tile_count,
            "var": var_key,
            "source": str(src_path),
        }
        validation_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build raster PMTiles archive from a COG/GeoTIFF frame.")
    parser.add_argument("--src", required=True, help="Source COG/GeoTIFF path")
    parser.add_argument("--dst", required=True, help="Destination PMTiles path")
    parser.add_argument("--var", required=True, help="Normalized variable key for LUT handling")
    parser.add_argument("--zoom-min", type=int, default=0)
    parser.add_argument("--zoom-max", type=int, default=7)
    parser.add_argument("--validation-json", help="Optional validation sidecar output path")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        build_pmtiles(
            src_path=Path(args.src),
            dst_path=Path(args.dst),
            var_key=str(args.var).strip(),
            zoom_min=int(args.zoom_min),
            zoom_max=int(args.zoom_max),
            validation_json_path=Path(args.validation_json) if args.validation_json else None,
        )
    except Exception as exc:
        print(f"PMTiles build failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
