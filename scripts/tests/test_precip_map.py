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
from app.services.model_factory import ModelFactory
from app.models.model_registry import ModelRegistry
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
    
    # Get all enabled models
    enabled_models = ModelRegistry.get_enabled()
    
    # Use configured forecast hours (6-hour increments)
    forecast_hours = settings.forecast_hours_list
    
    print(f"\nModels: {', '.join(enabled_models.keys())}")
    print(f"Forecast Hours: {', '.join(map(str, forecast_hours))}")
    print(f"Map Type: Total Precipitation")
    print("-" * 70)
    
    total_success = 0
    total_attempts = 0
    
    for model_id in enabled_models.keys():
        print(f"\n{'=' * 70}")
        print(f"MODEL: {model_id}")
        print(f"{'=' * 70}")
        
        try:
            fetcher = ModelFactory.create_fetcher(model_id)
            run_time = fetcher.get_latest_run_time()
            
            print(f"Run Time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
            
            success_count = 0
            
            for hour in forecast_hours:
                total_attempts += 1
                print(f"\n🗺️  Generating precipitation map for +{hour}h...")
                try:
                    # For precipitation, we need to use fetch_total_precipitation() which sums
                    # all forecast hours from 0 to the target hour (e.g., f006+f012+...+f072)
                    # because GFS GRIB files contain 6-hour buckets, not cumulative totals
                    
                    if hour == 0:
                        # Hour 0 (analysis) has no accumulated precipitation
                        # Fetch regular data with prate
                        ds = fetcher.build_dataset_for_maps(
                            run_time=run_time,
                            forecast_hour=hour,
                            variables=['prate'],
                            subset_region=True
                        )
                    else:
                        # For hours > 0, fetch total accumulated precipitation
                        # The build_dataset_for_maps method handles accumulation automatically
                        print(f"  Fetching total precipitation (0-{hour}h)...")
                        ds = fetcher.build_dataset_for_maps(
                            run_time=run_time,
                            forecast_hour=hour,
                            variables=['tp_total'],  # Request total precipitation
                            subset_region=True
                        )
                        
                        # Rename tp_total to tp for the map generator
                        if 'tp_total' in ds:
                            ds['tp'] = ds['tp_total']
                    
                    # Generate map with dataset
                    output_path = generator.generate_map(
                        ds=ds,
                        variable='precip',
                        model=model_id,
                        run_time=run_time,
                        forecast_hour=hour,
                        region='pnw'
                    )
                    
                    file_size = output_path.stat().st_size / 1024
                    print(f"  ✅ Success: {output_path.name} ({file_size:.1f} KB)")
                    success_count += 1
                    total_success += 1
                    
                except Exception as e:
                    print(f"  ❌ Error: {e}")
                    import traceback
                    traceback.print_exc()
            
            print(f"\n{model_id} Results: {success_count}/{len(forecast_hours)} maps generated")
            
        except Exception as e:
            print(f"  ❌ Error initializing {model_id}: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print(f"OVERALL RESULTS: {total_success}/{total_attempts} maps generated")
    print("=" * 70)
    
    if total_success == total_attempts:
        print("\n✅ All precipitation maps generated successfully!")
    else:
        print(f"\n⚠️  {total_attempts - total_success} map(s) failed")


if __name__ == "__main__":
    test_precip_map()
