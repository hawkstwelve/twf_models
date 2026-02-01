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
        
        # Variable name mapping (canonical names only → Herbie search strings)
        # Herbie uses GRIB2 search patterns (e.g., "TMP:2 m", "UGRD:10 m")
        # Be specific to avoid pulling extra levels (e.g., ":2 m" not just "TMP")
        # CANONICAL NAMES: One name per variable for clarity and consistency
        self._variable_map = {
            # Surface fields
            'tmp2m': ':TMP:2 m',
            'dpt2m': ':DPT:2 m',
            'ugrd10m': ':UGRD:10 m',
            'vgrd10m': ':VGRD:10 m',
            'prmsl': ':PRMSL:mean sea level',
            'tp': ':APCP:surface',
            'prate': ':PRATE:surface',
            'refc': ':REFC:entire atmosphere',
            'asnow': ':ASNOW:surface',
            'crain': ':CRAIN:surface',
            'csnow': ':CSNOW:surface',
            'cicep': ':CICEP:surface',
            'cfrzr': ':CFRZR:surface',
            # Geopotential height
            'gh_500': ':HGT:500 mb',
            'gh_1000': ':HGT:1000 mb',
            # Upper air fields (850mb)
            'tmp_850': ':TMP:850 mb',
            'ugrd_850': ':UGRD:850 mb',
            'vgrd_850': ':VGRD:850 mb',
        }
        
        # Data source priority (fallback order)
        self.priority_sources = ['aws', 'nomads', 'google', 'azure']
        
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
    
    def _build_search_string(self, raw_fields: Set[str], forecast_hour: Optional[int] = None) -> str:
        """
        Build Herbie search string from raw field names.
        
        Herbie uses regex patterns to match GRIB2 variables.
        Multiple variables can be combined with | (OR operator).
        
        Example: "TMP:2 m|UGRD:10 m|VGRD:10 m"
        """
        search_patterns = []
        
        for field in raw_fields:
            pattern = self._variable_map.get(field)
            # Bucketed APCP to avoid double-counting for models with bucketed precip
            if (
                field == "apcp"
                and forecast_hour is not None
                and forecast_hour > 0
                and not self.model_config.tp_is_accumulated_from_init
            ):
                increment = self.model_config.forecast_increment
                bucket_start = max(forecast_hour - increment, 0)
                bucket_pattern = f":APCP:surface:{bucket_start}-{forecast_hour} hour acc fcst"
                pattern = bucket_pattern
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
            
            # Get product from model config (e.g., "pgrb2.0p25" for GFS, "sfc" for HRRR)
            product = getattr(self.model_config, 'herbie_product', None)
            logger.debug(f"  Model config herbie_product: {product}")
            
            # Build Herbie initialization parameters
            herbie_params = {
                'date': run_time_naive,
                'model': herbie_model,
                'fxx': forecast_hour,
                'save_dir': str(self.herbie_save_dir),
                'overwrite': False,  # Don't re-download existing files
                'priority': self.priority_sources,  # Multi-source fallback
                'verbose': False
            }
            
            # Add product if specified in model config (must be before Herbie creation)
            if product:
                herbie_params['product'] = product
                logger.info(f"  Herbie product parameter: {product}")
            else:
                logger.warning(f"  No herbie_product specified for {self.model_id}, using Herbie default")
            
            logger.debug(f"  Herbie params: {herbie_params}")
            H = self.Herbie(**herbie_params)
            
            # Build search string for variable subsetting
            search_string = self._build_search_string(raw_fields, forecast_hour)
            
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
                ds = self._subset_dataset(ds)
                logger.info(f"  ✓ Subset to region: {dict(ds.dims)}")
            
            # Rename variables to our standard names
            ds = self._standardize_variable_names(ds)

            # HRRR ASNOW/APCP can come back as an unnamed/unknown variable
            # Ensure it matches requested raw_fields for pipeline contract
            if 'unknown' in ds:
                if 'asnow' in raw_fields and 'asnow' not in ds:
                    ds = ds.rename({'unknown': 'asnow'})
                    logger.debug("Renamed 'unknown' variable to 'asnow' for HRRR")
                elif 'apcp' in raw_fields and 'apcp' not in ds and 'APCP_surface' not in ds and 'tp' not in ds:
                    ds = ds.rename({'unknown': 'apcp'})
                    logger.debug("Renamed 'unknown' variable to 'apcp' for HRRR")
            
            # Select specific pressure levels and remove extra dimensions
            ds = self._select_pressure_levels(ds)
            
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
        We need to rename them to match our standard names with underscores.
        """
        # Herbie/GRIB2 → Canonical name mappings
        # Convert all variations to our single canonical form
        rename_map = {
            # Herbie's native short names → canonical
            't2m': 'tmp2m',
            'd2m': 'dpt2m',
            'u10': 'ugrd10m',
            'v10': 'vgrd10m',
            'msl': 'prmsl',
            't': 'tmp_850',
            'u': 'ugrd_850',
            'v': 'vgrd_850',
            # Legacy naming variations → canonical
            'tmp850': 'tmp_850',
            'ugrd850': 'ugrd_850',
            'vgrd850': 'vgrd_850',
            'apcp': 'tp',
            'gh500': 'gh_500',
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
    
    def _select_pressure_levels(self, ds: xr.Dataset) -> xr.Dataset:
        """
        Select specific pressure levels for upper air variables and remove extra dimensions.
        
        When requesting specific pressure levels (e.g., 850mb), the data may still have
        an isobaricInhPa dimension. This method selects the correct level and squeezes
        out the dimension to return 2D (lat, lon) arrays.
        """
        import xarray as xr
        
        # Check if isobaricInhPa dimension exists
        if 'isobaricInhPa' not in ds.dims:
            return ds
        
        # Map variables to their expected pressure levels (in hPa)
        level_map = {
            'tmp_850': 850,
            'ugrd_850': 850,
            'vgrd_850': 850,
            'gh500': 500,
        }
        
        # Process each variable that needs level selection
        vars_to_process = []
        for var_name, level in level_map.items():
            if var_name in ds.data_vars:
                if 'isobaricInhPa' in ds[var_name].dims:
                    vars_to_process.append((var_name, level))
        
        if not vars_to_process:
            return ds
        
        # Select levels for each variable
        for var_name, level in vars_to_process:
            if level in ds['isobaricInhPa'].values:
                # Select the specific level and drop the dimension
                ds[var_name] = ds[var_name].sel(isobaricInhPa=level, drop=True)
                logger.debug(f"Selected {level}mb for {var_name}, dropped isobaricInhPa dimension")
            else:
                logger.warning(f"Level {level}mb not found for {var_name}, available: {ds['isobaricInhPa'].values}")
        
        # If no variables still use isobaricInhPa, drop it as a coordinate
        vars_with_level = [v for v in ds.data_vars if 'isobaricInhPa' in ds[v].dims]
        if not vars_with_level and 'isobaricInhPa' in ds.coords:
            ds = ds.drop_vars('isobaricInhPa')
            logger.debug("Dropped isobaricInhPa coordinate (no variables use it)")
        
        return ds
    
    
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
