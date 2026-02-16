#!/usr/bin/env python3
"""Test DISCRETE binning vs continuous gradient — the real fix for GFS blur.

Professional weather maps (NWS, Windy, etc.) use discrete bins, not continuous
gradients, precisely because low-res models like GFS look blurry with continuous
color interpolation.

Run on prod:
    python3 backend_v2/scripts/test_binned_colormap.py
Then on Mac:
    scp -r weather-server:/tmp/binned_test/ /tmp/binned_test/ && open /tmp/binned_test/
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))


def _build_binned_lut(colors_hex: list[str], n_bins: int = 20) -> np.ndarray:
    """Build a LUT where each color band is a SOLID block — no gradient within a bin.

    This creates sharp edges between temperature zones, mimicking how
    professional weather maps (NWS, Windy, etc.) render low-res data.
    """
    from app.services.colormaps_v2 import hex_to_rgba_u8

    # Interpolate colors to n_bins stops
    stops = np.array([hex_to_rgba_u8(c, 255)[:3] for c in colors_hex], dtype=float)
    stop_positions = np.linspace(0.0, 1.0, num=len(colors_hex))
    bin_centers = np.linspace(0.0, 1.0, num=n_bins)
    r = np.interp(bin_centers, stop_positions, stops[:, 0])
    g = np.interp(bin_centers, stop_positions, stops[:, 1])
    b = np.interp(bin_centers, stop_positions, stops[:, 2])

    # Build 256-entry LUT where each range of indices maps to ONE solid color
    lut = np.zeros((256, 4), dtype=np.uint8)
    for i in range(255):
        bin_idx = int(i / 255.0 * n_bins)
        bin_idx = min(bin_idx, n_bins - 1)
        lut[i] = [int(r[bin_idx]), int(g[bin_idx]), int(b[bin_idx]), 255]
    lut[255] = [0, 0, 0, 0]  # nodata
    return lut


def main() -> None:
    import rasterio
    from PIL import Image

    from app.config import Settings
    from app.services.colormaps_v2 import VAR_SPECS, build_continuous_lut

    settings = Settings()
    run_parent = settings.DATA_V2_ROOT / "gfs" / "pnw"
    runs = sorted((d.name for d in run_parent.iterdir() if d.is_dir() and "z" in d.name), reverse=True)
    run_id = runs[0]
    cog_path = settings.DATA_V2_ROOT / "gfs" / "pnw" / run_id / "tmp2m" / "fh012.cog.tif"

    out_dir = Path("/tmp/binned_test")
    out_dir.mkdir(exist_ok=True)

    with rasterio.open(cog_path) as src:
        native_data = src.read()
        w, h = src.width, src.height
    print(f"COG: {w}x{h}")

    band1 = native_data[0].astype(np.uint8)
    alpha_band = native_data[1].astype(np.uint8) if native_data.shape[0] >= 2 else np.full_like(band1, 255)
    valid_mask = band1 != 255
    valid = band1[valid_mask]
    byte_min, byte_max = int(valid.min()), int(valid.max())

    # Stretch to use full palette range
    stretched = np.zeros_like(band1, dtype=np.uint8)
    stretched[valid_mask] = np.clip(
        np.rint((band1[valid_mask].astype(float) - byte_min) / max(byte_max - byte_min, 1) * 254.0),
        0, 254,
    ).astype(np.uint8)
    stretched[~valid_mask] = 255

    colors = VAR_SPECS["tmp2m"]["colors"]

    def render(lut: np.ndarray, data: np.ndarray, label: str, filename: str, resample=Image.Resampling.LANCZOS) -> None:
        rgba = lut[data].copy()
        rgba[..., 3] = np.where(data == 255, 0, alpha_band)
        img = Image.fromarray(rgba, mode="RGBA").resize((2048, 2048), resample)
        img.save(out_dir / filename)
        print(f"[{label}] → {out_dir / filename}")

    # ── A) Current: continuous gradient, LANCZOS ──
    lut_cont = build_continuous_lut(colors, n=256)
    render(lut_cont, stretched, "A", "A_continuous_gradient.png")

    # ── B) 10 bins (~3.5°F per bin) ──
    lut_10 = _build_binned_lut(colors, n_bins=10)
    render(lut_10, stretched, "B - 10 bins", "B_10_bins.png")

    # ── C) 16 bins (~2.2°F per bin) ──
    lut_16 = _build_binned_lut(colors, n_bins=16)
    render(lut_16, stretched, "C - 16 bins", "C_16_bins.png")

    # ── D) 24 bins (~1.5°F per bin) ──
    lut_24 = _build_binned_lut(colors, n_bins=24)
    render(lut_24, stretched, "D - 24 bins", "D_24_bins.png")

    # ── E) 36 bins (1 per color stop, ~1°F per bin) ──
    lut_36 = _build_binned_lut(colors, n_bins=36)
    render(lut_36, stretched, "E - 36 bins", "E_36_bins.png")

    # ── F) 16 bins + NEAREST (sharp grid cells) ──
    lut_16b = _build_binned_lut(colors, n_bins=16)
    render(lut_16b, stretched, "F - 16 bins NEAREST", "F_16_bins_nearest.png", resample=Image.Resampling.NEAREST)

    # ── G) Continuous but with NEAREST resize (raw grid cells visible) ──
    render(lut_cont, stretched, "G - continuous NEAREST", "G_continuous_nearest.png", resample=Image.Resampling.NEAREST)

    print(f"\n{'='*60}")
    print(f"On your Mac:")
    print(f"  scp -r weather-server:{out_dir}/ /tmp/binned_test/ && open /tmp/binned_test/")


if __name__ == "__main__":
    main()
