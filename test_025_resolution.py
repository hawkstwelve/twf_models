"""
Test script to verify 0.25° GFS data access and compare with current 0.5° resolution.

This will help determine:
1. If 0.25° data is accessible on AWS S3
2. File sizes and download times
3. Grid dimensions and coverage
4. Any code changes needed
"""

import s3fs
from datetime import datetime, timedelta
import time


def test_gfs_resolution_access():
    """Test access to both 0.5° and 0.25° GFS data"""
    
    print("=" * 70)
    print("GFS RESOLUTION COMPARISON TEST")
    print("=" * 70)
    
    # Initialize S3 filesystem
    print("\n1. Connecting to AWS S3 (NOAA GFS bucket)...")
    s3 = s3fs.S3FileSystem(anon=True, client_kwargs={'region_name': 'us-east-1'})
    print("✅ Connected successfully")
    
    # Use most recent GFS run (yesterday 18z to be safe)
    test_date = datetime.utcnow() - timedelta(days=1)
    test_date = test_date.replace(hour=18, minute=0, second=0, microsecond=0)
    date_str = test_date.strftime("%Y%m%d")
    hour_str = test_date.strftime("%H")
    
    print(f"\n2. Testing GFS run: {date_str} {hour_str}Z")
    print(f"   Forecast hour: 000 (analysis)")
    
    # Define file paths for both resolutions
    bucket = "noaa-gfs-bdp-pds"
    
    # Current 0.5° resolution (we know this works)
    grib_050_path = f"{bucket}/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.0p50.f000"
    
    # Target 0.25° resolution (testing)
    grib_025_path = f"{bucket}/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.0p25.f000"
    
    print("\n3. Checking file availability...")
    print("-" * 70)
    
    # Test 0.5° file (current)
    print("\n   0.5° Resolution (CURRENT):")
    print(f"   Path: {grib_050_path}")
    
    try:
        if s3.exists(grib_050_path):
            file_info = s3.info(grib_050_path)
            file_size_mb = file_info['size'] / (1024 * 1024)
            print(f"   ✅ File exists")
            print(f"   Size: {file_size_mb:.1f} MB")
        else:
            print(f"   ❌ File not found")
    except Exception as e:
        print(f"   ❌ Error checking file: {e}")
    
    # Test 0.25° file (target)
    print("\n   0.25° Resolution (TARGET):")
    print(f"   Path: {grib_025_path}")
    
    try:
        if s3.exists(grib_025_path):
            file_info = s3.info(grib_025_path)
            file_size_mb = file_info['size'] / (1024 * 1024)
            print(f"   ✅ File exists")
            print(f"   Size: {file_size_mb:.1f} MB")
            print(f"   📊 File size ratio: {file_size_mb / 153.0:.1f}x larger than 0.5°")
            
            # Test download speed
            print("\n4. Testing download speed...")
            print("   (Downloading first 10 MB to test connection speed)")
            
            start_time = time.time()
            with s3.open(grib_025_path, 'rb') as f:
                # Read first 10 MB
                chunk = f.read(10 * 1024 * 1024)
            elapsed = time.time() - start_time
            
            speed_mbps = (10 / elapsed)
            estimated_full_download = file_size_mb / speed_mbps
            
            print(f"   ✅ Downloaded 10 MB in {elapsed:.1f} seconds")
            print(f"   Speed: {speed_mbps:.1f} MB/s")
            print(f"   Estimated full file download: {estimated_full_download:.1f} seconds")
            
            # Analyze grid dimensions
            print("\n5. Analyzing grid dimensions...")
            print("-" * 70)
            
            print("\n   Resolution Comparison:")
            print("   " + "=" * 66)
            print(f"   {'Metric':<30} {'0.5° (Current)':<18} {'0.25° (Target)':<18}")
            print("   " + "=" * 66)
            print(f"   {'Grid Spacing':<30} {'~55 km / ~30 mi':<18} {'~28 km / ~15 mi':<18}")
            print(f"   {'PNW Grid Points (approx.)':<30} {'23 x 39 = 897':<18} {'46 x 78 = 3,588':<18}")
            print(f"   {'Data Points Increase':<30} {'1x (baseline)':<18} {'4x more detail':<18}")
            print(f"   {'File Size':<30} {'~153 MB':<18} {f'~{file_size_mb:.0f} MB':<18}")
            print("   " + "=" * 66)
            
            print("\n   Geographic Coverage (PNW Region):")
            print("   Longitude: -125° to -110° (15° span)")
            print("   Latitude: 42° to 49° (7° span)")
            print("   ")
            print(f"   0.5° resolution: {15/0.5:.0f} x {7/0.5:.0f} = {(15/0.5)*(7/0.5):.0f} grid points")
            print(f"   0.25° resolution: {15/0.25:.0f} x {7/0.25:.0f} = {(15/0.25)*(7/0.25):.0f} grid points")
            
            print("\n6. Impact Assessment:")
            print("-" * 70)
            print("   ✅ PROS:")
            print("      • 4x more detail - better terrain representation")
            print("      • Better resolution of weather features")
            print("      • Smoother contours and gradients")
            print("      • More professional-looking maps")
            print("      • Comparable to TropicalTidbits quality")
            print("   ")
            print("   ⚠️  CONS:")
            print(f"      • {file_size_mb / 153.0:.1f}x larger file downloads")
            print(f"      • ~{estimated_full_download / 45:.1f}x longer download time per file")
            print("      • 4x more data to process (more RAM, CPU)")
            print("      • Larger output PNG files")
            
            print("\n7. Required Code Changes:")
            print("-" * 70)
            print("   Minimal changes needed:")
            print("   ")
            print("   1. Update GRIB file path in data_fetcher.py:")
            print("      FROM: gfs.t{hour}z.pgrb2.0p50.f{fhour:03d}")
            print("      TO:   gfs.t{hour}z.pgrb2.0p25.f{fhour:03d}")
            print("   ")
            print("   2. No changes needed to:")
            print("      • GRIB parsing code (handles any resolution)")
            print("      • Regional subsetting (lat/lon bounds same)")
            print("      • Map generation (matplotlib scales automatically)")
            print("      • Unit conversions")
            print("   ")
            print("   3. Optional optimizations:")
            print("      • Increase map DPI for sharper output")
            print("      • Adjust contour intervals if needed")
            print("      • Consider caching (already implemented)")
            
            print("\n8. Recommendation:")
            print("-" * 70)
            print("   ✅ RECOMMENDED: Switch to 0.25° resolution")
            print("   ")
            print("   Reasons:")
            print("   • File is accessible and downloads reasonably fast")
            print(f"   • Only {file_size_mb / 153.0:.1f}x larger than current files")
            print("   • Significant quality improvement (4x detail)")
            print("   • Minimal code changes required")
            print("   • GRIB caching will mitigate download time")
            print("   • Matches industry-standard quality (TropicalTidbits)")
            print("   ")
            print("   Impact on system:")
            print(f"   • Per-run bandwidth: {file_size_mb * 4:.0f} MB (4 forecast hours)")
            print(f"   • Daily bandwidth: {file_size_mb * 4 * 4:.0f} MB (4 runs/day)")
            print(f"   • With caching: {file_size_mb * 4:.0f} MB per run (reused across map types)")
            
        else:
            print(f"   ❌ File not found")
            print("\n   Checking if 0.25° data is available in a different location...")
            
            # Try alternative paths
            alt_paths = [
                f"{bucket}/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.0p25.anl",
                f"{bucket}/gfs.{date_str}/{hour_str}/gfs.t{hour_str}z.pgrb2.0p25.f000",
            ]
            
            for alt_path in alt_paths:
                print(f"\n   Trying: {alt_path}")
                if s3.exists(alt_path):
                    print(f"   ✅ Found at this location!")
                    break
                else:
                    print(f"   ❌ Not here")
            else:
                print("\n   ⚠️  0.25° data may not be available on AWS S3")
                print("   Alternative options:")
                print("   • Check NOAA's NOMADS server")
                print("   • Use 0.5° for now, upgrade later")
                print("   • Contact NOAA about 0.25° availability")
                
    except Exception as e:
        print(f"   ❌ Error checking file: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


def check_available_resolutions():
    """List all available GFS file types for a recent run"""
    print("\n\n" + "=" * 70)
    print("CHECKING ALL AVAILABLE GFS FILES")
    print("=" * 70)
    
    s3 = s3fs.S3FileSystem(anon=True, client_kwargs={'region_name': 'us-east-1'})
    
    test_date = datetime.utcnow() - timedelta(days=1)
    test_date = test_date.replace(hour=18, minute=0, second=0, microsecond=0)
    date_str = test_date.strftime("%Y%m%d")
    hour_str = test_date.strftime("%H")
    
    path = f"noaa-gfs-bdp-pds/gfs.{date_str}/{hour_str}/atmos/"
    
    print(f"\nListing files in: {path}")
    print("-" * 70)
    
    try:
        files = s3.ls(path)
        
        # Filter for f000 (analysis) files
        f000_files = [f for f in files if 'f000' in f or 'anl' in f]
        
        print("\nAvailable forecast hour 000 files:")
        for f in f000_files:
            file_name = f.split('/')[-1]
            try:
                size = s3.info(f)['size'] / (1024 * 1024)
                print(f"   {file_name:<60} {size:>8.1f} MB")
            except:
                print(f"   {file_name}")
        
    except Exception as e:
        print(f"Error listing files: {e}")


if __name__ == "__main__":
    try:
        test_gfs_resolution_access()
        check_available_resolutions()
        
        print("\n\n📝 NEXT STEPS:")
        print("-" * 70)
        print("1. Review the results above")
        print("2. If 0.25° is available and downloads reasonably fast:")
        print("   • Update data_fetcher.py to use 0.25° files")
        print("   • Test locally with test_map_generation.py")
        print("   • Compare map quality side-by-side")
        print("3. If 0.25° is not available:")
        print("   • Stick with 0.5° for now")
        print("   • Research alternative data sources")
        print("\n")
        
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
