#!/usr/bin/env python3
"""
Test script for HRRR model via Herbie.

Tests HRRR (High-Resolution Rapid Refresh):
- 3km resolution (vs 25km GFS)
- Hourly updates (vs 6-hourly)
- 48-hour forecast range
- Multiple map types (temp, radar, wind, precip)
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import logging

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

# Override storage path for testing (avoid permission issues with /opt/twf_models)
os.environ['STORAGE_PATH'] = str(Path(__file__).parent.parent.parent / "test_cache")

from app.services.map_generator import MapGenerator
from app.services.model_factory import ModelFactory
from app.models.model_registry import ModelRegistry
from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_hrrr_maps():
    """Test HRRR map generation via Herbie"""
    print("=" * 80)
    print("TEST: HRRR Model via Herbie Integration")
    print("=" * 80)
    
    model_id = "HRRR"
    
    # Check if HRRR is enabled
    hrrr_config = ModelRegistry.get(model_id)
    if not hrrr_config:
        print(f"\n❌ {model_id} not found in registry")
        return
    
    if not hrrr_config.enabled:
        print(f"\n❌ {model_id} is not enabled")
        print("   Enable it in backend/app/models/model_registry.py")
        return
    
    print(f"\n✓ {model_id} is enabled")
    print(f"  Resolution: {hrrr_config.resolution}")
    print(f"  Forecast Range: 0-{hrrr_config.max_forecast_hour}h")
    print(f"  Increment: {hrrr_config.forecast_increment}h (hourly)")
    print(f"  Fetcher: {hrrr_config.fetcher_type or 'auto'}")
    
    generator = MapGenerator()
    
    try:
        fetcher = ModelFactory.create_fetcher(model_id)
        run_time = fetcher.get_latest_run_time()
        
        print(f"\n📅 Latest Run: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
        print("-" * 80)
        
        # Test multiple map types at different forecast hours
        # HRRR is hourly, test only recent hours (data availability)
        test_cases = [
            (0, 'temp', 'Temperature (analysis)'),
            (1, 'radar', 'Radar Reflectivity'),
            (3, 'wind_speed', 'Wind Speed'),
            (6, 'precip', 'Total Precipitation'),
        ]
        
        success_count = 0
        total_tests = len(test_cases)
        
        for hour, variable, description in test_cases:
            print(f"\n🗺️  Test {success_count + 1}/{total_tests}: {description} @ +{hour}h")
            try:
                # Fetch data
                print(f"   Fetching data via Herbie...")
                ds = fetcher.build_dataset_for_maps(
                    run_time=run_time,
                    forecast_hour=hour,
                    variables=[variable],
                    subset_region=True
                )
                
                print(f"   ✓ Data fetched: {list(ds.data_vars)}")
                print(f"   ✓ Shape: {dict(ds.dims)}")
                
                # Generate map
                print(f"   Generating {variable} map...")
                output_path = generator.generate_map(
                    ds=ds,
                    variable=variable,
                    model=model_id,
                    run_time=run_time,
                    forecast_hour=hour
                )
                
                # Verify output
                if output_path and Path(output_path).exists():
                    file_size = Path(output_path).stat().st_size / 1024
                    print(f"   ✓ Map generated: {output_path}")
                    print(f"   ✓ File size: {file_size:.1f} KB")
                    success_count += 1
                else:
                    print(f"   ✗ Map generation failed (no output)")
                    
            except Exception as e:
                print(f"   ✗ Error: {e}")
                logger.exception(f"Failed to generate {variable} map for +{hour}h")
        
        print("\n" + "=" * 80)
        print(f"RESULTS: {success_count}/{total_tests} tests passed")
        print("=" * 80)
        
        if success_count == total_tests:
            print("\n✅ All HRRR tests passed!")
            print("\nNext steps:")
            print("  1. Check output maps in images/ directory")
            print("  2. Verify high resolution (3km) detail visible")
            print("  3. Compare quality vs GFS maps")
            print("  4. Add HRRR to frontend config.js if satisfied")
        else:
            print(f"\n⚠️  {total_tests - success_count} test(s) failed")
            print("   Review logs above for details")
        
    except Exception as e:
        print(f"\n❌ HRRR test failed: {e}")
        logger.exception("HRRR test error")


def test_hrrr_herbie_integration():
    """Verify Herbie integration is working correctly"""
    print("\n" + "=" * 80)
    print("HERBIE INTEGRATION CHECK")
    print("=" * 80)
    
    try:
        from app.services.herbie_data_fetcher import HerbieDataFetcher
        print("✓ HerbieDataFetcher imported successfully")
        
        # Test initialization
        fetcher = HerbieDataFetcher("HRRR")
        print(f"✓ HRRR fetcher initialized")
        print(f"  Cache: {fetcher.herbie_save_dir}")
        print(f"  Sources: {' → '.join(fetcher.priority_sources)}")
        
        # Check if HRRR is in model map
        if "HRRR" in fetcher._herbie_model_map:
            print(f"✓ HRRR mapped to: {fetcher._herbie_model_map['HRRR']}")
        else:
            print("✗ HRRR not in Herbie model map")
            return False
        
        # Check variable mappings
        required_vars = ['tmp2m', 'ugrd10m', 'vgrd10m', 'refc', 'tp']
        missing_vars = [v for v in required_vars if v not in fetcher._variable_map]
        
        if missing_vars:
            print(f"⚠️  Missing variable mappings: {missing_vars}")
        else:
            print(f"✓ All required variables mapped")
        
        return True
        
    except ImportError as e:
        print(f"✗ Failed to import HerbieDataFetcher: {e}")
        print("  Install with: pip install herbie-data")
        return False
    except Exception as e:
        print(f"✗ Integration check failed: {e}")
        return False


if __name__ == "__main__":
    print("\n" + "🌩️ " * 20)
    print("HRRR MODEL TEST (Phase 2: Herbie Implementation)")
    print("🌩️ " * 20)
    
    # First verify Herbie integration
    if test_hrrr_herbie_integration():
        # Then test map generation
        test_hrrr_maps()
    else:
        print("\n❌ Herbie integration check failed. Fix issues before testing maps.")
    
    print("\n✅ Test complete!")
