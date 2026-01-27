"""Weather data fetching service"""
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
    """Fetches GFS data from NOMADS"""
    
    def __init__(self):
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
    
    def _cache_filename(self, cache_key: str) -> Path:
        """Generate the cache filename for a given cache key"""
        return self._cache_dir / f"gfs_nomads_{cache_key}.grib2"

    def _get_cached_grib_path(self, cache_key: str) -> Optional[str]:
        """
        Get path to cached GRIB file, or None if not cached.
        Also cleans up old cache files.
        """
        self._cleanup_old_cache()
        
        # First check in-memory cache (fast path for same process)
        if cache_key in self._grib_cache:
            local_path, t = self._grib_cache[cache_key]
            if os.path.exists(local_path):
                return local_path
            del self._grib_cache[cache_key]
        
        # Check if file exists on disk (for multiprocessing - other workers may have downloaded it)
        # Use a stable, short, and safe cache key for the filename (SHA1-based, no path chars)
        local_path = str(self._cache_filename(cache_key))
        
        if os.path.exists(local_path):
            age_seconds = time.time() - os.path.getmtime(local_path)
            if age_seconds < self._cache_max_age_seconds:
                self._grib_cache[cache_key] = (local_path, os.path.getmtime(local_path))
                return local_path
        
        return None
    
    
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
        """Fetch total accumulated precipitation from hour 0 to target forecast_hour.

        Uses _tp_is_cumulative() to distinguish cumulative vs bucketed tp so that
        cumulative fields are not double-counted.
        """
        if run_time is None:
            run_time = self.get_latest_run_time()

        # Forecast hour 0: no accumulation, but return a zero field with proper grid
        if forecast_hour == 0:
            ds0 = self.fetch_gfs_data(
                run_time=run_time,
                forecast_hour=0,
                variables=['tp', 'prate'],
                subset_region=subset_region,
            )
            base = ds0['tp'] if 'tp' in ds0 else ds0['prate']
            return base.squeeze() * 0.0

        # For forecast hours > 0, build list of hours to inspect
        hours_to_fetch = list(range(6, forecast_hour + 1, 6))
        if forecast_hour % 6 == 3:
            hours_to_fetch.append(forecast_hour)

        precip_total: Optional[xr.DataArray] = None
        cumulative_mode: Optional[bool] = None

        for hour in hours_to_fetch:
            try:
                ds = self.fetch_gfs_data(
                    run_time=run_time,
                    forecast_hour=hour,
                    variables=['tp'],
                    subset_region=subset_region,
                )
                if 'tp' not in ds:
                    raise ValueError(f"No tp in f{hour:03d}")

                tp_raw = ds['tp']

                # Decide mode based on the first successful tp
                if cumulative_mode is None:
                    cumulative_mode = self._tp_is_cumulative(tp_raw)
                    logger.info(
                        f"fetch_total_precipitation: detected tp mode at f{hour:03d}: "
                        f"{'cumulative' if cumulative_mode else 'bucketed'}"
                    )

                tp = tp_raw.squeeze()
                drop_coords = [c for c in ['time', 'valid_time', 'step'] if c in tp.coords]
                if drop_coords:
                    tp = tp.drop_vars(drop_coords)

                if cumulative_mode:
                    # Cumulative: field already represents 0 -> hour accumulation.
                    # For the target hour, just return tp directly.
                    if hour == forecast_hour:
                        logger.info(
                            f"fetch_total_precipitation: using cumulative tp at f{hour:03d} "
                            f"for total 0-{forecast_hour}h precipitation"
                        )
                        return tp
                    # Otherwise skip (we only need the target cumulative field)
                    continue

                # Bucketed mode: sum buckets
                precip_total = tp.copy(deep=True) if precip_total is None else (precip_total + tp)

            except FileNotFoundError:
                # Skip missing hours (common during progressive availability)
                continue
            except Exception as e:
                logger.error(f"Error fetching precipitation for f{hour:03d}: {e}")
                continue

        if precip_total is None:
            raise ValueError(f"No precipitation data available up to f{forecast_hour:03d}")

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
        buffer = 4.0  # degrees - increased buffer to prevent edge cutoff in precip data
        
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
        # Copy variables to avoid mutating caller's list
        variables = list(variables)
        # If gh is requested, we need both 1000mb and 500mb for thickness
        if 'gh' in variables:
            variables += [v for v in ['gh_1000', 'gh_500'] if v not in variables]
        # Ensure precip is requested for MSLP & Precip maps
        if 'mslp_precip' in variables or 'mslp_pcpn' in variables:
            for v in ['prate', 'tp', 'prmsl', 'gh', 'gh_1000', 'gh_500', 'crain', 'csnow', 'cicep', 'cfrzr']:
                if v not in variables:
                    variables.append(v)
        # After this point, treat variables as immutable
        
        date_str = run_time.strftime("%Y%m%d")
        run_hour_str = run_time.strftime("%H")  # Just the hour (00, 06, 12, 18)
        hour_str = f"{forecast_hour:03d}"
        
        # NOMADS HTTP access with optional filtering
        logger.info(f"Fetching GFS data from NOMADS...")
        
        import cfgrib
        import requests
        import hashlib
        
        if settings.nomads_use_filter and subset_region and variables:
            # Use NOMADS filter to download only what we need (much faster!)
            logger.info("Using NOMADS filter for selective download")
            file_url = self._build_nomads_filter_url(
                date_str=date_str,
                run_hour=run_hour_str,
                forecast_hour=hour_str,
                variables=variables,
                subset_region=subset_region
            )
        else:
            # Download full GRIB file (fallback)
            logger.info("Downloading full GRIB file from NOMADS")
            file_url = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{date_str}/{run_hour_str}/atmos/gfs.t{run_hour_str}z.pgrb2.{settings.gfs_resolution}.f{hour_str}"
        
        logger.info(f"NOMADS URL: {file_url}")
        
        # Create cache key from URL hash to ensure different URLs cache separately
        # This prevents cache collisions between filtered vs full files, different variables, etc.
        url_hash = hashlib.sha1(file_url.encode()).hexdigest()[:16]
        cache_key = f"nomads_{url_hash}"
        tmp_path = self._get_cached_grib_path(cache_key)
        cache_hit = tmp_path is not None
        
        if not cache_hit:
            # Download from NOMADS
            tmp_path = self._download_from_nomads(file_url, cache_key)
        
        try:
            # Open GRIB file with cfgrib
            logger.info("Opening GRIB file with cfgrib...")
            
            all_data_vars = {}
            coords = None
            
            # Try surface level
            try:
                logger.info("Opening surface level...")
                surface_datasets = []
                
                if forecast_hour > 0:
                    # IMPORTANT: Load accumulated FIRST so precipitation variables take precedence
                    
                    # Try accumulated stepType FIRST (precipitation - must have priority)
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
                    
                    # Try instant stepType SECOND (most other variables)
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
                else:
                    ds_surface = xr.open_dataset(
                        tmp_path,
                        engine='cfgrib',
                        backend_kwargs={'filter_by_keys': {'typeOfLevel': 'surface'}},
                        decode_timedelta=False
                    )
                    ds_surface = self._subset_dataset(ds_surface)
                    surface_datasets.append(ds_surface)
                
                for ds_surf in surface_datasets:
                    for var in ds_surf.data_vars:
                        if var in all_data_vars:
                            continue
                        var_data = ds_surf[var].drop_vars(['heightAboveGround'], errors='ignore')
                        all_data_vars[var] = var_data
                    if coords is None:
                        coords = {k: v for k, v in ds_surf.coords.items() if k != 'heightAboveGround'}
                    ds_surf.close()
                
            except Exception as e:
                logger.warning(f"  Surface level failed: {str(e)[:100]}")
            
            # Try 2m height (temperature)
            try:
                logger.info("Opening 2m heightAboveGround...")
                ds_2m = xr.open_dataset(
                    tmp_path,
                    engine='cfgrib',
                    backend_kwargs={'filter_by_keys': {'typeOfLevel': 'heightAboveGround', 'level': 2}},
                    decode_timedelta=False
                )
                ds_2m = self._subset_dataset(ds_2m)
                for var in ds_2m.data_vars:
                    var_data = ds_2m[var].drop_vars(['heightAboveGround'], errors='ignore')
                    all_data_vars[var] = var_data
                if coords is None:
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
                    decode_timedelta=False
                )
                ds_10m = self._subset_dataset(ds_10m)
                for var in ds_10m.data_vars:
                    var_data = ds_10m[var].drop_vars(['heightAboveGround'], errors='ignore')
                    all_data_vars[var] = var_data
                if coords is None:
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
            
            # Try atmosphere level (for REFC - composite reflectivity)
            try:
                logger.info("Opening atmosphere level...")
                ds_atmos = xr.open_dataset(
                    tmp_path,
                    engine='cfgrib',
                    backend_kwargs={'filter_by_keys': {'typeOfLevel': 'atmosphere'}},
                    decode_timedelta=False
                )
                ds_atmos = self._subset_dataset(ds_atmos)
                for var in ds_atmos.data_vars:
                    all_data_vars[var] = ds_atmos[var]
                if coords is None:
                    coords = {k: v for k, v in ds_atmos.coords.items()}
                logger.info(f"  atmosphere variables: {list(ds_atmos.data_vars)}")
                ds_atmos.close()
            except Exception as e:
                logger.warning(f"  atmosphere level failed: {str(e)[:100]}")
            
            # Try isobaricInhPa levels
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
            
            # Create combined dataset
            logger.info("Combining extracted variables into dataset...")
            ds = xr.Dataset(coords=coords)
            
            for var_name, var_data in all_data_vars.items():
                var_clean = var_data.drop_vars(['heightAboveGround'], errors='ignore')
                # Don't drop coordinate variables - they're needed for plotting!
                # Only drop non-coord variables that aren't in our shared coords
                coords_to_drop = [c for c in var_clean.coords if c not in coords and c not in var_clean.dims]
                var_clean = var_clean.drop_vars(coords_to_drop, errors='ignore')
                ds[var_name] = var_clean
            
            logger.info("GRIB file opened and variables extracted successfully")
            logger.info(f"Available variables: {list(ds.data_vars)[:20]}...")
            logger.info(f"Dataset coords: {list(ds.coords.keys())}")
            logger.info(f"Dataset dims: {list(ds.dims.keys())}")
            
            # Load data into memory
            logger.info("Loading GRIB data into memory...")
            ds = ds.load()
            logger.info(f"GRIB data loaded: {ds.nbytes / 1024 / 1024:.2f} MB")
            
        finally:
            # Keep cached files for reuse
            if not cache_hit:
                logger.info("GRIB file cached for reuse")
        
        # Variable selection and return moved here (after try/finally)
        variable_map = {
            'tmp2m': ['t2m', 'tmp2m', 'TMP_2maboveground', '2t', 'Temperature_surface', 'TMP_P0_L103_GLL0'],
            'prate': ['prate', 'prcp', 'PRATE_P0_L1_GLL0'],
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
        available_vars = list(ds.data_vars)
        selected_vars = []
        # Remove duplicate expansion logic below (after dataset load)
        # Only do variable selection based on the finalized variables list
        for our_var in variables:
            possible_names = variable_map.get(our_var, [our_var])
            found = False
            for name in possible_names:
                if name in available_vars:
                    selected_vars.append(name)
                    found = True
                    break
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
        return ds
    
    def _build_nomads_filter_url(
        self,
        date_str: str,
        run_hour: str,
        forecast_hour: str,
        variables: list,
        subset_region: bool = True
    ) -> str:
        """
        Build NOMADS filter URL to download only needed variables and region.
        
        NOMADS filter allows selective download, saving bandwidth and time.
        Example: https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?
                 dir=%2Fgfs.20260126%2F00%2Fatmos&
                 file=gfs.t00z.pgrb2.0p25.f006&
                 var_TMP=on&lev_2_m_above_ground=on&
                 subregion=&leftlon=-125&rightlon=-110&toplat=49&bottomlat=42
        
        Args:
            date_str: Date string YYYYMMDD
            run_hour: Run hour HH
            forecast_hour: Forecast hour FFF
            variables: List of variables needed
            subset_region: If True, subset to PNW region
            
        Returns:
            Filtered NOMADS URL
        """
        # Base filter URL
        if settings.gfs_resolution == "0p25":
            base_url = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
        else:
            base_url = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p50.pl"
        
        # Directory and file
        dir_path = f"/gfs.{date_str}/{run_hour}/atmos"
        file_name = f"gfs.t{run_hour}z.pgrb2.{settings.gfs_resolution}.f{forecast_hour}"
        
        # Build URL parameters
        params = {
            'dir': dir_path,
            'file': file_name,
        }
        
        # Map our variable names to NOMADS variable names
        nomads_var_map = {
            'tmp2m': ('TMP', '2_m_above_ground'),
            'prate': ('PRATE', 'surface'),
            'tp': ('APCP', 'surface'),
            'ugrd10m': ('UGRD', '10_m_above_ground'),
            'vgrd10m': ('VGRD', '10_m_above_ground'),
            'prmsl': ('PRMSL', 'mean_sea_level'),
            'gh_1000': ('HGT', '1000_mb'),
            'gh_500': ('HGT', '500_mb'),
            'tmp_850': ('TMP', '850_mb'),
            'ugrd_850': ('UGRD', '850_mb'),
            'vgrd_850': ('VGRD', '850_mb'),
            'crain': ('CRAIN', 'surface'),
            'csnow': ('CSNOW', 'surface'),
            'cicep': ('CICEP', 'surface'),
            'cfrzr': ('CFRZR', 'surface'),
            'refc': ('REFC', 'entire_atmosphere'),
        }
        
        # Add variables
        for var in variables:
            if var in nomads_var_map:
                var_name, level = nomads_var_map[var]
                params[f'var_{var_name}'] = 'on'
                params[f'lev_{level}'] = 'on'
        
        # Add region subset if requested
        if subset_region and settings.map_region_bounds:
            bounds = settings.map_region_bounds
            # Add a buffer to ensure data extends beyond map boundaries
            # This allows contourf to fill all the way to the edges
            # Buffer is 1.0 degree on each side (roughly 4 grid points at 0.25° resolution)
            buffer = 1.0
            params['subregion'] = ''
            params['leftlon'] = str(bounds["west"] - buffer)
            params['rightlon'] = str(bounds["east"] + buffer)
            params['toplat'] = str(bounds["north"] + buffer)
            params['bottomlat'] = str(bounds["south"] - buffer)
        else:
            # Download full file
            params['all_var'] = 'on'
            params['all_lev'] = 'on'
        
        # Build query string
        import urllib.parse
        query_string = urllib.parse.urlencode(params)
        full_url = f"{base_url}?{query_string}"
        
        logger.info(f"NOMADS filter URL built with {len([k for k in params if k.startswith('var_')])} variables")
        
        return full_url
    
    def _download_from_nomads(self, url: str, cache_key: str) -> str:
        """
        Download GRIB file from NOMADS with retry logic.
        
        Args:
            url: NOMADS URL (direct or filtered)
            cache_key: Cache key for storing locally
            
        Returns:
            Path to downloaded file
        """
        import requests
        
        # Create cache file path
        local_path = str(self._cache_filename(cache_key))
        # file_hash = hash(cache_key) % 10000  # Removed: do not use hash()
        logger.info(f"Downloading from NOMADS to cache...")
        logger.info(f"Cache file: {local_path}")
        
        # Download with retry logic
        for attempt in range(settings.nomads_max_retries):
            try:
                response = requests.get(
                    url,
                    timeout=settings.nomads_timeout,
                    stream=True
                )
                response.raise_for_status()
                
                # Write to file
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # Verify file was downloaded
                if not os.path.exists(local_path):
                    raise FileNotFoundError(f"Download completed but file not found: {local_path}")
                
                file_size_mb = os.path.getsize(local_path) / 1024 / 1024
                logger.info(f"✅ Downloaded {file_size_mb:.1f} MB from NOMADS")
                
                # Add to cache
                self._grib_cache[cache_key] = (local_path, time.time())
                
                return local_path
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"Download attempt {attempt + 1}/{settings.nomads_max_retries} failed: {e}")
                if attempt < settings.nomads_max_retries - 1:
                    time.sleep(5)  # Wait 5 seconds before retry
                else:
                    raise Exception(f"Failed to download from NOMADS after {settings.nomads_max_retries} attempts: {e}")
        
    def fetch_6hr_precip_rate_mmhr(
        self,
        run_time: Optional[datetime] = None,
        forecast_hour: int = 6,
        subset_region: bool = True
    ) -> xr.DataArray:
        """
        Fetch 6-hour window precipitation rate (mm/hr) for a given forecast hour.
        Computes (tp_fh - tp_fh6) / 6.
        Returns DataArray in mm/hr.
        """
        if forecast_hour < 6:
            raise ValueError("6-hour rate requires forecast_hour >= 6")
        if run_time is None:
            run_time = self.get_latest_run_time()

        # Fetch total precip at fh and fh-6
        ds_fh = self.fetch_gfs_data(
            run_time=run_time,
            forecast_hour=forecast_hour,
            variables=['tp', 'prate'],
            subset_region=subset_region
        )
        ds_fh6 = self.fetch_gfs_data(
            run_time=run_time,
            forecast_hour=forecast_hour - 6,
            variables=['tp', 'prate'],
            subset_region=subset_region
        )

        # Extract and normalize total precip (mm)
        def _norm(da):
            # Drop time/step coords and normalize lon/lat for safe math
            drop_coords = [c for c in ['time', 'valid_time', 'step'] if c in da.coords]
            if drop_coords:
                da = da.drop_vars(drop_coords)
            lon_name = 'longitude' if 'longitude' in da.coords else 'lon'
            lat_name = 'latitude' if 'latitude' in da.coords else 'lat'
            # Only rewrite longitude if max(lon) > 180
            if da[lon_name].max() > 180:
                da = da.assign_coords({lon_name: (((da[lon_name] + 180) % 360) - 180)})
                da = da.sortby(lon_name)
            return da

        # Fetch and normalize tp for fh and fh-6
        tp_fh = None
        tp_fh6 = None
        if 'tp' in ds_fh and 'tp' in ds_fh6:
            tp_fh = _norm(ds_fh['tp'].squeeze())
            tp_fh6 = _norm(ds_fh6['tp'].squeeze())
            if self._tp_is_cumulative(ds_fh['tp']):
                # Cumulative: (tp_fh - tp_fh6) / 6
                rate_mmhr = (tp_fh - tp_fh6) / 6.0
                logger.info(f"6hr precip rate (mm/hr, cumulative): min={float(rate_mmhr.min()):.4f}, max={float(rate_mmhr.max()):.4f}, mean={float(rate_mmhr.mean()):.4f}")
                return rate_mmhr
            else:
                # Bucket: tp_fh / 6
                rate_mmhr = tp_fh / 6.0
                logger.info(f"6hr precip rate (mm/hr, bucket): min={float(rate_mmhr.min()):.4f}, max={float(rate_mmhr.max()):.4f}, mean={float(rate_mmhr.mean()):.4f}")
                return rate_mmhr
        elif 'prate' in ds_fh:
            prate = _norm(ds_fh['prate'].squeeze())
            rate_mmhr = prate * 3600.0
            logger.info(f"Instantaneous prate (mm/hr) used: min={float(rate_mmhr.min()):.4f}, max={float(rate_mmhr.max()):.4f}, mean={float(rate_mmhr.mean()):.4f}")
            return rate_mmhr
        else:
            raise ValueError("No suitable precipitation variable (tp or prate) found for 6hr rate computation at forecast_hour.")
        
    def _tp_is_cumulative(self, tp_da) -> bool:
        sr = tp_da.attrs.get("GRIB_stepRange") or tp_da.attrs.get("stepRange")
        if not sr:
            return False
        try:
            a, b = [int(x) for x in str(sr).split("-")]
            return a == 0 and b > 0
        except Exception:
            return False
        

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
