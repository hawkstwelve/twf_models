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
    
    # Storage
    storage_path: str = "./images"
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
    max_forecast_hour: int = 120
    forecast_hours: str = "0,24,48,72"  # Key forecast hours for initial release
    
    # Map Generation
    map_width: int = 1920
    map_height: int = 1080
    map_dpi: int = 150
    map_region: str = "pnw"  # pnw (Pacific Northwest: WA, OR, ID), us, global, custom
    # PNW boundaries: approximately -125 to -110 longitude, 42 to 49 latitude
    map_region_bounds: Optional[dict] = None  # Will be set for PNW
    
    # Logging
    log_level: str = "INFO"
    log_file: Optional[str] = None
    
    # Security
    admin_api_key: Optional[str] = None
    
    @property
    def forecast_hours_list(self) -> List[int]:
        """Parse forecast hours string into list"""
        return [int(h.strip()) for h in self.forecast_hours.split(",")]
    
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
