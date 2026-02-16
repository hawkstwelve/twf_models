#!/usr/bin/env python3
"""Test sharpening approaches on the existing COG.

Run on prod:
    python3 backend_v2/scripts/test_sharpening.py
Then on Mac:
    scp -r weather-server:/tmp/sharpening_test/ /tmp/sharpening_test/ && open /tmp/sharpening_test/
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
    from PIL import Image, ImageFilter
    from rasterio.enums import Resampling

    from app.config import Settings
    from app.services.colormaps_v2 import VAR_SPECS, build_continuous_lut

    settings = Settings()
    run_parent = settings.DATA_V2_ROOT / "gfs" / "pnw"
    runs = sorted((d.name for d in run_parent.iterdir() if d.is_dir() and "z" in d.name), reverse=True)
    run_id = runs[0]
    cog_path = settings.DATA_V2_ROOT / "gfs" / "pnw" / run_id / "tmp2m" / "fh012.cog.tif"

    out_dir = Path("/tmp/sharpening_test")
    out_dir.mkdir(exist_ok=True)

    with rasterio.open(cog_path) as src:
        native_data = src.read()
        w, h = src.width, src.height
    print(f"COG: {w}x{h}")

    band1 = native_data[0].astype(np.uint8)
    alpha_band = native_data[1].astype(np.uint8) if native_data.shape[0] >= 2 else np.full_like(band1, 255)

    # Use the seasonal range for better contrast
    lut = build_continuous_lut(VAR_SPECS["tmp2m"]["colors"], n=256)
    valid_mask = band1 != 255
    valid = band1[valid_mask]
    byte_min, byte_max = int(valid.min()), int(valid.max())

    # Stretch to full palette
    stretched = np.zeros_like(band1, dtype=np.uint8)
    stretched[valid_mask] = np.clip(
        np.rint((band1[valid_mask].astype(float) - byte_min) / max(byte_max - byte_min, 1) * 254.0),
        0, 254,
    ).astype(np.uint8)
    stretched[~valid_mask] = 255

    rgba = lut[stretched].copy()
    rgba[..., 3] = np.where(stretched == 255, 0, alpha_band)
    native_img = Image.fromarray(rgba, mode="RGBA")

    # ── A) LANCZOS only (current) ──
    img_a = native_img.resize((2048, 2048), Image.Resampling.LANCZOS)
    img_a.save(out_dir / "A_lanczos_only.png")
    print(f"[A] LANCZOS only → {out_dir / 'A_lanczos_only.png'}")

    # ── B) LANCZOS + light unsharp mask ──
    img_b = native_img.resize((2048, 2048), Image.Resampling.LANCZOS)
    img_b = img_b.filter(ImageFilter.UnsharpMask(radius=2, percent=100, threshold=2))
    img_b.save(out_dir / "B_lanczos_unsharp_light.png")
    print(f"[B] LANCZOS + light unsharp → {out_dir / 'B_lanczos_unsharp_light.png'}")

    # ── C) LANCZOS + strong unsharp mask ──
    img_c = native_img.resize((2048, 2048), Image.Resampling.LANCZOS)
    img_c = img_c.filter(ImageFilter.UnsharpMask(radius=3, percent=200, threshold=2))
    img_c.save(out_dir / "C_lanczos_unsharp_strong.png")
    print(f"[C] LANCZOS + strong unsharp → {out_dir / 'C_lanczos_unsharp_strong.png'}")

    # ── D) NEAREST (blocky/sharp grid cells) ──
    img_d = native_img.resize((2048, 2048), Image.Resampling.NEAREST)
    img_d.save(out_dir / "D_nearest.png")
    print(f"[D] NEAREST (raw grid cells) → {out_dir / 'D_nearest.png'}")

    # ── E) BICUBIC (slightly sharper than LANCZOS) ──
    img_e = native_img.resize((2048, 2048), Image.Resampling.BICUBIC)
    img_e = img_e.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=2))
    img_e.save(out_dir / "E_bicubic_unsharp.png")
    print(f"[E] BICUBIC + unsharp → {out_dir / 'E_bicubic_unsharp.png'}")

    # ── F) Double the native res: warp to 1.5km then LANCZOS to 2048 ──
    # Read COG at 2x native with bilinear
    with rasterio.open(cog_path) as src:
        data_2x = src.read(
            out_shape=(src.count, src.height * 2, src.width * 2),
            resampling=Resampling.bilinear,
        )
    band1_2x = data_2x[0].astype(np.uint8)
    alpha_2x = data_2x[1].astype(np.uint8) if data_2x.shape[0] >= 2 else np.full_like(band1_2x, 255)
    valid_2x = band1_2x != 255
    stretched_2x = np.zeros_like(band1_2x, dtype=np.uint8)
    stretched_2x[valid_2x] = np.clip(
        np.rint((band1_2x[valid_2x].astype(float) - byte_min) / max(byte_max - byte_min, 1) * 254.0),
        0, 254,
    ).astype(np.uint8)
    stretched_2x[~valid_2x] = 255
    rgba_2x = lut[stretched_2x].copy()
    rgba_2x[..., 3] = np.where(stretched_2x == 255, 0, alpha_2x)
    img_f = Image.fromarray(rgba_2x, mode="RGBA").resize((2048, 2048), Image.Resampling.LANCZOS)
    img_f = img_f.filter(ImageFilter.UnsharpMask(radius=2, percent=100, threshold=2))
    img_f.save(out_dir / "F_2x_native_lanczos_unsharp.png")
    print(f"[F] 2x read + LANCZOS + unsharp → {out_dir / 'F_2x_native_lanczos_unsharp.png'}")

    print(f"\nOn your Mac:")
    print(f"  scp -r weather-server:{out_dir}/ /tmp/sharpening_test/ && open /tmp/sharpening_test/")


if __name__ == "__main__":
    main()
