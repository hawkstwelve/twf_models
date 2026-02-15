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

# ------------------------------------------------------------------
# Per-endpoint Cache-Control headers
# ------------------------------------------------------------------
# Models list changes very rarely (new model added every few months).
_CACHE_MODELS = "public, max-age=3600"
# Runs/vars lists change every few hours (when a new model run lands).
# 30-second caching prevents redundant fetches on quick navigation
# while keeping the data reasonably fresh.
_CACHE_RUNS_VARS = "public, max-age=30, stale-while-revalidate=120"
# The run manifest changes during progressive publishing (new frames
# appear every few seconds), so browsers must always revalidate.
_CACHE_MANIFEST = "public, no-cache"


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
        headers={"Cache-Control": _CACHE_MODELS},
    )


@router.get("/runs")
def list_runs(model: str = Query(..., min_length=1)) -> JSONResponse:
    _ensure_segment("model", model)
    return JSONResponse(
        content=list_published_runs(model),
        headers={"Cache-Control": _CACHE_RUNS_VARS},
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
        headers={"Cache-Control": _CACHE_RUNS_VARS},
    )


@router.get("/run/{model}/{run}/manifest.json")
def get_run_manifest(model: str, run: str) -> JSONResponse:
    _ensure_segment("model", model)
    _ensure_segment("run", run)
    return JSONResponse(
        content=load_published_run_manifest(model, run),
        headers={"Cache-Control": _CACHE_MANIFEST},
    )
