#!/usr/bin/env python3
"""Diagnostic: inspect EVERY step of the COG → frame pipeline.

Run on prod:
    cd /opt/twf_models && source venv_v2/bin/activate
    python3 backend_v2/scripts/diagnose_frame.py --var tmp2m --fh 12

This dumps raw intermediate PNGs so you can see exactly what each stage produces.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose frame pipeline step-by-step")
    parser.add_argument("--model", default="gfs")
    parser.add_argument("--region", default="pnw")
    parser.add_argument("--run", default=None)
    parser.add_argument("--var", default="tmp2m")
    parser.add_argument("--fh", type=int, default=12)
    args = parser.parse_args()

    from app.config import Settings
    settings = Settings()

    # Find COG
    if args.run:
        run_id = args.run
    else:
        run_parent = settings.DATA_V2_ROOT / args.model / args.region
        runs = sorted((d.name for d in run_parent.iterdir() if d.is_dir() and "z" in d.name), reverse=True)
        run_id = runs[0]

    cog_path = settings.DATA_V2_ROOT / args.model / args.region / run_id / args.var / f"fh{args.fh:03d}.cog.tif"
    print(f"COG: {cog_path}")
    print(f"COG exists: {cog_path.exists()}")
    print(f"COG size: {cog_path.stat().st_size / 1024:.0f} KB")

    import rasterio
    from PIL import Image
    from rasterio.enums import Resampling

    out_dir = Path("/tmp/diagnose_frame")
    out_dir.mkdir(exist_ok=True)

    # ── Step 1: Read COG native ──
    with rasterio.open(cog_path) as src:
        print(f"\n{'='*60}")
        print(f"COG native: {src.width}x{src.height} bands={src.count} crs={src.crs}")
        print(f"COG dtype: {src.dtypes}")
        print(f"COG nodata: {src.nodata}")
        print(f"COG transform: {src.transform}")
        native_data = src.read()
        print(f"Band 1 (byte): min={native_data[0].min()} max={native_data[0].max()} "
              f"unique_vals={len(np.unique(native_data[0]))}")
        if src.count >= 2:
            print(f"Band 2 (alpha): min={native_data[1].min()} max={native_data[1].max()} "
                  f"nonzero={np.count_nonzero(native_data[1])}/{native_data[1].size}")

    # ── Step 2: Apply LUT at native resolution ──
    from app.services.colormaps_v2 import get_lut
    lut = get_lut(args.var)
    print(f"\nLUT shape: {lut.shape} dtype={lut.dtype}")

    band1 = native_data[0].astype(np.uint8)
    rgba_native = lut[band1].copy()
    if native_data.shape[0] >= 2:
        alpha = np.where(band1 == 255, 0, native_data[1].astype(np.uint8))
    else:
        alpha = np.where(band1 == 255, 0, 255).astype(np.uint8)
    rgba_native[..., 3] = alpha

    native_img = Image.fromarray(rgba_native, mode="RGBA")
    native_path = out_dir / "1_native_rgba.png"
    native_img.save(native_path)
    print(f"\n[Step 1] Native RGBA: {native_img.size[0]}x{native_img.size[1]} → {native_path}")

    # ── Step 3: NEAREST resize to 2048 (what blocks look like) ──
    nearest_img = native_img.resize((2048, 2048), resample=Image.Resampling.NEAREST)
    nearest_path = out_dir / "2_nearest_2048.png"
    nearest_img.save(nearest_path)
    print(f"[Step 2] NEAREST 2048: {nearest_img.size[0]}x{nearest_img.size[1]} → {nearest_path}")

    # ── Step 4: LANCZOS resize to 2048 (what we currently do) ──
    lanczos_img = native_img.resize((2048, 2048), resample=Image.Resampling.LANCZOS)
    lanczos_path = out_dir / "3_lanczos_2048.png"
    lanczos_img.save(lanczos_path)
    print(f"[Step 3] LANCZOS 2048: {lanczos_img.size[0]}x{lanczos_img.size[1]} → {lanczos_path}")

    # ── Step 5: What the actual render_frame_image_webp produces ──
    from app.services.frame_images import render_frame_image_webp
    actual_webp = out_dir / "4_actual_output.webp"
    render_frame_image_webp(
        model=args.model, run=run_id, varKey=args.var, fh=args.fh,
        pmtiles_path=Path("/dev/null"), tiles_json_path=Path("/dev/null"),
        out_webp_path=actual_webp,
        region_bounds=(-125.5, 41.5, -111.0, 49.5),
        size_px=2048, quality=90,
        source_cog_path=cog_path,
    )
    actual_img = Image.open(actual_webp)
    print(f"[Step 4] Actual output: {actual_img.size[0]}x{actual_img.size[1]} → {actual_webp}")

    # ── Step 6: Show byte distribution ──
    valid_bytes = band1[band1 != 255]
    if valid_bytes.size:
        print(f"\n{'='*60}")
        print(f"BYTE DISTRIBUTION (palette indices actually used):")
        print(f"  min={valid_bytes.min()} max={valid_bytes.max()} "
              f"range={valid_bytes.max()-valid_bytes.min()} unique={len(np.unique(valid_bytes))}")
        print(f"  This means {valid_bytes.max()-valid_bytes.min()+1} out of 255 palette slots are used")
        print(f"  = only {(valid_bytes.max()-valid_bytes.min()+1)/255*100:.0f}% of the color range")

        # Show what colors those byte values map to
        used_min_color = lut[valid_bytes.min()]
        used_max_color = lut[valid_bytes.max()]
        mid_byte = (valid_bytes.min() + valid_bytes.max()) // 2
        used_mid_color = lut[mid_byte]
        print(f"\n  Color at byte {valid_bytes.min()}: RGBA={tuple(used_min_color)}")
        print(f"  Color at byte {mid_byte}: RGBA={tuple(used_mid_color)}")
        print(f"  Color at byte {valid_bytes.max()}: RGBA={tuple(used_max_color)}")

    # ── Summary ──
    print(f"\n{'='*60}")
    print(f"FILES SAVED TO {out_dir}/")
    print(f"  1_native_rgba.png   - Raw COG at native resolution (no resize)")
    print(f"  2_nearest_2048.png  - NEAREST upscale to 2048 (blocky)")
    print(f"  3_lanczos_2048.png  - LANCZOS upscale to 2048 (smooth)")
    print(f"  4_actual_output.webp - What render_frame_image_webp produces")
    print(f"\nOn your Mac:")
    print(f"  scp -r weather-server:{out_dir}/ /tmp/diagnose_frame/ && open /tmp/diagnose_frame/")


if __name__ == "__main__":
    main()
