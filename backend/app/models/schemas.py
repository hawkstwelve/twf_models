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


class GFSRun(BaseModel):
    """Information about a GFS model run"""
    run_time: str  # ISO format: "2026-01-24T00:00:00Z"
    run_time_formatted: str  # Human readable: "00Z Jan 24"
    date: str  # "2026-01-24"
    hour: str  # "00Z"
    is_latest: bool
    maps_count: int
    generated_at: str  # ISO format
    age_hours: float  # Hours since run time


class GFSRunListResponse(BaseModel):
    """Response for GFS runs list endpoint"""
    runs: List[GFSRun]
    total_runs: int


class ModelInfo(BaseModel):
    """Information about a weather model"""
    id: str  # e.g., "GFS", "AIGFS"
    name: str  # e.g., "GFS"
    full_name: str  # e.g., "Global Forecast System"
    description: str
    resolution: str  # e.g., "0.25"
    max_forecast_hour: int
    forecast_increment: int
    run_hours: List[int]
    excluded_variables: List[str]
    color: str  # Hex color code
    enabled: bool
    # Optional detailed fields
    provider: Optional[str] = None  # e.g., "NOMADS"
    has_refc: Optional[bool] = None
    has_upper_air: Optional[bool] = None
    has_precip_type_masks: Optional[bool] = None  # True if model has CSNOW, CRAIN, etc.


class ModelListResponse(BaseModel):
    """Response for models list endpoint"""
    models: List[ModelInfo]
