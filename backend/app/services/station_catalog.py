"""Station catalog loading and filtering."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Station:
    """Weather station with location and metadata."""
    id: str
    name: str
    lat: float
    lon: float  # Normalized to -180 to 180
    abbr: Optional[str] = None
    state: Optional[str] = None
    elevation_m: Optional[float] = None
    station_type: str = 'unknown'
    display_weight: float = 1.0
    
    def __post_init__(self):
        """Normalize longitude to -180 to 180 range."""
        if self.lon > 180:
            self.lon = self.lon - 360


class StationCatalog:
    """Manages loading and filtering of station catalog."""
    
    def __init__(self, cache_path: Optional[Path] = None, overrides_path: Optional[Path] = None):
        """
        Initialize catalog.
        
        Args:
            cache_path: Path to station cache JSON file
            overrides_path: Path to station overrides JSON file
        """
        if cache_path is None:
            # Default to backend/app/data/station_cache.json
            cache_path = Path(__file__).parent.parent / 'data' / 'station_cache.json'
        
        if overrides_path is None:
            overrides_path = cache_path.parent / 'station_overrides.json'
        
        self.cache_path = cache_path
        self.overrides_path = overrides_path
        self._stations: Optional[List[Station]] = None
        self._overrides: Optional[Dict] = None
    
    def load_from_cache(self, force_reload: bool = False) -> List[Station]:
        """
        Load stations from cached JSON file.
        
        Args:
            force_reload: Force reload even if already loaded
        
        Returns:
            List of Station objects
        
        Raises:
            FileNotFoundError: If cache file doesn't exist
        """
        if self._stations is not None and not force_reload:
            return self._stations
        
        if not self.cache_path.exists():
            raise FileNotFoundError(
                f"Station cache not found: {self.cache_path}. "
                f"Run scripts/fetch_stations.py to generate."
            )
        
        with open(self.cache_path, 'r') as f:
            data = json.load(f)
        
        station_dicts = data.get('stations', [])
        self._stations = [Station(**s) for s in station_dicts]
        
        logger.info(f"Loaded {len(self._stations)} stations from cache")
        return self._stations
    
    def load_overrides(self) -> Dict:
        """
        Load station overrides (always_include, weight_overrides, exclude).
        
        Returns:
            Dict with overrides, or empty dict if file doesn't exist
        """
        if self._overrides is not None:
            return self._overrides
        
        if not self.overrides_path.exists():
            logger.debug(f"No overrides file found: {self.overrides_path}")
            self._overrides = {'always_include': [], 'weight_overrides': {}, 'exclude': []}
            return self._overrides
        
        with open(self.overrides_path, 'r') as f:
            self._overrides = json.load(f)
        
        logger.info(f"Loaded station overrides: {len(self._overrides.get('weight_overrides', {}))} weight overrides, "
                   f"{len(self._overrides.get('always_include', []))} always_include, "
                   f"{len(self._overrides.get('exclude', []))} excluded")
        return self._overrides
    
    def apply_overrides(self, stations: List[Station]) -> List[Station]:
        """
        Apply overrides to stations: exclude list, weight bumps.
        
        Args:
            stations: List of stations to modify
        
        Returns:
            Modified list of stations (excludes removed, weights updated)
        """
        overrides = self.load_overrides()
        
        # Apply exclusions
        exclude_ids = set(overrides.get('exclude', []))
        stations = [s for s in stations if s.id not in exclude_ids]
        
        # Apply weight overrides
        weight_overrides = overrides.get('weight_overrides', {})
        for station in stations:
            if station.id in weight_overrides:
                station.display_weight = weight_overrides[station.id]
        
        return stations
    
    def get_always_include_ids(self) -> List[str]:
        """
        Get list of station IDs that should always be included.
        
        Returns:
            List of station IDs
        """
        overrides = self.load_overrides()
        return overrides.get('always_include', [])
    
    def filter_by_bbox(
        self,
        stations: List[Station],
        bbox: Tuple[float, float, float, float]
    ) -> List[Station]:
        """
        Filter stations within bbox.
        
        Args:
            stations: List of stations to filter
            bbox: (west_lon, south_lat, east_lon, north_lat)
        
        Returns:
            Filtered list of stations
        """
        west, south, east, north = bbox
        
        filtered = [
            s for s in stations
            if west <= s.lon <= east and south <= s.lat <= north
        ]
        
        logger.debug(f"Filtered {len(stations)} -> {len(filtered)} stations for bbox {bbox}")
        return filtered
    
    def get_stations_for_region(self, region_id: str) -> List[Station]:
        """
        Get stations for a named region with overrides applied.
        
        Args:
            region_id: Region identifier (e.g., 'pnw_large', 'puget_sound')
        
        Returns:
            List of stations in region (with overrides applied)
        """
        from app.config.regions import get_region_bbox
        
        stations = self.load_from_cache()
        stations = self.apply_overrides(stations)  # Apply excludes and weight bumps
        bbox = get_region_bbox(region_id)
        return self.filter_by_bbox(stations, bbox)
