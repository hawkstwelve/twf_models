"""Herbie-based data fetcher for weather models"""
from datetime import datetime
from pathlib import Path
from typing import Optional, Set
import xarray as xr
import logging

from app.services.base_data_fetcher import BaseDataFetcher
from app.config import settings

logger = logging.getLogger(__name__)


class HerbieDataFetcher(BaseDataFetcher):
    """
    Data fetcher using Herbie library for multi-source weather data access.
    
    Provides:
    - Multi-source fallback (NOMADS → AWS → Google → Azure)
    - Byte-range HTTP subsetting (download only needed variables)
    - Progressive data monitoring (HerbieWait)
    - Support for 15+ weather models (HRRR, RAP, ECMWF, etc.)
    
    Maintains compatibility with BaseDataFetcher interface.
    """
    
    def __init__(self, model_id: str):
        """Initialize Herbie fetcher for a specific model"""
        super().__init__(model_id)
        
        # Check if Herbie is installed
        try:
            from herbie import Herbie, HerbieWait
            self.Herbie = Herbie
            self.HerbieWait = HerbieWait
        except ImportError:
            raise ImportError(
                "Herbie library not installed. Install with:\n"
                "  pip install herbie-data\n"
                "Note: Ensure numpy<2.0 compatibility if using scipy/matplotlib"
            )
        
        # Herbie cache configuration (CRITICAL for production)
        # Must be persistent, shared across workers, and not auto-deleted
        self.herbie_save_dir = Path(settings.storage_path).parent / "herbie_cache" / f"{model_id.lower()}"
        self.herbie_save_dir.mkdir(parents=True, exist_ok=True)
        
        # Model name mapping (your model_id → Herbie model name)
        # Note: AIGFS is NOT supported by Herbie yet (as of 2026.1.0)
        # AIGFS will continue using NOMADSDataFetcher
        self._herbie_model_map = {
            "GFS": "gfs",
            "HRRR": "hrrr",
            "RAP": "rap",
            "NAM": "nam",
            "ECMWF": "ecmwf",
        }
        
        # Variable name mapping (your names → Herbie search strings)
        # Herbie uses GRIB2 search patterns (e.g., "TMP:2 m", "UGRD:10 m")
        # Be specific to avoid pulling extra levels (e.g., ":2 m" not just "TMP")
        self._variable_map = {
            'tmp2m': ':TMP:2 m',
            'dpt2m': ':DPT:2 m',
            'ugrd10m': ':UGRD:10 m',
            'vgrd10m': ':VGRD:10 m',
            'prmsl': ':PRMSL:mean sea level',
            'tp': ':APCP:surface',  # Accumulated precipitation
            'prate': ':PRATE:surface',  # Precipitation rate
            'refc': ':REFC:entire atmosphere',  # Composite reflectivity
            'crain': ':CRAIN:surface',
            'csnow': ':CSNOW:surface',
            'cicep': ':CICEP:surface',
            'cfrzr': ':CFRZR:surface',
            'gh500': ':HGT:500 mb',
            'tmp850': ':TMP:850 mb',
            'ugrd850': ':UGRD:850 mb',
            'vgrd850': ':VGRD:850 mb',
        }
        
        # Data source priority (fallback order)
        self.priority_sources = ['nomads', 'aws', 'google', 'azure']
        
        logger.info(f"HerbieDataFetcher initialized for {model_id}")
        logger.info(f"  Cache directory: {self.herbie_save_dir}")
        logger.info(f"  Multi-source priority: {' → '.join(self.priority_sources)}")
    
    def _get_herbie_model_name(self) -> str:
        """Get Herbie model name from model_id"""
        herbie_name = self._herbie_model_map.get(self.model_id)
        if not herbie_name:
            raise ValueError(
                f"Model {self.model_id} not mapped to Herbie model name. "
                f"Available: {list(self._herbie_model_map.keys())}"
            )
        return herbie_name
    
    def _build_search_string(self, raw_fields: Set[str]) -> str:
        """
        Build Herbie search string from raw field names.
        
        Herbie uses regex patterns to match GRIB2 variables.
        Multiple variables can be combined with | (OR operator).
        
        Example: "TMP:2 m|UGRD:10 m|VGRD:10 m"
        """
        search_patterns = []
        
        for field in raw_fields:
            pattern = self._variable_map.get(field)
            if pattern:
                search_patterns.append(pattern)
            else:
                logger.warning(f"No Herbie mapping for field: {field}")
        
        if not search_patterns:
            raise ValueError(f"No valid Herbie search patterns for fields: {raw_fields}")
        
        # Combine with OR operator
        search_string = "|".join(search_patterns)
        logger.debug(f"Herbie search string: {search_string}")
        
        return search_string
    
    def fetch_raw_data(
        self,
        run_time: datetime,
        forecast_hour: int,
        raw_fields: Set[str],
        subset_region: bool = True
    ) -> xr.Dataset:
        """
        Fetch raw GRIB fields using Herbie.
        
        This method:
        1. Creates a Herbie object for the specified run/forecast
        2. Uses byte-range requests to download only needed variables
        3. Converts to xarray Dataset
        4. Applies regional subsetting if requested
        
        Args:
            run_time: Model run time (datetime)
            forecast_hour: Forecast hour (0-384)
            raw_fields: Set of raw GRIB variable names
            subset_region: Whether to subset to US region
        
        Returns:
            xr.Dataset with requested variables
        """
        logger.info(f"Fetching {self.model_id} data via Herbie:")
        logger.info(f"  Run: {run_time.strftime('%Y-%m-%d %H:%M')} UTC")
        logger.info(f"  Forecast hour: f{forecast_hour:03d}")
        logger.info(f"  Variables: {raw_fields}")
        
        try:
            # Create Herbie object
            herbie_model = self._get_herbie_model_name()
            
            # Herbie expects timezone-naive datetime
            run_time_naive = run_time.replace(tzinfo=None) if run_time.tzinfo else run_time
            
            H = self.Herbie(
                date=run_time_naive,
                model=herbie_model,
                fxx=forecast_hour,
                # CRITICAL: Production configuration
                save_dir=str(self.herbie_save_dir),
                overwrite=False,  # Don't re-download existing files
                priority=self.priority_sources,  # Multi-source fallback
                verbose=False
            )
            
            # Build search string for variable subsetting
            search_string = self._build_search_string(raw_fields)
            
            # Download and convert to xarray
            # Herbie uses byte-range requests to download only matching variables
            logger.info(f"  Downloading via Herbie (byte-range subsetting)...")
            ds = H.xarray(
                search_string,
                remove_grib=False  # CRITICAL: Keep GRIB files for caching
            )
            
            # Herbie may return a list of datasets if multiple matches
            # Merge them into a single dataset
            if isinstance(ds, list):
                if len(ds) == 0:
                    raise ValueError(f"No data returned for search: {search_string}")
                elif len(ds) == 1:
                    ds = ds[0]
                else:
                    import xarray as xr
                    # Use compat='override' to handle conflicting coordinates (e.g., different heightAboveGround values)
                    ds = xr.merge(ds, compat='override')
            
            logger.info(f"  ✓ Downloaded {len(ds.data_vars)} variables")
            logger.info(f"    Size: ~{ds.nbytes / (1024**2):.1f} MB in memory")
            
            # Apply regional subsetting if requested
            if subset_region:
                ds = self._subset_to_region(ds)
                logger.info(f"  ✓ Subset to region: {dict(ds.dims)}")
            
            # Rename variables to our standard names
            ds = self._standardize_variable_names(ds)
            
            return ds
            
        except Exception as e:
            logger.error(f"Herbie fetch failed: {e}")
            logger.error(f"  Model: {self.model_id}")
            logger.error(f"  Run: {run_time}")
            logger.error(f"  Forecast: f{forecast_hour:03d}")
            logger.error(f"  Fields: {raw_fields}")
            raise
    
    def _standardize_variable_names(self, ds: xr.Dataset) -> xr.Dataset:
        """
        Standardize Herbie variable names to our naming convention.
        
        Herbie may return variables with GRIB2 naming (e.g., "t2m", "u10", "v10")
        We need to rename them to match our standard names (tmp2m, ugrd10m, etc.)
        """
        # Common Herbie → Standard name mappings
        rename_map = {
            't2m': 'tmp2m',
            'd2m': 'dpt2m',
            'u10': 'ugrd10m',
            'v10': 'vgrd10m',
            'msl': 'prmsl',
            'tp': 'tp',
            'refc': 'refc',
            't': 'tmp850',  # May need level-specific handling
            'u': 'ugrd850',
            'v': 'vgrd850',
            'gh': 'gh500',
        }
        
        # Find which variables exist and need renaming
        vars_to_rename = {}
        for herbie_name, standard_name in rename_map.items():
            if herbie_name in ds:
                vars_to_rename[herbie_name] = standard_name
        
        if vars_to_rename:
            ds = ds.rename(vars_to_rename)
            logger.debug(f"Renamed variables: {vars_to_rename}")
        
        return ds
    
    def _subset_to_region(self, ds: xr.Dataset) -> xr.Dataset:
        """
        Subset dataset to US region.
        
        Handles both 1D coordinates (GFS) and 2D coordinates (HRRR).
        Uses same logic as NOMADSDataFetcher for consistency.
        """
        # US region bounds (same as NOMADS fetcher)
        lat_min, lat_max = 20.0, 55.0
        lon_min, lon_max = -130.0, -60.0
        
        # Detect coordinate names (Herbie may use different names)
        lat_coord = None
        lon_coord = None
        
        for coord in ['latitude', 'lat', 'y']:
            if coord in ds.coords:
                lat_coord = coord
                break
        
        for coord in ['longitude', 'lon', 'x']:
            if coord in ds.coords:
                lon_coord = coord
                break
        
        if not lat_coord or not lon_coord:
            logger.warning(f"Could not find lat/lon coordinates in dataset: {list(ds.coords)}")
            return ds
        
        # Check if coordinates are 1D or 2D
        lat_dims = len(ds[lat_coord].dims)
        lon_dims = len(ds[lon_coord].dims)
        
        if lat_dims == 2 and lon_dims == 2:
            # 2D coordinates (HRRR) - use where() for boolean indexing
            logger.debug("Using 2D coordinate subsetting (HRRR-style)")
            
            # Handle longitude wrapping (0-360 vs -180-180)
            lon_vals = ds[lon_coord].values
            if lon_vals.min() >= 0:  # 0-360 format
                lon_min_adj = lon_min + 360
                lon_max_adj = lon_max + 360
            else:
                lon_min_adj = lon_min
                lon_max_adj = lon_max
            
            # Create boolean mask for region
            mask = (
                (ds[lat_coord] >= lat_min) & 
                (ds[lat_coord] <= lat_max) &
                (ds[lon_coord] >= lon_min_adj) & 
                (ds[lon_coord] <= lon_max_adj)
            )
            
            # For 2D coords, we need to find the bounding box in grid space
            # Get the indices where mask is True
            import numpy as np
            indices = np.where(mask.values)
            if len(indices[0]) == 0:
                logger.warning("No data points in specified region")
                return ds
            
            # Find bounding box in grid coordinates
            y_min, y_max = indices[0].min(), indices[0].max()
            x_min, x_max = indices[1].min(), indices[1].max()
            
            # Subset using isel (index-based selection)
            ds_subset = ds.isel({ds[lat_coord].dims[0]: slice(y_min, y_max+1),
                                 ds[lat_coord].dims[1]: slice(x_min, x_max+1)})
            
        else:
            # 1D coordinates (GFS) - use sel() for label-based selection
            logger.debug("Using 1D coordinate subsetting (GFS-style)")
            
            # Handle longitude wrapping (0-360 vs -180-180)
            lon_vals = ds[lon_coord].values
            if lon_vals.min() >= 0:  # 0-360 format
                lon_min_adj = lon_min + 360
                lon_max_adj = lon_max + 360
            else:
                lon_min_adj = lon_min
                lon_max_adj = lon_max
            
            # Check latitude ordering (GFS is typically descending: 90 to -90)
            lat_vals = ds[lat_coord].values
            lat_ascending = lat_vals[0] < lat_vals[-1]
            
            if lat_ascending:
                # Ascending latitude (south to north)
                lat_slice = slice(lat_min, lat_max)
            else:
                # Descending latitude (north to south) - REVERSE the slice
                lat_slice = slice(lat_max, lat_min)
            
            logger.debug(f"Latitude order: {'ascending' if lat_ascending else 'descending'}")
            logger.debug(f"Subsetting: lat={lat_slice}, lon=slice({lon_min_adj}, {lon_max_adj})")
            
            # Apply subset
            ds_subset = ds.sel(
                {lat_coord: lat_slice,
                 lon_coord: slice(lon_min_adj, lon_max_adj)}
            )
        
        return ds_subset
    
    def wait_for_data(
        self,
        run_time: datetime,
        forecast_hour: int,
        max_wait_minutes: int = 120,
        check_interval_seconds: int = 60
    ) -> bool:
        """
        Wait for data to become available using HerbieWait.
        
        This replaces custom polling logic with Herbie's built-in progressive monitoring.
        
        Args:
            run_time: Model run time
            forecast_hour: Forecast hour to wait for
            max_wait_minutes: Maximum time to wait
            check_interval_seconds: How often to check
        
        Returns:
            True if data became available, False if timeout
        """
        logger.info(f"Waiting for {self.model_id} f{forecast_hour:03d} data...")
        
        try:
            herbie_model = self._get_herbie_model_name()
            
            H = self.HerbieWait(
                date=run_time,
                model=herbie_model,
                fxx=forecast_hour,
                wait_for='valid',  # Wait for valid GRIB file
                check_interval=check_interval_seconds,
                max_wait_time=max_wait_minutes * 60,
                save_dir=str(self.herbie_save_dir),
                priority=self.priority_sources,
                verbose=True
            )
            
            if H.grib:
                logger.info(f"  ✓ Data available: {H.grib}")
                return True
            else:
                logger.warning(f"  ✗ Data not available after {max_wait_minutes}min")
                return False
                
        except Exception as e:
            logger.error(f"HerbieWait failed: {e}")
            return False
