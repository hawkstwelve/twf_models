import os
import sys
from datetime import datetime, timedelta
import xarray as xr
import numpy as np
import logging

# Add the backend directory to sys.path to allow imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from app.services.data_fetcher import GFSDataFetcher
from app.services.map_generator import MapGenerator
from app.core.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_850mb_map():
    fetcher = GFSDataFetcher()
    generator = MapGenerator()
    
    # Use 12z run from today
    now = datetime.utcnow()
    run_time = datetime(now.year, now.month, now.day, 12)
    
    forecast_hours = [0, 24, 48, 72]
    variable = "temp_850_wind_mslp"
    
    print("=" * 60)
    print("Testing 850mb Temperature, Wind, and MSLP Map Generation")
    print("=" * 60)
    print(f"Run Time: {run_time.strftime('%Y-%m-%d %H:%00 UTC')}")
    print(f"Forecast Hours: {forecast_hours}")
    print(f"Map Type: {variable}")
    print("-" * 60)
    
    for hour in forecast_hours:
        print(f"\n🗺️  Generating 850mb map for +{hour}h...")
        try:
            # Fetch data
            ds = fetcher.fetch_gfs_data(
                run_time=run_time,
                forecast_hour=hour,
                variables=['tmp_850', 'ugrd_850', 'vgrd_850', 'prmsl']
            )
            
            # Generate map
            output_path = generator.generate_map(
                ds, 
                variable=variable,
                forecast_hour=hour,
                run_time=run_time
            )
            
            if os.path.exists(output_path):
                print(f"  ✅ Success! Map saved to: {output_path}")
            else:
                print(f"  ❌ Error: Map file not found at {output_path}")
                
        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_850mb_map()
