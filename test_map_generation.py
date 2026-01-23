#!/usr/bin/env python3
"""Test map generation with real GFS data"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(name)s - %(levelname)s - %(message)s'
)

sys.path.insert(0, str(Path(__file__).parent / "backend"))

def test_map_generation():
    """Test generating weather maps"""
    print("=" * 70)
    print("Testing Weather Map Generation")
    print("=" * 70)
    print()
    
    from app.services.map_generator import MapGenerator
    
    # Get latest run time (go back one cycle to ensure data is available)
    now = datetime.utcnow()
    run_hour = ((now.hour // 6) * 6) - 6
    if run_hour < 0:
        run_hour = 18
        now = now - timedelta(days=1)
    
    run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    print(f"Using GFS run time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
    print()
    
    generator = MapGenerator()
    
    # Test 1: Temperature map
    print("Test 1: Generating temperature map...")
    try:
        temp_path = generator.generate_map(
            variable="temp",
            model="GFS",
            run_time=run_time,
            forecast_hour=0,
            region="pnw"
        )
        print(f"✅ Temperature map saved: {temp_path}")
        print(f"   File size: {temp_path.stat().st_size / 1024:.1f} KB")
    except Exception as e:
        print(f"❌ Temperature map failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    print()
    
    # Test 2: Precipitation map
    print("Test 2: Generating precipitation map...")
    try:
        precip_path = generator.generate_map(
            variable="precip",
            model="GFS",
            run_time=run_time,
            forecast_hour=0,
            region="pnw"
        )
        print(f"✅ Precipitation map saved: {precip_path}")
        print(f"   File size: {precip_path.stat().st_size / 1024:.1f} KB")
    except Exception as e:
        print(f"❌ Precipitation map failed: {e}")
        import traceback
        traceback.print_exc()
        # Continue to next test
    
    print()
    
    # Test 3: Wind speed map
    print("Test 3: Generating wind speed map...")
    try:
        wind_path = generator.generate_map(
            variable="wind_speed",
            model="GFS",
            run_time=run_time,
            forecast_hour=0,
            region="pnw"
        )
        print(f"✅ Wind speed map saved: {wind_path}")
        print(f"   File size: {wind_path.stat().st_size / 1024:.1f} KB")
    except Exception as e:
        print(f"❌ Wind speed map failed: {e}")
        import traceback
        traceback.print_exc()
        # Continue to next test
    
    print()
    
    # Test 4: Precipitation type map
    print("Test 4: Generating precipitation type map...")
    try:
        precip_type_path = generator.generate_map(
            variable="precip_type",
            model="GFS",
            run_time=run_time,
            forecast_hour=0,
            region="pnw"
        )
        print(f"✅ Precipitation type map saved: {precip_type_path}")
        print(f"   File size: {precip_type_path.stat().st_size / 1024:.1f} KB")
    except Exception as e:
        print(f"❌ Precipitation type map failed: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    print("=" * 70)
    print("Map Generation Test Complete!")
    print("=" * 70)
    print()
    print(f"Maps saved to: {generator.storage_path}")
    print()
    
    return 0

if __name__ == "__main__":
    sys.exit(test_map_generation())
