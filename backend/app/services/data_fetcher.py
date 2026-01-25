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
        
        # First check in-memory cache (fast path for same process)
        if grib_file_path in self._grib_cache:
            local_path, download_time = self._grib_cache[grib_file_path]
            if os.path.exists(local_path):
                age_minutes = (time.time() - download_time) / 60
                logger.info(f"✅ Using cached GRIB file (age: {age_minutes:.1f} minutes)")
                return local_path
            else:
                # File was deleted, remove from cache
                del self._grib_cache[grib_file_path]
        
        # Check if file exists on disk (for multiprocessing - other workers may have downloaded it)
        file_hash = hash(grib_file_path) % 10000
        local_path = str(self._cache_dir / f"gfs_{file_hash}.grib2")
        
        if os.path.exists(local_path):
            # File exists on disk, add to in-memory cache and use it
            file_age_seconds = time.time() - os.path.getmtime(local_path)
            age_minutes = file_age_seconds / 60
            
            # Only use if file is less than 6 hours old (stale files cleaned up separately)
            if age_minutes < 360:
                logger.info(f"✅ Using cached GRIB file from disk (age: {age_minutes:.1f} minutes)")
                self._grib_cache[grib_file_path] = (local_path, os.path.getmtime(local_path))
                return local_path
        
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
        # Go back 3.5 hours to find which run should be finishing/available
        # This matches the logic used in run_latest_now.py
        from datetime import timezone
        now = datetime.now(timezone.utc)
        adjusted_now = now - timedelta(hours=3, minutes=30)
        run_hour = (adjusted_now.hour // 6) * 6
        run_time = adjusted_now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
        
        return run_time
    
    def fetch_total_precipitation(
        self,
        run_time: Optional[datetime] = None,
        forecast_hour: int = 72,
        subset_region: bool = True
    ) -> xr.DataArray:
        """
        Fetch total accumulated precipitation from hour 0 to target forecast_hour.
        
        GFS GRIB files contain incremental precipitation buckets (e.g., 66-72h for f072),
        not total accumulation from hour 0. To get true total precipitation, we must
        download and sum precipitation from all intermediate forecast files.
        
        For example, for 72-hour total precipitation:
        - Total precip = sum(f006 + f012 + f018 + f024 + f030 + f036 + f042 + f048 + f054 + f060 + f066 + f072)
        
        Args:
            run_time: GFS run time (defaults to latest)
            forecast_hour: Target forecast hour (24, 48, 72, etc.)
            subset_region: If True, only fetch PNW region data
            
        Returns:
            xr.DataArray: Total accumulated precipitation in mm
        """
        if run_time is None:
            run_time = self.get_latest_run_time()
        
        logger.info(f"Fetching total precipitation for 0-{forecast_hour}h accumulation")
        logger.info(f"This requires downloading and summing multiple GRIB files")
        
        # GFS outputs precipitation in 6-hour buckets for forecast hours > 0
        # Hour 0 (analysis) has no precipitation
        # Hours 1-5 may have hourly buckets (depends on GFS version)
        # Hours 6+ have 6-hour buckets (f006, f012, f018, f024, etc.)
        
        # Determine which forecast hours to fetch based on target hour
        # For 0.25° GFS: outputs every 3 hours to 120h, then every 12h to 384h
        # But precipitation accumulation is in 6-hour buckets
        
        if forecast_hour == 0:
            logger.warning("Forecast hour 0 (analysis) has no precipitation accumulation")
            # Return zeros - analysis has no accumulated precipitation
            # We'll fetch f000 just to get the grid structure
            ds = self.fetch_gfs_data(
                run_time=run_time,
                forecast_hour=0,
                variables=['tp', 'prate'],
                subset_region=subset_region
            )
            # Create a zero array with the same shape
            if 'tp' in ds:
                precip_total = ds['tp'] * 0.0
            elif 'prate' in ds:
                precip_total = ds['prate'] * 0.0
            else:
                raise ValueError("Could not find precipitation variable to determine grid shape")
            return precip_total
        
        # For forecast hours > 0, we need to sum 6-hour buckets
        # GFS precipitation buckets are at f006, f012, f018, f024, etc.
        hours_to_fetch = list(range(6, forecast_hour + 1, 6))
        
        # Handle case where target hour is not divisible by 6
        # e.g., if user requests 72h, we fetch [6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72]
        # But if user requests 75h (future 3-hour increment), we need [6, 12, ..., 72, 75]
        if forecast_hour % 6 != 0:
            # Add intermediate hours if available (GFS has 3-hour outputs)
            last_6h_bucket = (forecast_hour // 6) * 6
            remaining_hours = forecast_hour - last_6h_bucket
            
            # For remaining hours, check if 3-hour increment exists
            if remaining_hours == 3:
                hours_to_fetch.append(forecast_hour)
                logger.info(f"Including 3-hour increment: f{forecast_hour:03d}")
        
        logger.info(f"Fetching precipitation from hours: {hours_to_fetch}")
        logger.info(f"Total files to download: {len(hours_to_fetch)}")
        
        precip_total = None
        successful_hours = []
        
        for hour in hours_to_fetch:
            try:
                logger.info(f"  Fetching f{hour:03d}...")
                
                # Fetch just the precipitation variable for this hour
                ds = self.fetch_gfs_data(
                    run_time=run_time,
                    forecast_hour=hour,
                    variables=['tp', 'prate'],  # Only need precip
                    subset_region=subset_region
                )
                
                # Extract precipitation variable
                if 'tp' in ds:
                    precip = ds['tp']
                elif 'prate' in ds:
                    # prate is kg/m²/s, convert to mm by multiplying by seconds in bucket
                    # For 6-hour bucket: prate * 6 * 3600 seconds
                    bucket_hours = 6 if hour >= 6 else hour
                    precip = ds['prate'] * (bucket_hours * 3600)
                else:
                    logger.warning(f"    No precipitation variable in f{hour:03d}, skipping")
                    continue
                
                # Clean up dimensions
                # Remove time, valid_time, step coordinates to avoid conflicts when summing
                precip = precip.squeeze()
                drop_coords = [c for c in ['time', 'valid_time', 'step'] if c in precip.coords]
                if drop_coords:
                    precip = precip.drop_vars(drop_coords)
                
                # Log the precipitation bucket value
                precip_values = precip.values
                if hasattr(precip_values, 'max'):
                    logger.info(f"    f{hour:03d} bucket: max={float(precip_values.max()):.4f} mm, mean={float(precip_values.mean()):.4f} mm")
                
                # Add to total
                if precip_total is None:
                    # First hour - initialize
                    precip_total = precip.copy(deep=True)
                else:
                    # Add to running total
                    # Make sure coordinates match
                    precip_total = precip_total + precip
                
                successful_hours.append(hour)
                
            except FileNotFoundError as e:
                logger.warning(f"    f{hour:03d} not available yet: {e}")
                # Don't fail entire request if one hour is missing
                # This is common during progressive data availability
                continue
            except Exception as e:
                logger.error(f"    Error fetching f{hour:03d}: {e}")
                # Continue with other hours
                continue
        
        if precip_total is None:
            raise ValueError(f"Could not fetch precipitation data for any forecast hour up to {forecast_hour}")
        
        logger.info(f"Successfully summed precipitation from {len(successful_hours)} forecast hours: {successful_hours}")
        
        # Log final total
        total_values = precip_total.values
        if hasattr(total_values, 'max'):
            logger.info(f"Total precipitation (0-{forecast_hour}h): max={float(total_values.max()):.4f} mm ({float(total_values.max())/25.4:.4f} in), mean={float(total_values.mean()):.4f} mm ({float(total_values.mean())/25.4:.4f} in)")
        
        return precip_total

    def _subset_dataset(self, ds: xr.Dataset) -> xr.Dataset:
        """Subset a dataset to the PNW region immediately after opening"""
        if ds is None:
            return ds
            
        # Define bounds
        bounds = settings.map_region_bounds or {
            "west": -125.0, "east": -110.0,
            "south": 42.0, "north": 49.0
        }
        buffer = 2.0  # degrees
        
        # Detect coordinate names
        if 'lon' in ds.coords:
            lon_name, lat_name = 'lon', 'lat'
        elif 'longitude' in ds.coords:
            lon_name, lat_name = 'longitude', 'latitude'
        else:
            return ds
            
        # Handle 0-360 longitude
        lon_vals = ds.coords[lon_name].values
        if lon_vals.min() >= 0 and lon_vals.max() > 180:
            west = bounds["west"] % 360
            east = bounds["east"] % 360
        else:
            west = bounds["west"]
            east = bounds["east"]
            
        # Handle latitude direction
        lat_vals = ds.coords[lat_name].values
        lat_decreasing = lat_vals[0] > lat_vals[-1]
        
        lon_slice = slice(west - buffer, east + buffer)
        if lat_decreasing:
            lat_slice = slice(bounds["north"] + buffer, bounds["south"] - buffer)
        else:
            lat_slice = slice(bounds["south"] - buffer, bounds["north"] + buffer)
            
        return ds.sel({lon_name: lon_slice, lat_name: lat_slice})

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
        
        # If gh is requested, we need both 1000mb and 500mb for thickness
        if 'gh' in variables:
            variables = variables + ['gh_1000', 'gh_500']
        
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
                    # If f000 doesn't exist, try 'anl' (Analysis)
                    if forecast_hour == 0:
                        anl_file_path = grib_file_path.replace('.f000', '.anl')
                        if self.s3.exists(anl_file_path):
                            logger.info(f"Using analysis file (anl) for f000")
                            grib_file_path = anl_file_path
                        else:
                            raise FileNotFoundError(f"GRIB file not found on S3: {grib_file_path} (also tried .anl)")
                    else:
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
                            ds_surf_instant = self._subset_dataset(ds_surf_instant)
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
                            ds_surf_accum = self._subset_dataset(ds_surf_accum)
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
                        ds_surface = self._subset_dataset(ds_surface)
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
                        # Close dataset to free memory
                        ds_surf.close()
                    
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
                    ds_2m = self._subset_dataset(ds_2m)
                    for var in ds_2m.data_vars:
                        # Drop heightAboveGround coordinate to avoid conflicts
                        var_data = ds_2m[var].drop_vars(['heightAboveGround'], errors='ignore')
                        all_data_vars[var] = var_data
                    if coords is None:
                        # Get coords but exclude heightAboveGround
                        coords = {k: v for k, v in ds_2m.coords.items() if k != 'heightAboveGround'}
                    logger.info(f"  2m variables: {list(ds_2m.data_vars)}")
                    ds_2m.close()
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
                    ds_10m = self._subset_dataset(ds_10m)
                    for var in ds_10m.data_vars:
                        # Drop heightAboveGround coordinate to avoid conflicts
                        var_data = ds_10m[var].drop_vars(['heightAboveGround'], errors='ignore')
                        all_data_vars[var] = var_data
                    if coords is None:
                        # Get coords but exclude heightAboveGround
                        coords = {k: v for k, v in ds_10m.coords.items() if k != 'heightAboveGround'}
                    logger.info(f"  10m variables: {list(ds_10m.data_vars)}")
                    ds_10m.close()
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
                    ds_msl = self._subset_dataset(ds_msl)
                    for var in ds_msl.data_vars:
                        all_data_vars[var] = ds_msl[var]
                    if coords is None:
                        coords = {k: v for k, v in ds_msl.coords.items()}
                    logger.info(f"  meanSea variables: {list(ds_msl.data_vars)}")
                    ds_msl.close()
                except Exception as e:
                    logger.warning(f"  meanSea level failed: {str(e)[:100]}")
                
                # Try isobaricInhPa levels (geopotential height, 850mb temp/wind)
                needed_levels = []
                if 'gh' in variables or 'gh_1000' in variables: needed_levels.append(1000)
                if 'gh' in variables or 'gh_500' in variables: needed_levels.append(500)
                if any(v in variables for v in ['tmp_850', 'ugrd_850', 'vgrd_850']): needed_levels.append(850)
                
                if needed_levels:
                    try:
                        logger.info(f"Opening isobaricInhPa levels: {list(set(needed_levels))}")
                        for level in set(needed_levels):
                            try:
                                logger.info(f"  Extracting level {level}mb...")
                                ds_level = xr.open_dataset(
                                    tmp_path,
                                    engine='cfgrib',
                                    backend_kwargs={'filter_by_keys': {
                                        'typeOfLevel': 'isobaricInhPa',
                                        'level': level
                                    }},
                                    decode_timedelta=False
                                )
                                ds_level = self._subset_dataset(ds_level)
                                
                                # GFS variable naming varies
                                for v in ds_level.data_vars:
                                    if level == 1000 and v in ['gh', 'hgt']:
                                        all_data_vars['gh_1000'] = ds_level[v].squeeze()
                                    elif level == 500 and v in ['gh', 'hgt']:
                                        all_data_vars['gh_500'] = ds_level[v].squeeze()
                                    elif level == 850:
                                        if v in ['t', 'tmp']: all_data_vars['tmp_850'] = ds_level[v].squeeze()
                                        if v in ['u', 'ugrd']: all_data_vars['ugrd_850'] = ds_level[v].squeeze()
                                        if v in ['v', 'vgrd']: all_data_vars['vgrd_850'] = ds_level[v].squeeze()
                                
                                if coords is None:
                                    coords = {k: v for k, v in ds_level.coords.items() if k not in ['isobaricInhPa', 'level']}
                                ds_level.close()
                            except Exception as e:
                                logger.warning(f"  Could not extract gh at {level}mb: {str(e)[:100]}")
                    except Exception as e:
                        logger.warning(f"  isobaricInhPa level extraction failed: {str(e)[:100]}")
                
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
                'prate': ['tp', 'prate', 'prcp', 'APCP_surface', 'Total_precipitation', 'PRATE_P0_L1_GLL0'],
                'ugrd10m': ['u10', 'ugrd10m', 'UGRD_10maboveground', '10u', 'u-component_of_wind_height_above_ground', 'UGRD_P0_L103_GLL0'],
                'vgrd10m': ['v10', 'vgrd10m', 'VGRD_10maboveground', '10v', 'v-component_of_wind_height_above_ground', 'VGRD_P0_L103_GLL0'],
                'prmsl': ['prmsl', 'msl', 'PRMSL_meansealevel', 'MSL_meansealevel', 'Mean_sea_level_pressure', 'PRES_P0_L101_GLL0'],
                'tp': ['tp', 'Total_precipitation', 'APCP_surface'],
                'gh': ['gh', 'Geopotential_height_isobaric', 'HGT_isobaric', 'z'],
                'gh_1000': ['gh_1000'],
                'gh_500': ['gh_500'],
                'tmp_850': ['tmp_850'],
                'ugrd_850': ['ugrd_850'],
                'vgrd_850': ['vgrd_850'],
                'crain': ['crain', 'CRAIN_surface'],
                'refc': ['refc', 'REFC', 'refc_surface', 'REFC_surface', 'Composite_reflectivity'],
                'csnow': ['csnow', 'CSNOW_surface'],
                'cicep': ['cicep', 'CICEP_surface'],
                'cfrzr': ['cfrzr', 'CFRZR_surface'],
            }
            
            # Find matching variables
            available_vars = list(ds.data_vars)
            selected_vars = []
            
            # Ensure precip is requested for MSLP & Precip maps
            if variables is not None and ('mslp_precip' in variables or 'mslp_pcpn' in variables):
                for v in ['prate', 'tp', 'prmsl', 'gh', 'gh_1000', 'gh_500', 'crain', 'csnow', 'cicep', 'cfrzr']:
                    if v not in variables:
                        variables.append(v)
            
            # If gh is requested, we need both 1000mb and 500mb for thickness
            if variables is not None and 'gh' in variables:
                if 'gh_1000' not in variables: variables.append('gh_1000')
                if 'gh_500' not in variables: variables.append('gh_500')

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
