"""Overlay policy configuration per map product."""

from typing import Dict, Any

OVERLAY_RULES: Dict[str, Dict[str, Any]] = {
    # Temperature products - overlays enabled, dense
    'temp_2m': {
        'enabled': True,
        'min_px_spacing': 80,
        'interpolation': 'nearest'
    },
    'temp_850mb': {
        'enabled': True,
        'min_px_spacing': 100,
        'interpolation': 'nearest'
    },
    
    # Wind products - overlays enabled, medium density
    'wind_speed_10m': {
        'enabled': True,
        'min_px_spacing': 100,
        'interpolation': 'nearest'
    },
    
    # Precipitation products - overlays enabled, sparse
    'precipitation': {
        'enabled': True,
        'min_px_spacing': 120,
        'interpolation': 'nearest'
    },
    'snowfall': {
        'enabled': True,
        'min_px_spacing': 120,
        'interpolation': 'nearest'
    },
    
    # Radar/MSLP - explicitly disabled (too cluttered)
    'radar': {
        'enabled': False
    },
    'mslp_precip': {
        'enabled': False
    },
    
    # Any product not listed defaults to enabled=False (fail-safe)
}


def is_overlay_enabled(product_id: str) -> bool:
    """
    Check if station overlays are enabled for a product.
    
    Args:
        product_id: Canonical product identifier
    
    Returns:
        True if overlays should be rendered, False otherwise
        
    Note:
        Defaults to FALSE for unknown products (fail-safe)
    """
    return OVERLAY_RULES.get(product_id, {}).get('enabled', False)


def get_overlay_config(product_id: str) -> Dict[str, Any]:
    """
    Get full overlay configuration for a product.
    
    Args:
        product_id: Canonical product identifier
    
    Returns:
        Overlay config dict, or empty dict if not enabled
    """
    if not is_overlay_enabled(product_id):
        return {}
    return OVERLAY_RULES[product_id]
