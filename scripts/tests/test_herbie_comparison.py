#!/usr/bin/env python3
"""
Compare NOMADS fetcher vs Herbie fetcher for GFS data.

This test helps evaluate:
1. Download speed (full GRIB vs byte-range subsetting)
2. Data quality (same variables?)
3. Cache behavior (integration with existing cache)
4. Memory usage
5. Reliability (multi-source fallback)

Usage:
    python scripts/tests/test_herbie_comparison.py
"""

import sys
import os
import time
import logging
from datetime import datetime
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

# Override storage path for testing (avoid permission issues with /opt/twf_models)
os.environ['STORAGE_PATH'] = str(Path(__file__).parent.parent.parent / "test_cache")

from app.services.nomads_data_fetcher import NOMADSDataFetcher
from app.models.model_registry import ModelRegistry

# Lazy import for HerbieDataFetcher (may not be available yet)
try:
    from app.services.herbie_data_fetcher import HerbieDataFetcher
    HERBIE_AVAILABLE = True
except ImportError:
    HERBIE_AVAILABLE = False
    logger.warning("HerbieDataFetcher not available - will skip Herbie tests")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_fetch_comparison():
    """Compare NOMADS vs Herbie for same data request."""
    
    print("\n" + "="*80)
    print("HERBIE vs NOMADS COMPARISON TEST")
    print("="*80 + "\n")
    
    # Test parameters
    model_id = "GFS"
    forecast_hour = 24
    test_variables = {'tmp2m', 'prmsl', 'ugrd10m', 'vgrd10m', 'tp'}
    
    # Get latest run time
    nomads_fetcher = NOMADSDataFetcher(model_id)
    run_time = nomads_fetcher.get_latest_run_time()
    
    print(f"📅 Model: {model_id}")
    print(f"📅 Run Time: {run_time}")
    print(f"📅 Forecast Hour: f{forecast_hour:03d}")
    print(f"📊 Variables: {test_variables}\n")
    
    # Clear any existing cache for fair comparison
    print("🗑️  Clearing cache for fair comparison...")
    date_str = run_time.strftime("%Y%m%d")
    run_hour_str = run_time.strftime("%H")
    cache_key = f"{model_id.lower()}_{date_str}_{run_hour_str}_f{forecast_hour:03d}"
    
    nomads_cache_path = nomads_fetcher._cache_dir / f"{cache_key}_sfc.grib2"
    if nomads_cache_path.exists():
        nomads_cache_path.unlink()
        print(f"  Removed: {nomads_cache_path}")
    
    # Test 1: NOMADS Fetcher
    print("\n" + "-"*80)
    print("TEST 1: NOMADS Data Fetcher (Your Current System)")
    print("-"*80 + "\n")
    
    try:
        start = time.time()
        ds_nomads = nomads_fetcher.fetch_raw_data(
            run_time=run_time,
            forecast_hour=forecast_hour,
            raw_fields=test_variables,
            subset_region=True
        )
        nomads_time = time.time() - start
        
        print(f"✓ NOMADS fetch successful")
        print(f"  Duration: {nomads_time:.2f} seconds")
        print(f"  Variables: {list(ds_nomads.data_vars)}")
        print(f"  Shape: {ds_nomads.dims}")
        print(f"  Memory: ~{ds_nomads.nbytes / (1024**2):.1f} MB")
        
        # Check file size
        if nomads_cache_path.exists():
            size_mb = nomads_cache_path.stat().st_size / (1024**2)
            print(f"  GRIB file size: {size_mb:.1f} MB")
        
    except Exception as e:
        print(f"✗ NOMADS fetch failed: {e}")
        ds_nomads = None
        nomads_time = None
    
    # Test 2: Herbie Fetcher
    print("\n" + "-"*80)
    print("TEST 2: Herbie Data Fetcher (Proposed Alternative)")
    print("-"*80 + "\n")
    
    if not HERBIE_AVAILABLE:
        print("⚠️  HerbieDataFetcher not available")
        print("   This is expected if you haven't installed herbie-data yet")
        print("\nTo install Herbie, run:")
        print("   ./scripts/install_herbie.sh")
        print("   OR")
        print("   pip install herbie-data 'numpy>=1.21.6,<2.0'")
        print("\nSkipping Herbie test.")
        ds_herbie = None
        herbie_time = None
    else:
        try:
            herbie_fetcher = HerbieDataFetcher(model_id)
            
            start = time.time()
            ds_herbie = herbie_fetcher.fetch_raw_data(
                run_time=run_time,
                forecast_hour=forecast_hour,
                raw_fields=test_variables,
                subset_region=True
            )
            herbie_time = time.time() - start
            
            print(f"✓ Herbie fetch successful")
            print(f"  Duration: {herbie_time:.2f} seconds")
            print(f"  Variables: {list(ds_herbie.data_vars)}")
            print(f"  Shape: {ds_herbie.dims}")
            print(f"  Memory: ~{ds_herbie.nbytes / (1024**2):.1f} MB")
            
            # Check Herbie's cache
            herbie_cache_dir = herbie_fetcher.herbie_save_dir
            herbie_files = list(herbie_cache_dir.glob("*.grib2"))
            if herbie_files:
                total_size = sum(f.stat().st_size for f in herbie_files)
                print(f"  Herbie cache: {len(herbie_files)} files, {total_size/(1024**2):.1f} MB total")
            
        except Exception as e:
            print(f"✗ Herbie fetch failed: {e}")
            import traceback
            traceback.print_exc()
            ds_herbie = None
            herbie_time = None
    
    # Comparison
    print("\n" + "="*80)
    print("COMPARISON SUMMARY")
    print("="*80 + "\n")
    
    if nomads_time and herbie_time:
        speedup = nomads_time / herbie_time
        print(f"⏱️  Speed:")
        print(f"   NOMADS:  {nomads_time:.2f}s")
        print(f"   Herbie:  {herbie_time:.2f}s")
        print(f"   Speedup: {speedup:.2f}x {'(Herbie faster)' if speedup > 1 else '(NOMADS faster)'}")
    
    if ds_nomads and ds_herbie:
        print(f"\n📊 Data Quality:")
        nomads_vars = set(ds_nomads.data_vars)
        herbie_vars = set(ds_herbie.data_vars)
        
        if nomads_vars == herbie_vars:
            print(f"   ✓ Same variables: {nomads_vars}")
        else:
            print(f"   ⚠️  Different variables!")
            print(f"   NOMADS only: {nomads_vars - herbie_vars}")
            print(f"   Herbie only: {herbie_vars - nomads_vars}")
        
        # Compare a sample variable
        if 'tmp2m' in ds_nomads and 'tmp2m' in ds_herbie:
            diff = (ds_nomads['tmp2m'] - ds_herbie['tmp2m']).values
            max_diff = abs(diff).max()
            print(f"   Temperature difference (max): {max_diff:.6f} K")
            print(f"   {'✓ Data matches!' if max_diff < 0.001 else '⚠️  Data differs!'}")
    
    print("\n" + "="*80)
    print("RECOMMENDATION:")
    print("="*80)
    
    if herbie_time and nomads_time:
        if herbie_time < nomads_time * 0.7:
            print("✅ Herbie is significantly faster (>30% improvement)")
            print("   Consider using Herbie for new models (HRRR, RAP)")
        elif herbie_time < nomads_time:
            print("✅ Herbie is slightly faster")
            print("   Worth using for new models, maybe migrate existing")
        else:
            print("⚠️  Herbie is slower than NOMADS")
            print("   Stick with NOMADS for GFS/AIGFS, use Herbie only for unavailable models")
    
    print("\n💡 Next Steps:")
    print("   1. Test with AIGFS (larger files, ~2-3GB)")
    print("   2. Test HerbieWait for progressive monitoring")
    print("   3. Test multi-source fallback (disable NOMADS, see if AWS works)")
    print("   4. Measure memory usage under parallel generation")
    print()


