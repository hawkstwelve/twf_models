#!/usr/bin/env python3
"""
Test script to verify the total precipitation fix.

This tests that precipitation is now correctly summed across all forecast hours
instead of just using a single 6-hour bucket.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import logging

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.services.data_fetcher import GFSDataFetcher
from app.services.map_generator import MapGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_total_precip():
    """Test total precipitation calculation"""
    print("=" * 80)
    print("TEST: Total Precipitation Fix Verification")
    print("=" * 80)
    
    fetcher = GFSDataFetcher()
    generator = MapGenerator()
    
    # Get latest run time
    run_time = fetcher.get_latest_run_time()
    
    print(f"\nRun Time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
    print("-" * 80)
    
    # Test 72-hour total precipitation
    forecast_hour = 72
    
    print(f"\n📊 Testing {forecast_hour}-hour total precipitation...")
    print(f"   This should sum precipitation from f006 + f012 + ... + f{forecast_hour:03d}")
    print()
    
    try:
        # Fetch total precipitation (new method)
        total_precip = fetcher.fetch_total_precipitation(
            run_time=run_time,
            forecast_hour=forecast_hour,
            subset_region=True
        )
        
        print("\n✅ Successfully fetched total precipitation")
        print(f"   Shape: {total_precip.shape}")
        print(f"   Dims: {total_precip.dims}")
        
        # Get statistics
        import numpy as np
        values = total_precip.values
        max_mm = float(np.max(values))
        mean_mm = float(np.mean(values))
        max_inches = max_mm / 25.4
        mean_inches = mean_mm / 25.4
        
        print(f"\n📈 Statistics:")
        print(f"   Maximum: {max_mm:.2f} mm = {max_inches:.2f} inches")
        print(f"   Mean:    {mean_mm:.2f} mm = {mean_inches:.2f} inches")
        
        # Find location of maximum
        max_idx = np.unravel_index(np.argmax(values), values.shape)
        lon_coord = 'lon' if 'lon' in total_precip.coords else 'longitude'
        lat_coord = 'lat' if 'lat' in total_precip.coords else 'latitude'
        
        max_lon = float(total_precip.coords[lon_coord].values[max_idx[1] if len(max_idx) > 1 else 0])
        max_lat = float(total_precip.coords[lat_coord].values[max_idx[0] if len(max_idx) > 1 else 0])
        
        # Convert longitude to -180/180 if needed
        if max_lon > 180:
            max_lon = max_lon - 360
        
        print(f"   Max location: {abs(max_lon):.2f}°W, {max_lat:.2f}°N")
        
        # Compare with known-good value
        print(f"\n🔍 Comparison with WeatherBELL:")
        print(f"   WeatherBELL shows ~3.03\" at 125°W, 48°N")
        print(f"   Our data shows {max_inches:.2f}\" at {abs(max_lon):.2f}°W, {max_lat:.2f}°N")
        
        if max_inches > 2.0:
            print(f"\n✅ Values look reasonable! Data appears to be correctly summed.")
        else:
            print(f"\n⚠️  Values still seem low. May need further investigation.")
        
        # Now test generating a map
        print(f"\n🗺️  Generating precipitation map...")
        
        # Create a minimal dataset with the total precipitation
        import xarray as xr
        ds = xr.Dataset()
        ds['tp'] = total_precip
        
        # Copy coordinates
        for coord in total_precip.coords:
            ds.coords[coord] = total_precip.coords[coord]
        
        # Generate map
        map_path = generator.generate_map(
            ds=ds,
            variable="precip",
            model="GFS",
            run_time=run_time,
            forecast_hour=forecast_hour
        )
        
        print(f"✅ Map generated: {map_path}")
        print(f"   File size: {map_path.stat().st_size / 1024:.1f} KB")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = test_total_precip()
    sys.exit(0 if success else 1)
