#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_V2_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_V2_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_V2_DIR))

from app.config import settings
from app.services.offline_tiles import validate_manifest_contract


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate published PMTiles + frame image overlays for a run variable.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--var", required=True)
    return parser.parse_args()


def _expected_frame_image_url(model: str, run: str, var_key: str, frame_id: str) -> str:
    return f"/frames/{model}/{run}/{var_key}/{frame_id}.webp"


def main() -> int:
    args = _parse_args()
    model = str(args.model).strip()
    run = str(args.run).strip()
    var_key = str(args.var).strip()

    var_root = settings.PUBLISH_ROOT / model / run / var_key
    manifest_path = var_root / "manifest.json"
    if not manifest_path.exists():
        print(f"manifest missing: {manifest_path}")
        return 1

    payload = json.loads(manifest_path.read_text())
    validate_manifest_contract(payload)
    frames = payload.get("frames", [])

    failures: list[str] = []
    rows: list[dict[str, object]] = []
    for frame in frames:
        frame_id = str(frame["frame_id"])
        pmtiles_path = var_root / "frames" / f"{frame_id}.pmtiles"
        webp_path = var_root / "frames" / f"{frame_id}.webp"
        manifest_image_url = frame.get("frame_image_url")
        expected_image_url = _expected_frame_image_url(model, run, var_key, frame_id)

        pmtiles_ok = pmtiles_path.exists()
        webp_ok = webp_path.exists()
        manifest_image_ok = manifest_image_url == expected_image_url
        row_ok = pmtiles_ok and webp_ok and manifest_image_ok
        rows.append(
            {
                "frame_id": frame_id,
                "pmtiles": pmtiles_ok,
                "webp": webp_ok,
                "frame_image_url": manifest_image_url,
                "expected_frame_image_url": expected_image_url,
                "ok": row_ok,
            }
        )
        if not row_ok:
            failures.append(
                f"frame_id={frame_id} pmtiles={pmtiles_ok} webp={webp_ok} "
                f"manifest_image_url={manifest_image_url!r} expected={expected_image_url!r}"
            )

    summary = {
        "model": model,
        "run": run,
        "var": var_key,
        "available_frames": int(payload.get("available_frames", 0)),
        "checked_frames": len(rows),
        "ok_frames": sum(1 for row in rows if row["ok"]),
        "failed_frames": len(failures),
    }

    print(json.dumps({"summary": summary, "frames": rows}, indent=2, sort_keys=True))
    if failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
