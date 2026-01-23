#!/usr/bin/env python3
"""Test generating maps for multiple forecast hours"""
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

def test_multiple_forecast_hours():
    """Test generating maps for forecast hours 0, 24, 48, 72"""
    print("=" * 70)
    print("Testing Multiple Forecast Hours (0, 24, 48, 72)")
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
    forecast_hours = [0, 24, 48, 72]
    
    results = {
        'success': [],
        'failed': []
    }
    
    # Test temperature maps for each forecast hour
    print("Testing Temperature Maps:")
    print("-" * 70)
    
    for fh in forecast_hours:
        print(f"\nForecast Hour {fh:03d}:")
        try:
            temp_path = generator.generate_map(
                variable="temp",
                model="GFS",
                run_time=run_time,
                forecast_hour=fh,
                region="pnw"
            )
            size_kb = temp_path.stat().st_size / 1024
            print(f"  ✅ Success: {temp_path.name} ({size_kb:.1f} KB)")
            results['success'].append(f"temp_{fh}")
        except Exception as e:
            print(f"  ❌ Failed: {str(e)[:100]}")
            results['failed'].append(f"temp_{fh}")
    
    print()
    print("=" * 70)
    print("Summary:")
    print("=" * 70)
    print(f"✅ Successful: {len(results['success'])}/{len(forecast_hours) * 1}")
    print(f"❌ Failed: {len(results['failed'])}/{len(forecast_hours) * 1}")
    
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
    sys.exit(test_multiple_forecast_hours())
