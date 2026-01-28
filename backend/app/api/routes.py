"""API routes"""
from fastapi import APIRouter, HTTPException, Query, Header, Response
from fastapi.responses import FileResponse, JSONResponse
from typing import Optional, List
from pathlib import Path
from datetime import datetime, timedelta
import os
import logging

from app.config import settings
from app.models.schemas import MapInfo, MapListResponse, UpdateResponse, GFSRun, GFSRunListResponse, ModelInfo, ModelListResponse
from app.services.map_generator import MapGenerator
from app.models.model_registry import ModelRegistry

router = APIRouter()
logger = logging.getLogger(__name__)


def parse_run_time_from_filename(run_time_str: str) -> datetime:
    """
    Parse run time from filename format (YYYYMMDD_HH) to datetime.
    Example: "20260124_00" -> datetime(2026, 1, 24, 0, 0, 0)
    """
    date_part = run_time_str.split('_')[0]
    hour_part = run_time_str.split('_')[1]
    return datetime.strptime(f"{date_part}_{hour_part}", "%Y%m%d_%H")


def format_run_time_label(dt: datetime) -> str:
    """
    Format run time as human-readable label.
    Example: datetime(2026, 1, 24, 0, 0, 0) -> "00Z Jan 24"
    """
    return dt.strftime("%HZ %b %d")


@router.get("/models", response_model=ModelListResponse)
async def get_models(response: Response):
    """
    Get list of available models and their capabilities.
    
    Returns only enabled models with their metadata.
    Frontend uses this to populate model dropdown.
    """
    # Cache model list for 5 minutes
    response.headers["Cache-Control"] = "public, max-age=300"
    
    models = ModelRegistry.get_enabled()
    
    model_list = [
        ModelInfo(
            id=model_id,
            name=config.name,
            full_name=config.full_name,
            description=config.description,
            resolution=config.resolution,
            max_forecast_hour=config.max_forecast_hour,
            forecast_increment=config.forecast_increment,
            run_hours=config.run_hours,
            excluded_variables=config.excluded_variables,
            color=config.color,
            enabled=config.enabled
        )
        for model_id, config in models.items()
    ]
    
    return ModelListResponse(models=model_list)


@router.get("/models/{model_id}", response_model=ModelInfo)
async def get_model_info(model_id: str, response: Response):
    """
    Get detailed info about a specific model.
    
    Args:
        model_id: Model identifier (e.g., "GFS", "AIGFS")
    
    Raises:
        404: Model not found in registry
        403: Model exists but is not enabled
    """
    # Cache model info for 5 minutes
    response.headers["Cache-Control"] = "public, max-age=300"
    
    config = ModelRegistry.get(model_id)
    
    if not config:
        raise HTTPException(
            status_code=404, 
            detail=f"Model {model_id} not found"
        )
    
    if not config.enabled:
        raise HTTPException(
            status_code=403, 
            detail=f"Model {model_id} is not enabled"
        )
    
    return ModelInfo(
        id=model_id,
        name=config.name,
        full_name=config.full_name,
        description=config.description,
        resolution=config.resolution,
        max_forecast_hour=config.max_forecast_hour,
        forecast_increment=config.forecast_increment,
        run_hours=config.run_hours,
        excluded_variables=config.excluded_variables,
        color=config.color,
        enabled=config.enabled,
        provider=config.provider.value,
        has_refc=config.has_refc,
        has_upper_air=config.has_upper_air
    )


