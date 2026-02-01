"""Grid locator for regular lat/lon grids (GFS, AIGFS)."""

import logging
from typing import Dict, List
import xarray as xr
from .base import GridLocator

logger = logging.getLogger(__name__)


class LatLon1DLocator(GridLocator):
    """Locator for regular lat/lon grids with 1D coordinates."""
    
    @classmethod
    def can_handle(cls, ds: xr.Dataset) -> bool:
        """Check if dataset has 1D lat/lon coordinates."""
        lat_coord = 'latitude' if 'latitude' in ds.coords else 'lat'
        lon_coord = 'longitude' if 'longitude' in ds.coords else 'lon'
        
        if lat_coord not in ds.coords or lon_coord not in ds.coords:
            return False
        
        return (ds.coords[lat_coord].ndim == 1 and 
                ds.coords[lon_coord].ndim == 1)
    
    def sample(self, ds: xr.Dataset, variable: str, 
               stations: List['Station']) -> Dict[str, float]:
        """Sample using .sel() with nearest neighbor."""
        if variable not in ds:
            raise ValueError(f"Variable {variable} not in dataset")
        
        # Detect coordinate names
        lat_name = 'latitude' if 'latitude' in ds.coords else 'lat'
        lon_name = 'longitude' if 'longitude' in ds.coords else 'lon'
        
        # Detect 0-360 longitude format
        lon_vals = ds.coords[lon_name].values
        uses_360 = lon_vals.min() >= 0 and lon_vals.max() > 180
        
        values = {}
        for station in stations:
            try:
                station_lon = station.lon
                if uses_360 and station_lon < 0:
                    station_lon = station_lon % 360
                
                value = ds[variable].sel(
                    {lat_name: station.lat, lon_name: station_lon},
                    method='nearest'
                ).values
                
                if hasattr(value, 'item'):
                    value = value.item()
                
                values[station.id] = float(value)
                
            except Exception as e:
                logger.warning(f"Could not sample station {station.id}: {e}")
                continue
        
        return values
