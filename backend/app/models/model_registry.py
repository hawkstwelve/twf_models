"""Model Registry - Central configuration for all weather models"""
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum


class ModelProvider(Enum):
    """Model data providers"""
    NOMADS = "nomads"
    AWS = "aws"
    ECMWF = "ecmwf"
    CUSTOM = "custom"


class URLLayout(Enum):
    """Known NOMADS URL directory layouts"""
    GFS_STANDARD = "gfs_standard"  # .../gfs.{date}/{hour}/atmos/...
    AIGFS_EXTENDED = "aigfs_extended"  # .../aigfs.{date}/{hour}/model/atmos/grib2/...
    HRRR_STYLE = "hrrr_style"  # .../hrrr.{date}/conus/...


@dataclass
class ProductPattern:
    """Pattern for a specific GRIB product (surface, pressure levels, etc.)"""
    name: str  # "sfc", "pres", "analysis"
    file_pattern: str  # e.g., "gfs.t{run_hour}z.pgrb2.0p25.f{forecast_hour}"
    filter_script: Optional[str] = None  # e.g., "filter_gfs_0p25.pl"
    

@dataclass
class ModelConfig:
    """Configuration for a weather model"""
    id: str
    name: str
    full_name: str
    description: str
    provider: ModelProvider
    
    # Data fetcher configuration
    fetcher_type: Optional[str] = None  # "nomads", "herbie", None=auto-detect from provider
    
    # NOMADS URL structure
    nomads_base_path: str = ""  # e.g., "gfs/prod" or "aigfs/prod"
    url_layout: Optional[URLLayout] = None  # Which directory pattern
    subdir_template: str = ""  # e.g., "{model}.{date}/{hour}/atmos" or "{model}.{date}/{hour}/model/atmos/grib2"
    
    # Products (multiple GRIB files per forecast time)
    products: Dict[str, ProductPattern] = field(default_factory=dict)
    
    # Analysis file handling
    has_analysis_file: bool = True  # Does f000 use "anl" instead of "f000"?
    analysis_pattern: Optional[str] = None  # e.g., "gfs.t{run_hour}z.pgrb2.0p25.anl"
    
    # Model characteristics
    resolution: str = "0.25"
    run_hours: List[int] = field(default_factory=lambda: [0, 6, 12, 18])
    max_forecast_hour: int = 384
    forecast_increment: int = 6  # Hours between forecasts
    
    # Data availability
    availability_delay_hours: float = 3.5  # Hours after run time before data available
    
    # Capabilities (explicit feature flags)
    has_refc: bool = True  # Radar reflectivity field
    has_precip_type_masks: bool = True  # crain, csnow, cicep, cfrzr
    has_upper_air: bool = True  # 850mb, 500mb, etc.
    tp_is_accumulated_from_init: bool = False  # True = cumulative, False = bucketed
    products_supported: Set[str] = field(default_factory=lambda: {"sfc", "pres"})
    
    # Variable exclusions (high-level)
    excluded_variables: List[str] = field(default_factory=list)
    
    # Processing options
    use_filter: bool = True
    timeout: int = 120
    max_retries: int = 3
    
    # Display options
    color: str = "#1E90FF"
    enabled: bool = True


class ModelRegistry:
    """Registry of all available weather models"""
    
    _models: Dict[str, ModelConfig] = {}
    
    @classmethod
    def register(cls, config: ModelConfig):
        """Register a model"""
        cls._models[config.id] = config
    
    @classmethod
    def get(cls, model_id: str) -> Optional[ModelConfig]:
        """Get model config by ID"""
        return cls._models.get(model_id)
    
    @classmethod
    def get_all(cls) -> Dict[str, ModelConfig]:
        """Get all registered models"""
        return cls._models.copy()
    
    @classmethod
    def get_enabled(cls) -> Dict[str, ModelConfig]:
        """Get only enabled models"""
        return {k: v for k, v in cls._models.items() if v.enabled}
    
    @classmethod
    def supports_variable(cls, model_id: str, variable: str) -> bool:
        """Check if a model supports a specific variable"""
        model = cls.get(model_id)
        if not model:
            return False
        return variable not in model.excluded_variables
    
    @classmethod
    def get_variables_for_model(cls, model_id: str, all_variables: List[str]) -> List[str]:
        """Get list of variables supported by a model"""
        model = cls.get(model_id)
        if not model:
            return []
        return [v for v in all_variables if v not in model.excluded_variables]


# ============================================================================
# MODEL REGISTRATIONS
# ============================================================================

