from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services.offline_tiles import (
    list_published_models,
    list_published_runs,
    list_published_vars,
    load_published_run_manifest,
)

router = APIRouter(prefix="/api", tags=["offline"])
SEGMENT_RE = re.compile(r"^[a-z0-9_-]+$")


def _ensure_segment(label: str, value: str) -> None:
    if not SEGMENT_RE.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label} segment: must match ^[a-z0-9_-]+$",
        )


@router.get("/models")
def list_models() -> list[dict[str, str]]:
    return list_published_models()


@router.get("/runs")
def list_runs(model: str = Query(..., min_length=1)) -> list[str]:
    _ensure_segment("model", model)
    return list_published_runs(model)


@router.get("/vars")
def list_vars(
    model: str = Query(..., min_length=1),
    run: str = Query(..., min_length=1),
) -> list[str]:
    _ensure_segment("model", model)
    _ensure_segment("run", run)
    return list_published_vars(model, run)


@router.get("/run/{model}/{run}/manifest.json")
def get_run_manifest(model: str, run: str) -> dict[str, Any]:
    _ensure_segment("model", model)
    _ensure_segment("run", run)
    return load_published_run_manifest(model, run)
