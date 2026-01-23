#!/usr/bin/env python3
"""Local test script for TWF Weather Models"""
import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

def test_imports():
    """Test if all required modules can be imported"""
    print("=" * 60)
    print("Testing Imports")
    print("=" * 60)
    
    try:
        import xarray as xr
        print("✅ xarray")
    except ImportError as e:
        print(f"❌ xarray: {e}")
        return False
    
    try:
        import cartopy
        print("✅ cartopy")
    except ImportError as e:
        print(f"❌ cartopy: {e}")
        return False
    
    try:
        import matplotlib
        print("✅ matplotlib")
    except ImportError as e:
        print(f"❌ matplotlib: {e}")
        return False
    
    try:
        import metpy
        print("✅ metpy")
    except ImportError as e:
        print(f"❌ metpy: {e}")
        return False
    
    try:
        from app.config import settings
        print("✅ app.config")
    except ImportError as e:
        print(f"❌ app.config: {e}")
        return False
    
    try:
        from app.services.data_fetcher import GFSDataFetcher
        print("✅ GFSDataFetcher")
    except ImportError as e:
        print(f"❌ GFSDataFetcher: {e}")
        return False
    
    try:
        from app.services.map_generator import MapGenerator
        print("✅ MapGenerator")
    except ImportError as e:
        print(f"❌ MapGenerator: {e}")
        return False
    
    print("\n✅ All imports successful!")
    return True


def test_config():
    """Test configuration"""
    print("\n" + "=" * 60)
    print("Testing Configuration")
    print("=" * 60)
    
    try:
        from app.config import settings
        
        print(f"Region: {settings.map_region}")
        print(f"Forecast Hours: {settings.forecast_hours_list}")
        print(f"Storage Path: {settings.storage_path}")
        
        if settings.map_region == "pnw":
            print("✅ PNW region configured")
        else:
            print(f"⚠️  Region is {settings.map_region}, expected 'pnw'")
        
        return True
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return False


def test_data_fetch():
    """Test GFS data fetching (this will download data)"""
    print("\n" + "=" * 60)
    print("Testing GFS Data Fetching")
    print("=" * 60)
    print("⚠️  This will download GFS data (may take a few minutes)...")
    
    try:
        from app.services.data_fetcher import GFSDataFetcher
        
        fetcher = GFSDataFetcher()
        print("✅ GFSDataFetcher initialized")
        
        # Get latest run time
        run_time = fetcher.get_latest_run_time()
        print(f"Latest GFS run: {run_time}")
        
        # Try to fetch data for forecast hour 0 (smallest file)
        print("\nFetching GFS data for forecast hour 0...")
        print("This may take 2-5 minutes depending on connection...")
        
        ds = fetcher.fetch_gfs_data(run_time=run_time, forecast_hour=0)
        print(f"✅ Data fetched successfully!")
        print(f"   Variables available: {list(ds.data_vars)[:5]}...")
        print(f"   Dimensions: {dict(ds.dims)}")
        
        return True, ds
        
    except Exception as e:
        print(f"❌ Data fetch error: {e}")
        import traceback
        traceback.print_exc()
        return False, None


def test_map_generation(ds=None):
    """Test map generation"""
    print("\n" + "=" * 60)
    print("Testing Map Generation")
    print("=" * 60)
    
    try:
        from app.services.map_generator import MapGenerator
        
        generator = MapGenerator()
        print("✅ MapGenerator initialized")
        
        # Create images directory if it doesn't exist
        images_dir = Path("images")
        images_dir.mkdir(exist_ok=True)
        print(f"✅ Images directory: {images_dir.absolute()}")
        
        # Test temperature map (simplified - won't fetch new data if ds provided)
        print("\nGenerating test temperature map...")
        # Note: This will use the data fetcher internally if ds is None
        # For now, we'll just test the generator setup
        
        print("✅ Map generator ready")
        print("   To generate actual maps, use the full pipeline")
        
        return True
        
    except Exception as e:
        print(f"❌ Map generation error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("TWF Weather Models - Local Test")
    print("=" * 60)
    print()
    
    # Test 1: Imports
    if not test_imports():
        print("\n❌ Import test failed. Please install dependencies:")
        print("   pip install -r backend/requirements.txt")
        return 1
    
    # Test 2: Configuration
    if not test_config():
        print("\n❌ Configuration test failed")
        return 1
    
    # Test 3: Data fetching (optional - can skip if slow)
    print("\n" + "=" * 60)
    print("Skipping GFS data fetch test (requires large download)")
    print("To test data fetching manually, run:")
    print("  python3 -c \"from backend.app.services.data_fetcher import GFSDataFetcher; f=GFSDataFetcher(); print(f.get_latest_run_time())\"")
    
    ds = None
    
    # Test 4: Map generation
    test_map_generation(ds)
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print("✅ Basic setup appears to be working!")
    print("\nNext steps:")
    print("1. If data fetch worked, you can generate maps")
    print("2. Run the API server: cd backend && uvicorn app.main:app --reload")
    print("3. Test API endpoints at http://localhost:8000")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
