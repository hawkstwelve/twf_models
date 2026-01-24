"""Weather data fetching service"""
import s3fs
import xarray as xr
from datetime import datetime, timedelta
from pathlib import Path
import logging
from typing import Optional
import tempfile
import os
import time

from app.config import settings

# Type hint alias
Dataset = xr.Dataset

logger = logging.getLogger(__name__)


class GFSDataFetcher:
    """Fetches GFS data from AWS S3 or NOMADS"""
    
    def __init__(self):
        self.s3 = None
        if settings.gfs_source == "aws":
            self.s3 = s3fs.S3FileSystem(
                anon=True,
                client_kwargs={'region_name': 'us-east-1'}
            )
        
        # GRIB file cache to avoid re-downloading same file multiple times
        # Format: {grib_file_path: (local_path, download_time)}
        self._grib_cache = {}
        self._cache_dir = Path(tempfile.gettempdir()) / "gfs_cache"
        self._cache_dir.mkdir(exist_ok=True)
        
        # Cache files for 2 hours (enough for a full run, cleans up after)
        self._cache_max_age_seconds = 2 * 3600
    
    def _cleanup_old_cache(self):
        """Clean up GRIB files older than cache_max_age_seconds"""
        now = time.time()
        to_remove = []
        
        for grib_path, (local_path, download_time) in self._grib_cache.items():
            age = now - download_time
            if age > self._cache_max_age_seconds:
                to_remove.append(grib_path)
                # Remove the physical file
                try:
                    if os.path.exists(local_path):
                        os.remove(local_path)
                        logger.debug(f"Removed old cache file: {local_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove cache file {local_path}: {e}")
        
        # Remove from cache dict
        for grib_path in to_remove:
            del self._grib_cache[grib_path]
            logger.debug(f"Removed from cache: {grib_path}")
    
    def _get_cached_grib_path(self, grib_file_path: str) -> Optional[str]:
        """
        Get path to cached GRIB file, or None if not cached.
        Also cleans up old cache files.
        """
        self._cleanup_old_cache()
        
        if grib_file_path in self._grib_cache:
            local_path, download_time = self._grib_cache[grib_file_path]
            if os.path.exists(local_path):
                age_minutes = (time.time() - download_time) / 60
                logger.info(f"✅ Using cached GRIB file (age: {age_minutes:.1f} minutes)")
                return local_path
            else:
                # File was deleted, remove from cache
                del self._grib_cache[grib_file_path]
        
        return None
    
    def _download_and_cache_grib(self, grib_file_path: str) -> str:
        """
        Download GRIB file and add to cache.
        Returns path to local file.
        """
        # Create a persistent temp file in our cache directory
        file_hash = hash(grib_file_path) % 10000  # Simple hash for unique filename
        local_path = str(self._cache_dir / f"gfs_{file_hash}.grib2")
        
        logger.info(f"Downloading GFS GRIB file to cache...")
        logger.info(f"Cache file: {local_path}")
        
        # Download the file using s3fs.get()
        self.s3.get(grib_file_path, local_path)
        
        # Verify the file was downloaded
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Download completed but cache file not found: {local_path}")
        
        file_size_mb = os.path.getsize(local_path) / 1024 / 1024
        logger.info(f"Downloaded {file_size_mb:.1f} MB file to cache")
        
        # Add to cache
        self._grib_cache[grib_file_path] = (local_path, time.time())
        
        return local_path
    
    def get_latest_run_time(self) -> datetime:
        """Get the latest available GFS run time"""
        # GFS runs at 00, 06, 12, 18 UTC
        # Data is typically available 2-4 hours after run time
        now = datetime.utcnow()
        
        # Try to find the most recent run that's likely available
        # Go back to previous 6-hour cycle to ensure data is available
        run_hour = ((now.hour // 6) * 6) - 6
        if run_hour < 0:
            run_hour = 18
            now = now - timedelta(days=1)
        
        run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
        
        return run_time
    
    def fetch_gfs_data(
        self,
        run_time: Optional[datetime] = None,
        forecast_hour: int = 0,
        variables: Optional[list] = None,
        subset_region: bool = True
    ) -> xr.Dataset:
        """
        Fetch GFS data for specified run time and forecast hour.
        Optimized to fetch only needed variables and region.
        
        Args:
            run_time: GFS run time (defaults to latest)
            forecast_hour: Forecast hour (0, 24, 48, 72, etc.)
            variables: List of variable names to fetch (defaults to our needs)
            subset_region: If True, only fetch PNW region data
        """
        if run_time is None:
            run_time = self.get_latest_run_time()
        
        # Only fetch variables we actually use
        if variables is None:
            # Our current variables: temp, precip, precip_type, wind_speed
            variables = ['tmp2m', 'prate', 'ugrd10m', 'vgrd10m']
        
        date_str = run_time.strftime("%Y%m%d")
        run_hour_str = run_time.strftime("%H")  # Just the hour (00, 06, 12, 18)
        hour_str = f"{forecast_hour:03d}"
        
        if settings.gfs_source == "aws":
            # Try NetCDF files first - much easier to work with than GRIB
            # Path structure: gfs.YYYYMMDD/HH/atmos/gfs.tHHz.atmfFFF.nc
            base_path = f"s3://noaa-gfs-bdp-pds/gfs.{date_str}/{run_hour_str}/atmos"
            nc_file_path = f"{base_path}/gfs.t{run_hour_str}z.atmf{hour_str}.nc"
            # Use configured resolution (0p25 for high-res, 0p50 for standard)
            grib_file_path = f"{base_path}/gfs.t{run_hour_str}z.pgrb2.{settings.gfs_resolution}.f{hour_str}"
            
            logger.info(f"Variables needed: {variables}")
            logger.info(f"Subsetting region: {subset_region}")
            
            # Open the S3 file using s3fs
            if self.s3 is None:
                self.s3 = s3fs.S3FileSystem(
                    anon=True,
                    client_kwargs={'region_name': 'us-east-1'}
                )
            
            # Use GRIB files (NetCDF has SSL issues on droplet)
            # GRIB is reliable and cached for performance
            ds = None
            import cfgrib
            
            logger.info(f"Fetching GFS data from GRIB: {grib_file_path}")
            
            # Check if the GRIB file exists on S3
            logger.info("Checking if GRIB file exists on S3...")
            try:
                if not self.s3.exists(grib_file_path):
                    raise FileNotFoundError(f"GRIB file not found on S3: {grib_file_path}")
                logger.info("✅ GRIB file exists on S3")
            except Exception as e:
                logger.error(f"Failed to check if file exists: {e}")
                raise
            
            # Try to get from cache first, otherwise download
            tmp_path = self._get_cached_grib_path(grib_file_path)
            cache_hit = tmp_path is not None
            
            if not cache_hit:
                tmp_path = self._download_and_cache_grib(grib_file_path)
            
            try:
                # Open each level type separately and extract only the variables we need
                # This avoids coordinate conflicts when merging
                logger.info("Opening GRIB file with cfgrib (opening levels separately to avoid conflicts)...")
                
                all_data_vars = {}
                coords = None
                
                # Try surface level (precipitation and other surface variables)
                # For forecast hours > 0, GRIB files have multiple stepType values
                # We need to try different stepTypes to get all variables
                try:
                    logger.info("Opening surface level...")
                    
                    # Try to open surface level with different stepType filters
                    surface_datasets = []
                    
                    if forecast_hour > 0:
                        # For forecast hours, try both instant and accumulated
                        logger.info("  Forecast hour > 0, trying multiple stepTypes...")
                        
                        # Try instant stepType (most variables)
                        try:
                            ds_surf_instant = xr.open_dataset(
                                tmp_path,
                                engine='cfgrib',
                                backend_kwargs={'filter_by_keys': {
                                    'typeOfLevel': 'surface',
                                    'stepType': 'instant'
                                }},
                                decode_timedelta=False
                            )
                            surface_datasets.append(ds_surf_instant)
                            logger.info(f"    Instant stepType variables: {list(ds_surf_instant.data_vars)}")
                        except Exception as e:
                            logger.info(f"    Instant stepType not available: {str(e)[:80]}")
                        
                        # Try accumulated stepType (precipitation)
                        try:
                            ds_surf_accum = xr.open_dataset(
                                tmp_path,
                                engine='cfgrib',
                                backend_kwargs={'filter_by_keys': {
                                    'typeOfLevel': 'surface',
                                    'stepType': 'accum'
                                }},
                                decode_timedelta=False
                            )
                            surface_datasets.append(ds_surf_accum)
                            logger.info(f"    Accumulated stepType variables: {list(ds_surf_accum.data_vars)}")
                        except Exception as e:
                            logger.info(f"    Accumulated stepType not available: {str(e)[:80]}")
                    else:
                        # Hour 0 (analysis) doesn't have stepType complexity
                        ds_surface = xr.open_dataset(
                            tmp_path,
                            engine='cfgrib',
                            backend_kwargs={'filter_by_keys': {'typeOfLevel': 'surface'}},
                            decode_timedelta=False
                        )
                        surface_datasets.append(ds_surface)
                    
                    # Extract variables from all surface datasets
                    for ds_surf in surface_datasets:
                        for var in ds_surf.data_vars:
                            # Skip if we already have this variable
                            if var in all_data_vars:
                                continue
                            # Drop heightAboveGround coordinate if it exists to avoid conflicts
                            var_data = ds_surf[var].drop_vars(['heightAboveGround'], errors='ignore')
                            all_data_vars[var] = var_data
                        if coords is None:
                            # Get coords but exclude heightAboveGround
                            coords = {k: v for k, v in ds_surf.coords.items() if k != 'heightAboveGround'}
                    
                    if surface_datasets:
                        all_surf_vars = list(set([v for ds in surface_datasets for v in ds.data_vars]))
                        logger.info(f"  Surface variables (combined): {all_surf_vars[:20]}...")
                    else:
                        logger.warning("  No surface data loaded")
                        
                except Exception as e:
                    logger.warning(f"  Surface level failed: {str(e)[:100]}")
                
                # Try 2m height (temperature)
                try:
                    logger.info("Opening 2m heightAboveGround...")
                    ds_2m = xr.open_dataset(
                        tmp_path,
                        engine='cfgrib',
                        backend_kwargs={'filter_by_keys': {'typeOfLevel': 'heightAboveGround', 'level': 2}},
                        decode_timedelta=False  # Avoid timedelta decoding issues
                    )
                    for var in ds_2m.data_vars:
                        # Drop heightAboveGround coordinate to avoid conflicts
                        var_data = ds_2m[var].drop_vars(['heightAboveGround'], errors='ignore')
                        all_data_vars[var] = var_data
                    if coords is None:
                        # Get coords but exclude heightAboveGround
                        coords = {k: v for k, v in ds_2m.coords.items() if k != 'heightAboveGround'}
                    logger.info(f"  2m variables: {list(ds_2m.data_vars)}")
                except Exception as e:
                    logger.warning(f"  2m level failed: {str(e)[:100]}")
                
                # Try 10m height (wind)
                try:
                    logger.info("Opening 10m heightAboveGround...")
                    ds_10m = xr.open_dataset(
                        tmp_path,
                        engine='cfgrib',
                        backend_kwargs={'filter_by_keys': {'typeOfLevel': 'heightAboveGround', 'level': 10}},
                        decode_timedelta=False  # Avoid timedelta decoding issues
                    )
                    for var in ds_10m.data_vars:
                        # Drop heightAboveGround coordinate to avoid conflicts
                        var_data = ds_10m[var].drop_vars(['heightAboveGround'], errors='ignore')
                        all_data_vars[var] = var_data
                    if coords is None:
                        # Get coords but exclude heightAboveGround
                        coords = {k: v for k, v in ds_10m.coords.items() if k != 'heightAboveGround'}
                    logger.info(f"  10m variables: {list(ds_10m.data_vars)}")
                except Exception as e:
                    logger.warning(f"  10m level failed: {str(e)[:100]}")
                
                # Try meanSea level (MSLP)
                try:
                    logger.info("Opening meanSea level...")
                    ds_msl = xr.open_dataset(
                        tmp_path,
                        engine='cfgrib',
                        backend_kwargs={'filter_by_keys': {'typeOfLevel': 'meanSea'}},
                        decode_timedelta=False
                    )
                    for var in ds_msl.data_vars:
                        all_data_vars[var] = ds_msl[var]
                    if coords is None:
                        coords = {k: v for k, v in ds_msl.coords.items()}
                    logger.info(f"  meanSea variables: {list(ds_msl.data_vars)}")
                except Exception as e:
                    logger.warning(f"  meanSea level failed: {str(e)[:100]}")
                
                # Try isobaricInhPa levels (geopotential height for thickness)
                if 'gh' in variables:
                    try:
                        logger.info("Opening isobaricInhPa levels for geopotential height...")
                        # Open both 1000mb and 500mb levels
                        ds_gh = xr.open_dataset(
                            tmp_path,
                            engine='cfgrib',
                            backend_kwargs={'filter_by_keys': {'typeOfLevel': 'isobaricInhPa'}},
                            decode_timedelta=False
                        )
                        # Extract geopotential height and filter to 1000mb and 500mb
                        if 'gh' in ds_gh.data_vars and 'isobaricInhPa' in ds_gh.dims:
                            gh_data = ds_gh['gh'].sel(isobaricInhPa=[1000, 500])
                            all_data_vars['gh'] = gh_data
                            if coords is None:
                                # Use coords from gh but drop isobaricInhPa
                                coords = {k: v for k, v in ds_gh.coords.items() if k != 'isobaricInhPa'}
                            logger.info(f"  isobaricInhPa variables: geopotential height at 1000mb and 500mb")
                        else:
                            logger.warning("Geopotential height not found at isobaricInhPa levels")
                    except Exception as e:
                        logger.warning(f"  isobaricInhPa level failed: {str(e)[:100]}")
                
                if not all_data_vars:
                    raise ValueError("Could not extract any variables from GRIB file")
                
                if coords is None:
                    raise ValueError("Could not get coordinates from any dataset")
                
                # Create new dataset with extracted variables
                # Build dataset incrementally to avoid coordinate conflicts
                logger.info("Combining extracted variables into dataset...")
                ds = xr.Dataset(coords=coords)
                
                # Add variables one at a time, ensuring no coordinate conflicts
                for var_name, var_data in all_data_vars.items():
                    # Make sure variable doesn't have conflicting coordinates
                    var_clean = var_data.drop_vars(['heightAboveGround'], errors='ignore')
                    # Ensure coordinates match the base dataset
                    var_clean = var_clean.drop_vars([c for c in var_clean.coords if c not in coords], errors='ignore')
                    ds[var_name] = var_clean
                
                logger.info("GRIB file opened and variables extracted successfully")
                logger.info(f"Available variables: {list(ds.data_vars)[:20]}...")
                
                # IMPORTANT: Load data into memory NOW, before file might be deleted
                # cfgrib uses lazy loading, so we must load before the finally block
                logger.info("Loading GRIB data into memory...")
                ds = ds.load()
                logger.info(f"GRIB data loaded: {ds.nbytes / 1024 / 1024:.2f} MB")
                
            finally:
                # Only delete if it wasn't a cache hit (new download to temp location)
                # Cached files are managed by _cleanup_old_cache()
                if not cache_hit and os.path.exists(tmp_path) and tmp_path not in [v[0] for v in self._grib_cache.values()]:
                    os.unlink(tmp_path)
                    logger.info("Cleaned up temp file")
                elif cache_hit:
                    logger.debug("Keeping cached GRIB file for reuse")
            
            # Now handle variable selection and subsetting (for both NetCDF and GRIB)
            if ds is None:
                raise ValueError("Failed to open dataset from both NetCDF and GRIB")
            
            # Map our variable names to possible GRIB/NetCDF names
            variable_map = {
                'tmp2m': ['t2m', 'tmp2m', 'TMP_2maboveground', '2t', 'Temperature_surface', 'TMP_P0_L103_GLL0'],
                'prate': ['prate', 'prcp', 'APCP_surface', 'tp', 'Total_precipitation', 'PRATE_P0_L1_GLL0'],
                'ugrd10m': ['u10', 'ugrd10m', 'UGRD_10maboveground', '10u', 'u-component_of_wind_height_above_ground', 'UGRD_P0_L103_GLL0'],
                'vgrd10m': ['v10', 'vgrd10m', 'VGRD_10maboveground', '10v', 'v-component_of_wind_height_above_ground', 'VGRD_P0_L103_GLL0'],
                'prmsl': ['prmsl', 'msl', 'PRMSL_meansealevel', 'MSL_meansealevel', 'Mean_sea_level_pressure', 'PRES_P0_L101_GLL0'],
                'gh': ['gh', 'Geopotential_height_isobaric', 'HGT_isobaric', 'z'],
            }
            
            # Find matching variables
            available_vars = list(ds.data_vars)
            selected_vars = []
            
            for our_var in variables:
                possible_names = variable_map.get(our_var, [our_var])
                found = False
                for name in possible_names:
                    # Check exact match
                    if name in available_vars:
                        selected_vars.append(name)
                        found = True
                        break
                    # Check case-insensitive and partial matches
                    for av in available_vars:
                        if name.lower() in av.lower() or av.lower() in name.lower():
                            selected_vars.append(av)
                            found = True
                            break
                    if found:
                        break
                
                if not found:
                    logger.warning(f"Variable {our_var} not found in dataset")
            
            if selected_vars:
                ds = ds[selected_vars]
                logger.info(f"Selected variables: {selected_vars}")
            else:
                logger.warning("No matching variables found, using all available variables")
                logger.info(f"Available variables: {available_vars[:10]}...")
            
            # Subset to PNW region if requested
            if subset_region and settings.map_region == "pnw":
                # Log coordinate info before subsetting
                logger.info(f"Dataset coordinates: {list(ds.coords.keys())}")
                for coord_name in ['lon', 'longitude', 'lat', 'latitude']:
                    if coord_name in ds.coords:
                        coord_vals = ds.coords[coord_name].values
                        logger.info(f"  {coord_name}: range={coord_vals.min():.2f} to {coord_vals.max():.2f}, shape={coord_vals.shape}")
                
                bounds = settings.map_region_bounds or {
                    "west": -125.0, "east": -110.0,
                    "south": 42.0, "north": 49.0
                }
                
                # Add buffer for better map edges
                buffer = 2.0  # degrees
                
                # Detect coordinate names and handle longitude wrapping (0-360 vs -180 to 180)
                if 'lon' in ds.coords:
                    lon_name, lat_name = 'lon', 'lat'
                elif 'longitude' in ds.coords:
                    lon_name, lat_name = 'longitude', 'latitude'
                else:
                    logger.warning("Could not find lon/lat coordinates for subsetting")
                    lon_name, lat_name = None, None
                
                if lon_name and lat_name:
                    # Check if longitudes are in 0-360 range
                    lon_vals = ds.coords[lon_name].values
                    if lon_vals.min() >= 0 and lon_vals.max() > 180:
                        # Convert our bounds to 0-360 range
                        west = bounds["west"] % 360  # -125 -> 235
                        east = bounds["east"] % 360  # -110 -> 250
                        logger.info(f"Converting longitude bounds from ({bounds['west']}, {bounds['east']}) to ({west}, {east})")
                    else:
                        west = bounds["west"]
                        east = bounds["east"]
                    
                    # Check if latitude is decreasing (common in GFS: 90 to -90)
                    lat_vals = ds.coords[lat_name].values
                    lat_decreasing = lat_vals[0] > lat_vals[-1]
                    
                    lon_slice = slice(west - buffer, east + buffer)
                    
                    # If latitude is decreasing, reverse the slice bounds
                    if lat_decreasing:
                        lat_slice = slice(bounds["north"] + buffer, bounds["south"] - buffer)
                        logger.info(f"Latitude is decreasing, reversing slice order")
                    else:
                        lat_slice = slice(bounds["south"] - buffer, bounds["north"] + buffer)
                    
                    logger.info(f"Subsetting to PNW: lon={lon_slice}, lat={lat_slice}")
                    ds = ds.sel(
                        {lon_name: lon_slice, lat_name: lat_slice}
                    )
                    logger.info(f"After subsetting: dims={dict(ds.dims)}")
            
            # Load only what we need into memory
            logger.info(f"Dataset size before load: {ds.nbytes / 1024 / 1024:.2f} MB")
            logger.info("Loading subset into memory...")
            ds = ds.load()  # Load into memory (now that it's subset)
            logger.info(f"Dataset loaded: {ds.nbytes / 1024 / 1024:.2f} MB")
            
            return ds
        
        elif settings.gfs_source == "nomads":
            # NOMADS HTTP access
            run_str = run_time.strftime("%Y%m%d%H")
            base_url = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{date_str}/{run_str}/atmos"
            file_url = f"{base_url}/gfs.t{run_str[-2:]}z.pgrb2.0p25.f{hour_str}"
            
            logger.info(f"Fetching GFS data from: {file_url}")
            
            # Download and open
            # This is a simplified version - you may need to handle multiple files
            raise NotImplementedError("NOMADS fetching not yet implemented")
        
        else:
            raise ValueError(f"Unknown GFS source: {settings.gfs_source}")


class GraphcastDataFetcher:
    """Fetches Graphcast data"""
    
    def __init__(self):
        self.api_key = settings.graphcast_api_key
    
    def fetch_graphcast_data(
        self,
        run_time: Optional[datetime] = None,
        forecast_hour: int = 0
    ) -> xr.Dataset:
        """Fetch Graphcast data"""
        # TODO: Implement Graphcast fetching
        # This will depend on Graphcast API or local model execution
        raise NotImplementedError("Graphcast fetching not yet implemented")
