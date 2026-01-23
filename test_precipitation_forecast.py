#!/usr/bin/env python3
"""Test precipitation maps for forecast hours 24, 48, 72 to verify surface level fix"""
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

def test_precipitation_forecast():
    """Test precipitation maps for forecast hours to verify fix"""
    print("=" * 70)
    print("Testing Precipitation Maps for Forecast Hours")
    print("=" * 70)
    print()
    
    from app.services.map_generator import MapGenerator
    
    # Get latest run time
    now = datetime.utcnow()
    run_hour = ((now.hour // 6) * 6) - 6
    if run_hour < 0:
        run_hour = 18
        now = now - timedelta(days=1)
    
    run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    print(f"Using GFS run time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
    print()
    
    generator = MapGenerator()
    forecast_hours = [0, 24, 48, 72]
    
    results = {
        'success': [],
        'failed': []
    }
    
    # Test precipitation maps for each forecast hour
    print("Testing Precipitation Maps:")
    print("-" * 70)
    
    for fh in forecast_hours:
        print(f"\nForecast Hour {fh:03d}:")
        try:
            precip_path = generator.generate_map(
                variable="precip",
                model="GFS",
                run_time=run_time,
                forecast_hour=fh,
                region="pnw"
            )
            size_kb = precip_path.stat().st_size / 1024
            print(f"  ✅ Success: {precip_path.name} ({size_kb:.1f} KB)")
            results['success'].append(f"precip_{fh}")
        except Exception as e:
            print(f"  ❌ Failed: {str(e)[:150]}")
            results['failed'].append(f"precip_{fh}")
            # Print more detail for debugging
            import traceback
            print("  Error details:")
            traceback.print_exc()
    
    print()
    print("=" * 70)
    print("Testing Precipitation Type Maps:")
    print("-" * 70)
    
    for fh in forecast_hours:
        print(f"\nForecast Hour {fh:03d}:")
        try:
            precip_type_path = generator.generate_map(
                variable="precip_type",
                model="GFS",
                run_time=run_time,
                forecast_hour=fh,
                region="pnw"
            )
            size_kb = precip_type_path.stat().st_size / 1024
            print(f"  ✅ Success: {precip_type_path.name} ({size_kb:.1f} KB)")
            results['success'].append(f"precip_type_{fh}")
        except Exception as e:
            print(f"  ❌ Failed: {str(e)[:150]}")
            results['failed'].append(f"precip_type_{fh}")
    
    print()
    print("=" * 70)
    print("Summary:")
    print("=" * 70)
    total_tests = len(forecast_hours) * 2  # precip + precip_type
    print(f"✅ Successful: {len(results['success'])}/{total_tests}")
    print(f"❌ Failed: {len(results['failed'])}/{total_tests}")
    
    if results['failed']:
        print()
        print("Failed tests:")
        for test in results['failed']:
            print(f"  - {test}")
    
    print()
    print(f"Maps saved to: {generator.storage_path}")
    print()
    
    # Return 0 if all tests passed, 1 otherwise
    return 0 if len(results['failed']) == 0 else 1

if __name__ == "__main__":
    sys.exit(test_precipitation_forecast())
