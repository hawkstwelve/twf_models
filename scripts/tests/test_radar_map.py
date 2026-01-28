#!/usr/bin/env python3
"""
Test script for Radar Reflectivity map generation.

Tests the simulated composite radar reflectivity map.
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


def test_radar_map():
    """Test radar reflectivity map generation"""
    print("=" * 70)
    print("TEST: Radar Reflectivity Map Generation")
    print("=" * 70)
    
    generator = MapGenerator()
    
    # Get all enabled models
    enabled_models = ModelRegistry.get_enabled()
    
    # Use configured forecast hours (6-hour increments)
    forecast_hours = settings.forecast_hours_list
    
    print(f"\nModels: {', '.join(enabled_models.keys())}")
    print(f"Forecast Hours: {', '.join(map(str, forecast_hours))}")
    print(f"Map Type: Simulated Composite Radar Reflectivity")
    print("-" * 70)
    
    total_success = 0
    total_attempts = 0
    
    for model_id in enabled_models.keys():
        model_config = enabled_models[model_id]
        
        # Skip models that don't support radar
        if not model_config.has_refc:
            print(f"\n⏭️  Skipping {model_id} - radar not supported")
            continue
        
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
                print(f"\n🗺️  Generating radar map for +{hour}h...")
                try:
                    # Fetch data first - include precipitation type variables for proper coloring
                    ds = fetcher.build_dataset_for_maps(
                        run_time=run_time,
                        forecast_hour=hour,
                        variables=['refc', 'crain', 'csnow', 'cicep', 'cfrzr'],
                        subset_region=True
                    )
                    
                    # Generate map with dataset
                    output_path = generator.generate_map(
                        ds=ds,
                        variable='radar',
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
        print("\n✅ All radar maps generated successfully!")
    else:
        print(f"\n⚠️  {total_attempts - total_success} map(s) failed")


if __name__ == "__main__":
    test_radar_map()
