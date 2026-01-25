#!/usr/bin/env python3
"""
Test script for Precipitation map generation.

Tests the total precipitation map with station overlays.
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


def test_precip_map():
    """Test precipitation map generation"""
    print("=" * 70)
    print("TEST: Precipitation Map Generation")
    print("=" * 70)
    
    generator = MapGenerator()
    fetcher = GFSDataFetcher()
    
    # Get the latest available run time (00Z, 06Z, 12Z, or 18Z)
    run_time = fetcher.get_latest_run_time()
    
    # Use configured forecast hours (6-hour increments)
    forecast_hours = settings.forecast_hours_list
    
    print(f"\nRun Time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
    print(f"Forecast Hours: {', '.join(map(str, forecast_hours))}")
    print(f"Map Type: Total Precipitation")
    print("-" * 70)
    
    success_count = 0
    
    for hour in forecast_hours:
        print(f"\n🗺️  Generating precipitation map for +{hour}h...")
        try:
            # For precipitation, we need to use fetch_total_precipitation() which sums
            # all forecast hours from 0 to the target hour (e.g., f006+f012+...+f072)
            # because GFS GRIB files contain 6-hour buckets, not cumulative totals
            
            if hour == 0:
                # Hour 0 (analysis) has no accumulated precipitation
                # Fetch regular data with prate
                ds = fetcher.fetch_gfs_data(
                    run_time=run_time,
                    forecast_hour=hour,
                    variables=['prate'],
                    subset_region=True
                )
            else:
                # For hours > 0, fetch total accumulated precipitation
                # This downloads and sums multiple files (f006, f012, ..., target_hour)
                print(f"  Fetching total precipitation (0-{hour}h) by summing multiple files...")
                total_precip = fetcher.fetch_total_precipitation(
                    run_time=run_time,
                    forecast_hour=hour,
                    subset_region=True
                )
                
                # Create dataset with the total precipitation
                import xarray as xr
                ds = xr.Dataset()
                ds['tp'] = total_precip
                # Copy coordinates
                for coord in total_precip.coords:
                    ds.coords[coord] = total_precip.coords[coord]
            
            # Generate map with dataset
            output_path = generator.generate_map(
                ds=ds,
                variable='precip',
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
        print("\n✅ All precipitation maps generated successfully!")
    else:
        print(f"\n⚠️  {len(forecast_hours) - success_count} map(s) failed")


if __name__ == "__main__":
    test_precip_map()
