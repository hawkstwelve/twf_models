# Station Overlay Implementation Plan

## Overview

This document outlines the comprehensive plan to implement robust, model-agnostic station data overlays on weather maps. The implementation addresses current incompatibilities (particularly with HRRR), expands station coverage using NWS API data, and introduces intelligent decluttering.

**Timeline**: ~12-14 hours across 4 phases  
**Status**: Planning complete, implementation pending

---

## Problem Statement

### Current Issues

1. **HRRR Incompatibility**: Station extraction fails on HRRR due to 2D curvilinear coordinates
   - Error: `Could not automatically create PandasIndex for coord 'latitude' with 2 dimensions`
   - Root cause: Attempting `.sel(latitude=X, longitude=Y)` on projected grids with 2D lat/lon

2. **Limited Station Coverage**: Only 15 hardcoded stations in PNW region
   - Manual maintenance burden when expanding coverage
   - No scalable source of authoritative station metadata

3. **No Decluttering Logic**: All stations shown at fixed priority levels
   - Risk of overlapping labels as station count increases
   - No adaptation to map extent or zoom level

4. **Inconsistent Overlay Behavior**: No centralized control over which products show overlays
   - Potential for cluttered radar/MSLP maps
   - No per-product density controls

---

## Solution Architecture

### Core Concept: Strategy-Based Grid Locator System

Replace monolithic `extract_station_values()` with:
- **Three grid locator strategies** chosen automatically based on dataset structure
- **NWS API-sourced station catalog** with 200-500+ stations
- **Dynamic decluttering** using grid-binning algorithm
- **Centralized overlay policy** per map product

### Grid Locator Strategies

| Strategy | Grid Type | Detection | Sampling Method | Models |
|----------|-----------|-----------|----------------|--------|
| **LatLon1D** | Regular lat/lon | 1D lat + 1D lon coords | `.sel(lat, lon, method='nearest')` | GFS, AIGFS |
| **ProjectedXY** | Projected rectilinear | 1D x + 1D y coords | Transform (lon,lat)→(x,y), `.sel(x, y)` | HRRR, RAP, NAM |
| **CurvilinearKDTree** | True curvilinear | 2D lat + 2D lon, no 1D coords | KDTree on flattened coords | Rare ocean models |

---

## Critical Implementation Fixes Applied

The following critical fixes have been integrated into the implementation plan:

### **Fix #1: Enhanced Projection Detection with Fallback Scanning**
- **Issue**: Original code only checked target variable for `grid_mapping` attribute
- **Fix**: Added fallback that scans all variables/coordinates for grid mapping
- **Why**: Some GRIB→xarray backends attach grid mapping to coords or other vars, not the target variable
- **Impact**: More robust projection detection, reduces need for HRRR fallback

### **Fix #2: Clarified Bbox-Normalized Binning (Not True Screen-Space)**
- **Issue**: Documentation claimed "screen-space" binning but implementation uses lat/lon normalization  
- **Fix**: Renamed to "bbox-normalized binning" with clear note about projection effects
- **Why**: Visual spacing varies with map projection and latitude; setting correct expectations
- **Future**: True screen-space would require transforming stations to map projection first

### **Fix #3: Per-Dataset Caching for ProjectedXYLocator**
- **Issue**: Cache was per-instance only, could apply wrong CRS when reused across different datasets
- **Fix**: Cache keyed by dataset signature (x_size, y_size, grid_mapping_name)
- **Why**: Same locator instance may be reused across different runs/grids
- **Impact**: Prevents subtle bugs from stale projection caches

### **Fix #4: Warning Log for HRRR Fallback Projection**
- **Issue**: Silent fallback to hardcoded HRRR projection parameters
- **Fix**: Added warning log when fallback is used, prompts verification
- **Why**: Fallback parameters (R=6371229, LCC coords) must match GRIB source
- **Impact**: Makes projection issues visible during testing/deployment

### **Fix #5: NWS API Pagination URL Handling**
- **Issue**: Code assumed `pagination.next` is always a cursor token
- **Fix**: Handle both cursor tokens and full URLs, extract cursor from URL if needed
- **Why**: NWS API may return full URL instead of cursor token
- **Impact**: Robust pagination across all API response formats

### **Fix #6: Station Rendering Clarification**
- **Issue**: Unclear whether station IDs would be displayed on maps
- **Fix**: Explicit documentation that IDs are internal keys only, never rendered
- **Why**: Maps should show only formatted values (e.g., "52°"), not station identifiers
- **Impact**: Clear rendering expectations

