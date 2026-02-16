from __future__ import annotations

import uuid
from pathlib import Path
from typing import Sequence

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling

from app.services.colormaps_v2 import get_lut


def _normalize_size_px(size_px: int | Sequence[int]) -> tuple[int, int]:
    if isinstance(size_px, int):
        return max(64, size_px), max(64, size_px)
    values = list(size_px)
    if len(values) != 2:
        raise ValueError("size_px must be an int or [width, height]")
    width = max(64, int(values[0]))
    height = max(64, int(values[1]))
    return width, height


def _rgba_from_encoded_bands(tile_data: np.ndarray, var_key: str) -> np.ndarray:
    if tile_data.ndim != 3:
        raise RuntimeError(f"Expected 3D data (bands,y,x), got shape={tile_data.shape}")

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

    raise RuntimeError(f"Unsupported source band count for frame image conversion: {band_count}")


# Variables using discrete/categorical palette indices — must use nearest-neighbor
# resampling to avoid creating invalid intermediate palette values.
DISCRETE_VARS: frozenset[str] = frozenset({
    "radar_ptype", "ptype", "radar", "radar_ptype_combo", "precip_ptype",
})


def _read_cog_direct(
    *,
    source_cog_path: Path,
    output_width: int | None = None,
    output_height: int | None = None,
    resampling: Resampling = Resampling.nearest,
) -> np.ndarray:
    """Read byte-encoded bands directly from a COG — no CRS conversion.

    If output_width/output_height are provided and differ from the native
    COG dimensions, rasterio's built-in overviews + decimated read is used
    to produce the requested size in the COG's native CRS (EPSG:3857).
    This avoids the blurriness introduced by a 3857 → 4326 reprojection.
    """
    with rasterio.open(source_cog_path) as src:
        out_w = output_width or src.width
        out_h = output_height or src.height

        if out_w == src.width and out_h == src.height:
            # Exact native resolution — simple read, no resampling.
            return src.read()

        # Resample within the same grid (no CRS change).
        return src.read(
            out_shape=(src.count, out_h, out_w),
            resampling=resampling,
        )


def _read_encoded_frame(
    *,
    source_cog_path: Path,
    region_bounds: Sequence[float],
    output_width: int,
    output_height: int,
    resampling: Resampling = Resampling.nearest,
) -> np.ndarray:
    """Legacy path: reprojects from COG CRS to EPSG:4326 at arbitrary size.

    Kept for discrete variables that need exact region-clipped output at a
    specific pixel size with nearest-neighbor resampling.
    """
    from rasterio.transform import from_bounds as transform_from_bounds
    from rasterio.warp import reproject as rasterio_reproject

    west, south, east, north = [float(v) for v in region_bounds]
    if east <= west or north <= south:
        raise ValueError(f"Invalid region bounds: {region_bounds}")

    dst_transform = transform_from_bounds(west, south, east, north, output_width, output_height)
    with rasterio.open(source_cog_path) as src:
        destination = np.zeros((src.count, output_height, output_width), dtype=np.uint8)
        for band_index in range(src.count):
            if src.count == 1:
                dst_nodata = 255
            elif src.count == 2:
                dst_nodata = 255 if band_index == 0 else 0
            elif src.count >= 4 and band_index == 3:
                dst_nodata = 0
            else:
                dst_nodata = 0

            rasterio_reproject(
                source=rasterio.band(src, band_index + 1),
                destination=destination[band_index],
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata,
                dst_transform=dst_transform,
                dst_crs="EPSG:4326",
                dst_nodata=dst_nodata,
                resampling=resampling,
            )

    return destination


def _atomic_save_webp(image: Image.Image, out_webp_path: Path, *, quality: int) -> None:
    out_webp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_webp_path.with_name(f".{out_webp_path.name}.{uuid.uuid4().hex}.tmp")
    image.save(tmp_path, format="WEBP", quality=max(1, min(100, int(quality))), method=4)
    tmp_path.replace(out_webp_path)


def render_frame_image_webp(
    model: str,
    run: str,
    varKey: str,
    fh: int,
    pmtiles_path: Path,
    tiles_json_path: Path,
    out_webp_path: Path,
    region_bounds: Sequence[float],
    size_px: int | Sequence[int],
    quality: int,
    *,
    source_cog_path: Path | None = None,
) -> None:
    del model, run, fh, pmtiles_path, tiles_json_path
    if source_cog_path is None:
        raise ValueError("source_cog_path is required for frame image rendering")
    if not source_cog_path.exists():
        raise FileNotFoundError(f"Source COG not found for frame image render: {source_cog_path}")

    var_key_lower = str(varKey or "").strip().lower()
    is_discrete = var_key_lower in DISCRETE_VARS
    out_w, out_h = _normalize_size_px(size_px)

    # Single-resample path: read byte-encoded COG at the final output
    # resolution in one step, then apply LUT.  For continuous vars the
    # COG bytes were encoded from float-warped data, so bilinear on the
    # byte indices produces correct intermediate palette positions in
    # the smooth colour gradient.  For discrete/categorical vars we use
    # nearest to preserve exact palette boundaries.
    read_resampling = Resampling.nearest if is_discrete else Resampling.bilinear
    encoded = _read_cog_direct(
        source_cog_path=source_cog_path,
        output_width=out_w,
        output_height=out_h,
        resampling=read_resampling,
    )

    rgba = _rgba_from_encoded_bands(encoded, varKey)
    image = Image.fromarray(rgba, mode="RGBA")

    _atomic_save_webp(image, out_webp_path, quality=quality)
