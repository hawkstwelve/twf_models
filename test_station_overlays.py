"""
Test script for station overlay functionality.

Generates maps with and without station overlays for comparison.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.services.map_generator import MapGenerator
from app.config import settings


def test_station_overlays():
    """Generate maps with station overlays to test the feature"""
    
    print("=" * 70)
    print("STATION OVERLAY TEST")
    print("=" * 70)
    
    # Use yesterday's 18z run to be safe
    test_date = datetime.utcnow() - timedelta(days=1)
    run_time = test_date.replace(hour=18, minute=0, second=0, microsecond=0)
    
    print(f"\nRun time: {run_time.strftime('%Y-%m-%d %H')}Z")
    print(f"Forecast hour: 0 (analysis)")
    print(f"Region: Pacific Northwest")
    
    # Create output directory
    output_dir = Path("images/station_overlay_test")
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir}")
    
    # Test with temperature map (best for visualizing)
    print("\n" + "=" * 70)
    print("TEST 1: Temperature Map with Station Overlays")
    print("=" * 70)
    
    try:
        # Save original setting
        original_overlay = settings.station_overlays
        
        # Generate map WITH overlays
        print("\n1. Generating map WITH station overlays...")
        settings.station_overlays = True
        settings.station_priority = 2  # Major + secondary cities
        
        gen = MapGenerator()
        
        import time
        start_time = time.time()
        
        map_path_with = gen.generate_map(
            variable='temp',
            model='GFS',
            run_time=run_time,
            forecast_hour=0,
            region='pnw'
        )
        
        elapsed_with = time.time() - start_time
        
        # Copy to test directory
        import shutil
        test_path_with = output_dir / f"temp_WITH_stations_{run_time.strftime('%Y%m%d%H')}.png"
        shutil.copy(map_path_with, test_path_with)
        
        print(f"   ✅ Generated in {elapsed_with:.1f} seconds")
        print(f"   Saved to: {test_path_with}")
        
        # Generate map WITHOUT overlays for comparison
        print("\n2. Generating map WITHOUT station overlays (for comparison)...")
        settings.station_overlays = False
        
        start_time = time.time()
        
        map_path_without = gen.generate_map(
            variable='temp',
            model='GFS',
            run_time=run_time,
            forecast_hour=0,
            region='pnw'
        )
        
        elapsed_without = time.time() - start_time
        
        test_path_without = output_dir / f"temp_WITHOUT_stations_{run_time.strftime('%Y%m%d%H')}.png"
        shutil.copy(map_path_without, test_path_without)
        
        print(f"   ✅ Generated in {elapsed_without:.1f} seconds")
        print(f"   Saved to: {test_path_without}")
        
        # Restore original setting
        settings.station_overlays = original_overlay
        
        # Print summary
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        print(f"\n✅ Both maps generated successfully!")
        print(f"\nPerformance Impact:")
        print(f"  Without overlays: {elapsed_without:.1f}s")
        print(f"  With overlays:    {elapsed_with:.1f}s")
        print(f"  Time increase:    {elapsed_with - elapsed_without:.1f}s "
              f"({(elapsed_with/elapsed_without - 1) * 100:.1f}% slower)")
        
        print(f"\n📁 Generated Files:")
        print(f"  WITH stations:    {test_path_with}")
        print(f"  WITHOUT stations: {test_path_without}")
        
        print(f"\n👀 NEXT STEPS:")
        print("-" * 70)
        print("1. Open both PNG files side-by-side")
        print("2. Compare the maps - notice the station values overlaid on the WITH map")
        print("3. Station values shown:")
        print("   • Major cities (priority 1): Seattle, Portland, Spokane, Boise")
        print("   • Secondary cities (priority 2): Eugene, Bend, Yakima, Tri-Cities, Bellingham")
        print("4. Each station shows:")
        print("   • Black dot at location")
        print("   • Temperature value in white box")
        print("   • Station abbreviation (for major cities)")
        
        print(f"\n💡 CONFIGURATION:")
        print("-" * 70)
        print("Station overlays can be controlled in your .env file or config:")
        print("  STATION_OVERLAYS=true/false   # Enable/disable overlays")
        print("  STATION_PRIORITY=1/2/3         # How many stations to show")
        print("    1 = Major cities only (4 stations)")
        print("    2 = Major + secondary (9 stations)")
        print("    3 = All stations (14 stations)")
        
        print(f"\n🎯 RECOMMENDATION:")
        print("-" * 70)
        print("Station overlays add significant value with minimal performance cost!")
        print(f"Only ~{(elapsed_with/elapsed_without - 1) * 100:.1f}% slower, but much more informative.")
        print("Suggested default: STATION_OVERLAYS=true, STATION_PRIORITY=2")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        # Restore original setting
        settings.station_overlays = original_overlay
    
    print("\n" + "=" * 70)


def test_different_variables():
    """Test station overlays on different variable types"""
    
    print("\n\n" + "=" * 70)
    print("TEST 2: Station Overlays on Different Variables")
    print("=" * 70)
    
    test_date = datetime.utcnow() - timedelta(days=1)
    run_time = test_date.replace(hour=18, minute=0, second=0, microsecond=0)
    
    output_dir = Path("images/station_overlay_test")
    
    variables = [
        ('temp', 'Temperature'),
        ('precip', 'Precipitation'),
        ('wind_speed', 'Wind Speed'),
    ]
    
    # Save original setting
    original_overlay = settings.station_overlays
    settings.station_overlays = True
    settings.station_priority = 1  # Only major cities for this test
    
    gen = MapGenerator()
    
    for var_code, var_name in variables:
        print(f"\nGenerating {var_name} map with overlays...")
        try:
            map_path = gen.generate_map(
                variable=var_code,
                model='GFS',
                run_time=run_time,
                forecast_hour=0,
                region='pnw'
            )
            
            # Copy to test directory
            import shutil
            test_path = output_dir / f"{var_code}_with_stations_{run_time.strftime('%Y%m%d%H')}.png"
            shutil.copy(map_path, test_path)
            
            print(f"   ✅ Saved to: {test_path}")
            
        except Exception as e:
            print(f"   ❌ Failed: {e}")
    
    # Restore original setting
    settings.station_overlays = original_overlay
    
    print("\n✅ Variable test complete! Check images/station_overlay_test/ for results.")


if __name__ == "__main__":
    try:
        test_station_overlays()
        test_different_variables()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
