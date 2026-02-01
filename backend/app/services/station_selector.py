"""Station selection and decluttering for map overlays."""

import logging
import math
from typing import Dict, List, Optional, Tuple
from .station_catalog import Station

logger = logging.getLogger(__name__)


class StationSelector:
    """Selects and declutters stations for map rendering."""
    
    def __init__(self, bbox: Tuple[float, float, float, float], grid_size_px: float = 80.0):
        """
        Initialize selector.
        
        Args:
            bbox: Map viewport (west_lon, south_lat, east_lon, north_lat)
            grid_size_px: Minimum pixel spacing between stations (bbox-normalized)
        """
        self.bbox = bbox
        self.grid_size_px = grid_size_px
        
        # Calculate normalization factors
        self.lon_range = bbox[2] - bbox[0]  # east - west
        self.lat_range = bbox[3] - bbox[1]  # north - south
    
    def select_decluttered_stations(
        self,
        stations: List[Station],
        always_include_ids: List[str]
    ) -> List[Station]:
        """
        Select stations with grid-binning declutter.
        
        Algorithm: Bbox-normalized grid binning
        - Divide bbox into grid cells based on grid_size_px
        - Keep highest-weight station per cell
        - Force-include always_include stations regardless of weight
        
        Args:
            stations: Candidate stations (already filtered by region bbox)
            always_include_ids: Station IDs that must always appear
        
        Returns:
            Decluttered list of stations
        """
        if not stations:
            return []
        
        # Separate always_include stations from others
        always_include_set = set(always_include_ids)
        forced_stations = [s for s in stations if s.id in always_include_set]
        regular_stations = [s for s in stations if s.id not in always_include_set]
        
        logger.debug(f"Decluttering: {len(stations)} total, {len(forced_stations)} forced, {len(regular_stations)} regular")
        
        # Grid-binning for regular stations
        # Convert grid_size_px to normalized bbox units (0-1 range)
        # Assume 800px map width as baseline (rough estimate)
        map_width_px = 800.0
        grid_size_normalized_lon = (self.grid_size_px / map_width_px)
        grid_size_normalized_lat = (self.grid_size_px / map_width_px)
        
        # Calculate grid cell dimensions in degrees
        cell_width_deg = self.lon_range * grid_size_normalized_lon
        cell_height_deg = self.lat_range * grid_size_normalized_lat
        
        logger.debug(f"Grid cell size: {cell_width_deg:.3f}° lon × {cell_height_deg:.3f}° lat (grid_size_px={self.grid_size_px})")
        
        # Bin stations into grid cells
        grid: Dict[Tuple[int, int], Station] = {}
        
        for station in regular_stations:
            # Calculate grid cell indices
            col = int((station.lon - self.bbox[0]) / cell_width_deg)
            row = int((station.lat - self.bbox[1]) / cell_height_deg)
            cell_key = (col, row)
            
            # Keep highest-weight station per cell
            if cell_key not in grid or station.display_weight > grid[cell_key].display_weight:
                grid[cell_key] = station
        
        # Collect decluttered regular stations
        decluttered_regular = list(grid.values())
        
        # Combine forced + decluttered regular
        selected = forced_stations + decluttered_regular
        
        logger.info(f"Selected {len(selected)} stations after declutter ({len(forced_stations)} forced + {len(decluttered_regular)} decluttered from {len(regular_stations)} regular)")
        
        return selected
