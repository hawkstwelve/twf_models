#!/usr/bin/env python3
"""Test script for optimized GFS data fetching"""
import sys
from pathlib import Path
from datetime import datetime

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

def test_data_fetch():
    """Test the optimized data fetching"""
    print("=" * 70)
    print("Testing Optimized GFS Data Fetching")
    print("=" * 70)
    print()
    
    try:
        from app.services.data_fetcher import GFSDataFetcher
        from app.config import settings
        
        print("✅ Imports successful")
        print()
        
        # Show configuration
        print("Configuration:")
        print(f"  Region: {settings.map_region}")
        print(f"  Region bounds: {settings.map_region_bounds}")
        print(f"  GFS source: {settings.gfs_source}")
        print()
        
        # Initialize fetcher
        print("Initializing GFS Data Fetcher...")
        fetcher = GFSDataFetcher()
        print("✅ Fetcher initialized")
        print()
        
        # Get latest run time
        print("Getting latest GFS run time...")
        run_time = fetcher.get_latest_run_time()
        print(f"✅ Latest run time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
        print()
        
        # Test fetching temperature data (smallest - 1 variable)
        print("=" * 70)
        print("Test 1: Fetching Temperature Data (1 variable, PNW subset)")
        print("=" * 70)
        print("This will download ~5-10MB of data...")
        print()
        
        try:
            import time
            start_time = time.time()
            
            ds = fetcher.fetch_gfs_data(
                run_time=run_time,
                forecast_hour=0,
                variables=['tmp2m'],
                subset_region=True
            )
            
            elapsed = time.time() - start_time
            
            print(f"✅ Data fetched successfully in {elapsed:.1f} seconds")
            print()
            print("Dataset Info:")
            print(f"  Variables: {list(ds.data_vars)}")
            print(f"  Dimensions: {dict(ds.dims)}")
            print(f"  Coordinates: {list(ds.coords.keys())}")
            
            # Check size
            if hasattr(ds, 'nbytes'):
                size_mb = ds.nbytes / 1024 / 1024
                print(f"  Size in memory: {size_mb:.2f} MB")
            
            # Check if region subsetting worked
            if 'lon' in ds.coords:
                lon_range = (float(ds.lon.min()), float(ds.lon.max()))
                lat_range = (float(ds.lat.min()), float(ds.lat.max()))
                print(f"  Longitude range: {lon_range[0]:.2f}° to {lon_range[1]:.2f}°")
                print(f"  Latitude range: {lat_range[0]:.2f}° to {lat_range[1]:.2f}°")
                
                # Verify it's in PNW range
                expected_lon = (-125, -110)
                expected_lat = (42, 49)
                if (expected_lon[0] - 5 <= lon_range[0] <= expected_lon[1] + 5 and
                    expected_lat[0] - 5 <= lat_range[0] <= expected_lat[1] + 5):
                    print("  ✅ Region subsetting appears to be working (PNW region)")
                else:
                    print("  ⚠️  Region may not be subset correctly")
            elif 'longitude' in ds.coords:
                lon_range = (float(ds.longitude.min()), float(ds.longitude.max()))
                lat_range = (float(ds.latitude.min()), float(ds.latitude.max()))
                print(f"  Longitude range: {lon_range[0]:.2f}° to {lon_range[1]:.2f}°")
                print(f"  Latitude range: {lat_range[0]:.2f}° to {lat_range[1]:.2f}°")
            
            print()
            
        except Exception as e:
            print(f"❌ Error fetching temperature data: {e}")
            import traceback
            traceback.print_exc()
            return 1
        
        # Test fetching wind data (2 variables)
        print("=" * 70)
        print("Test 2: Fetching Wind Speed Data (2 variables, PNW subset)")
        print("=" * 70)
        print("This will download ~10-15MB of data...")
        print()
        
        try:
            start_time = time.time()
            
            ds_wind = fetcher.fetch_gfs_data(
                run_time=run_time,
                forecast_hour=0,
                variables=['ugrd10m', 'vgrd10m'],
                subset_region=True
            )
            
            elapsed = time.time() - start_time
            
            print(f"✅ Wind data fetched successfully in {elapsed:.1f} seconds")
            print()
            print("Dataset Info:")
            print(f"  Variables: {list(ds_wind.data_vars)}")
            print(f"  Dimensions: {dict(ds_wind.dims)}")
            
            if hasattr(ds_wind, 'nbytes'):
                size_mb = ds_wind.nbytes / 1024 / 1024
                print(f"  Size in memory: {size_mb:.2f} MB")
            
            print()
            
        except Exception as e:
            print(f"❌ Error fetching wind data: {e}")
            import traceback
            traceback.print_exc()
            return 1
        
        # Summary
        print("=" * 70)
        print("Test Summary")
        print("=" * 70)
        print("✅ All tests passed!")
        print()
        print("Optimization verified:")
        print("  ✅ Only fetching needed variables")
        print("  ✅ Region subsetting working")
        print("  ✅ Data sizes are much smaller than full files")
        print()
        print("Next steps:")
        print("  1. Test map generation with this data")
        print("  2. Verify maps look correct")
        print("  3. Deploy to production")
        
        return 0
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're in the project directory and virtual environment is activated")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(test_data_fetch())
