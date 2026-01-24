#!/usr/bin/env python3
"""
Test script for MSLP & Precipitation map generation

Tests the new combined MSLP + Precipitation map type with:
- Mean Sea Level Pressure contours (every 4mb)
- Precipitation color-fill
- HIGH/LOW pressure center labels
- Labeled contour lines
"""

import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent / 'backend'
sys.path.insert(0, str(backend_path))

from app.services.map_generator import MapGenerator
from datetime import datetime, timedelta

def test_mslp_precip():
    """Test MSLP & Precipitation map generation"""
    print("=" * 60)
    print("Testing MSLP & Precipitation Map Generation")
    print("=" * 60)
    
    generator = MapGenerator()
    
    # Use most recent 12Z run (today or yesterday)
    now = datetime.utcnow()
    if now.hour >= 12:
        run_time = datetime(now.year, now.month, now.day, 12, 0, 0)
    else:
        yesterday = now - timedelta(days=1)
        run_time = datetime(yesterday.year, yesterday.month, yesterday.day, 12, 0, 0)
    
    print(f"\nRun Time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
    print(f"Forecast Hours: 0, 24, 48, 72")
    print(f"Map Type: MSLP & Precipitation")
    print("\nFeatures to check:")
    print("  ✓ Precipitation color-fill (greens/blues)")
    print("  ✓ MSLP contour lines (black, every 4mb)")
    print("  ✓ Contour labels")
    print("  ✓ HIGH/LOW pressure center labels (blue H, red L)")
    print("-" * 60)
    
    forecast_hours = [0, 24, 48, 72]
    
    for hour in forecast_hours:
        print(f"\n🗺️  Generating MSLP & Precip map for +{hour}h...")
        
        try:
            output_path = generator.generate_map(
                variable='mslp_precip',
                model='GFS',
                run_time=run_time,
                forecast_hour=hour
            )
            
            print(f"  ✅ Success: {output_path.name}")
            print(f"     Full path: {output_path}")
            
        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("MSLP & Precipitation Map Test Complete!")
    print("=" * 60)
    print("\nNext Steps:")
    print("1. Check the generated maps in /opt/twf_models/images/")
    print("2. View via: https://api.sodakweather.com/images/gfs_YYYYMMDD_HH_mslp_precip_*.png")
    print("3. Verify:")
    print("   - Precipitation shows green/blue color gradient")
    print("   - MSLP contours are visible (black lines)")
    print("   - Contours have labeled values (e.g., 1016, 1020)")
    print("   - HIGH and LOW labels appear on pressure centers")
    print("\n4. If looks good, approve for deployment to frontend!")
    print("5. Then we'll move to Priority #2: 850mb Temperature/Wind/MSLP")

if __name__ == "__main__":
    test_mslp_precip()
