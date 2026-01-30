"""Base class for all weather model data fetchers"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Set, Dict, Tuple
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
        # Use a persistent cache directory (not tempfile) so it survives restarts
        # and is shared across workers
        self._cache_dir = Path(settings.storage_path).parent / "grib_cache" / f"{model_id.lower()}"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_max_age_seconds = 2 * 3600
        
        # cfgrib index cache directory (critical for performance!)
        # Store .idx files alongside GRIB files for persistent indexing
        self._index_cache_dir = self._cache_dir / "indexes"
        self._index_cache_dir.mkdir(exist_ok=True)
        
        # Incremental accumulation cache (prevents O(H²) explosion)
        # Key: (run_time_str, forecast_hour) -> Value: (precip_total, snow_total)
        self._accumulation_cache: Dict[Tuple[str, int], Tuple[Optional[xr.DataArray], Optional[xr.DataArray]]] = {}
        self._current_run_time_str: Optional[str] = None
    
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
        
        if VariableRegistry.needs_snow_total(variables):
            logger.info(f"  Computing tp_snow_total (0→{forecast_hour}h)")
            ds['tp_snow_total'] = self._compute_total_snowfall(run_time, forecast_hour, subset_region)
        
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
        
        **OPTIMIZED**: Uses incremental accumulation to avoid O(H²) complexity.
        Instead of re-fetching all hours 0→H for each forecast hour, we:
        1. Check cache for previous hour's total
        2. Fetch only the current bucket
        3. Add to previous total
        
        Handles both accumulated and bucketed precip based on model config.
        """
        run_time_str = run_time.strftime("%Y%m%d_%H")
        
        # Clear cache if we're processing a new run
        if self._current_run_time_str != run_time_str:
            logger.info(f"    New run detected ({run_time_str}), clearing accumulation cache")
            self._accumulation_cache.clear()
            self._current_run_time_str = run_time_str
        
        # Check if we already computed this
        cache_key = (run_time_str, forecast_hour)
        if cache_key in self._accumulation_cache:
            cached_precip, _ = self._accumulation_cache[cache_key]
            if cached_precip is not None:
                logger.info(f"    Using cached precip total for f{forecast_hour:03d}")
                return cached_precip
        
        if forecast_hour == 0:
            # No accumulation at f000
            ds0 = self.fetch_raw_data(run_time, 0, {"tp", "prate"}, subset_region)
            base = ds0['tp'] if 'tp' in ds0 else ds0['prate']
            result = base.squeeze() * 0.0
            self._accumulation_cache[cache_key] = (result, None)
            return result
        
        if self.model_config.tp_is_accumulated_from_init:
            # Cumulative: tp(fH) already represents 0→H, no incremental needed
            logger.info(f"    Using accumulated precip (cumulative from init)")
            ds_target = self.fetch_raw_data(run_time, forecast_hour, {"tp"}, subset_region)
            if 'tp' not in ds_target:
                raise ValueError(f"No tp in f{forecast_hour:03d}")
            
            tp = ds_target['tp'].squeeze()
            drop_coords = [c for c in ['time', 'valid_time', 'step'] if c in tp.coords]
            if drop_coords:
                tp = tp.drop_vars(drop_coords)
            
            self._accumulation_cache[cache_key] = (tp, None)
            return tp
        
        else:
            # Bucketed: compute full accumulation from f000 to forecast_hour
            # This is necessary because maps are generated in parallel (not sequentially),
            # so we can't rely on previous hours being in the cache
            logger.info(f"    Computing bucketed precip: summing all buckets from f000 to f{forecast_hour:03d}")
            
            precip_total = None
            increment = self.model_config.forecast_increment

            def _drop_timeish(da: xr.DataArray) -> xr.DataArray:
                drop_coords = [c for c in ['time', 'valid_time', 'step'] if c in da.coords]
                if drop_coords:
                    da = da.drop_vars(drop_coords)
                return da.squeeze()

            def _to_mm(da: xr.DataArray) -> xr.DataArray:
                units = (da.attrs.get('units') or '').lower()
                if units in ('m', 'meter', 'meters'):
                    return da * 1000.0
                if units in ('mm', 'millimeter', 'millimeters'):
                    return da
                # Heuristic: if max < 5, likely meters
                return (da * 1000.0) if float(da.max()) < 5.0 else da
            
            # Loop through all forecast hours from increment to forecast_hour
            # (skip f000 which has zero precip)
            for fh in range(increment, forecast_hour + increment, increment):
                if fh > forecast_hour:
                    break
                    
                try:
                    ds = self.fetch_raw_data(run_time, fh, {"apcp"}, subset_region)

                    if 'apcp' in ds:
                        p = _to_mm(_drop_timeish(ds['apcp']))
                    elif 'tp' in ds:
                        p = _to_mm(_drop_timeish(ds['tp']))
                    else:
                        logger.warning(f"      No apcp/tp in f{fh:03d}, skipping")
                        continue

                    if precip_total is None:
                        precip_total = p.copy(deep=True)
                    else:
                        precip_total = precip_total + p
                    
                    logger.debug(f"      Added bucket f{fh:03d}")
                
                except FileNotFoundError:
                    logger.warning(f"      f{fh:03d} not found, skipping")
                except Exception as e:
                    logger.error(f"      Error fetching f{fh:03d}: {e}")
            
            if precip_total is None:
                raise ValueError(f"No precipitation data available from f000 to f{forecast_hour:03d}")
            
            # Cache the result
            self._accumulation_cache[cache_key] = (precip_total, None)
            return precip_total
    
    def _compute_total_snowfall(
        self,
        run_time: datetime,
        forecast_hour: int,
        subset_region: bool = True
    ) -> xr.DataArray:
        """
        Compute total snowfall from hour 0 to forecast_hour using 10:1 ratio.
        
        **OPTIMIZED**: Uses incremental accumulation to avoid O(H²) complexity.
        
        Two approaches based on model capabilities:
        
        GFS (has_precip_type_masks=True):
          - Uses native CSNOW field (categorical snow mask)
          - Direct classification from model output
          
        AIGFS (has_precip_type_masks=False):
          - Derives snow fraction from T850 and T2m
          - Temperature-based classification: <= -2°C = 100% snow, >= +1°C = 0% snow
        
        Returns:
            DataArray with total snowfall in inches (10:1 ratio), 2D grid (lat, lon)
        """
        
        run_time_str = run_time.strftime("%Y%m%d_%H")
        
        # Ensure cache is for current run
        if self._current_run_time_str != run_time_str:
            logger.info(f"    New run detected ({run_time_str}), clearing accumulation cache")
            self._accumulation_cache.clear()
            self._current_run_time_str = run_time_str
        
        # Check if we already computed this
        cache_key = (run_time_str, forecast_hour)
        if cache_key in self._accumulation_cache:
            _, cached_snow = self._accumulation_cache[cache_key]
            if cached_snow is not None:
                logger.info(f"    Using cached snowfall total for f{forecast_hour:03d}")
                return cached_snow
        
        # Helper functions
        def _drop_timeish(da: xr.DataArray) -> xr.DataArray:
            """Drop time-related coordinates and squeeze singleton dims"""
            drop_coords = [c for c in ['time', 'valid_time', 'step'] if c in da.coords]
            if drop_coords:
                da = da.drop_vars(drop_coords)
            return da.squeeze()
        
        def _get_bucket_precip_mm(ds: xr.Dataset) -> xr.DataArray:
            """Extract precipitation and convert to mm"""
            if 'tp' in ds:
                p = ds['tp']
            elif 'apcp' in ds:
                p = ds['apcp']
            elif 'APCP_surface' in ds:
                p = ds['APCP_surface']
            else:
                cand = [v for v in ds.data_vars if v.lower() in ('tp', 'apcp') or 'apcp' in v.lower()]
                if not cand:
                    raise ValueError("No precip field found (tp/apcp)")
                p = ds[cand[0]]
            
            p = _drop_timeish(p)
            
            # Unit handling
            units = (p.attrs.get('units') or '').lower()
            if units in ('m', 'meter', 'meters'):
                p_mm = p * 1000.0
            elif units in ('mm', 'millimeter', 'millimeters'):
                p_mm = p
            else:
                # Heuristic: GRIB precip often in meters; if max < 5 => probably meters
                p_mm = (p * 1000.0) if float(p.max()) < 5.0 else p
            
            return p_mm
        
        def _to_celsius(temp_k_or_c: xr.DataArray) -> xr.DataArray:
            """Convert temperature to Celsius"""
            t = _drop_timeish(temp_k_or_c)
            # Heuristic: Kelvin if values typically > 100
            return (t - 273.15) if float(t.max()) > 100.0 else t

        
        def _snow_fraction_from_thermal(t850_c: xr.DataArray, t2m_c: xr.DataArray | None) -> xr.DataArray:
            """
            AIGFS fallback: derive snow fraction from temperature.
            
            Core logic: piecewise-linear ramp based on T850:
              <= -2°C => 1.0 (100% snow)
              >= +1°C => 0.0 (0% snow)
              Between => linear interpolation
            
            Optional surface penalty: suppress snow where T2m is clearly warm
            """
            # Piecewise-linear ramp
            snow_frac = xr.where(
                t850_c <= -2.0, 1.0,
                xr.where(
                    t850_c >= 1.0, 0.0,
                    (1.0 - (t850_c - (-2.0)) / (1.0 - (-2.0)))  # maps -2->1.0, +1->0.0
                )
            )
            
            if t2m_c is not None:
                # Surface warm penalty: >= +3°C forces 0, 0-3°C tapers down
                warm_penalty = xr.where(
                    t2m_c >= 3.0, 0.0,
                    xr.where(
                        t2m_c <= 0.0, 1.0,
                        (1.0 - (t2m_c / 3.0))
                    )
                )
                snow_frac = snow_frac * warm_penalty
            
            # Clamp to valid range
            snow_frac = snow_frac.clip(0.0, 1.0)
            return snow_frac
        
        # Main logic
        
        # f000 => no accumulation
        if forecast_hour == 0:
            ds0 = self.fetch_raw_data(run_time, 0, {'tmp2m', 't2m'}, subset_region)
            base = ds0['t2m'] if 't2m' in ds0 else ds0['tmp2m']
            base = _drop_timeish(base)
            result = base * 0.0
            # Cache both precip and snow as zeros
            precip_cached, _ = self._accumulation_cache.get(cache_key, (None, None))
            self._accumulation_cache[cache_key] = (precip_cached, result)
            return result

        if self.model_id == "HRRR":
            logger.info("    Using APCP * 10 with CSNOW mask (HRRR path)")

            snow_liq_mm_total = None
            increment = self.model_config.forecast_increment
            hours_to_process = list(range(increment, forecast_hour + increment, increment))
            logger.info(f"    Accumulating HRRR snowfall from f000 through {hours_to_process}")

            for fh in hours_to_process:
                try:
                    ds = self.fetch_raw_data(run_time, fh, {'apcp', 'csnow'}, subset_region)

                    p_mm = _get_bucket_precip_mm(ds)

                    if 'csnow' not in ds:
                        logger.warning(f"CSNOW missing at f{fh:03d}, skipping bucket")
                        if snow_liq_mm_total is None:
                            raise ValueError(f"No snowfall data for f{fh:03d}")
                        continue

                    # Normalize csnow to [0,1]
                    cs = _drop_timeish(ds['csnow'])
                    cs_units = (cs.attrs.get('units') or '').lower()
                    if cs_units in ('%', 'percent'):
                        cs_frac = (cs / 100.0)
                    else:
                        cs_frac = (cs / 100.0) if float(cs.max()) > 1.5 else cs
                    cs_frac = cs_frac.clip(0.0, 1.0)

                    snow_bucket_mm = p_mm * cs_frac

                    snow_liq_mm_total = (snow_bucket_mm.copy(deep=True) if snow_liq_mm_total is None
                                        else (snow_liq_mm_total + snow_bucket_mm))

                except FileNotFoundError:
                    logger.warning(f"Data not found for f{fh:03d}")
                    if snow_liq_mm_total is None:
                        raise ValueError(f"No snowfall data for f{fh:03d}")
                except Exception as e:
                    logger.error(f"Error computing HRRR snowfall for f{fh:03d}: {e}")
                    if snow_liq_mm_total is None:
                        raise

            if snow_liq_mm_total is None:
                raise ValueError(f"No snowfall/precip data available up to f{forecast_hour:03d}")

            snow_in_10to1 = (snow_liq_mm_total / 25.4) * 10.0
            snow_in_10to1 = _drop_timeish(snow_in_10to1)

            precip_cached, _ = self._accumulation_cache.get(cache_key, (None, None))
            self._accumulation_cache[cache_key] = (precip_cached, snow_in_10to1)
            return snow_in_10to1
        
        # Try to get previous accumulation for incremental update
        prev_hour = forecast_hour - self.model_config.forecast_increment
        prev_key = (run_time_str, prev_hour)
        
        snow_liq_mm_total = None
        hours_to_process = []
        
        if prev_hour > 0 and prev_key in self._accumulation_cache:
            _, snow_prev_in = self._accumulation_cache[prev_key]
            if snow_prev_in is not None:
                logger.info(f"    Reusing f{prev_hour:03d} snowfall, adding f{forecast_hour:03d} bucket")
                # Convert previous snow (in inches) back to liquid mm for accumulation
                snow_liq_mm_total = (snow_prev_in / 10.0) * 25.4  # inches -> mm liquid
                # Only process the current bucket
                hours_to_process = [forecast_hour]
        
        # If no cached data, accumulate from all hours
        if not hours_to_process:
            increment = self.model_config.forecast_increment
            hours_to_process = list(range(increment, forecast_hour + increment, increment))
            logger.info(f"    No cache, accumulating snowfall from f000 through {hours_to_process}")
        
        # Process each forecast hour bucket
        for fh in hours_to_process:
            # Branch: model has native precip-type masks?
            if self.model_config.has_precip_type_masks:
                # -------- GFS PATH (native csnow) --------
                logger.info(f"    Using native CSNOW mask (GFS path) for f{fh:03d}")
                
                try:
                    ds = self.fetch_raw_data(run_time, fh, {'apcp', 'csnow'}, subset_region)
                    
                    p_mm = _get_bucket_precip_mm(ds)
                    
                    if 'csnow' not in ds:
                        # Model claims masks but csnow missing => treat as no-snow for this bucket
                        logger.warning(f"CSNOW missing at f{fh:03d}, skipping bucket")
                        if snow_liq_mm_total is None:
                            raise ValueError(f"No snowfall data for f{fh:03d}")
                    else:
                        cs = _drop_timeish(ds['csnow'])
                        
                        # Normalize csnow to [0,1]
                        cs_units = (cs.attrs.get('units') or '').lower()
                        if cs_units in ('%', 'percent'):
                            cs_frac = (cs / 100.0)
                        else:
                            # Heuristic: if max > 1.5 => likely 0-100 scale
                            cs_frac = (cs / 100.0) if float(cs.max()) > 1.5 else cs
                        
                        cs_frac = cs_frac.clip(0.0, 1.0)
                        
                        snow_bucket_mm = p_mm * cs_frac
                        
                        snow_liq_mm_total = (snow_bucket_mm.copy(deep=True) if snow_liq_mm_total is None 
                                            else (snow_liq_mm_total + snow_bucket_mm))
                
                except FileNotFoundError:
                    logger.warning(f"Data not found for f{fh:03d}")
                    if snow_liq_mm_total is None:
                        raise ValueError(f"No snowfall data for f{fh:03d}")
                except Exception as e:
                    logger.error(f"Error computing snowfall (mask path) for f{fh:03d}: {e}")
                    if snow_liq_mm_total is None:
                        raise
            
            else:
                # -------- AIGFS PATH (derive snow fraction from temperature) --------
                logger.info(f"    Deriving snow fraction from T850/T2m (AIGFS path) for f{fh:03d}")
            
            try:
                # Need precip from surface and thermal from pressure levels
                ds_sfc = self.fetch_raw_data(run_time, fh, {'tp', 'apcp', 'tmp2m', 't2m'}, subset_region)
                ds_pres = self.fetch_raw_data(run_time, fh, {'tmp_850'}, subset_region)
                
                p_mm = _get_bucket_precip_mm(ds_sfc)
                
                if 'tmp_850' not in ds_pres:
                    # Cannot classify without T850; skip bucket
                    logger.warning(f"tmp_850 missing at f{fh:03d}, skipping bucket")
                    if snow_liq_mm_total is None:
                        raise ValueError(f"No snowfall data for f{fh:03d}")
                else:
                    t850_c = _to_celsius(ds_pres['tmp_850'])
                    
                    # Optional 2m temp if present
                    t2m = None
                    if 't2m' in ds_sfc:
                        t2m = ds_sfc['t2m']
                    elif 'tmp2m' in ds_sfc:
                        t2m = ds_sfc['tmp2m']
                    
                    t2m_c = _to_celsius(t2m) if t2m is not None else None
                    
                    snow_frac = _snow_fraction_from_thermal(t850_c, t2m_c)
                    
                    # Align grids if needed (in case pressure/surface coords differ)
                    if (snow_frac.shape != p_mm.shape) or (set(snow_frac.coords.keys()) != set(p_mm.coords.keys())):
                        logger.debug(f"Interpolating snow_frac to match precip grid")
                        snow_frac = snow_frac.interp_like(p_mm, method="linear")
                    
                    snow_bucket_mm = p_mm * snow_frac
                    
                    snow_liq_mm_total = (snow_bucket_mm.copy(deep=True) if snow_liq_mm_total is None 
                                        else (snow_liq_mm_total + snow_bucket_mm))
            
            except FileNotFoundError:
                logger.warning(f"Data not found for f{fh:03d}")
                if snow_liq_mm_total is None:
                    raise ValueError(f"No snowfall data for f{fh:03d}")
            except Exception as e:
                logger.error(f"Error computing snowfall (thermal path) for f{fh:03d}: {e}")
                if snow_liq_mm_total is None:
                    raise
        
        if snow_liq_mm_total is None:
            raise ValueError(f"No snowfall/precip data available up to f{forecast_hour:03d}")
        
        # Convert liquid-equivalent mm to inches of snow at 10:1 ratio
        # snow_in = (mm_liq / 25.4) * 10
        snow_in_10to1 = (snow_liq_mm_total / 25.4) * 10.0
        
        # Final cleanup of time-like coords
        snow_in_10to1 = _drop_timeish(snow_in_10to1)
        
        # Cache the result
        precip_cached, _ = self._accumulation_cache.get(cache_key, (None, None))
        self._accumulation_cache[cache_key] = (precip_cached, snow_in_10to1)
        
        return snow_in_10to1
    
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