### **Fix #7: Station Overrides Integration**
- **Issue**: `station_overrides.json` defined but never loaded or applied
- **Fix**: Added `load_overrides()`, `apply_overrides()`, and `get_always_include_ids()` methods to StationCatalog
- **Why**: Allows manual control over station selection without editing main cache
- **Impact**: 
  - `exclude` list removes unwanted stations
  - `weight_overrides` bumps priority for important stations (Seattle, Portland)
  - `always_include` forces major cities to appear even after decluttering

### **Fix #8: Enhanced Station Cache Metadata**
- **Issue**: Cache only stored `version` and `station_count`, no context about coverage
- **Fix**: Added `generated_at`, `source`, and `coverage_bbox` to cache metadata
- **Why**: Prevents "which bbox did this come from?" confusion when expanding beyond PNW
- **Impact**: 
  - `generated_at`: Timestamp for cache freshness tracking
  - `source`: Documents data origin (NWS API)
  - `coverage_bbox`: Explicit bbox used for this cache (supports multiple coverage areas)

---

## Critical Implementation Fixes (Detailed)

### Fix #1: CF Grid Mapping Detection (Phase 1)

**Original (WRONG)**:
```python
if 'grid_mapping' in ds.attrs:
    return pyproj.CRS.from_cf(ds.attrs['grid_mapping'])
```

**Problem**: In CF conventions, `grid_mapping` is an attribute on **data variables** pointing to a **grid mapping variable**, not a dict in `ds.attrs`.

**Corrected (RIGHT)**:
```python
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
        ...
    except ImportError:
        pass
    
    # Fallback: Known grid parameters (HRRR/RAP)
    if self._looks_like_hrrr_or_rap(ds):
        return self._hrrr_projection()  # Lambert Conformal CONUS
    
    raise ValueError("Cannot determine projection from dataset")
```

**Key changes**:
- Read `grid_mapping` attribute from data variable, not dataset
- Use that value to find the grid mapping variable in dataset
- Prefer `crs_wkt` attribute if present (more reliable than CF attrs)
- Fall back to `from_cf(gm_var.attrs)` with grid mapping variable attributes

