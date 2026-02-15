from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.services.offline_tiles import (
    list_published_models,
    list_published_runs,
    list_published_vars,
    load_published_run_manifest,
)

router = APIRouter(prefix="/api", tags=["offline"])
SEGMENT_RE = re.compile(r"^[a-z0-9_-]+$")

# Short-lived cache for API JSON — prevents heuristic browser caching from
# serving stale runs/vars/manifest data, while still allowing quick
# back-to-back navigations to reuse the response briefly.
_API_JSON_CACHE = "public, no-cache"


def _ensure_segment(label: str, value: str) -> None:
    if not SEGMENT_RE.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label} segment: must match ^[a-z0-9_-]+$",
        )


@router.get("/models")
def list_models() -> JSONResponse:
    return JSONResponse(
        content=list_published_models(),
        headers={"Cache-Control": _API_JSON_CACHE},
    )


@router.get("/runs")
def list_runs(model: str = Query(..., min_length=1)) -> JSONResponse:
    _ensure_segment("model", model)
    return JSONResponse(
        content=list_published_runs(model),
        headers={"Cache-Control": _API_JSON_CACHE},
    )


@router.get("/vars")
def list_vars(
    model: str = Query(..., min_length=1),
    run: str = Query(..., min_length=1),
) -> JSONResponse:
    _ensure_segment("model", model)
    _ensure_segment("run", run)
    return JSONResponse(
        content=list_published_vars(model, run),
        headers={"Cache-Control": _API_JSON_CACHE},
    )


@router.get("/run/{model}/{run}/manifest.json")
def get_run_manifest(model: str, run: str) -> JSONResponse:
    _ensure_segment("model", model)
    _ensure_segment("run", run)
    return JSONResponse(
        content=load_published_run_manifest(model, run),
        headers={"Cache-Control": _API_JSON_CACHE},
    )
