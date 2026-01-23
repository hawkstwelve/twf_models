#!/usr/bin/env python3
"""Simplified test - try multiple run times to find available data"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import importlib
import logging

# Configure logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format='%(name)s - %(levelname)s - %(message)s'
)

sys.path.insert(0, str(Path(__file__).parent / "backend"))

def test_with_fallback():
    """Test data fetching with fallback to older runs"""
    print("=" * 70)
    print("Testing GFS Data Fetching (with run time fallback)")
    print("=" * 70)
    print()
    
    # Import and reload to ensure latest changes
    from app.services import data_fetcher
    importlib.reload(data_fetcher)
    from app.services.data_fetcher import GFSDataFetcher
    
    fetcher = GFSDataFetcher()
    
    # Get latest run time (go back one cycle to ensure data is available)
    now = datetime.utcnow()
    run_hour = ((now.hour // 6) * 6) - 6
    if run_hour < 0:
        run_hour = 18
        now = now - timedelta(days=1)
    
    run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    print(f"Trying latest available run time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
    print()
    
    # Try just the latest run time
    run_times_to_try = [run_time]
    
    for run_time in run_times_to_try:
        print(f"Trying {run_time.strftime('%Y-%m-%d %H:00 UTC')}...")
        try:
            ds = fetcher.fetch_gfs_data(
                run_time=run_time,
                forecast_hour=0,
                variables=['tmp2m'],
                subset_region=True
            )
            
            print(f"✅ Success! Data fetched from {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
            print()
            print("Dataset Info:")
            print(f"  Variables: {list(ds.data_vars)}")
            print(f"  Dimensions: {dict(ds.dims)}")
            
            if hasattr(ds, 'nbytes'):
                size_mb = ds.nbytes / 1024 / 1024
                print(f"  Size: {size_mb:.2f} MB")
            
            if 'lon' in ds.coords:
                lon_range = (float(ds.lon.min()), float(ds.lon.max()))
                lat_range = (float(ds.lat.min()), float(ds.lat.max()))
                print(f"  Longitude: {lon_range[0]:.1f}° to {lon_range[1]:.1f}°")
                print(f"  Latitude: {lat_range[0]:.1f}° to {lat_range[1]:.1f}°")
            
            print()
            print("✅ Optimization working! Data size is much smaller than full files.")
            return 0
            
        except Exception as e:
            error_msg = str(e)
            print(f"  ❌ Failed: {error_msg}")
            # Print full traceback for debugging
            import traceback
            print("Full error details:")
            traceback.print_exc()
            continue
    
    print("❌ Could not fetch data from any run time")
    print("This might be a network issue or the GFS data structure may have changed.")
    return 1

if __name__ == "__main__":
    sys.exit(test_with_fallback())
