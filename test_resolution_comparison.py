"""
Test script to generate and compare maps at different resolutions.

This will generate the same map using both 0.5° and 0.25° resolution
so you can visually compare the quality improvement.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.services.map_generator import MapGenerator
from app.config import settings
from app.services.data_fetcher import GFSDataFetcher


def test_resolution_comparison():
    """Generate maps at both resolutions for comparison"""
    
    print("=" * 70)
    print("GFS RESOLUTION COMPARISON - MAP GENERATION")
    print("=" * 70)
    
    # Use yesterday's 18z run to be safe
    test_date = datetime.utcnow() - timedelta(days=1)
    run_time = test_date.replace(hour=18, minute=0, second=0, microsecond=0)
    
    print(f"\nGenerating maps for: {run_time.strftime('%Y-%m-%d %H')}Z")
    print(f"Forecast hour: 0 (analysis)")
    print(f"Variable: Temperature (2m)")
    print(f"Region: Pacific Northwest")
    
    # Create images directory if it doesn't exist
    images_dir = Path("images/resolution_test")
    images_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\nOutput directory: {images_dir}")
    
    # Test both resolutions
    resolutions = {
        "0p50": "0.5° Standard Resolution (~30 mile spacing)",
        "0p25": "0.25° High Resolution (~15 mile spacing)"
    }
    
    results = {}
    
    for res_code, res_name in resolutions.items():
        print("\n" + "-" * 70)
        print(f"\nTesting: {res_name}")
        print(f"Resolution code: {res_code}")
        
        try:
            # Temporarily override the settings for this test
            original_res = settings.gfs_resolution
            settings.gfs_resolution = res_code
            
            print("\n1. Initializing map generator...")
            gen = MapGenerator()
            
            print("2. Fetching GFS data and generating map...")
            print("   (This will take 30-90 seconds depending on resolution)")
            
            import time
            start_time = time.time()
            
            # Generate the map
            map_path = gen.generate_map(
                variable='temp',
                model='GFS',
                run_time=run_time,
                forecast_hour=0,
                region='pnw'
            )
            
            elapsed = time.time() - start_time
            
            # Get file size
            file_size = Path(map_path).stat().st_size / (1024 * 1024)  # MB
            
            # Move to test directory with descriptive name
            new_name = f"temp_pnw_{res_code}_{run_time.strftime('%Y%m%d%H')}_f000.png"
            new_path = images_dir / new_name
            
            # Copy the file
            import shutil
            shutil.copy(map_path, new_path)
            
            print(f"\n✅ SUCCESS!")
            print(f"   Time taken: {elapsed:.1f} seconds")
            print(f"   File size: {file_size:.2f} MB")
            print(f"   Saved to: {new_path}")
            
            results[res_code] = {
                'success': True,
                'time': elapsed,
                'size': file_size,
                'path': str(new_path)
            }
            
            # Restore original resolution setting
            settings.gfs_resolution = original_res
            
        except Exception as e:
            print(f"\n❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            results[res_code] = {
                'success': False,
                'error': str(e)
            }
            # Restore original resolution setting
            settings.gfs_resolution = original_res
    
    # Print comparison summary
    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY")
    print("=" * 70)
    
    if all(r.get('success') for r in results.values()):
        print("\n✅ Both resolutions generated successfully!")
        
        print("\n📊 Performance Comparison:")
        print("-" * 70)
        print(f"{'Metric':<30} {'0.5° Standard':<20} {'0.25° High-Res':<20}")
        print("-" * 70)
        
        time_050 = results['0p50']['time']
        time_025 = results['0p25']['time']
        size_050 = results['0p50']['size']
        size_025 = results['0p25']['size']
        
        print(f"{'Generation time':<30} {f'{time_050:.1f}s':<20} {f'{time_025:.1f}s':<20}")
        print(f"{'Time increase':<30} {'(baseline)':<20} {f'{time_025/time_050:.1f}x slower':<20}")
        print(f"{'Output file size':<30} {f'{size_050:.2f} MB':<20} {f'{size_025:.2f} MB':<20}")
        print(f"{'Size increase':<30} {'(baseline)':<20} {f'{size_025/size_050:.1f}x larger':<20}")
        
        print("\n📁 Generated Files:")
        print("-" * 70)
        for res_code in ['0p50', '0p25']:
            print(f"{resolutions[res_code]}:")
            print(f"  {results[res_code]['path']}")
        
        print("\n👀 NEXT STEPS:")
        print("-" * 70)
        print("1. Open both PNG files side-by-side in your image viewer")
        print("2. Compare the detail and smoothness of contours")
        print("3. Look especially at:")
        print("   • Terrain representation (mountains, coastline)")
        print("   • Smoothness of temperature gradients")
        print("   • Overall professional appearance")
        print("4. Decide if the quality improvement justifies:")
        print(f"   • {time_025/time_050:.1f}x longer generation time")
        print(f"   • {size_025/size_050:.1f}x larger file sizes")
        print("   • 3.1x larger GRIB downloads (but cached!)")
        
        print("\n💡 RECOMMENDATION:")
        print("-" * 70)
        print("For a TropicalTidbits-quality product, 0.25° is strongly recommended.")
        print("The quality improvement is substantial and visible.")
        print("With GRIB caching, the download time impact is mitigated.")
        
    else:
        print("\n❌ One or more resolutions failed to generate.")
        for res_code, result in results.items():
            if not result.get('success'):
                print(f"\n{resolutions[res_code]}:")
                print(f"  Error: {result.get('error', 'Unknown error')}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    try:
        test_resolution_comparison()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
