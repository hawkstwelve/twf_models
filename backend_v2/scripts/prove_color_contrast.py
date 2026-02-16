#!/usr/bin/env python3
"""Render the SAME COG with a tightened colormap range to prove color contrast is the issue.

Run on prod:
    cd /opt/twf_models && source venv_v2/bin/activate
    python3 backend_v2/scripts/prove_color_contrast.py

Then on your Mac:
    scp -r weather-server:/tmp/color_contrast_test/ /tmp/color_contrast_test/ && open /tmp/color_contrast_test/
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))


def main() -> None:
    import rasterio
    from PIL import Image
    from rasterio.enums import Resampling

    from app.config import Settings
    from app.services.colormaps_v2 import VAR_SPECS, build_continuous_lut

    settings = Settings()

    # Find the latest COG
    run_parent = settings.DATA_V2_ROOT / "gfs" / "pnw"
    runs = sorted((d.name for d in run_parent.iterdir() if d.is_dir() and "z" in d.name), reverse=True)
    run_id = runs[0]
    cog_path = settings.DATA_V2_ROOT / "gfs" / "pnw" / run_id / "tmp2m" / "fh012.cog.tif"
    print(f"COG: {cog_path}")

    out_dir = Path("/tmp/color_contrast_test")
    out_dir.mkdir(exist_ok=True)

    # Read COG natively
    with rasterio.open(cog_path) as src:
        native_data = src.read()
        w, h = src.width, src.height
    print(f"COG: {w}x{h} bands={native_data.shape[0]}")

    band1 = native_data[0].astype(np.uint8)
    alpha_band = native_data[1].astype(np.uint8) if native_data.shape[0] >= 2 else np.full_like(band1, 255)

    valid = band1[band1 != 255]
    byte_min, byte_max = int(valid.min()), int(valid.max())
    print(f"Byte range: {byte_min}–{byte_max} ({byte_max - byte_min + 1} values)")

    # The current encoding: -40 to 120°F → byte 0–254
    # byte_min=93 → 93/254 * 160 - 40 = 18.6°F
    # byte_max=148 → 148/254 * 160 - 40 = 53.2°F
    temp_min = byte_min / 254.0 * 160.0 - 40.0
    temp_max = byte_max / 254.0 * 160.0 - 40.0
    print(f"Temperature range in frame: {temp_min:.1f}°F to {temp_max:.1f}°F")

    spec = VAR_SPECS["tmp2m"]
    colors = spec["colors"]

    # ── A) CURRENT: full -40→120 range (what we have now) ──
    lut_wide = build_continuous_lut(colors, n=256)
    rgba_wide = lut_wide[band1].copy()
    rgba_wide[..., 3] = np.where(band1 == 255, 0, alpha_band)
    img_wide = Image.fromarray(rgba_wide, mode="RGBA").resize((2048, 2048), Image.Resampling.LANCZOS)
    img_wide.save(out_dir / "A_current_wide_range.png")
    print(f"\n[A] Current (-40 to 120°F): {out_dir / 'A_current_wide_range.png'}")

    # ── B) TIGHT: remap bytes so the FULL palette uses just the data range ──
    # Stretch byte_min..byte_max → 0..254, then apply same LUT
    stretched = np.zeros_like(band1, dtype=np.uint8)
    valid_mask = band1 != 255
    stretched[valid_mask] = np.clip(
        np.rint((band1[valid_mask].astype(float) - byte_min) / max(byte_max - byte_min, 1) * 254.0),
        0, 254,
    ).astype(np.uint8)
    stretched[~valid_mask] = 255

    rgba_tight = lut_wide[stretched].copy()
    rgba_tight[..., 3] = np.where(stretched == 255, 0, alpha_band)
    img_tight = Image.fromarray(rgba_tight, mode="RGBA").resize((2048, 2048), Image.Resampling.LANCZOS)
    img_tight.save(out_dir / "B_tight_data_range.png")
    print(f"[B] Tight ({temp_min:.0f} to {temp_max:.0f}°F): {out_dir / 'B_tight_data_range.png'}")

    # ── C) SEASONAL: use a winter-focused range 0→60°F ──
    # Re-encode from the raw bytes: convert byte → °F, then re-scale to 0–60 range
    temps = band1.astype(float) / 254.0 * 160.0 - 40.0  # back to °F
    seasonal_min, seasonal_max = 0.0, 60.0
    seasonal_byte = np.clip(
        np.rint((temps - seasonal_min) / (seasonal_max - seasonal_min) * 254.0),
        0, 254,
    ).astype(np.uint8)
    seasonal_byte[~valid_mask] = 255

    rgba_seasonal = lut_wide[seasonal_byte].copy()
    rgba_seasonal[..., 3] = np.where(seasonal_byte == 255, 0, alpha_band)
    img_seasonal = Image.fromarray(rgba_seasonal, mode="RGBA").resize((2048, 2048), Image.Resampling.LANCZOS)
    img_seasonal.save(out_dir / "C_seasonal_0_60F.png")
    print(f"[C] Seasonal (0 to 60°F): {out_dir / 'C_seasonal_0_60F.png'}")

    print(f"\n{'='*60}")
    print(f"On your Mac:")
    print(f"  scp -r weather-server:{out_dir}/ /tmp/color_contrast_test/ && open /tmp/color_contrast_test/")


if __name__ == "__main__":
    main()
