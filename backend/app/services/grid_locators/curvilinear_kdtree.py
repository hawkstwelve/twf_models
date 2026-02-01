"""Grid locator for true curvilinear grids (fallback)."""

import logging
from typing import Dict, List, Optional
import xarray as xr
import numpy as np
from scipy.spatial import cKDTree
from .base import GridLocator

logger = logging.getLogger(__name__)


class CurvilinearKDTreeLocator(GridLocator):
    """Locator for curvilinear grids using KDTree nearest neighbor."""
    
    def __init__(self):
        self._kdtree_cache: Optional[cKDTree] = None
        self._grid_shape_cache: Optional[tuple] = None
        self._uses_360_lon: Optional[bool] = None
    
    @classmethod
    def can_handle(cls, ds: xr.Dataset) -> bool:
        """Check if dataset has 2D lat/lon without 1D x/y."""
        lat_coord = 'latitude' if 'latitude' in ds.coords else 'lat'
        lon_coord = 'longitude' if 'longitude' in ds.coords else 'lon'
        
        if lat_coord not in ds.coords or lon_coord not in ds.coords:
            return False
        
        # Must have 2D lat/lon (curvilinear coordinates)
        return (ds.coords[lat_coord].ndim == 2 and
            ds.coords[lon_coord].ndim == 2)
    
    def _build_kdtree(self, ds: xr.Dataset) -> cKDTree:
        """Build KDTree from flattened lat/lon coordinates."""
        if self._kdtree_cache is not None:
            return self._kdtree_cache
        
        lat_coord = 'latitude' if 'latitude' in ds.coords else 'lat'
        lon_coord = 'longitude' if 'longitude' in ds.coords else 'lon'
        
        lats = ds.coords[lat_coord].values
        lons = ds.coords[lon_coord].values
        self._uses_360_lon = (np.nanmin(lons) >= 0) and (np.nanmax(lons) > 180)
        
        # Store grid shape for index reconstruction
        self._grid_shape_cache = lats.shape
        
        # Flatten and stack coordinates
        lats_flat = lats.flatten()
        lons_flat = lons.flatten()
        coords = np.column_stack([lats_flat, lons_flat])
        
        # Build KDTree
        self._kdtree_cache = cKDTree(coords)
        logger.debug(f"Built KDTree with {len(coords)} grid points")
        
        return self._kdtree_cache
    
    def sample(self, ds: xr.Dataset, variable: str, 
               stations: List['Station']) -> Dict[str, float]:
        """Sample using KDTree nearest neighbor search."""
        if variable not in ds:
            raise ValueError(f"Variable {variable} not in dataset")
        
        kdtree = self._build_kdtree(ds)
        uses_360_lon = self._uses_360_lon
        
        # Get dimension names from 2D lat coord
        lat_coord = 'latitude' if 'latitude' in ds.coords else 'lat'
        dim_names = ds.coords[lat_coord].dims
        
        values = {}
        for station in stations:
            try:
                # Find nearest grid point
                station_lon = station.lon
                if uses_360_lon and station_lon < 0:
                    station_lon = station_lon % 360
                elif uses_360_lon is False and station_lon > 180:
                    station_lon = station_lon - 360

                station_coords = np.array([[station.lat, station_lon]])
                _, idx = kdtree.query(station_coords, k=1)
                
                # Convert flat index to 2D indices
                idx_2d = np.unravel_index(idx[0], self._grid_shape_cache)
                
                # Extract value using 2D indices
                value = ds[variable].isel({
                    dim_names[0]: idx_2d[0],
                    dim_names[1]: idx_2d[1]
                }).values
                
                if hasattr(value, 'item'):
                    value = value.item()
                
                values[station.id] = float(value)
                
            except Exception as e:
                logger.warning(f"Could not sample station {station.id}: {e}")
                continue
        
        return values
