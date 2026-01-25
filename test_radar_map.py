#!/usr/bin/env python3
"""
Test script for Radar Reflectivity map generation.

Tests the simulated composite radar reflectivity map.
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


def test_radar_map():
    """Test radar reflectivity map generation"""
    print("=" * 70)
    print("TEST: Radar Reflectivity Map Generation")
    print("=" * 70)
    
    generator = MapGenerator()
    fetcher = GFSDataFetcher()
    
    # Get the latest available run time (00Z, 06Z, 12Z, or 18Z)
    run_time = fetcher.get_latest_run_time()
    
    # Use configured forecast hours (6-hour increments)
    forecast_hours = settings.forecast_hours_list
    
    print(f"\nRun Time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
    print(f"Forecast Hours: {', '.join(map(str, forecast_hours))}")
    print(f"Map Type: Simulated Composite Radar Reflectivity")
    print("-" * 70)
    
    success_count = 0
    
    for hour in forecast_hours:
        print(f"\n🗺️  Generating radar map for +{hour}h...")
        try:
            # Fetch data first
            ds = fetcher.fetch_gfs_data(
                run_time=run_time,
                forecast_hour=hour,
                variables=['refc'],
                subset_region=True
            )
            
            # Generate map with dataset
            output_path = generator.generate_map(
                ds=ds,
                variable='radar',
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
        print("\n✅ All radar maps generated successfully!")
    else:
        print(f"\n⚠️  {len(forecast_hours) - success_count} map(s) failed")


if __name__ == "__main__":
    test_radar_map()
