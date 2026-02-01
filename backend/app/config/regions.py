"""Region definitions for map generation and station filtering."""

from typing import Dict, Tuple

# Coverage area for NWS API fetching
# Format: (west_lon, south_lat, east_lon, north_lat)
PNW_COVERAGE_BBOX = (-125.0, 42.0, -110.0, 49.0)

# Region definitions for map viewports
REGIONS = {
    'pnw_large': {
        'bbox': (-125.0, 42.0, -110.0, 49.0),  # (west, south, east, north)
        'name': 'Pacific Northwest',
        'description': 'Full PNW coverage: WA, OR, ID, western MT'
    },
    'puget_sound': {
        'bbox': (-123.5, 47.0, -121.0, 49.0),
        'name': 'Puget Sound Region',
        'description': 'Seattle metro and surrounding areas'
    },
    'willamette_valley': {
        'bbox': (-123.5, 43.5, -122.0, 45.8),
        'name': 'Willamette Valley',
        'description': 'Portland to Eugene corridor'
    },
}

def get_region_bbox(region_id: str) -> Tuple[float, float, float, float]:
    """
    Get bbox for a region.
    
    Args:
        region_id: Region identifier
    
    Returns:
        Tuple of (west_lon, south_lat, east_lon, north_lat)
    
    Raises:
        KeyError: If region not found
    """
    return REGIONS[region_id]['bbox']
