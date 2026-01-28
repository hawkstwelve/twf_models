#!/usr/bin/env python3
"""
Debug script to test map generation with timeout
Helps diagnose if map generation is hanging or just slow
"""
import os
import sys
import logging
import signal
from datetime import datetime, timedelta
from pathlib import Path

# Add the backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from app.services.map_generator import MapGenerator
from app.services.model_factory import ModelFactory
from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Map generation timed out!")

def test_single_map(model_id='GFS', forecast_hour=6, variable='temp', timeout_seconds=300):
    """
    Test generating a single map with timeout protection.
    
    Args:
        model_id: Model to test (GFS or AIGFS)
        forecast_hour: Forecast hour to generate
        variable: Variable to generate
        timeout_seconds: Timeout in seconds (default 5 minutes)
    """
    print("="*70)
    print(f"🧪 TESTING SINGLE MAP GENERATION")
    print("="*70)
    print(f"Model: {model_id}")
    print(f"Variable: {variable}")
    print(f"Forecast Hour: f{forecast_hour:03d}")
    print(f"Timeout: {timeout_seconds} seconds")
    print("="*70)
    print()
    
    try:
        # Create fetcher and generator
        data_fetcher = ModelFactory.create_fetcher(model_id)
        map_generator = MapGenerator()
        
        # Get run time
        run_time = data_fetcher.get_latest_run_time()
        print(f"📅 Run Time: {run_time.strftime('%Y-%m-%d %HZ')}")
        print()
        
        # Set up timeout (Unix only)
        if hasattr(signal, 'SIGALRM'):
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout_seconds)
            print(f"⏰ Timeout protection enabled ({timeout_seconds}s)")
        else:
            print(f"⚠️  Timeout not available on this platform")
        print()
        
        # Build dataset
        print(f"📥 Building dataset...")
        ds = data_fetcher.build_dataset_for_maps(
            run_time=run_time,
            forecast_hour=forecast_hour,
            variables=[variable],
            subset_region=True
        )
        print(f"✓ Dataset ready with {len(ds.data_vars)} fields")
        print()
        
        # Generate map
        print(f"🗺️  Generating map...")
        filepath = map_generator.generate_map(
            ds=ds,
            variable=variable,
            model=model_id,
            run_time=run_time,
            forecast_hour=forecast_hour
        )
        
        # Cancel timeout
        if hasattr(signal, 'SIGALRM'):
            signal.alarm(0)
        
        print()
        print("="*70)
        print("✅ SUCCESS!")
        print("="*70)
        print(f"Map saved to: {filepath}")
        print(f"File size: {filepath.stat().st_size / 1024:.1f} KB")
        print()
        
        # Cleanup
        ds.close()
        
    except TimeoutError as e:
        print()
        print("="*70)
        print("⏰ TIMEOUT!")
        print("="*70)
        print(f"Map generation exceeded {timeout_seconds} seconds")
        print()
        print("This suggests the process is hanging, not just slow.")
        print("Check for:")
        print("  - Matplotlib/cartopy configuration issues")
        print("  - Memory issues")
        print("  - Missing dependencies")
        print()
        
    except KeyboardInterrupt:
        print()
        print("⚠️  Interrupted by user")
        
    except Exception as e:
        print()
        print("="*70)
        print("❌ ERROR!")
        print("="*70)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test single map generation with timeout')
    parser.add_argument('--model', default='GFS', choices=['GFS', 'AIGFS'], 
                       help='Model to test (default: GFS)')
    parser.add_argument('--variable', default='temp',
                       choices=['temp', 'precip', 'wind_speed', 'mslp_precip', 
                               'temp_850_wind_mslp', 'radar'],
                       help='Variable to test (default: temp)')
    parser.add_argument('--hour', type=int, default=6,
                       help='Forecast hour (default: 6)')
    parser.add_argument('--timeout', type=int, default=300,
                       help='Timeout in seconds (default: 300 = 5 minutes)')
    
    args = parser.parse_args()
    
    test_single_map(
        model_id=args.model,
        forecast_hour=args.hour,
        variable=args.variable,
        timeout_seconds=args.timeout
    )
