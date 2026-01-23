#!/usr/bin/env python3
"""Test script to verify setup and dependencies"""
import sys
import importlib

def test_import(module_name, package_name=None):
    """Test if a module can be imported"""
    try:
        importlib.import_module(module_name)
        print(f"✅ {package_name or module_name}")
        return True
    except ImportError as e:
        print(f"❌ {package_name or module_name}: {e}")
        return False

def main():
    """Run all tests"""
    print("Testing TWF Weather Models Setup\n")
    print("=" * 50)
    
    # Core dependencies
    print("\n📦 Core Dependencies:")
    core_deps = [
        ("fastapi", "FastAPI"),
        ("uvicorn", "Uvicorn"),
        ("pydantic", "Pydantic"),
        ("xarray", "XArray"),
        ("numpy", "NumPy"),
    ]
    core_results = [test_import(mod, name) for mod, name in core_deps]
    
    # Weather data dependencies
    print("\n🌦️  Weather Data Dependencies:")
    weather_deps = [
        ("netcdf4", "NetCDF4"),
        ("cfgrib", "cfgrib"),
        ("metpy", "MetPy"),
    ]
    weather_results = [test_import(mod, name) for mod, name in weather_deps]
    
    # Map generation dependencies
    print("\n🗺️  Map Generation Dependencies:")
    map_deps = [
        ("cartopy", "Cartopy"),
        ("matplotlib", "Matplotlib"),
        ("PIL", "Pillow"),
    ]
    map_results = [test_import(mod, name) for mod, name in map_deps]
    
    # Data fetching dependencies
    print("\n📥 Data Fetching Dependencies:")
    fetch_deps = [
        ("requests", "Requests"),
        ("s3fs", "s3fs"),
        ("boto3", "Boto3"),
    ]
    fetch_results = [test_import(mod, name) for mod, name in fetch_deps]
    
    # Scheduling dependencies
    print("\n⏰ Scheduling Dependencies:")
    sched_deps = [
        ("apscheduler", "APScheduler"),
    ]
    sched_results = [test_import(mod, name) for mod, name in sched_deps]
    
    # System dependencies check (basic)
    print("\n🖥️  System Dependencies:")
    try:
        import cartopy
        # Try to create a basic projection
        import cartopy.crs as ccrs
        proj = ccrs.PlateCarree()
        print("✅ Cartopy projections working")
    except Exception as e:
        print(f"⚠️  Cartopy may have issues: {e}")
        print("   Make sure system libraries are installed:")
        print("   sudo apt-get install libproj-dev proj-data proj-bin")
        print("   sudo apt-get install libgeos-dev libgdal-dev")
    
    # Summary
    print("\n" + "=" * 50)
    all_results = core_results + weather_results + map_results + fetch_results + sched_results
    passed = sum(all_results)
    total = len(all_results)
    
    print(f"\n📊 Summary: {passed}/{total} dependencies available")
    
    if passed == total:
        print("✅ All dependencies installed correctly!")
        return 0
    else:
        print("⚠️  Some dependencies are missing.")
        print("   Run: pip install -r requirements.txt")
        return 1

if __name__ == "__main__":
    sys.exit(main())
