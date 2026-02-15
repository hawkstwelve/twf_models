from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings

from .api.offline import router as offline_router

app = FastAPI(
    title="TWF Models API (V2)",
    version="0.1.0",
)

SEGMENT_RE = re.compile(r"^[a-z0-9_-]+$")
FRAME_VERSION_RE = re.compile(r"^[a-f0-9]{12,64}$")


def _ensure_segment(label: str, value: str) -> None:
    if not SEGMENT_RE.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {label} segment")


def _published_frame_path(model: str, run: str, var: str, frame_id: str) -> Path:
    return settings.PUBLISH_ROOT / model / run / var / "frames" / f"{frame_id}.pmtiles"


def _published_frame_image_path(model: str, run: str, var: str, frame_id: str) -> Path:
    return settings.PUBLISH_ROOT / model / run / var / "frames" / f"{frame_id}.webp"


def _manifest_latest_path(model: str) -> Path:
    return settings.MANIFEST_ROOT / model / "latest.json"


def _frame_cache_control(version: str | None) -> str:
    if version and FRAME_VERSION_RE.match(version):
        return "public, max-age=31536000, immutable"
    # No version token → content may change (progressive publish).
    # Allow revalidation so refreshed frames are picked up promptly.
    return "public, max-age=60, stale-while-revalidate=300"


@app.get("/tiles/{model}/{run}/{var}/{frame_id}.pmtiles")
def get_pmtiles(model: str, run: str, var: str, frame_id: str) -> Response:
    _ensure_segment("model", model)
    _ensure_segment("run", run)
    _ensure_segment("var", var)
    _ensure_segment("frame_id", frame_id)
    path = _published_frame_path(model, run, var, frame_id)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="PMTiles frame not found")
    return FileResponse(
        path=path,
        media_type="application/vnd.pmtiles",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.head("/tiles/{model}/{run}/{var}/{frame_id}.pmtiles")
def get_pmtiles_head(model: str, run: str, var: str, frame_id: str) -> Response:
    response = get_pmtiles(model=model, run=run, var=var, frame_id=frame_id)
    return Response(
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )


@app.get("/frames/{model}/{run}/{var}/{frame_id}.webp")
def get_frame_image(
    model: str,
    run: str,
    var: str,
    frame_id: str,
    v: str | None = Query(default=None),
) -> Response:
    _ensure_segment("model", model)
    _ensure_segment("run", run)
    _ensure_segment("var", var)
    _ensure_segment("frame_id", frame_id)
    path = _published_frame_image_path(model, run, var, frame_id)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Frame image not found")
    return FileResponse(
        path=path,
        media_type="image/webp",
        headers={
            "Cache-Control": _frame_cache_control(v),
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )


@app.head("/frames/{model}/{run}/{var}/{frame_id}.webp")
def get_frame_image_head(
    model: str,
    run: str,
    var: str,
    frame_id: str,
    v: str | None = Query(default=None),
) -> Response:
    response = get_frame_image(model=model, run=run, var=var, frame_id=frame_id, v=v)
    return Response(
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )


@app.get("/manifests/{model}/latest.json")
def get_latest_manifest_pointer(model: str):
    path = settings.MANIFEST_ROOT / model / "latest.json"

    headers = {"Cache-Control": "public, max-age=5, must-revalidate"}

    return FileResponse(
        path,
        media_type="application/json",
        headers=headers,
    )


app.include_router(offline_router)

app.mount("/published", StaticFiles(directory=settings.PUBLISH_ROOT, check_dir=False), name="published-static")
app.mount("/manifests", StaticFiles(directory=settings.MANIFEST_ROOT, check_dir=False), name="manifests-static")

@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
