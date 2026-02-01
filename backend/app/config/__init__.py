"""Configuration module for TWF Models."""

# Import settings from config.py using direct file loading to avoid circular import
import importlib.util
from pathlib import Path

# Load settings from the config.py file directly
config_file = Path(__file__).parent.parent / 'config.py'
spec = importlib.util.spec_from_file_location("app.config_settings", config_file)
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)
settings = config_module.settings

# Import overlay rules and regions from this package
from .overlay_rules import is_overlay_enabled, get_overlay_config, OVERLAY_RULES
from .regions import get_region_bbox, REGIONS, PNW_COVERAGE_BBOX

__all__ = [
    'settings',
    'is_overlay_enabled',
    'get_overlay_config',
    'get_region_bbox',
    'OVERLAY_RULES',
    'REGIONS',
    'PNW_COVERAGE_BBOX'
]