**Reference**: [CF-xarray Grid Mappings](https://cf-xarray.readthedocs.io/en/latest/grid_mappings.html)

---

### Fix #2: NWS Bbox Ordering (Phase 0 & 2)

**Original (WRONG)**:
```python
# Bbox: (min_lat, min_lon, max_lat, max_lon)
PNW_COVERAGE_BBOX = (42.0, -125.0, 49.0, -110.0)
```

**Problem**: NWS API expects `(west_lon, south_lat, east_lon, north_lat)` order, not lat-first.

**Corrected (RIGHT)**:
```python
# Bbox format: (west_lon, south_lat, east_lon, north_lat)
# Standard NWS API convention
PNW_COVERAGE_BBOX = (-125.0, 42.0, -110.0, 49.0)
```

**CLI validation**:
```python
def parse_bbox(bbox_str: str) -> Tuple[float, float, float, float]:
    """
    Parse bbox string in NWS API format: west,south,east,north
    
    Args:
        bbox_str: Comma-separated "west_lon,south_lat,east_lon,north_lat"
    
    Returns:
        Tuple of (west_lon, south_lat, east_lon, north_lat)
    
    Raises:
        ValueError: If bbox is invalid
    """
    try:
        west, south, east, north = map(float, bbox_str.split(','))
    except ValueError:
        raise ValueError("Bbox must be 4 comma-separated numbers")
    
    # Validate ranges
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise ValueError(f"Longitude must be -180 to 180, got west={west}, east={east}")
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        raise ValueError(f"Latitude must be -90 to 90, got south={south}, north={north}")
    if west >= east:
        raise ValueError(f"West longitude must be < east, got {west} >= {east}")
    if south >= north:
        raise ValueError(f"South latitude must be < north, got {south} >= {north}")
    
    return (west, south, east, north)
```

**Corrected CLI usage**:
```bash
# Format: west_lon,south_lat,east_lon,north_lat
python scripts/fetch_stations.py \
    --bbox -125.0,42.0,-110.0,49.0 \
    --output backend/app/data/station_cache.json
```

**Reference**: [NWS API Web Service Documentation](https://www.weather.gov/documentation/services-web-api)

---

### Fix #3: Overlay Rules Default (Phase 0 & 3)

**Original (UNSAFE)**:
```python
overlay_config = OVERLAY_RULES.get(product_id, {})
if not overlay_config.get('enabled', True):  # ❌ Defaults to enabled
    skip...
```

**Problem**: New/unknown products would unexpectedly get overlays, potentially cluttering maps.

**Corrected (FAIL-SAFE)**:
```python
# Fail-safe: default to overlays OFF for unknown products
enabled = OVERLAY_RULES.get(product_id, {}).get('enabled', False)
if not enabled:
    logger.debug(f"Station overlays disabled for product: {product_id}")
    # Skip entire station pipeline
    ...
    return filepath
```

**Configuration helper**:
```python
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
```

---

## Phase Breakdown

### Phase 0: Configuration Foundation (1 hour)

**Objective**: Establish configuration contracts before implementing components.

**Files to create**:

#### 1. `backend/app/config/__init__.py`
```python
"""Configuration module for TWF Models."""
```

#### 2. `backend/app/config/regions.py`
```python
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
```

#### 3. `backend/app/config/overlay_rules.py`
```python
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
```

**Validation**:
- ✅ All bbox definitions use `(west, south, east, north)` order
- ✅ Longitude ranges: -180 to 180
- ✅ Latitude ranges: -90 to 90
- ✅ Overlay rules explicitly list enabled products only
- ✅ Unknown products default to `enabled=False`

---

### Phase 1: GridLocator (Fix HRRR) (3-4 hours)

**Objective**: Implement model-agnostic station sampling that works with GFS, AIGFS, and HRRR.

**Files to create**:

#### 1. `backend/app/services/grid_locators/__init__.py`
```python
"""Grid locator strategies for model-agnostic station sampling."""

from .base import GridLocator
from .latlon_1d import LatLon1DLocator
from .projected_xy import ProjectedXYLocator
from .curvilinear_kdtree import CurvilinearKDTreeLocator

__all__ = [
    'GridLocator',
    'LatLon1DLocator',
    'ProjectedXYLocator',
    'CurvilinearKDTreeLocator',
]
```

#### 2. `backend/app/services/grid_locators/base.py`
```python
"""Base class for grid locator strategies."""

from abc import ABC, abstractmethod
from typing import Dict, List
import xarray as xr


class GridLocator(ABC):
    """Abstract base class for grid location strategies."""
    
    @abstractmethod
    def sample(self, ds: xr.Dataset, variable: str, 
               stations: List['Station']) -> Dict[str, float]:
        """
        Extract model values at station locations.
        
        Args:
            ds: xarray Dataset with forecast data
            variable: Variable name to sample
            stations: List of Station objects with lat/lon
        
        Returns:
            Dictionary mapping station IDs to extracted values
        """
        pass
    
    @classmethod
    @abstractmethod
    def can_handle(cls, ds: xr.Dataset) -> bool:
        """
        Check if this locator can handle the given dataset.
        
        Args:
            ds: xarray Dataset to check
        
        Returns:
            True if this locator can sample from this dataset
        """
        pass
```

#### 3. `backend/app/services/grid_locators/latlon_1d.py`
```python
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
```

#### 4. `backend/app/services/grid_locators/projected_xy.py`
```python
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
```

#### 5. `backend/app/services/grid_locators/curvilinear_kdtree.py`
```python
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
    
    @classmethod
    def can_handle(cls, ds: xr.Dataset) -> bool:
        """Check if dataset has 2D lat/lon without 1D x/y."""
        lat_coord = 'latitude' if 'latitude' in ds.coords else 'lat'
        lon_coord = 'longitude' if 'longitude' in ds.coords else 'lon'
        
        if lat_coord not in ds.coords or lon_coord not in ds.coords:
            return False
        
        # Must have 2D lat/lon
        has_2d = (ds.coords[lat_coord].ndim == 2 and 
                  ds.coords[lon_coord].ndim == 2)
        
        # Must NOT have 1D x/y (that would be projected)
        has_xy = ('x' in ds.coords and 'y' in ds.coords and
                  ds.coords['x'].ndim == 1 and ds.coords['y'].ndim == 1)
        
        return has_2d and not has_xy
    
    def _build_kdtree(self, ds: xr.Dataset) -> cKDTree:
        """Build KDTree from flattened lat/lon coordinates."""
        if self._kdtree_cache is not None:
            return self._kdtree_cache
        
        lat_coord = 'latitude' if 'latitude' in ds.coords else 'lat'
        lon_coord = 'longitude' if 'longitude' in ds.coords else 'lon'
        
        lats = ds.coords[lat_coord].values
        lons = ds.coords[lon_coord].values
        
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
        
        # Get dimension names from 2D lat coord
        lat_coord = 'latitude' if 'latitude' in ds.coords else 'lat'
        dim_names = ds.coords[lat_coord].dims
        
        values = {}
        for station in stations:
            try:
                # Find nearest grid point
                station_coords = np.array([[station.lat, station.lon]])
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
```

#### 6. `backend/app/services/station_sampling.py`
```python
"""Factory for creating appropriate grid locator strategies."""

import logging
import xarray as xr
from .grid_locators import (
    GridLocator,
    LatLon1DLocator,
    ProjectedXYLocator,
    CurvilinearKDTreeLocator
)

logger = logging.getLogger(__name__)


class GridLocatorFactory:
    """Factory for creating appropriate grid locator based on dataset structure."""
    
    @staticmethod
    def from_dataset(ds: xr.Dataset) -> GridLocator:
        """
        Create appropriate grid locator for dataset.
        
        Args:
            ds: xarray Dataset to analyze
        
        Returns:
            GridLocator instance appropriate for this dataset
        
        Raises:
            ValueError: If no suitable locator found
        """
        # Try in priority order (fastest to slowest)
        if LatLon1DLocator.can_handle(ds):
            logger.debug("Using LatLon1DLocator (regular grid)")
            return LatLon1DLocator()
        
        elif ProjectedXYLocator.can_handle(ds):
            logger.debug("Using ProjectedXYLocator (projected rectilinear)")
            return ProjectedXYLocator()
        
        elif CurvilinearKDTreeLocator.can_handle(ds):
            logger.debug("Using CurvilinearKDTreeLocator (curvilinear fallback)")
            return CurvilinearKDTreeLocator()
        
        else:
            raise ValueError(
                "No suitable grid locator for dataset. "
                "Dataset must have either: 1D lat/lon, 1D x/y, or 2D lat/lon coords."
            )
```

**Test target**:
```bash
# Generate HRRR map with stations
python scripts/tests/test_hrrr_temp.py --run 2026-02-01T18:00:00Z --fxx 6
```

**Expected outcome**:
- ✅ No CF grid_mapping warnings
- ✅ ProjectedXYLocator selected automatically
- ✅ Station values extracted successfully
- ✅ No errors in logs

---

### Phase 2: Station Catalog (NWS API) (4-5 hours)

**Objective**: Fetch authoritative station data from NWS API and cache locally.

**Files to create**:

#### 1. `scripts/fetch_stations.py`
```python
"""
Fetch weather stations from NWS API and cache locally.

Usage:
    python scripts/fetch_stations.py --bbox -125.0,42.0,-110.0,49.0 --output backend/app/data/station_cache.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_bbox(bbox_str: str) -> Tuple[float, float, float, float]:
    """
    Parse bbox string in NWS API format: west,south,east,north
    
    Args:
        bbox_str: Comma-separated "west_lon,south_lat,east_lon,north_lat"
    
    Returns:
        Tuple of (west_lon, south_lat, east_lon, north_lat)
    
    Raises:
        ValueError: If bbox is invalid
    """
    try:
        west, south, east, north = map(float, bbox_str.split(','))
    except ValueError:
        raise ValueError("Bbox must be 4 comma-separated numbers")
    
    # Validate ranges
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise ValueError(f"Longitude must be -180 to 180, got west={west}, east={east}")
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        raise ValueError(f"Latitude must be -90 to 90, got south={south}, north={north}")
    if west >= east:
        raise ValueError(f"West longitude must be < east, got {west} >= {east}")
    if south >= north:
        raise ValueError(f"South latitude must be < north, got {south} >= {north}")
    
    return (west, south, east, north)


def fetch_stations_from_nws(
    bbox: Tuple[float, float, float, float],
    max_stations: Optional[int] = None
) -> List[Dict]:
    """
    Fetch stations from NWS API with pagination.
    
    Args:
        bbox: (west_lon, south_lat, east_lon, north_lat)
        max_stations: Maximum number of stations to fetch (None = all)
    
    Returns:
        List of station dicts with normalized fields
    """
    base_url = "https://api.weather.gov/stations"
    
    # Format bbox for NWS API: west,south,east,north
    bbox_param = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
    
    stations = []
    cursor = None
    page = 1
    
    while True:
        params = {'bbox': bbox_param}
        if cursor:
            params['cursor'] = cursor
        
        logger.info(f"Fetching page {page} from NWS API...")
        
        try:
            response = requests.get(
                base_url,
                params=params,
                headers={'User-Agent': 'TWF-Models/1.0'},
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error(f"API request failed: {e}")
            break
        
        features = data.get('features', [])
        if not features:
            break
        
        logger.info(f"  Retrieved {len(features)} stations")
        
        # Normalize station data
        for feature in features:
            props = feature.get('properties', {})
            geom = feature.get('geometry', {})
            coords = geom.get('coordinates', [None, None])
            
            station = {
                'id': props.get('stationIdentifier', ''),
                'name': props.get('name', ''),
                'lat': coords[1],  # GeoJSON is [lon, lat]
                'lon': coords[0],
                'elevation_m': props.get('elevation', {}).get('value'),
                'state': None,  # Extract from name if possible
                'abbr': props.get('stationIdentifier', '')[:4],
                'station_type': 'nws',
                'display_weight': 1.0
            }
            
            # Skip invalid stations
            if not station['id'] or station['lat'] is None or station['lon'] is None:
                continue
            
            stations.append(station)
        
        # Check for more pages
        next_val = data.get('pagination', {}).get('next')
        if not next_val:
            break
        
        # Handle both cursor token and full URL
        if next_val.startswith('http'):
            # NWS returned full URL, extract cursor from it
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(next_val)
            query_params = parse_qs(parsed.query)
            cursor = query_params.get('cursor', [None])[0]
            if not cursor:
                # If no cursor param, we can't paginate further
                logger.warning(f"Got URL pagination but no cursor param: {next_val}")
                break
        else:
            # Assume it's a cursor token
            cursor = next_val
        
        if max_stations and len(stations) >= max_stations:
            stations = stations[:max_stations]
            break
        
        page += 1
    
    logger.info(f"Total stations fetched: {len(stations)}")
    return stations


def save_station_cache(stations: List[Dict], output_path: Path, bbox: Tuple[float, float, float, float]):
    """Save stations to JSON cache file with metadata."""
    from datetime import datetime
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    cache_data = {
        'version': '1.0',
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'source': 'nws',
        'coverage_bbox': {
            'west': bbox[0],
            'south': bbox[1],
            'east': bbox[2],
            'north': bbox[3]
        },
        'station_count': len(stations),
        'stations': stations
    }
    
    with open(output_path, 'w') as f:
        json.dump(cache_data, f, indent=2)
    
    logger.info(f"Saved {len(stations)} stations to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Fetch stations from NWS API')
    parser.add_argument(
        '--bbox',
        required=True,
        help='Bounding box: west_lon,south_lat,east_lon,north_lat'
    )
    parser.add_argument(
        '--output',
        type=Path,
        required=True,
        help='Output JSON file path'
    )
    parser.add_argument(
        '--max',
        type=int,
        default=None,
        help='Maximum number of stations to fetch'
    )
    
    args = parser.parse_args()
    
    try:
        bbox = parse_bbox(args.bbox)
        logger.info(f"Fetching stations for bbox: {bbox}")
        
        stations = fetch_stations_from_nws(bbox, args.max)
        
        if not stations:
            logger.error("No stations fetched")
            sys.exit(1)
        
        save_station_cache(stations, args.output, bbox)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
```

#### 2. `backend/app/services/station_catalog.py`
```python
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
            from app.config import STATION_CACHE_PATH
            cache_path = STATION_CACHE_PATH
        
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
```

#### 3. `backend/app/data/station_overrides.json`
```json
{
  "version": "1.0",
  "always_include": [
    "KSEA",
    "KPDX",
    "KGEG",
    "KBOI"
  ],
  "weight_overrides": {
    "KSEA": 2.0,
    "KPDX": 2.0,
    "KGEG": 1.5,
    "KBOI": 1.5
  },
  "exclude": []
}
```

**CLI usage**:
```bash
# Fetch PNW coverage area (correct bbox order)
python scripts/fetch_stations.py \
    --bbox -125.0,42.0,-110.0,49.0 \
    --output backend/app/data/station_cache.json
```

**Test target**:
```python
from app.services.station_catalog import StationCatalog

catalog = StationCatalog()
stations = catalog.get_stations_for_region('pnw_large')
print(f"Loaded {len(stations)} stations for PNW region")

# Verify overrides are applied
overrides = catalog.load_overrides()
print(f"Always include: {overrides['always_include']}")
print(f"Weight overrides: {len(overrides['weight_overrides'])}")
```

**Expected station_cache.json format**:
```json
{
  "version": "1.0",
  "generated_at": "2026-02-01T12:00:00Z",
  "source": "nws",
  "coverage_bbox": {
    "west": -125.0,
    "south": 42.0,
    "east": -110.0,
    "north": 49.0
  },
  "station_count": 347,
  "stations": [
    {
      "id": "KSEA",
      "name": "Seattle-Tacoma International Airport",
      "lat": 47.45,
      "lon": -122.31,
      "elevation_m": 131.0,
      "abbr": "KSEA",
      "station_type": "nws",
      "display_weight": 1.0
    },
    ...
  ]
}
```

---

### Phase 3: Decluttering + Integration (3-4 hours)

**Objective**: Implement grid-binning declutter and integrate into map generator.

**Files to create**:

#### 1. `backend/app/services/station_selector.py`
```python
"""Station selection and decluttering for map overlays."""

import logging
import math
from typing import Dict, List, Optional, Tuple
from .station_catalog import Station

logger = logging.getLogger(__name__)


class StationSelector:
    """Selects and declutters stations for map rendering."""
    
    def select_for_map(
        self,
        stations: List[Station],
        bbox: Tuple[float, float, float, float],
        image_size: Tuple[int, int],
        min_px_spacing: int = 100,
        always_include: Optional[List[str]] = None
    ) -> List[Station]:
        """
        Select stations using bbox-normalized grid-binning declutter.
        
        Note: This bins in normalized lat/lon space, not true screen-space pixels.
        Visual spacing will vary with map projection (Lambert vs PlateCarree) and
        latitude. For true screen-space binning, would need to transform stations
        to map projection coordinates first.
        
        Algorithm:
        1. Filter stations to bbox
        2. Create bbox-normalized grid (cells based on min_px_spacing)
        3. Assign each station to grid cell by normalized lat/lon
        4. Keep highest-weight station per cell
        5. Force-include always_include stations
        
        Args:
            stations: Full list of stations to choose from
            bbox: Map bbox (west_lon, south_lat, east_lon, north_lat)
            image_size: Image dimensions (width_px, height_px)
            min_px_spacing: Minimum pixel spacing between stations
            always_include: List of station IDs to always include
        
        Returns:
            Selected subset of stations
        """
        west, south, east, north = bbox
        width_px, height_px = image_size
        
        # Filter to bbox
        in_bbox = [
            s for s in stations
            if west <= s.lon <= east and south <= s.lat <= north
        ]
        
        logger.debug(f"Stations in bbox: {len(in_bbox)}")
        
        if not in_bbox:
            return []
        
        # Calculate grid dimensions
        lon_range = east - west
        lat_range = north - south
        
        # Convert min_px_spacing to grid cells
        cells_x = max(1, int(width_px / min_px_spacing))
        cells_y = max(1, int(height_px / min_px_spacing))
        
        logger.debug(f"Grid dimensions: {cells_x}x{cells_y} cells")
        
        # Assign stations to grid cells
        grid: Dict[Tuple[int, int], List[Station]] = {}
        
        for station in in_bbox:
            # Normalize to 0-1 range
            x_norm = (station.lon - west) / lon_range if lon_range > 0 else 0
            y_norm = (station.lat - south) / lat_range if lat_range > 0 else 0
            
            # Convert to cell index
            cell_x = min(cells_x - 1, int(x_norm * cells_x))
            cell_y = min(cells_y - 1, int(y_norm * cells_y))
            
            cell = (cell_x, cell_y)
            if cell not in grid:
                grid[cell] = []
            grid[cell].append(station)
        
        # Keep highest-weight station per cell
        selected = []
        for cell_stations in grid.values():
            best = max(cell_stations, key=lambda s: s.display_weight)
            selected.append(best)
        
        # Force-include always_include stations
        if always_include:
            always_ids = set(always_include)
            selected_ids = {s.id for s in selected}
            
            for station in in_bbox:
                if station.id in always_ids and station.id not in selected_ids:
                    selected.append(station)
                    logger.debug(f"Force-included station: {station.id}")
        
        logger.info(f"Selected {len(selected)} stations after declutter")
        return selected
```

**Files to modify**:

#### 2. `backend/app/services/map_generator.py`

Key modifications to integrate station overlay system:

```python
from app.config.overlay_rules import is_overlay_enabled, get_overlay_config
from app.config.regions import get_region_bbox
from app.services.station_catalog import StationCatalog
from app.services.station_selector import StationSelector
from app.services.station_sampling import GridLocatorFactory

class MapGenerator:
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        # Initialize station catalog once
        self._station_catalog = StationCatalog()
    
    def generate_map(...):
        # ... existing map setup code ...
        
        # ==============================================
        # STATION OVERLAY PIPELINE (NEW)
        # ==============================================
        
        # Check if overlays enabled for this product (fail-safe default)
        if not is_overlay_enabled(product_id):
            logger.debug(f"Station overlays disabled for product: {product_id}")
            # Continue with map rendering without stations
            ...
            return filepath
        
        # Load overlay configuration
        overlay_config = get_overlay_config(product_id)
        min_spacing = overlay_config.get('min_px_spacing', 100)
        
        # Load stations for region
        try:
            region_bbox = get_region_bbox(region or 'pnw_large')
            all_stations = self._station_catalog.get_stations_for_region(region or 'pnw_large')
            
            # Declutter stations
            selector = StationSelector()
            fig_size_px = (int(fig.get_figwidth() * fig.dpi), 
                          int(fig.get_figheight() * fig.dpi))
            
            # Get always_include list from overrides
            always_include = self._station_catalog.get_always_include_ids()
            
            selected_stations = selector.select_for_map(
                all_stations,
                region_bbox,
                fig_size_px,
                min_px_spacing=min_spacing,
                always_include=always_include
            )
            
            if selected_stations:
                # Sample values using grid locator factory
                locator = GridLocatorFactory.from_dataset(ds)
                station_values = locator.sample(ds, variable, selected_stations)
                
                # Render station overlays
                self._render_station_overlays(ax, station_values, selected_stations, variable)
                
                logger.info(f"Rendered {len(station_values)} station overlays")
            
        except Exception as e:
            # Don't fail entire map if overlays fail
            logger.warning(f"Could not add station overlays: {e}", exc_info=True)
        
        # ... rest of map rendering ...
    
    def _render_station_overlays(self, ax, values: Dict[str, float], 
                                  stations: List[Station], variable: str):
        """Render station overlays on map.
        
        Note: Station IDs are used as keys for lookup but NOT displayed on map.
        Only formatted values (e.g., "52°", "0.25\"") are rendered at station locations.
        """
        # Use existing plotting logic from plot_station_overlays
        # but simplified with Station objects
        # Display only formatted values, not station IDs or names
        ...
```

**Test target**:
```bash
# Temperature map with overlays (should show dense stations)
python scripts/tests/test_temp_map.py --model HRRR

# Radar map without overlays (should skip pipeline)
python scripts/tests/test_hrrr_radar_debug.py --run 2026-02-01T18:00:00Z --fxx 6

# Check logs for:
# - "Station overlays disabled for product: radar" (for radar)
# - "Selected X stations after declutter" (for temp)
# - No warnings about CF grid_mapping
```

---

### Phase 4: Testing & Validation (2 hours)

**Objective**: Comprehensive testing across all models and products.

**Test Matrix**:

| Model | Product | Expected Locator | Expected Overlay | Pass? |
|-------|---------|-----------------|------------------|-------|
| GFS | temp_2m | LatLon1D | Enabled, dense (80px) | ☐ |
| GFS | wind_speed_10m | LatLon1D | Enabled, medium (100px) | ☐ |
| GFS | precipitation | LatLon1D | Enabled, sparse (120px) | ☐ |
| GFS | radar | LatLon1D | Disabled (skip) | ☐ |
| AIGFS | temp_2m | LatLon1D | Enabled, dense | ☐ |
| HRRR | temp_2m | ProjectedXY | Enabled, dense | ☐ |
| HRRR | wind_speed_10m | ProjectedXY | Enabled, medium | ☐ |
| HRRR | radar | ProjectedXY | Disabled (skip) | ☐ |

**Validation Checks**:

1. **No Errors/Warnings**:
   - ✅ No CF grid_mapping parse failures
   - ✅ No "Could not automatically create PandasIndex" warnings
   - ✅ No station sampling failures

2. **Value Sanity**:
   - ✅ Temperature: -40°C to 50°C
   - ✅ Wind speed: 0 to 200 mph
   - ✅ Precipitation: 0 to 20 inches
   - ✅ No NaN values

3. **Visual Quality**:
   - ✅ No overlapping station labels
   - ✅ Appropriate density per product type
   - ✅ Major cities always visible (Seattle, Portland, etc.)

4. **Performance**:
   - ✅ Station pipeline < 500ms for 50 stations
   - ✅ Radar maps skip station work entirely
   - ✅ No memory leaks from cached locators

**Test Commands**:

```bash
# GFS tests
python scripts/tests/test_temp_map.py --model GFS --run latest
python scripts/tests/test_wind_speed_map.py --model GFS --run latest

# HRRR tests (critical for validation)
python scripts/tests/test_temp_map.py --model HRRR --run 2026-02-01T18:00:00Z --fxx 6
python scripts/tests/test_wind_speed_map.py --model HRRR --run 2026-02-01T18:00:00Z --fxx 6
python scripts/tests/test_hrrr_radar_debug.py --run 2026-02-01T18:00:00Z --fxx 6

# Visual spot checks
open backend/app/static/images/hrrr_*_temp_2m_*.png
open backend/app/static/images/hrrr_*_radar_*.png  # Should have no station labels
```

---

## Dependencies

Add to `backend/requirements.txt`:

```
pyproj>=3.4.0       # Projection transforms (CF grid_mapping)
scipy>=1.10.0       # KDTree for curvilinear fallback
requests>=2.28.0    # NWS API calls
```

Optional (evaluate during Phase 1):
```
metpy>=1.5.0        # Alternative GRIB projection parser if CF fails
```

---

## Configuration Files Summary

**New configuration structure**:

```
backend/app/
├── config/
│   ├── __init__.py
│   ├── regions.py              # Region bboxes
│   └── overlay_rules.py        # Per-product overlay policy
├── data/
│   ├── station_cache.json      # Generated by fetch_stations.py
│   └── station_overrides.json  # Manual tweaks (always_include, weights)
└── services/
    ├── grid_locators/          # Strategy implementations
    │   ├── __init__.py
    │   ├── base.py
    │   ├── latlon_1d.py
    │   ├── projected_xy.py
    │   └── curvilinear_kdtree.py
    ├── station_catalog.py      # Catalog loader/filter
    ├── station_sampling.py     # GridLocatorFactory
    └── station_selector.py     # Decluttering logic
```

---

## Production Considerations (Future)

**Not implementing now**, but design accommodates:

1. **Station Cache Refresh**: Scheduled job to update from NWS API
2. **Multiple Coverage Areas**: Expand beyond PNW (California, Northeast, etc.)
3. **Database Backing**: Replace JSON with SQLite if catalog grows >1000 stations
4. **CDN Caching**: Cache station values per forecast frame
5. **Dynamic Overlay Toggle**: API endpoint to enable/disable overlays per request

**Cache Location Strategy**:
- **Development**: `backend/app/data/station_cache.json`
- **Production Option A**: Build-time generation, bundled into image (read-only)
- **Production Option B**: Runtime generation, persistent volume (writable)

Current implementation uses Option A approach with configurable path via `STATION_CACHE_PATH` environment variable.

---

## Success Criteria

**Phase 1 Complete**:
- ✅ HRRR maps generate without CF warnings
- ✅ ProjectedXYLocator correctly transforms station coords
- ✅ All three locator strategies tested

**Phase 2 Complete**:
- ✅ NWS API fetch script working
- ✅ 200-500 stations cached for PNW
- ✅ Station catalog loads and filters by region

**Phase 3 Complete**:
- ✅ Grid-binning declutter prevents overlaps
- ✅ Radar/MSLP maps skip station pipeline
- ✅ Per-product density controls work

**Phase 4 Complete**:
- ✅ All model/product combinations tested
- ✅ No errors or warnings in logs
- ✅ Visual quality validated
- ✅ Performance benchmarks met

---

## References

- [CF-xarray Grid Mappings](https://cf-xarray.readthedocs.io/en/latest/grid_mappings.html)
- [pyproj Managing CRS to/from CF](https://pyproj4.github.io/pyproj/stable/build_crs_cf.html)
- [NWS API Web Service Documentation](https://www.weather.gov/documentation/services-web-api)
- [AI Context: Herbie Integration](./AI_CONTEXT_HERBIE.md) - GRIB cache contract

---

## Timeline Estimate

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase 0: Configuration | 1 hour | 1 hour |
| Phase 1: GridLocator | 3-4 hours | 4-5 hours |
| Phase 2: Station Catalog | 4-5 hours | 8-10 hours |
| Phase 3: Integration | 3-4 hours | 11-14 hours |
| Phase 4: Testing | 2 hours | 13-16 hours |

**Total: 13-16 hours** (conservative estimate with testing and debugging)

---

## Next Steps

1. **Review and approve plan** ✅ (You are here)
2. **Begin Phase 0**: Create configuration files
3. **Implement Phase 1**: Fix HRRR compatibility
4. **Continue through phases**: Build incrementally
5. **Final validation**: Test matrix completion

Ready to proceed with implementation?
