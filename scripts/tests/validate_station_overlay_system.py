#!/usr/bin/env python3
"""
Phase 4 Validation Script: Station Overlay System Integration Test

Tests all components of the station overlay system:
1. Configuration loading
2. Station catalog loading
3. Grid locator selection
4. Station decluttering
5. Overlay rules
"""

import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from app.config.regions import get_region_bbox, REGIONS
from app.config.overlay_rules import is_overlay_enabled, get_overlay_config, OVERLAY_RULES
from app.services.station_catalog import StationCatalog
from app.services.station_selector import StationSelector
from app.services.grid_locators import LatLon1DLocator, ProjectedXYLocator, CurvilinearKDTreeLocator
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_phase_0_config():
    """Test Phase 0: Configuration Foundation"""
    print("\n" + "="*70)
    print("PHASE 0 VALIDATION: Configuration Foundation")
    print("="*70)
    
    # Test regions
    print("\n1. Testing region definitions...")
    try:
        for region_id in ['pnw_large', 'puget_sound', 'willamette_valley']:
            bbox = get_region_bbox(region_id)
            west, south, east, north = bbox
            assert west < east, f"Invalid bbox for {region_id}: west >= east"
            assert south < north, f"Invalid bbox for {region_id}: south >= north"
            assert -180 <= west <= 180, f"Invalid west longitude: {west}"
            assert -180 <= east <= 180, f"Invalid east longitude: {east}"
            assert -90 <= south <= 90, f"Invalid south latitude: {south}"
            assert -90 <= north <= 90, f"Invalid north latitude: {north}"
            print(f"   ✓ {region_id}: {bbox}")
        print("   ✅ All regions valid")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False
    
    # Test overlay rules
    print("\n2. Testing overlay rules...")
    try:
        enabled_products = [pid for pid in OVERLAY_RULES if OVERLAY_RULES[pid].get('enabled', False)]
        disabled_products = [pid for pid in OVERLAY_RULES if not OVERLAY_RULES[pid].get('enabled', False)]
        
        print(f"   Enabled products ({len(enabled_products)}): {', '.join(enabled_products)}")
        print(f"   Disabled products ({len(disabled_products)}): {', '.join(disabled_products)}")
        
        # Test fail-safe default
        assert not is_overlay_enabled('unknown_product'), "Unknown products should default to disabled"
        print("   ✓ Fail-safe default works (unknown products disabled)")
        
        # Test specific products
        assert is_overlay_enabled('temp_2m'), "temp_2m should be enabled"
        assert not is_overlay_enabled('radar'), "radar should be disabled"
        print("   ✅ Overlay rules working correctly")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False
    
    return True


def test_phase_1_grid_locators():
    """Test Phase 1: Grid Locator Strategies"""
    print("\n" + "="*70)
    print("PHASE 1 VALIDATION: Grid Locator Strategies")
    print("="*70)
    
    print("\n1. Testing grid locator imports...")
    try:
        print(f"   ✓ LatLon1DLocator: {LatLon1DLocator.__name__}")
        print(f"   ✓ ProjectedXYLocator: {ProjectedXYLocator.__name__}")
        print(f"   ✓ CurvilinearKDTreeLocator: {CurvilinearKDTreeLocator.__name__}")
        print("   ✅ All locator classes imported successfully")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False
    
    print("\n2. Testing locator detection logic...")
    try:
        import xarray as xr
        import numpy as np
        
        # Mock dataset with 1D lat/lon (GFS-style)
        ds_latlon = xr.Dataset({
            'temp': (['lat', 'lon'], np.random.rand(10, 20))
        }, coords={
            'lat': np.linspace(40, 50, 10),
            'lon': np.linspace(-130, -110, 20)
        })
        
        assert LatLon1DLocator.can_handle(ds_latlon), "Should detect 1D lat/lon grid"
        assert not ProjectedXYLocator.can_handle(ds_latlon), "Should NOT detect as projected"
        print("   ✓ LatLon1D detection working")
        
        # Mock dataset with 1D x/y (HRRR-style)
        ds_xy = xr.Dataset({
            'temp': (['y', 'x'], np.random.rand(10, 20))
        }, coords={
            'x': np.linspace(0, 1000000, 20),
            'y': np.linspace(0, 1000000, 10)
        })
        
        assert ProjectedXYLocator.can_handle(ds_xy), "Should detect 1D x/y grid"
        assert not LatLon1DLocator.can_handle(ds_xy), "Should NOT detect as lat/lon"
        print("   ✓ ProjectedXY detection working")
        
        print("   ✅ Grid locator detection logic validated")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False
    
    return True


