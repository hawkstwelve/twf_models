"""API routes"""
from fastapi import APIRouter, HTTPException, Query, Header
from fastapi.responses import FileResponse
from typing import Optional, List
from pathlib import Path
from datetime import datetime
import os

from app.config import settings
from app.models.schemas import MapInfo, MapListResponse, UpdateResponse
from app.services.map_generator import MapGenerator

router = APIRouter()


@router.get("/maps", response_model=MapListResponse)
async def get_maps(
    model: Optional[str] = Query(None, description="Filter by model (GFS, Graphcast)"),
    variable: Optional[str] = Query(None, description="Filter by variable"),
    forecast_hour: Optional[int] = Query(None, description="Filter by forecast hour")
):
    """Get list of available maps"""
    images_path = Path(settings.storage_path)
    
    if not images_path.exists():
        return MapListResponse(maps=[])
    
    maps = []
    for image_file in images_path.glob("*.png"):
        # Parse map info from filename
        # Format: {model}_{run_time}_{variable}_{forecast_hour}.png
        try:
            parts = image_file.stem.split("_")
            if len(parts) >= 4:
                map_info = MapInfo(
                    id=image_file.stem,
                    model=parts[0].upper(),
                    run_time=f"{parts[1]}_{parts[2]}",
                    forecast_hour=int(parts[-1]),
                    variable="_".join(parts[3:-1]),
                    image_url=f"{settings.api_prefix}/images/{image_file.name}",
                    created_at=datetime.fromtimestamp(image_file.stat().st_mtime).isoformat()
                )
                
                # Apply filters
                if model and map_info.model.upper() != model.upper():
                    continue
                if variable and map_info.variable != variable:
                    continue
                if forecast_hour is not None and map_info.forecast_hour != forecast_hour:
                    continue
                
                maps.append(map_info)
        except (ValueError, IndexError):
            continue
    
    return MapListResponse(maps=maps)


@router.get("/maps/{map_id}", response_model=MapInfo)
async def get_map(map_id: str):
    """Get specific map metadata"""
    images_path = Path(settings.storage_path)
    image_file = images_path / f"{map_id}.png"
    
    if not image_file.exists():
        raise HTTPException(status_code=404, detail="Map not found")
    
    # Parse map info from filename
    try:
        parts = map_id.split("_")
        if len(parts) >= 4:
            stat = image_file.stat()
            return MapInfo(
                id=map_id,
                model=parts[0].upper(),
                run_time=f"{parts[1]}_{parts[2]}",
                forecast_hour=int(parts[-1]),
                variable="_".join(parts[3:-1]),
                image_url=f"{settings.api_prefix}/images/{image_file.name}",
                created_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                file_size=stat.st_size
            )
    except (ValueError, IndexError):
        pass
    
    raise HTTPException(status_code=404, detail="Invalid map ID format")


@router.get("/images/{filename}")
async def get_image(filename: str):
    """Get map image file"""
    images_path = Path(settings.storage_path)
    image_file = images_path / filename
    
    if not image_file.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(
        path=str(image_file),
        media_type="image/png",
        filename=filename
    )


@router.post("/update", response_model=UpdateResponse)
async def trigger_update(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """Manually trigger data update and map generation"""
    # Check admin API key if configured
    if settings.admin_api_key and x_api_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
    
    # TODO: Trigger background job
    # For now, just return a placeholder
    return UpdateResponse(
        status="started",
        job_id=f"update_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        message="Update job started. Maps will be generated in the background."
    )
