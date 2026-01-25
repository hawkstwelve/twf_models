#!/usr/bin/env python3
"""
Test script for Wind Speed map generation.

Tests the 10m wind speed map with station overlays.
Note: Wind speed is skipped for forecast hour 0 (analysis file).
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import logging

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.services.map_generator import MapGenerator
from app.services.data_fetcher import GFSDataFetcher
from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_wind_speed_map():
    """Test wind speed map generation"""
    print("=" * 70)
    print("TEST: Wind Speed Map Generation")
    print("=" * 70)
    
    generator = MapGenerator()
    fetcher = GFSDataFetcher()
    
    # Get the latest available run time (00Z, 06Z, 12Z, or 18Z)
    run_time = fetcher.get_latest_run_time()
    
    print(f"\nRun Time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
    print(f"Forecast Hours: 24, 48, 72 (wind_speed skipped for f000)")
    print(f"Map Type: Wind Speed (10m)")
    print("-" * 70)
    
    # Wind speed is not available in analysis file (f000)
    forecast_hours = [24, 48, 72]
    success_count = 0
    
    for hour in forecast_hours:
        print(f"\n🗺️  Generating wind speed map for +{hour}h...")
        try:
            # Fetch data first
            ds = fetcher.fetch_gfs_data(
                run_time=run_time,
                forecast_hour=hour,
                variables=['ugrd10m', 'vgrd10m'],
                subset_region=True
            )
            
            # Generate map with dataset
            output_path = generator.generate_map(
                ds=ds,
                variable='wind_speed',
                model='GFS',
                run_time=run_time,
                forecast_hour=hour,
                region='pnw'
            )
            
            file_size = output_path.stat().st_size / 1024
            print(f"  ✅ Success: {output_path.name} ({file_size:.1f} KB)")
            success_count += 1
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print(f"RESULTS: {success_count}/{len(forecast_hours)} maps generated")
    print("=" * 70)
    
    if success_count == len(forecast_hours):
        print("\n✅ All wind speed maps generated successfully!")
    else:
        print(f"\n⚠️  {len(forecast_hours) - success_count} map(s) failed")


if __name__ == "__main__":
    test_wind_speed_map()
