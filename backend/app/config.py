"""Application configuration"""
from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    """Application settings"""
    
    # Data Sources
    data_source: str = "GFS"
    gfs_source: str = "aws"  # aws or nomads
    gfs_resolution: str = "0p25"  # 0p25 (0.25°, high-res) or 0p50 (0.5°, standard)
    graphcast_api_key: Optional[str] = None
    
    # NOMADS-specific settings
    nomads_use_filter: bool = True  # Use NOMADS filter to download only needed variables/region
    nomads_timeout: int = 120  # Timeout in seconds for NOMADS downloads
    nomads_max_retries: int = 3  # Number of retries for failed downloads
    
    # Storage
    storage_path: str = "/opt/twf_models/backend/app/static/images"  # Absolute path for production
    storage_type: str = "local"  # local, s3, spaces
    
    # AWS/DO Spaces
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_region: str = "us-east-1"
    s3_bucket: Optional[str] = None
    
    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api"
    cors_origins: str = "https://theweatherforums.com,http://localhost:3000"
    
    # Processing
    update_interval: int = 6  # hours
    max_forecast_hour: int = 384
    # Recommended: 3h increments to 120h (short-range detail), 6h increments to 384h (extended range)
    # For 32GB/12vCPU server: Can handle ~64 forecast hours efficiently with parallel generation
    forecast_hours: str = "0,3,6,9,12,15,18,21,24,27,30,33,36,39,42,45,48,51,54,57,60,63,66,69,72,75,78,81,84,87,90,93,96,99,102,105,108,111,114,117,120,126,132,138,144,150,156,162,168,174,180,186,192,198,204,210,216,222,228,234,240,246,252,258,264,270,276,282,288,294,300,306,312,318,324,330,336,342,348,354,360,366,372,378,384"  # 3h to 120h, then 6h to 384h
    # HRRR-specific: Hourly forecasts (short-range high-resolution model)
    hrrr_forecast_hours: str = "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48"  # 1h increments to f48
    progressive_generation: bool = True  # Generate by forecast hour (f000 first) vs by variable
    
    # Map Generation
    map_width: int = 1920
    map_height: int = 1080
    map_dpi: int = 150
    map_region: str = "pnw"  # pnw (Pacific Northwest: WA, OR, ID), us, global, custom
    # PNW boundaries: approximately -125 to -110 longitude, 42 to 49 latitude
    map_region_bounds: Optional[dict] = None  # Will be set for PNW
    station_overlays: bool = True  # Show station values on maps
    station_priority: int = 2  # 1=major cities only, 2=+secondary, 3=all stations
    
    # Logging
    log_level: str = "INFO"
    log_file: Optional[str] = None
    
    # Security
    admin_api_key: Optional[str] = None
    
    # HTTP Caching
    cache_images_seconds: int = 604800  # 7 days - images are immutable
    cache_maps_list_seconds: int = 300  # 5 minutes - list changes as new maps generate
    cache_runs_list_seconds: int = 300  # 5 minutes - runs list changes as new runs generate
    enable_etag: bool = True  # Enable ETag support for conditional requests
    
    @property
    def forecast_hours_list(self) -> List[int]:
        """Parse forecast hours string into list"""
        return [int(h.strip()) for h in self.forecast_hours.split(",")]
    
    @property
    def hrrr_forecast_hours_list(self) -> List[int]:
        """Parse HRRR-specific forecast hours string into list"""
        return [int(h.strip()) for h in self.hrrr_forecast_hours.split(",")]
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins string into list"""
        return [origin.strip() for origin in self.cors_origins.split(",")]
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Set PNW region bounds if not specified
        if self.map_region == "pnw" and self.map_region_bounds is None:
            self.map_region_bounds = {
                "west": -125.0,  # Western boundary (Pacific coast)
                "east": -110.0,  # Eastern boundary (eastern ID)
                "south": 42.0,   # Southern boundary (southern OR)
                "north": 49.0    # Northern boundary (northern WA/Canada border)
            }
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
