"""NOMADS-based data fetcher for models using NCEP NOMADS"""
from datetime import datetime
from typing import Set
import xarray as xr
import logging
import requests
import hashlib
import os
import time

from app.services.base_data_fetcher import BaseDataFetcher
from app.models.model_registry import ModelProvider, URLLayout

logger = logging.getLogger(__name__)


class NOMADSDataFetcher(BaseDataFetcher):
    """Data fetcher for models hosted on NOMADS"""
    
    def __init__(self, model_id: str):
        super().__init__(model_id)
        
        # Verify this is a NOMADS model
        if self.model_config.provider != ModelProvider.NOMADS:
            raise ValueError(f"Model {model_id} is not a NOMADS model")
    
    def fetch_raw_data(
        self,
        run_time: datetime,
        forecast_hour: int,
        raw_fields: Set[str],
        subset_region: bool = True
    ) -> xr.Dataset:
        """Fetch raw GRIB fields from NOMADS"""
        
        date_str = run_time.strftime("%Y%m%d")
        run_hour_str = run_time.strftime("%H")
        
        # Determine if this is analysis (f000) and model has special analysis file
        is_analysis = (forecast_hour == 0) and self.model_config.has_analysis_file
        
        # Build URL based on model's URL layout
        file_url = self._build_nomads_url(
            date_str=date_str,
            run_hour=run_hour_str,
            forecast_hour=forecast_hour,
            is_analysis=is_analysis,
            raw_fields=raw_fields,
            subset_region=subset_region
        )
        
        logger.info(f"{self.model_id} URL: {file_url}")
        
        # Cache and download
        url_hash = hashlib.sha1(file_url.encode()).hexdigest()[:16]
        cache_key = f"{self.model_id.lower()}_{url_hash}"
        tmp_path = self._get_cached_grib_path(cache_key)
        
        if not tmp_path:
            tmp_path = self._download_from_nomads(file_url, cache_key)
        else:
            logger.info(f"  Using cached file")
        
        # Open GRIB file
        ds = self._open_grib_file(tmp_path, forecast_hour, raw_fields, subset_region)
        
        return ds
    
    def _build_nomads_url(
        self,
        date_str: str,
        run_hour: str,
        forecast_hour: int,
        is_analysis: bool,
        raw_fields: Set[str],
        subset_region: bool
    ) -> str:
        """
        Build NOMADS URL based on model configuration.
        Handles different URL layouts (GFS, AIGFS, HRRR, etc.)
        """
        forecast_hour_str = f"{forecast_hour:03d}"
        
        # Get product pattern (default to first available, usually "sfc")
        # For more complex models, may need to determine which product based on fields
        product_name = list(self.model_config.products.keys())[0]
        product = self.model_config.products[product_name]
        
        # Determine file pattern
        if is_analysis and self.model_config.analysis_pattern:
            file_pattern = self.model_config.analysis_pattern.format(run_hour=run_hour)
        else:
            file_pattern = product.file_pattern.format(
                run_hour=run_hour,
                forecast_hour=forecast_hour_str
            )
        
        # Build subdirectory path based on layout
        subdir = self.model_config.subdir_template.format(
            model=self.model_id.lower(),
            date=date_str,
            hour=run_hour
        )
        
        # Decide: filter or direct download
        if (self.model_config.use_filter and 
            product.filter_script and 
            subset_region and 
            raw_fields):
            # Use filter CGI
            return self._build_filter_url(
                date_str, run_hour, forecast_hour_str,
                is_analysis, product, subdir, file_pattern,
                raw_fields, subset_region
            )
        else:
            # Direct file download
            base_url = "https://nomads.ncep.noaa.gov/pub/data/nccf/com"
            return f"{base_url}/{self.model_config.nomads_base_path}/{subdir}/{file_pattern}"
    
    def _build_filter_url(
        self,
        date_str: str,
        run_hour: str,
        forecast_hour_str: str,
        is_analysis: bool,
        product,
        subdir: str,
        file_pattern: str,
        raw_fields: Set[str],
        subset_region: bool
    ) -> str:
        """Build NOMADS filter CGI URL"""
        
        base_url = f"https://nomads.ncep.noaa.gov/cgi-bin/{product.filter_script}"
        
        # File parameter
        file_param = f"{subdir}/{file_pattern}"
        
        # Variable mapping
        var_params = self._map_fields_to_grib_params(raw_fields)
        
        # Build params dict
        params = {'file': file_param}
        params.update(var_params)
        
        # Region subsetting
        if subset_region:
            from app.config import settings
            bounds = settings.map_region_bounds or {
                "west": -125.0, "east": -110.0,
                "south": 42.0, "north": 49.0
            }
            buffer = 4.0
            
            params.update({
                'subregion': '',
                'leftlon': str(bounds['west'] - buffer),
                'rightlon': str(bounds['east'] + buffer),
                'toplat': str(bounds['north'] + buffer),
                'bottomlat': str(bounds['south'] - buffer),
            })
        
        # Build URL
        url_parts = [f"{k}={v}" for k, v in params.items() if v]
        return base_url + "?" + "&".join(url_parts)
    
    def _map_fields_to_grib_params(self, raw_fields: Set[str]) -> dict:
        """Map our field names to NOMADS filter CGI parameters"""
        params = {}
        
        level_groups = {
            'surface': set(),
            '2m': set(),
            '10m': set(),
            'msl': set(),
            'atmosphere': set(),
            'isobaric': {}  # level -> vars
        }
        
        # Group fields by level
        for field in raw_fields:
            if field in ['tmp2m', 't2m']:
                level_groups['2m'].add('TMP')
            elif field in ['ugrd10m', 'u10']:
                level_groups['10m'].add('UGRD')
            elif field in ['vgrd10m', 'v10']:
                level_groups['10m'].add('VGRD')
            elif field in ['prmsl', 'msl']:
                level_groups['msl'].add('PRMSL')
            elif field in ['tp', 'prate', 'apcp']:
                level_groups['surface'].add('APCP')
                level_groups['surface'].add('PRATE')
            elif field in ['refc']:
                level_groups['atmosphere'].add('REFC')
            elif field in ['crain', 'csnow', 'cicep', 'cfrzr']:
                level_groups['surface'].add('CRAIN')
                level_groups['surface'].add('CSNOW')
                level_groups['surface'].add('CICEP')
                level_groups['surface'].add('CFRZR')
            elif field == 'tmp_850':
                if 850 not in level_groups['isobaric']:
                    level_groups['isobaric'][850] = set()
                level_groups['isobaric'][850].add('TMP')
            elif field == 'ugrd_850':
                if 850 not in level_groups['isobaric']:
                    level_groups['isobaric'][850] = set()
                level_groups['isobaric'][850].add('UGRD')
            elif field == 'vgrd_850':
                if 850 not in level_groups['isobaric']:
                    level_groups['isobaric'][850] = set()
                level_groups['isobaric'][850].add('VGRD')
            elif field in ['gh_500', 'hgt_500']:
                if 500 not in level_groups['isobaric']:
                    level_groups['isobaric'][500] = set()
                level_groups['isobaric'][500].add('HGT')
            elif field in ['gh_1000', 'hgt_1000']:
                if 1000 not in level_groups['isobaric']:
                    level_groups['isobaric'][1000] = set()
                level_groups['isobaric'][1000].add('HGT')
        
        # Build filter params
        if level_groups['surface']:
            params['lev_surface'] = 'on'
            for var in level_groups['surface']:
                params[f'var_{var}'] = 'on'
        
        if level_groups['2m']:
            params['lev_2_m_above_ground'] = 'on'
            for var in level_groups['2m']:
                params[f'var_{var}'] = 'on'
        
        if level_groups['10m']:
            params['lev_10_m_above_ground'] = 'on'
            for var in level_groups['10m']:
                params[f'var_{var}'] = 'on'
        
        if level_groups['msl']:
            params['lev_mean_sea_level'] = 'on'
            for var in level_groups['msl']:
                params[f'var_{var}'] = 'on'
        
        if level_groups['atmosphere']:
            params['lev_entire_atmosphere'] = 'on'
            for var in level_groups['atmosphere']:
                params[f'var_{var}'] = 'on'
        
        for level, vars in level_groups['isobaric'].items():
            params[f'lev_{level}_mb'] = 'on'
            for var in vars:
                params[f'var_{var}'] = 'on'
        
        return params
    
    def _download_from_nomads(self, url: str, cache_key: str) -> str:
        """Download GRIB file from NOMADS with retry logic"""
        local_path = str(self._cache_dir / f"{cache_key}.grib2")
        
        max_retries = self.model_config.max_retries
        timeout = self.model_config.timeout
        
        for attempt in range(max_retries):
            try:
                logger.info(f"  Downloading (attempt {attempt + 1}/{max_retries})...")
                response = requests.get(url, timeout=timeout, stream=True)
                response.raise_for_status()
                
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # Cache it
                self._grib_cache[cache_key] = (local_path, os.path.getmtime(local_path))
                
                file_size_mb = os.path.getsize(local_path) / (1024 * 1024)
                logger.info(f"  Downloaded {file_size_mb:.1f} MB")
                
                return local_path
            
            except Exception as e:
                logger.warning(f"  Download attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff
        
        raise RuntimeError(f"Failed to download after {max_retries} attempts")
    
    def _open_grib_file(self, path: str, forecast_hour: int, raw_fields: Set[str], subset_region: bool) -> xr.Dataset:
        """
        Open GRIB file and extract needed variables.
        Shared logic for all NOMADS/GRIB2 models.
        """
        logger.info("Opening GRIB file with cfgrib...")
        
        all_data_vars = {}
        coords = None
        
        # Try different levels and step types
        # Surface level
        try:
            logger.info("Opening surface level...")
            surface_datasets = []
            
            if forecast_hour > 0:
                # Try accumulated first (precipitation priority)
                try:
                    ds_surf_accum = xr.open_dataset(
                        path,
                        engine='cfgrib',
                        backend_kwargs={'filter_by_keys': {
                            'typeOfLevel': 'surface',
                            'stepType': 'accum'
                        }},
                        decode_timedelta=False
                    )
                    ds_surf_accum = self._subset_dataset(ds_surf_accum)
                    surface_datasets.append(ds_surf_accum)
                    logger.info(f"    Accumulated: {list(ds_surf_accum.data_vars)}")
                except Exception as e:
                    logger.info(f"    Accumulated not available: {str(e)[:80]}")
                
                # Try instant
                try:
                    ds_surf_instant = xr.open_dataset(
                        path,
                        engine='cfgrib',
                        backend_kwargs={'filter_by_keys': {
                            'typeOfLevel': 'surface',
                            'stepType': 'instant'
                        }},
                        decode_timedelta=False
                    )
                    ds_surf_instant = self._subset_dataset(ds_surf_instant)
                    surface_datasets.append(ds_surf_instant)
                    logger.info(f"    Instant: {list(ds_surf_instant.data_vars)}")
                except Exception as e:
                    logger.info(f"    Instant not available: {str(e)[:80]}")
            else:
                ds_surface = xr.open_dataset(
                    path,
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
                path,
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
                path,
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
                path,
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
                path,
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
        
        # Try isobaricInhPa levels (upper air)
        needed_levels = set()
        for field in raw_fields:
            if field in ['gh_1000', 'hgt_1000']:
                needed_levels.add(1000)
            elif field in ['gh_500', 'hgt_500']:
                needed_levels.add(500)
            elif field in ['tmp_850', 'ugrd_850', 'vgrd_850']:
                needed_levels.add(850)
        
        if needed_levels:
            try:
                logger.info(f"Opening isobaricInhPa levels: {sorted(needed_levels)}")
                for level in sorted(needed_levels):
                    try:
                        logger.info(f"  Extracting level {level}mb...")
                        ds_level = xr.open_dataset(
                            path,
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
                                if v in ['t', 'tmp']:
                                    all_data_vars['tmp_850'] = ds_level[v].squeeze()
                                if v in ['u', 'ugrd']:
                                    all_data_vars['ugrd_850'] = ds_level[v].squeeze()
                                if v in ['v', 'vgrd']:
                                    all_data_vars['vgrd_850'] = ds_level[v].squeeze()
                        
                        if coords is None:
                            coords = {k: v for k, v in ds_level.coords.items() if k not in ['isobaricInhPa', 'level']}
                        ds_level.close()
                    except Exception as e:
                        logger.warning(f"  Could not extract at {level}mb: {str(e)[:100]}")
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
            ds[var_name] = var_data
        
        logger.info(f"Extracted variables: {list(ds.data_vars)}")
        return ds
