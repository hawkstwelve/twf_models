"""Base class for all weather model data fetchers"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Set
import xarray as xr
import logging
import tempfile
import os
import time

from app.models.model_registry import ModelRegistry, ModelConfig
from app.models.variable_requirements import VariableRegistry
from app.config import settings

logger = logging.getLogger(__name__)


class BaseDataFetcher(ABC):
    """Abstract base class for weather data fetchers"""
    
    def __init__(self, model_id: str):
        """Initialize fetcher for a specific model"""
        self.model_config = ModelRegistry.get(model_id)
        if not self.model_config:
            raise ValueError(f"Unknown model: {model_id}")
        
        self.model_id = model_id
        
        # GRIB file cache (shared logic across all models)
        self._grib_cache = {}
        self._cache_dir = Path(tempfile.gettempdir()) / f"{model_id.lower()}_cache"
        self._cache_dir.mkdir(exist_ok=True)
        self._cache_max_age_seconds = 2 * 3600
    
    def get_latest_run_time(self) -> datetime:
        """Get the latest available run time for this model"""
        from datetime import timezone
        now = datetime.now(timezone.utc)
        
        # Go back by availability delay
        adjusted_now = now - timedelta(hours=self.model_config.availability_delay_hours)
        
        # Find the most recent run hour
        run_hours = sorted(self.model_config.run_hours)
        
        # Find which run hour we should use
        for i in range(len(run_hours) - 1, -1, -1):
            run_hour = run_hours[i]
            if adjusted_now.hour >= run_hour:
                run_time = adjusted_now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
                return run_time
        
        # If before first run of the day, use last run of previous day
        run_time = adjusted_now.replace(hour=run_hours[-1], minute=0, second=0, microsecond=0)
        run_time = run_time - timedelta(days=1)
        return run_time
    
    @abstractmethod
    def fetch_raw_data(
        self,
        run_time: datetime,
        forecast_hour: int,
        raw_fields: Set[str],
        subset_region: bool = True
    ) -> xr.Dataset:
        """
        Fetch raw GRIB fields for specified run time and forecast hour.
        Must be implemented by each model-specific fetcher.
        
        Returns dataset with ONLY the requested raw fields.
        No derived fields computed here.
        """
        pass
    
    def build_dataset_for_maps(
        self,
        run_time: datetime,
        forecast_hour: int,
        variables: List[str],
        subset_region: bool = True
    ) -> xr.Dataset:
        """
        Build complete dataset ready for map generation.
        
        This is the MAIN ENTRY POINT for the scheduler.
        Returns a dataset with:
        - All raw fields needed
        - All derived fields computed
        - Ready to pass directly to MapGenerator
        
        **MapGenerator must never call this or any fetch method.**
        """
        logger.info(f"Building dataset for {self.model_id} f{forecast_hour:03d}, variables: {variables}")
        
        # Get all raw fields needed
        all_raw_fields = VariableRegistry.get_all_raw_fields(variables)
        logger.info(f"  Raw fields needed: {sorted(all_raw_fields)}")
        
        # Fetch raw data once
        ds = self.fetch_raw_data(run_time, forecast_hour, all_raw_fields, subset_region)
        
        # Compute derived fields
        if VariableRegistry.needs_precip_total(variables):
            logger.info(f"  Computing tp_total (0→{forecast_hour}h)")
            ds['tp_total'] = self._compute_total_precipitation(run_time, forecast_hour, subset_region)
        
        if VariableRegistry.needs_precip_6hr_rate(variables):
            logger.info(f"  Computing p6_rate_mmhr")
            ds['p6_rate_mmhr'] = self._compute_6hr_precip_rate(run_time, forecast_hour, subset_region)
        
        logger.info(f"  Dataset complete with {len(ds.data_vars)} variables")
        return ds
    
    def _compute_total_precipitation(
        self,
        run_time: datetime,
        forecast_hour: int,
        subset_region: bool = True
    ) -> xr.DataArray:
        """
        Compute total precipitation from hour 0 to forecast_hour.
        
        Handles both accumulated and bucketed precip based on model config.
        """
        if forecast_hour == 0:
            # No accumulation at f000
            ds0 = self.fetch_raw_data(run_time, 0, {"tp", "prate"}, subset_region)
            base = ds0['tp'] if 'tp' in ds0 else ds0['prate']
            return base.squeeze() * 0.0
        
        if self.model_config.tp_is_accumulated_from_init:
            # Cumulative: tp(fH) already represents 0→H
            logger.info(f"    Using accumulated precip (cumulative from init)")
            ds_target = self.fetch_raw_data(run_time, forecast_hour, {"tp"}, subset_region)
            if 'tp' not in ds_target:
                raise ValueError(f"No tp in f{forecast_hour:03d}")
            
            tp = ds_target['tp'].squeeze()
            drop_coords = [c for c in ['time', 'valid_time', 'step'] if c in tp.coords]
            if drop_coords:
                tp = tp.drop_vars(drop_coords)
            
            return tp
        
        else:
            # Bucketed: sum all buckets from 0→H
            logger.info(f"    Summing bucketed precip")
            hours_to_fetch = list(range(
                self.model_config.forecast_increment,
                forecast_hour + 1,
                self.model_config.forecast_increment
            ))
            
            precip_total = None
            
            for hour in hours_to_fetch:
                try:
                    ds = self.fetch_raw_data(run_time, hour, {"tp"}, subset_region)
                    if 'tp' not in ds:
                        continue
                    
                    tp = ds['tp'].squeeze()
                    drop_coords = [c for c in ['time', 'valid_time', 'step'] if c in tp.coords]
                    if drop_coords:
                        tp = tp.drop_vars(drop_coords)
                    
                    precip_total = tp.copy(deep=True) if precip_total is None else (precip_total + tp)
                
                except FileNotFoundError:
                    continue
                except Exception as e:
                    logger.error(f"Error fetching precipitation for f{hour:03d}: {e}")
                    continue
            
            if precip_total is None:
                raise ValueError(f"No precipitation data available up to f{forecast_hour:03d}")
            
            return precip_total
    
    def _compute_6hr_precip_rate(
        self,
        run_time: datetime,
        forecast_hour: int,
        subset_region: bool = True
    ) -> xr.DataArray:
        """
        Compute 6-hour mean precipitation rate in mm/hr.
        
        For MSLP & Precip maps.
        """
        if forecast_hour < 6:
            # Not enough data for 6-hour rate
            ds = self.fetch_raw_data(run_time, forecast_hour, {"prate"}, subset_region)
            if 'prate' in ds:
                return ds['prate'].squeeze() * 0.0
            # Return zeros with proper shape
            ds_any = self.fetch_raw_data(run_time, forecast_hour, {"tmp2m"}, subset_region)
            return ds_any['tmp2m'].squeeze() * 0.0
        
        # Get precip for this 6-hour bucket
        # Depends on whether precip is accumulated or bucketed
        if self.model_config.tp_is_accumulated_from_init:
            # tp(H) - tp(H-6)
            ds_current = self.fetch_raw_data(run_time, forecast_hour, {"tp"}, subset_region)
            ds_previous = self.fetch_raw_data(run_time, forecast_hour - 6, {"tp"}, subset_region)
            
            tp_current = ds_current['tp'].squeeze() if 'tp' in ds_current else None
            tp_previous = ds_previous['tp'].squeeze() if 'tp' in ds_previous else None
            
            if tp_current is not None and tp_previous is not None:
                bucket_precip = tp_current - tp_previous
            elif tp_current is not None:
                bucket_precip = tp_current
            else:
                raise ValueError(f"No tp data for 6-hour rate calculation")
        else:
            # Just use tp from this forecast hour (already a bucket)
            ds = self.fetch_raw_data(run_time, forecast_hour, {"tp"}, subset_region)
            if 'tp' not in ds:
                raise ValueError(f"No tp in f{forecast_hour:03d}")
            bucket_precip = ds['tp'].squeeze()
        
        # Convert to mm/hr (assuming tp is in meters)
        # bucket is 6 hours of accumulation in meters
        rate_mmhr = (bucket_precip * 1000.0) / 6.0  # mm/hr
        
        # Drop time coords
        drop_coords = [c for c in ['time', 'valid_time', 'step'] if c in rate_mmhr.coords]
        if drop_coords:
            rate_mmhr = rate_mmhr.drop_vars(drop_coords)
        
        return rate_mmhr
    
    # Shared utility methods
    def _cleanup_old_cache(self):
        """Clean up old GRIB files"""
        now = time.time()
        to_remove = []
        
        for grib_path, (local_path, download_time) in self._grib_cache.items():
            age = now - download_time
            if age > self._cache_max_age_seconds:
                to_remove.append(grib_path)
                try:
                    if os.path.exists(local_path):
                        os.remove(local_path)
                        logger.debug(f"Removed old cache file: {local_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove cache file {local_path}: {e}")
        
        for grib_path in to_remove:
            del self._grib_cache[grib_path]
    
    def _get_cached_grib_path(self, cache_key: str) -> Optional[str]:
        """Get cached GRIB file path"""
        self._cleanup_old_cache()
        
        if cache_key in self._grib_cache:
            local_path, t = self._grib_cache[cache_key]
            if os.path.exists(local_path):
                return local_path
            del self._grib_cache[cache_key]
        
        # Check disk
        local_path = str(self._cache_dir / f"{cache_key}.grib2")
        if os.path.exists(local_path):
            age_seconds = time.time() - os.path.getmtime(local_path)
            if age_seconds < self._cache_max_age_seconds:
                self._grib_cache[cache_key] = (local_path, os.path.getmtime(local_path))
                return local_path
        
        return None
    
    def _subset_dataset(self, ds: xr.Dataset) -> xr.Dataset:
        """Subset dataset to configured region"""
        if ds is None:
            return ds
        
        bounds = settings.map_region_bounds or {
            "west": -125.0, "east": -110.0,
            "south": 42.0, "north": 49.0
        }
        buffer = 4.0
        
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
