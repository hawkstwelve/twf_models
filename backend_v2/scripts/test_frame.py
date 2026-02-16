#!/usr/bin/env python3
"""Quick COG + frame-image test without running the full scheduler.

Usage (on prod):
    cd /opt/twf_models && source venv_v2/bin/activate
    python3 backend_v2/scripts/test_frame.py --var tmp2m --fh 12
    python3 backend_v2/scripts/test_frame.py --var tmp2m --fh 12 --run 20260216_06z
    python3 backend_v2/scripts/test_frame.py --var wspd10m --fh 6 --size 2048

Then on your Mac:
    scp weather-server:/tmp/test_frame_tmp2m_fh012.webp /tmp/ && open /tmp/test_frame_tmp2m_fh012.webp
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# Ensure backend_v2 is on the path
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))


def _latest_run(model: str, region: str) -> str:
    """Find the most recent run directory under DATA_V2_ROOT/<model>/<region>/."""
    from app.config import Settings

    settings = Settings()
    run_parent = settings.DATA_V2_ROOT / model / region
    if not run_parent.is_dir():
        raise RuntimeError(f"No run directories found at {run_parent}")
    runs = sorted(
        (d.name for d in run_parent.iterdir() if d.is_dir() and "z" in d.name),
        reverse=True,
    )
    if not runs:
        raise RuntimeError(f"No run directories found in {run_parent}")
    return runs[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a COG + render a frame image for quick visual testing."
    )
    parser.add_argument("--model", default="gfs", help="Model name (default: gfs)")
    parser.add_argument("--region", default="pnw", help="Region (default: pnw)")
    parser.add_argument("--run", default=None, help="Run ID, e.g. 20260216_06z (default: latest)")
    parser.add_argument("--var", default="tmp2m", help="Variable (default: tmp2m)")
    parser.add_argument("--fh", type=int, default=12, help="Forecast hour (default: 12)")
    parser.add_argument("--size", type=int, default=2048, help="Frame image size in px (default: 2048)")
    parser.add_argument("--quality", type=int, default=90, help="WebP quality (default: 90)")
    parser.add_argument("--skip-cog", action="store_true", help="Skip COG build, only re-render frame")
    parser.add_argument("--out", default=None, help="Output WebP path (default: /tmp/test_frame_<var>_fh<fh>.webp)")
    args = parser.parse_args()

    run_id = args.run or _latest_run(args.model, args.region)
    run_short = run_id.replace("_", "")  # e.g. 20260216_06z → 2026021606z
    if args.out:
        out_webp = Path(args.out)
    else:
        out_webp = Path(f"/tmp/test_{args.model}_{args.var}_fh{args.fh:03d}_{run_short}.webp")

    print(f"{'=' * 60}")
    print(f"  Model:   {args.model}")
    print(f"  Region:  {args.region}")
    print(f"  Run:     {run_id}")
    print(f"  Var:     {args.var}")
    print(f"  FH:      {args.fh}")
    print(f"  Size:    {args.size}px")
    print(f"  Quality: {args.quality}")
    print(f"  Output:  {out_webp}")
    print(f"{'=' * 60}")

    # ── Step 1: Build COG ──
    if not args.skip_cog:
        print("\n[1/2] Building COG...")
        t0 = time.monotonic()
        build_cog_script = _SCRIPT_DIR / "build_cog.py"
        cmd = [
            sys.executable,
            str(build_cog_script),
            "--model", args.model,
            "--region", args.region,
            "--run", run_id,
            "--var", args.var,
            "--fh", str(args.fh),
        ]
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            print(f"ERROR: build_cog.py exited with code {result.returncode}")
            sys.exit(1)
        print(f"COG built in {time.monotonic() - t0:.1f}s")
    else:
        print("\n[1/2] Skipping COG build (--skip-cog)")

    # ── Step 2: Render frame image ──
    print("\n[2/2] Rendering frame image...")
    t0 = time.monotonic()

    from app.config import Settings
    from app.services.frame_images import render_frame_image_webp
    from app.services.offline_tiles import _resolve_bounds

    settings = Settings()
    cog_path = (
        settings.DATA_V2_ROOT
        / args.model
        / args.region
        / run_id
        / args.var
        / f"fh{args.fh:03d}.cog.tif"
    )
    if not cog_path.exists():
        print(f"ERROR: COG not found: {cog_path}")
        sys.exit(1)

    bounds = _resolve_bounds(args.model, args.region)
    print(f"  Bounds:  {bounds}")

    render_frame_image_webp(
        model=args.model,
        run=run_id,
        varKey=args.var,
        fh=args.fh,
        pmtiles_path=Path("/dev/null"),
        tiles_json_path=Path("/dev/null"),
        out_webp_path=out_webp,
        region_bounds=bounds,
        size_px=args.size,
        quality=args.quality,
        source_cog_path=cog_path,
    )
    file_size_kb = out_webp.stat().st_size / 1024
    print(f"Frame rendered in {time.monotonic() - t0:.1f}s  ({file_size_kb:.0f} KB)")
    print(f"\n✅ Done: {out_webp}")
    print(f"\nOn your Mac run:")
    print(f"  scp weather-server:{out_webp} /tmp/ && open /tmp/{out_webp.name}")


if __name__ == "__main__":
    main()
