"""Grid locator for projected rectilinear grids (HRRR, RAP, NAM)."""

import logging
from typing import Dict, List, Optional
import xarray as xr
import pyproj
import numpy as np
from .base import GridLocator

logger = logging.getLogger(__name__)


class ProjectedXYLocator(GridLocator):
    """Locator for projected grids with 1D x/y coordinates."""
    
    def __init__(self):
        # Cache projection and transformer per dataset signature
        # Key: (x_size, y_size, grid_mapping_name)
        self._projection_cache: Dict[tuple, pyproj.CRS] = {}
        self._transformer_cache: Dict[tuple, pyproj.Transformer] = {}
    
    @classmethod
    def can_handle(cls, ds: xr.Dataset) -> bool:
        """Check if dataset has 1D x/y coordinates (projected grid)."""
        return ('x' in ds.coords and 'y' in ds.coords and
                ds.coords['x'].ndim == 1 and ds.coords['y'].ndim == 1)
    
    def _detect_projection(self, ds: xr.Dataset, variable: str) -> pyproj.CRS:
        """
        Detect projection with CF-compliant fallback strategy.
        
        Priority:
        1. CF grid_mapping variable from target variable (correct CF pattern)
        2. CF grid_mapping variable from any variable (fallback scan)
        3. MetPy parsing (if available)
        4. Known grid fallback (HRRR Lambert Conformal)
        """
        # Try CF standard: grid_mapping attr on data variable -> grid mapping variable
        if variable in ds:
            da = ds[variable]
            grid_mapping_name = da.attrs.get('grid_mapping')
            
            if grid_mapping_name and grid_mapping_name in ds:
                gm_var = ds[grid_mapping_name]
                
                # Prefer crs_wkt if present (more reliable)
                if 'crs_wkt' in gm_var.attrs:
                    try:
                        crs = pyproj.CRS.from_wkt(gm_var.attrs['crs_wkt'])
                        logger.debug(f"Detected projection from crs_wkt: {crs}")
                        return crs
                    except Exception as e:
                        logger.debug(f"crs_wkt parse failed: {e}")
                
                # Fall back to CF attributes
                try:
                    crs = pyproj.CRS.from_cf(gm_var.attrs)
                    logger.debug(f"Detected projection from CF attrs: {crs}")
                    return crs
                except (KeyError, ValueError) as e:
                    logger.debug(f"CF grid_mapping parse failed: {e}")
        
        # Fallback: Scan all variables for grid_mapping attribute
        # Some GRIB→xarray stacks attach grid mapping to coords or other vars
        for var_name in ds.variables:
            grid_mapping_name = ds[var_name].attrs.get('grid_mapping')
            if grid_mapping_name and grid_mapping_name in ds:
                gm_var = ds[grid_mapping_name]
                logger.debug(f"Found grid_mapping on {var_name}, not target variable")
                
                if 'crs_wkt' in gm_var.attrs:
                    try:
                        crs = pyproj.CRS.from_wkt(gm_var.attrs['crs_wkt'])
                        logger.debug(f"Detected projection from fallback scan: {crs}")
                        return crs
                    except Exception as e:
                        pass
                
                try:
                    crs = pyproj.CRS.from_cf(gm_var.attrs)
                    logger.debug(f"Detected projection from fallback scan: {crs}")
                    return crs
                except (KeyError, ValueError):
                    pass
        
        # Try MetPy if available
        try:
            from metpy.crs import CFProjection
            # MetPy can extract projection from GRIB attributes
            # Implementation depends on MetPy availability
            pass
        except ImportError:
            logger.debug("MetPy not available for projection detection")
        
        # Fallback: Known grid parameters (HRRR/RAP)
        if self._looks_like_hrrr_or_rap(ds):
            crs = self._hrrr_projection()
            logger.warning(
                f"Using fallback HRRR/RAP projection (CF parsing failed): {crs}. "
                "Verify this matches your GRIB source projection."
            )
            return crs
        
        raise ValueError("Cannot determine projection from dataset")
    
    def _looks_like_hrrr_or_rap(self, ds: xr.Dataset) -> bool:
        """Check if dataset appears to be HRRR or RAP."""
        # Check for typical HRRR/RAP dimensions and attributes
        if 'x' in ds.dims and 'y' in ds.dims:
            # HRRR typically has ~1800x1060 grid
            x_size = ds.dims['x']
            y_size = ds.dims['y']
            if 1000 < x_size < 2000 and 800 < y_size < 1200:
                return True
        return False
    
    def _hrrr_projection(self) -> pyproj.CRS:
        """Return known HRRR Lambert Conformal projection.
        
        Note: Uses specific spherical Earth radius (R=6371229) and LCC parameters.
        Verify these match your GRIB source if fallback is used frequently.
        """
        return pyproj.CRS.from_proj4(
            "+proj=lcc +lat_1=38.5 +lat_2=38.5 +lat_0=38.5 "
            "+lon_0=-97.5 +x_0=0 +y_0=0 +R=6371229 +units=m +no_defs"
        )
    
    def _get_dataset_signature(self, ds: xr.Dataset, variable: str) -> tuple:
        """Generate cache key for dataset projection."""
        x_size = ds.dims['x']
        y_size = ds.dims['y']
        
        # Try to get grid mapping name for cache key
        grid_mapping = ''
        if variable in ds:
            grid_mapping = ds[variable].attrs.get('grid_mapping', '')
        
        return (x_size, y_size, grid_mapping)
    
    def _get_transformer(self, ds: xr.Dataset, variable: str) -> pyproj.Transformer:
        """Get cached transformer from WGS84 to dataset projection.
        
        Caches per dataset signature to avoid applying wrong CRS when
        same locator instance is reused across different runs/grids.
        """
        sig = self._get_dataset_signature(ds, variable)
        
        if sig not in self._transformer_cache:
            # Get or detect projection for this dataset
            if sig not in self._projection_cache:
                self._projection_cache[sig] = self._detect_projection(ds, variable)
            
            # Create transformer from WGS84 (lon, lat) to projection (x, y)
            wgs84 = pyproj.CRS.from_epsg(4326)
            self._transformer_cache[sig] = pyproj.Transformer.from_crs(
                wgs84, self._projection_cache[sig], always_xy=True
            )
        
        return self._transformer_cache[sig]
    
    def sample(self, ds: xr.Dataset, variable: str, 
               stations: List['Station']) -> Dict[str, float]:
        """Sample using projection transform + x/y selection."""
        if variable not in ds:
            raise ValueError(f"Variable {variable} not in dataset")
        
        transformer = self._get_transformer(ds, variable)
        
        values = {}
        for station in stations:
            try:
                # Transform (lon, lat) to (x, y) in projection
                x_proj, y_proj = transformer.transform(station.lon, station.lat)
                
                # Sample using x/y coordinates
                value = ds[variable].sel(
                    {'x': x_proj, 'y': y_proj},
                    method='nearest'
                ).values
                
                if hasattr(value, 'item'):
                    value = value.item()
                
                values[station.id] = float(value)
                
            except Exception as e:
                logger.warning(f"Could not sample station {station.id}: {e}")
                continue
        
        return values
