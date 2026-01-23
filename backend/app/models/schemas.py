"""Pydantic schemas for API"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class MapInfo(BaseModel):
    """Map information"""
    id: str
    model: str
    run_time: str
    forecast_hour: int
    variable: str
    image_url: str
    created_at: str
    file_size: Optional[int] = None
    units: Optional[str] = None
    valid_time: Optional[str] = None


class MapListResponse(BaseModel):
    """Response for map list endpoint"""
    maps: List[MapInfo]


class UpdateResponse(BaseModel):
    """Response for update trigger"""
    status: str
    job_id: str
    message: Optional[str] = None
