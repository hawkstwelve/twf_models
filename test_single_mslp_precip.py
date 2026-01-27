#!/usr/bin/env python3
"""
Quick test script for a single MSLP & Precipitation map.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
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


def test_single_mslp_precip():
    """Test single MSLP & Precipitation map generation"""
    print("=" * 70)
    print("TEST: Single MSLP & Precipitation Map")
    print("=" * 70)
    
    generator = MapGenerator()
    fetcher = GFSDataFetcher()
    
    # Get the latest available run time
    run_time = fetcher.get_latest_run_time()
    
    # Use 54-hour forecast as test
    forecast_hour = 54
    
    print(f"\nRun Time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
    print(f"Forecast Hour: +{forecast_hour}h")
    print(f"Map Type: MSLP & Precipitation Rate")
    print("-" * 70)
    
    print(f"\n🗺️  Generating MSLP & Precip map for +{forecast_hour}h...")
    try:
        # Fetch data first
        ds = fetcher.fetch_gfs_data(
            run_time=run_time,
            forecast_hour=forecast_hour,
            variables=['prate', 'tp', 'prmsl', 'gh', 'gh_1000', 'gh_500', 'crain', 'csnow', 'cicep', 'cfrzr'],
            subset_region=True
        )
        
        # Generate map with dataset
        output_path = generator.generate_map(
            ds=ds,
            variable='mslp_precip',
            model='GFS',
            run_time=run_time,
            forecast_hour=forecast_hour,
            region='pnw'
        )
        
        file_size = output_path.stat().st_size / 1024
        print(f"  ✅ Success: {output_path.name} ({file_size:.1f} KB)")
        print(f"\n📍 Map saved to: {output_path}")
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_single_mslp_precip()