# Register GFS Model
ModelRegistry.register(ModelConfig(
    id="GFS",
    name="GFS",
    full_name="Global Forecast System",
    description="NOAA's global weather model",
    provider=ModelProvider.NOMADS,
    fetcher_type="herbie",  # Use Herbie for robust GRIB handling (analysis + forecast)
    # NOMADS fields kept for reference but Herbie handles downloads
    nomads_base_path="gfs/prod",
    url_layout=URLLayout.GFS_STANDARD,
    subdir_template="gfs.{date}/{hour}/atmos",
    products={
        "sfc": ProductPattern(
            name="sfc",
            file_pattern="gfs.t{run_hour}z.pgrb2.0p25.f{forecast_hour}",
            filter_script="filter_gfs_0p25.pl"
        ),
    },
    has_analysis_file=True,
    analysis_pattern="gfs.t{run_hour}z.pgrb2.0p25.anl",
    resolution="0.25",
    max_forecast_hour=384,
    forecast_increment=6,
    availability_delay_hours=3.5,
    has_refc=True,
    has_precip_type_masks=True,
    has_upper_air=True,
    tp_is_accumulated_from_init=False,  # GFS uses bucketed precip
    products_supported={"sfc"},
    excluded_variables=[],
    color="#1E90FF",
    enabled=True
))

# Register AIGFS Model
ModelRegistry.register(ModelConfig(
    id="AIGFS",
    name="AIGFS",
    full_name="Artificial Intelligence Global Forecast System",
    description="NOAA's AI-enhanced global forecast model",
    provider=ModelProvider.NOMADS,
    nomads_base_path="aigfs/prod",
    url_layout=URLLayout.AIGFS_EXTENDED,
    subdir_template="aigfs.{date}/{hour}/model/atmos/grib2",
    products={
        "sfc": ProductPattern(
            name="sfc",
            file_pattern="aigfs.t{run_hour}z.sfc.f{forecast_hour}.grib2",
            filter_script=None  # No filter script exists for AIGFS
        ),
        "pres": ProductPattern(
            name="pres",
            file_pattern="aigfs.t{run_hour}z.pres.f{forecast_hour}.grib2",
            filter_script=None  # No filter script exists for AIGFS
        ),
    },
    has_analysis_file=True,
    analysis_pattern="aigfs.t{run_hour}z.sfc.f000.grib2",  # AIGFS uses f000 in sfc product
    resolution="0.25",
    run_hours=[0, 6, 12, 18],  # Explicitly set run hours
    max_forecast_hour=384,
    forecast_increment=6,
    availability_delay_hours=3.5,
    has_refc=False,  # No radar
    has_precip_type_masks=False,  # No CSNOW - must derive from temperature
    has_upper_air=True,
    tp_is_accumulated_from_init=False,  # Assume same as GFS (verify!)
    products_supported={"sfc", "pres"},
    excluded_variables=["radar", "radar_reflectivity"],
    use_filter=False,  # AIGFS filter script doesn't exist on NOMADS - download full files
    color="#4169E1",
    enabled=True
))

# Register HRRR Model (Herbie-based example - disabled for now)
ModelRegistry.register(ModelConfig(
    id="HRRR",
    name="HRRR",
    full_name="High-Resolution Rapid Refresh",
    description="NOAA's high-resolution short-range model",
    provider=ModelProvider.NOMADS,
    fetcher_type="herbie",  # Use Herbie instead of NOMADS fetcher
    # NOMADS fields optional when using Herbie
    nomads_base_path="hrrr/prod",
    url_layout=URLLayout.HRRR_STYLE,
    subdir_template="hrrr.{date}/conus",
    products={
        "2d": ProductPattern(
            name="2d",
            file_pattern="hrrr.t{run_hour}z.wrfprsf{forecast_hour}.grib2",
            filter_script="filter_hrrr_2d.pl"
        ),
    },
    has_analysis_file=False,  # HRRR has f00
    resolution="3km",
    run_hours=list(range(24)),  # Hourly runs
    max_forecast_hour=48,
    forecast_increment=1,  # Hourly forecasts
    availability_delay_hours=1.0,
    has_refc=True,
    has_precip_type_masks=False,  # HRRR may not have categorical types
    has_upper_air=False,  # HRRR is primarily surface
    tp_is_accumulated_from_init=False,
    products_supported={"2d"},
    excluded_variables=["temp_850_wind_mslp"],
    color="#FF6347",
    enabled=True  # Enabled: MapGenerator now supports 2D coordinates
))
