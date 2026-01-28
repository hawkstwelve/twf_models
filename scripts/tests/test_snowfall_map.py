#!/usr/bin/env python3
"""
Test script for Total Snowfall map generation.

Tests the new total snowfall (10:1 ratio) map feature which derives
snowfall from total precipitation (tp) and categorical snow mask (csnow).

Usage:
    python test_snowfall_map.py [--forecast-hour HOUR] [--model MODEL]
"""

import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent.parent / 'backend'
sys.path.insert(0, str(backend_path))

import argparse
import logging
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_snowfall_map(model_id: str = 'gfs', forecast_hour: int = 12):
    """
    Test total snowfall map generation.
    
    Args:
        model_id: Model to use ('gfs' or 'aigfs')
        forecast_hour: Forecast hour to test
    """
    try:
        from app.services.model_factory import ModelFactory
        from app.services.map_generator import MapGenerator
        from app.config import settings
        
        # Convert model_id to uppercase for registry lookup
        model_id = model_id.upper()
        
        print("=" * 80)
        print(f"Testing Total Snowfall Map Generation")
        print("=" * 80)
        print(f"Model: {model_id.upper()}")
        print(f"Map Type: Total Snowfall (10:1 Ratio)")
        print(f"Forecast Hour: {forecast_hour}")
        print(f"Variables: tp, csnow (derived: tp_snow_total)")
        print()
        
        # Get data fetcher
        fetcher = ModelFactory.create_fetcher(model_id)
        logger.info(f"Using fetcher: {type(fetcher).__name__}")
        
        # Get latest run time
        run_time = fetcher.get_latest_run_time()
        logger.info(f"Latest run time: {run_time}")
        
        # Determine region
        region = 'pnw'  # Pacific Northwest for snowfall testing
        
        # Build dataset with snowfall variable
        print(f"\nStep 1: Fetching data and computing total snowfall...")
        print(f"  Run: {run_time.strftime('%Y-%m-%d %HZ')}")
        print(f"  Forecast Hour: f{forecast_hour:03d}")
        print(f"  Valid: {(run_time + timedelta(hours=forecast_hour)).strftime('%Y-%m-%d %HZ')}")
        
        try:
            ds = fetcher.build_dataset_for_maps(
                run_time=run_time,
                forecast_hour=forecast_hour,
                variables=['snowfall'],  # This will trigger tp_snow_total computation
                subset_region=True
            )
            logger.info(f"Dataset built successfully")
            logger.info(f"  Variables in dataset: {list(ds.data_vars)}")
            
            # Verify tp_snow_total was computed
            if 'tp_snow_total' not in ds:
                raise ValueError("tp_snow_total was not computed in dataset")
            
            # Log snowfall statistics
            snow_data = ds['tp_snow_total']
            print(f"\nSnowfall Statistics:")
            print(f"  Min: {float(snow_data.min()):.3f} inches")
            print(f"  Max: {float(snow_data.max()):.3f} inches")
            print(f"  Mean: {float(snow_data.mean()):.3f} inches")
            print(f"  Shape: {snow_data.shape}")
            
        except Exception as e:
            logger.error(f"Failed to build dataset: {e}")
            raise
        
        # Generate map
        print(f"\nStep 2: Generating snowfall map...")
        map_gen = MapGenerator()
        
        try:
            map_path = map_gen.generate_map(
                ds=ds,
                variable='snowfall',
                model=model_id.upper(),
                run_time=run_time,
                forecast_hour=forecast_hour,
                region=region
            )
            
            print(f"\n✓ Map generated successfully!")
            print(f"  Path: {map_path}")
            print(f"  Size: {map_path.stat().st_size / 1024:.1f} KB")
            
            return map_path
            
        except Exception as e:
            logger.error(f"Failed to generate map: {e}")
            raise
    
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return None


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Test total snowfall map generation'
    )
    parser.add_argument(
        '--model',
        default='gfs',
        choices=['gfs', 'aigfs'],
        help='Model to use (default: gfs)'
    )
    parser.add_argument(
        '--forecast-hour',
        type=int,
        default=12,
        help='Forecast hour to test (default: 12)'
    )
    
    args = parser.parse_args()
    
    result = test_snowfall_map(
        model_id=args.model,
        forecast_hour=args.forecast_hour
    )
    
    if result:
        print(f"\n{'='*80}")
        print("✓ TEST PASSED")
        print(f"{'='*80}")
        sys.exit(0)
    else:
        print(f"\n{'='*80}")
        print("✗ TEST FAILED")
        print(f"{'='*80}")
        sys.exit(1)


if __name__ == '__main__':
    main()
