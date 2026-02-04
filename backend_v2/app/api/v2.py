from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from app.services import discovery_v2

router = APIRouter(prefix="/api/v2", tags=["v2"])
SEGMENT_RE = re.compile(r"^[a-z0-9_-]+$")


def _ensure_segment(label: str, value: str) -> None:
    if not SEGMENT_RE.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label} segment: must match ^[a-z0-9_-]+$",
        )


@router.get("/models")
def list_models() -> list[dict[str, str]]:
    return discovery_v2.list_models()


@router.get("/{model}/regions")
def list_regions(model: str) -> list[str]:
    _ensure_segment("model", model)
    return discovery_v2.list_regions(model)


@router.get("/{model}/{region}/runs")
def list_runs_endpoint(model: str, region: str) -> list[str]:
    _ensure_segment("model", model)
    _ensure_segment("region", region)
    return discovery_v2.list_runs(model, region)


@router.get("/{model}/{region}/{run}/vars")
def list_vars(model: str, region: str, run: str) -> list[str]:
    _ensure_segment("model", model)
    _ensure_segment("region", region)
    _ensure_segment("run", run)
    return discovery_v2.list_vars(model, region, run)


@router.get("/{model}/{region}/{run}/{var}/frames")
def list_frames(model: str, region: str, run: str, var: str) -> list[dict]:
    _ensure_segment("model", model)
    _ensure_segment("region", region)
    _ensure_segment("run", run)
    _ensure_segment("var", var)
    return discovery_v2.list_frames(model, region, run, var)