def test_herbie_wait():
    """Test Herbie's progressive data availability monitoring."""
    
    print("\n" + "="*80)
    print("HERBIE WAIT TEST (Progressive Monitoring)")
    print("="*80 + "\n")
    
    try:
        from herbie import Herbie, HerbieWait
    except ImportError:
        print("⚠️  Herbie not installed. Skipping HerbieWait test.")
        return
    
    model_id = "GFS"
    
    # Test with a future forecast hour that might not be available yet
    herbie_fetcher = HerbieDataFetcher(model_id)
    run_time = herbie_fetcher.get_latest_run_time()
    
    # Test with f120 (may or may not be available)
    forecast_hour = 120
    
    print(f"📅 Testing HerbieWait for {model_id} f{forecast_hour:03d}")
    print(f"📅 Run Time: {run_time}")
    print(f"⏳ Will wait up to 2 minutes with 10-second checks\n")
    
    start = time.time()
    ds = herbie_fetcher.fetch_with_wait(
        run_time=run_time,
        forecast_hour=forecast_hour,
        raw_fields={'tmp2m'},
        subset_region=True,
        max_wait_minutes=2,
        check_interval_seconds=10
    )
    elapsed = time.time() - start
    
    if ds:
        print(f"\n✓ Data became available after {elapsed:.1f} seconds")
        print(f"  Variables: {list(ds.data_vars)}")
    else:
        print(f"\n⏰ Data not available after {elapsed:.1f} seconds")
        print("  (This is expected if testing with distant forecast hours)")
    
    print("\n💡 HerbieWait could replace your check_forecast_hour_available() logic")
    print("   in scheduler.py lines 300-380")


if __name__ == "__main__":
    # Run comparison test
    test_fetch_comparison()
    
    # Optionally test HerbieWait
    print("\n" + "="*80)
    response = input("Test HerbieWait for progressive monitoring? (y/n): ")
    if response.lower() == 'y':
        test_herbie_wait()
    
    print("\n✅ Tests complete!")