def test_phase_2_station_catalog():
    """Test Phase 2: Station Catalog"""
    print("\n" + "="*70)
    print("PHASE 2 VALIDATION: Station Catalog")
    print("="*70)
    
    print("\n1. Loading station catalog...")
    try:
        catalog = StationCatalog()
        all_stations = catalog.load_from_cache()
        print(f"   ✓ Loaded {len(all_stations)} stations from cache")
        
        # Verify station structure
        sample = all_stations[0]
        assert hasattr(sample, 'id'), "Station missing 'id' field"
        assert hasattr(sample, 'lat'), "Station missing 'lat' field"
        assert hasattr(sample, 'lon'), "Station missing 'lon' field"
        assert hasattr(sample, 'display_weight'), "Station missing 'display_weight' field"
        print(f"   ✓ Sample station: {sample.id} at ({sample.lat:.2f}, {sample.lon:.2f})")
        print("   ✅ Station catalog loaded successfully")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False
    
    print("\n2. Testing station overrides...")
    try:
        overrides = catalog.load_overrides()
        always_include = overrides.get('always_include', [])
        weight_overrides = overrides.get('weight_overrides', {})
        
        print(f"   Always include ({len(always_include)}): {', '.join(always_include)}")
        print(f"   Weight overrides ({len(weight_overrides)}): {', '.join(weight_overrides.keys())}")
        print("   ✅ Station overrides loaded")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False
    
    print("\n3. Testing region filtering...")
    try:
        pnw_stations = catalog.get_stations_for_region('pnw_large')
        print(f"   ✓ PNW region: {len(pnw_stations)} stations")
        
        puget_stations = catalog.get_stations_for_region('puget_sound')
        print(f"   ✓ Puget Sound region: {len(puget_stations)} stations")
        
        assert len(puget_stations) < len(pnw_stations), "Puget Sound should have fewer stations than PNW"
        print("   ✅ Region filtering working correctly")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False
    
    return True


def test_phase_3_decluttering():
    """Test Phase 3: Station Decluttering"""
    print("\n" + "="*70)
    print("PHASE 3 VALIDATION: Station Decluttering & Integration")
    print("="*70)
    
    print("\n1. Testing station decluttering...")
    try:
        catalog = StationCatalog()
        all_stations = catalog.get_stations_for_region('pnw_large')
        
        # Test with different spacing values
        for spacing in [80, 100, 120]:
            bbox = get_region_bbox('pnw_large')
            selector = StationSelector(bbox, grid_size_px=spacing)
            always_include = catalog.get_always_include_ids()
            
            selected = selector.select_decluttered_stations(all_stations, always_include)
            print(f"   ✓ Spacing {spacing}px: {len(all_stations)} → {len(selected)} stations")
            
            # Verify always_include stations are present
            selected_ids = {s.id for s in selected}
            for station_id in always_include:
                if station_id in {s.id for s in all_stations}:
                    assert station_id in selected_ids, f"Always-include station {station_id} missing"
        
        print("   ✅ Decluttering working correctly")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False
    
    print("\n2. Testing overlay configuration integration...")
    try:
        # Test per-product spacing
        configs = {
            'temp_2m': get_overlay_config('temp_2m'),
            'wind_speed_10m': get_overlay_config('wind_speed_10m'),
            'precipitation': get_overlay_config('precipitation')
        }
        
        for product_id, config in configs.items():
            spacing = config.get('min_px_spacing', 100)
            enabled = config.get('enabled', False)
            print(f"   ✓ {product_id}: {'enabled' if enabled else 'disabled'}, spacing={spacing}px")
        
        print("   ✅ Overlay configuration integration validated")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False
    
    return True


def main():
    """Run all validation tests"""
    print("\n" + "="*70)
    print("STATION OVERLAY SYSTEM - PHASE 4 VALIDATION")
    print("="*70)
    
    results = {
        "Phase 0: Configuration": test_phase_0_config(),
        "Phase 1: Grid Locators": test_phase_1_grid_locators(),
        "Phase 2: Station Catalog": test_phase_2_station_catalog(),
        "Phase 3: Decluttering": test_phase_3_decluttering()
    }
    
    print("\n" + "="*70)
    print("VALIDATION SUMMARY")
    print("="*70)
    
    for phase, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {phase}")
    
    all_passed = all(results.values())
    
    print("\n" + "="*70)
    if all_passed:
        print("🎉 ALL PHASES VALIDATED SUCCESSFULLY!")
        print("="*70)
        print("\nReady to proceed with end-to-end map generation tests.")
        return 0
    else:
        print("⚠️  SOME PHASES FAILED - REVIEW ERRORS ABOVE")
        print("="*70)
        return 1


if __name__ == '__main__':
    sys.exit(main())
