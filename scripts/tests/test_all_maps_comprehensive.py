#!/usr/bin/env python3
"""
Comprehensive test script to validate all map types across all models.
Tests each variable for GFS, HRRR, and AIGFS to ensure map generation works.
"""

import sys
import os

# Add backend to path
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(script_dir, '../../backend')
sys.path.insert(0, backend_dir)

from datetime import datetime, timezone, timedelta
from pathlib import Path
import logging

from app.services.model_factory import ModelFactory
from app.services.map_generator import MapGenerator
from app.config import settings

# Override storage paths to use local workspace (not production /opt/twf_models)
workspace_root = Path(script_dir).parent.parent.resolve()
settings.storage_path = workspace_root / "backend" / "app" / "static" / "images"
settings.storage_path.mkdir(parents=True, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Test configuration
TEST_CONFIG = {
    'GFS': {
        'run_time': datetime(2026, 1, 29, 12, tzinfo=timezone.utc),
        'forecast_hour': 6,
        'variables': [
            'temperature_2m',
            'precipitation',
            'snowfall',
            'wind_speed_10m',
            'temp_850_wind_mslp',
            'mslp_precip'
        ]
    },
    'HRRR': {
        'run_time': datetime(2026, 1, 30, 20, tzinfo=timezone.utc),
        'forecast_hour': 3,
        'variables': [
            'temperature_2m',
            'precipitation',
            'snowfall',
            'wind_speed_10m',
            'radar'
        ]
    },
    'AIGFS': {
        'run_time': datetime(2026, 1, 29, 12, tzinfo=timezone.utc),
        'forecast_hour': 6,
        'variables': [
            'temperature_2m',
            'precipitation',
            'snowfall',
            'wind_speed_10m',
            'temp_850_wind_mslp',
            'mslp_precip'
        ]
    }
}


def test_model_variable(model_id: str, variable: str, run_time: datetime, forecast_hour: int) -> bool:
    """
    Test generating a single map for a model/variable combination.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"\n{'='*70}")
        logger.info(f"Testing: {model_id} - {variable}")
        logger.info(f"  Run: {run_time.strftime('%Y-%m-%d %HZ')}, Forecast: f{forecast_hour:03d}")
        logger.info(f"{'='*70}")
        
        # Create fetcher and map generator
        fetcher = ModelFactory.create_fetcher(model_id)
        generator = MapGenerator()
        
        # Build dataset
        logger.info(f"Building dataset for {model_id}...")
        ds = fetcher.build_dataset_for_maps(
            run_time=run_time,
            forecast_hour=forecast_hour,
            variables=[variable]
        )
        logger.info(f"  Dataset variables: {list(ds.data_vars)}")
        
        # Generate map
        logger.info(f"Generating map for {variable}...")
        filepath = generator.generate_map(
            ds=ds,
            variable=variable,
            model=model_id,
            run_time=run_time,
            forecast_hour=forecast_hour
        )
        
        # Verify output
        if filepath.exists():
            file_size = filepath.stat().st_size
            logger.info(f"✓ SUCCESS: {filepath.name} ({file_size:,} bytes)")
            return True
        else:
            logger.error(f"✗ FAILED: Map file not created")
            return False
            
    except Exception as e:
        logger.error(f"✗ FAILED: {type(e).__name__}: {str(e)}")
        import traceback
        logger.debug(traceback.format_exc())
        return False


def main():
    """Run comprehensive map generation tests."""
    print("\n" + "="*70)
    print("COMPREHENSIVE MAP GENERATION TEST")
    print("Testing all variables across GFS, HRRR, and AIGFS")
    print("="*70)
    
    results = {}
    total_tests = 0
    successful_tests = 0
    
    # Test each model
    for model_id, config in TEST_CONFIG.items():
        run_time = config['run_time']
        forecast_hour = config['forecast_hour']
        variables = config['variables']
        
        model_results = {}
        
        for variable in variables:
            total_tests += 1
            success = test_model_variable(model_id, variable, run_time, forecast_hour)
            model_results[variable] = success
            if success:
                successful_tests += 1
        
        results[model_id] = model_results
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for model_id, model_results in results.items():
        passed = sum(1 for v in model_results.values() if v)
        total = len(model_results)
        status = "✓ PASS" if passed == total else f"✗ {passed}/{total} PASSED"
        
        print(f"\n{model_id}: {status}")
        for variable, success in model_results.items():
            symbol = "✓" if success else "✗"
            print(f"  {symbol} {variable}")
    
    print(f"\n{'='*70}")
    print(f"OVERALL: {successful_tests}/{total_tests} tests passed")
    
    if successful_tests == total_tests:
        print("✓ ALL TESTS PASSED!")
        print("="*70)
        return 0
    else:
        print(f"✗ {total_tests - successful_tests} tests failed")
        print("="*70)
        return 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