@router.get("/maps", response_model=MapListResponse)
async def get_maps(
    response: Response,
    model: Optional[str] = Query(None, description="Filter by model (e.g., 'GFS', 'AIGFS')"),
    variable: Optional[str] = Query(None, description="Filter by variable"),
    forecast_hour: Optional[int] = Query(None, description="Filter by forecast hour"),
    run_time: Optional[str] = Query(None, description="Filter by run time (ISO format: 2026-01-24T00:00:00Z)")
):
    """
    Get list of available maps.
    
    Supports filtering by model, variable, forecast_hour, and run_time.
    If run_time is provided, only maps from that specific model run are returned.
    If no model specified, returns maps from all enabled models.
    """
    # Validate model if provided
    if model:
        model_config = ModelRegistry.get(model)
        if not model_config:
            raise HTTPException(
                status_code=400, 
                detail=f"Unknown model: {model}. Use /api/models to see available models."
            )
        if not model_config.enabled:
            raise HTTPException(
                status_code=400, 
                detail=f"Model {model} is not enabled"
            )
    
    # Cache for configured duration - maps list changes as new maps are generated
    response.headers["Cache-Control"] = f"public, max-age={settings.cache_maps_list_seconds}"
    
    images_path = Path(settings.storage_path)
    
    if not images_path.exists():
        return MapListResponse(maps=[])
    
    # Convert ISO run_time to filename format if provided
    run_time_filter = None
    if run_time:
        try:
            dt = datetime.fromisoformat(run_time.replace('Z', '+00:00'))
            run_time_filter = dt.strftime("%Y%m%d_%H")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid run_time format. Use ISO format: 2026-01-24T00:00:00Z")
    else:
        # If no run_time specified, default to latest run to avoid showing old maps
        # Find the latest run by scanning all files
        all_runs = set()
        for image_file in images_path.glob("*.png"):
            try:
                parts = image_file.stem.split("_")
                if len(parts) >= 3:
                    file_run_time = f"{parts[1]}_{parts[2]}"
                    all_runs.add(file_run_time)
            except (ValueError, IndexError):
                continue
        
        if all_runs:
            # Sort runs (newest first) and use the latest
            sorted_runs = sorted(all_runs, reverse=True)
            run_time_filter = sorted_runs[0]
            logger.debug(f"No run_time specified, defaulting to latest run: {run_time_filter}")
    
    maps = []
    for image_file in images_path.glob("*.png"):
        # Parse map info from filename
        # Format: {model}_{run_time}_{variable}_{forecast_hour}.png
        try:
            parts = image_file.stem.split("_")
            if len(parts) >= 4:
                file_run_time = f"{parts[1]}_{parts[2]}"
                
                map_info = MapInfo(
                    id=image_file.stem,
                    model=parts[0].upper(),
                    run_time=file_run_time,
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
                if run_time_filter and file_run_time != run_time_filter:
                    continue
                
                maps.append(map_info)
        except (ValueError, IndexError):
            continue
    
    return MapListResponse(maps=maps)


@router.get("/runs", response_model=GFSRunListResponse)
async def get_runs(
    response: Response,
    model: Optional[str] = Query("GFS", description="Filter by model (default: GFS)")
):
    """
    Get list of available GFS model runs.
    
    Returns the last 4 runs (24 hours) by default, sorted newest first.
    Each run includes metadata about available maps and generation time.
    """
    # Cache for configured duration - runs list changes as new runs are generated
    response.headers["Cache-Control"] = f"public, max-age={settings.cache_runs_list_seconds}"
    
    images_path = Path(settings.storage_path)
    
    if not images_path.exists():
        return GFSRunListResponse(runs=[], total_runs=0)
    
    # Parse all image filenames to extract unique run times
    image_files = list(images_path.glob(f"{model.lower()}_*.png"))
    
    if not image_files:
        return GFSRunListResponse(runs=[], total_runs=0)
    
    # Extract unique run times and count maps per run
    run_data = {}  # {run_time_str: {'count': int, 'latest_mtime': float}}
    
    for img in image_files:
        try:
            parts = img.stem.split('_')
            if len(parts) >= 3:
                run_time_str = f"{parts[1]}_{parts[2]}"  # e.g., "20260124_00"
                
                if run_time_str not in run_data:
                    run_data[run_time_str] = {'count': 0, 'latest_mtime': 0}
                
                run_data[run_time_str]['count'] += 1
                mtime = img.stat().st_mtime
                if mtime > run_data[run_time_str]['latest_mtime']:
                    run_data[run_time_str]['latest_mtime'] = mtime
        except Exception:
            continue
    
    # Sort run times (newest first) and convert to GFSRun objects
    sorted_runs = sorted(run_data.keys(), reverse=True)
    
    runs = []
    now = datetime.utcnow()
    
    for i, run_time_str in enumerate(sorted_runs):
        try:
            # Parse run time
            run_dt = parse_run_time_from_filename(run_time_str)
            
            # Calculate age
            age_hours = (now - run_dt).total_seconds() / 3600
            
            # Create GFSRun object
            run = GFSRun(
                run_time=run_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                run_time_formatted=format_run_time_label(run_dt),
                date=run_dt.strftime("%Y-%m-%d"),
                hour=run_dt.strftime("%HZ"),
                is_latest=(i == 0),
                maps_count=run_data[run_time_str]['count'],
                generated_at=datetime.fromtimestamp(run_data[run_time_str]['latest_mtime']).isoformat(),
                age_hours=round(age_hours, 1)
            )
            runs.append(run)
        except Exception as e:
            logger.warning(f"Failed to parse run {run_time_str}: {e}")
            continue
    
    return GFSRunListResponse(runs=runs, total_runs=len(runs))


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
async def get_image(
    filename: str,
    if_none_match: Optional[str] = Header(None)
):
    """
    Get map image file with proper caching headers.
    
    - Images are immutable once created (filename includes timestamp)
    - Cache for configured duration (default: 7 days, maps are historical data)
    - Support ETag for efficient cache validation
    """
    images_path = Path(settings.storage_path)
    image_file = images_path / filename
    
    if not image_file.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    
    # Generate ETag from file modification time and size (if enabled)
    stat = image_file.stat()
    etag = f'"{stat.st_mtime}-{stat.st_size}"' if settings.enable_etag else None
    
    # Check if client has valid cached version
    if etag and if_none_match and if_none_match == etag:
        from fastapi.responses import Response
        return Response(status_code=304)  # Not Modified
    
    # Calculate expiration date
    expires = (datetime.utcnow().replace(tzinfo=None) + 
               timedelta(seconds=settings.cache_images_seconds)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    headers = {
        "Cache-Control": f"public, max-age={settings.cache_images_seconds}, immutable",
        "Expires": expires
    }
    
    if etag:
        headers["ETag"] = etag
    
    return FileResponse(
        path=str(image_file),
        media_type="image/png",
        filename=filename,
        headers=headers
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
