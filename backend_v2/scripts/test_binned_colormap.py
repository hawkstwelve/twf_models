#!/usr/bin/env python3
"""Test DISCRETE binning vs continuous gradient — matching prod pipeline exactly.

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


def _build_binned_lut(colors_hex: list[str], n_bins: int = 36) -> np.ndarray:
    """Build a LUT where each color band is a SOLID block — no gradient within a bin."""
    from app.services.colormaps_v2 import hex_to_rgba_u8

    stops = np.array([hex_to_rgba_u8(c, 255)[:3] for c in colors_hex], dtype=float)
    stop_positions = np.linspace(0.0, 1.0, num=len(colors_hex))
    bin_centers = np.linspace(0.0, 1.0, num=n_bins)
    r = np.interp(bin_centers, stop_positions, stops[:, 0])
    g = np.interp(bin_centers, stop_positions, stops[:, 1])
    b = np.interp(bin_centers, stop_positions, stops[:, 2])

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

    # Output size: 2048 wide, correct aspect ratio
    out_w = 2048
    out_h = round(out_w * h / w)
    print(f"Output: {out_w}x{out_h}")

    colors = VAR_SPECS["tmp2m"]["colors"]

    def render(lut: np.ndarray, label: str, filename: str) -> None:
        rgba = lut[band1].copy()
        rgba[..., 3] = np.where(band1 == 255, 0, alpha_band)
        img = Image.fromarray(rgba, mode="RGBA").resize((out_w, out_h), Image.Resampling.BILINEAR)
        img.save(out_dir / filename)
        print(f"[{label}] → {out_dir / filename}")

    # ── A) Continuous gradient (current prod) ──
    lut_cont = build_continuous_lut(colors, n=256)
    render(lut_cont, "A - continuous", "A_continuous.png")

    # ── B) 36 bins (1 per color stop) ──
    lut_36 = _build_binned_lut(colors, n_bins=36)
    render(lut_36, "B - 36 bins", "B_36_bins.png")

    print(f"\n{'='*60}")
    print(f"On your Mac:")
    print(f"  scp -r weather-server:{out_dir}/ /tmp/binned_test/ && open /tmp/binned_test/")


if __name__ == "__main__":
    main()
