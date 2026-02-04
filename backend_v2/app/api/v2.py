from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.services.run_resolution import get_data_root, list_runs, resolve_run

router = APIRouter(prefix="/api/v2", tags=["v2"])
logger = logging.getLogger(__name__)
SEGMENT_RE = re.compile(r"^[a-z0-9_-]+$")
FH_RE = re.compile(r"^fh(\d{3})\.cog\.tif$")


def _ensure_segment(label: str, value: str) -> None:
    if not SEGMENT_RE.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label} segment: must match ^[a-z0-9_-]+$",
        )


def _safe_list_dirs(path: Path) -> list[Path]:
    if not path.exists() or not path.is_dir():
        return []
    return [p for p in path.iterdir() if p.is_dir()]


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        logger.warning("Failed to read JSON: %s", path)
        return None


@router.get("/models")
def list_models() -> list[dict[str, str]]:
    root = get_data_root()
    models = sorted(p.name for p in _safe_list_dirs(root))
    return [{"id": model, "name": model.upper()} for model in models]


@router.get("/{model}/regions")
def list_regions(model: str) -> list[str]:
    _ensure_segment("model", model)
    root = get_data_root() / model
    return sorted(p.name for p in _safe_list_dirs(root))


@router.get("/{model}/{region}/runs")
def list_runs_endpoint(model: str, region: str) -> list[str]:
    _ensure_segment("model", model)
    _ensure_segment("region", region)
    return list_runs(model, region)


@router.get("/{model}/{region}/{run}/vars")
def list_vars(model: str, region: str, run: str) -> list[str]:
    _ensure_segment("model", model)
    _ensure_segment("region", region)
    _ensure_segment("run", run)
    resolved_run = resolve_run(model, region, run)
    root = get_data_root() / model / region / resolved_run
    return sorted(p.name for p in _safe_list_dirs(root))


@router.get("/{model}/{region}/{run}/{var}/frames")
def list_frames(model: str, region: str, run: str, var: str) -> list[dict]:
    _ensure_segment("model", model)
    _ensure_segment("region", region)
    _ensure_segment("run", run)
    _ensure_segment("var", var)
    resolved_run = resolve_run(model, region, run)
    root = get_data_root() / model / region / resolved_run / var
    if not root.exists() or not root.is_dir():
        return []

    frames: list[dict] = []
    for entry in root.iterdir():
        if not entry.is_file():
            continue
        match = FH_RE.match(entry.name)
        if not match:
            continue
        fh = int(match.group(1))
        meta = _read_json(root / f"fh{fh:03d}.json")
        frames.append({"fh": fh, "has_cog": True, "meta": meta})

    frames.sort(key=lambda item: item["fh"])
    return frames
