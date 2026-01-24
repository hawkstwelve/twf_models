"""
Weather station data for map overlays.

Defines station locations and metadata for overlaying forecast values on maps.
"""

from typing import Dict, Any


# Major cities and weather stations in the Pacific Northwest
PNW_STATIONS = {
    'Seattle': {
        'lat': 47.61,
        'lon': -122.33,
        'abbr': 'SEA',
        'state': 'WA',
        'priority': 1  # 1 = major city, always show
    },
    'Portland': {
        'lat': 45.52,
        'lon': -122.68,
        'abbr': 'PDX',
        'state': 'OR',
        'priority': 1
    },
    'Spokane': {
        'lat': 47.66,
        'lon': -117.42,
        'abbr': 'GEG',
        'state': 'WA',
        'priority': 1
    },
    'Boise': {
        'lat': 43.62,
        'lon': -116.21,
        'abbr': 'BOI',
        'state': 'ID',
        'priority': 1
    },
    'Eugene': {
        'lat': 44.05,
        'lon': -123.09,
        'abbr': 'EUG',
        'state': 'OR',
        'priority': 2  # 2 = secondary, show on less busy maps
    },
    'Bend': {
        'lat': 44.06,
        'lon': -121.31,
        'abbr': 'BDN',
        'state': 'OR',
        'priority': 2
    },
    'Yakima': {
        'lat': 46.60,
        'lon': -120.51,
        'abbr': 'YKM',
        'state': 'WA',
        'priority': 2
    },
    'Tri-Cities': {
        'lat': 46.27,
        'lon': -119.28,
        'abbr': 'PSC',
        'state': 'WA',
        'priority': 2
    },
    'Bellingham': {
        'lat': 48.75,
        'lon': -122.49,
        'abbr': 'BLI',
        'state': 'WA',
        'priority': 2
    },
    'Olympia': {
        'lat': 47.04,
        'lon': -122.90,
        'abbr': 'OLM',
        'state': 'WA',
        'priority': 3  # 3 = tertiary, show only when space permits
    },
    'Salem': {
        'lat': 44.92,
        'lon': -123.04,
        'abbr': 'SLE',
        'state': 'OR',
        'priority': 3
    },
    'Medford': {
        'lat': 42.37,
        'lon': -122.87,
        'abbr': 'MFR',
        'state': 'OR',
        'priority': 3
    },
    'Lewiston': {
        'lat': 46.37,
        'lon': -117.02,
        'abbr': 'LWS',
        'state': 'ID',
        'priority': 3
    },
    'Wenatchee': {
        'lat': 47.42,
        'lon': -120.31,
        'abbr': 'EAT',
        'state': 'WA',
        'priority': 3
    },
    'Walla Walla': {
        'lat': 46.09,
        'lon': -118.33,
        'abbr': 'ALW',
        'state': 'WA',
        'priority': 3
    },
}


def get_stations_for_region(region: str, priority_level: int = 2) -> Dict[str, Dict[str, Any]]:
    """
    Get stations for a specific region, filtered by priority level.
    
    Args:
        region: Region identifier (e.g., 'pnw')
        priority_level: Maximum priority to include (1=major only, 2=major+secondary, 3=all)
    
    Returns:
        Dictionary of stations filtered by priority
    """
    if region == 'pnw':
        stations = PNW_STATIONS
    else:
        # Default to PNW for now
        stations = PNW_STATIONS
    
    # Filter by priority
    filtered = {
        name: data for name, data in stations.items()
        if data.get('priority', 3) <= priority_level
    }
    
    return filtered


def get_major_stations(region: str = 'pnw') -> Dict[str, Dict[str, Any]]:
    """Get only major (priority 1) stations for a region."""
    return get_stations_for_region(region, priority_level=1)


def format_station_value(value: float, variable: str, units: str = None) -> str:
    """
    Format a station value for display on map.
    
    Args:
        value: Numeric value to format
        variable: Variable type (temp, precip, wind_speed, etc.)
        units: Optional unit override
    
    Returns:
        Formatted string for display
    """
    if variable == 'temp':
        return f"{value:.0f}°"
    elif variable == 'precip':
        return f"{value:.2f}\""
    elif variable == 'wind_speed':
        return f"{value:.0f}"
    elif variable == 'precip_type':
        # For precip type, might show dominant type as text
        return ""  # Handle separately
    else:
        return f"{value:.1f}"
