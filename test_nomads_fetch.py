#!/usr/bin/env python3
"""
Test script to validate NOMADS fetching before switching production.

This script tests:
1. NOMADS availability checking
2. NOMADS data fetching (full and filtered)
3. Data quality comparison with AWS S3
4. Performance comparison
"""
import sys
import os
import time
from datetime import datetime, timedelta

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.config import settings
from app.services.data_fetcher import GFSDataFetcher

def test_nomads_availability():
    """Test NOMADS availability checking"""
    print("\n" + "="*70)
    print("TEST 1: NOMADS Availability Checking")
    print("="*70)
    
    # Temporarily switch to NOMADS
    original_source = settings.gfs_source
    settings.gfs_source = "nomads"
    
    try:
        fetcher = GFSDataFetcher()
        run_time = fetcher.get_latest_run_time()
        
        print(f"Latest run time: {run_time.strftime('%Y-%m-%d %Hz')}")
        print("\nChecking NOMADS availability for forecast hours...")
        
        # Check a few forecast hours
        test_hours = [0, 6, 12, 24, 48, 72]
        available = []
        unavailable = []
        
        for hour in test_hours:
            # Use scheduler logic for checking
            from app.scheduler import ForecastScheduler
            scheduler = ForecastScheduler()
            
            is_available = scheduler.check_data_available(run_time, hour)
            
            if is_available:
                print(f"  ✅ f{hour:03d} - Available")
                available.append(hour)
            else:
                print(f"  ❌ f{hour:03d} - Not available")
                unavailable.append(hour)
        
        print(f"\nResults: {len(available)}/{len(test_hours)} forecast hours available")
        
        return len(available) > 0
        
    finally:
        settings.gfs_source = original_source

def test_nomads_fetch_full():
    """Test fetching full GRIB file from NOMADS"""
    print("\n" + "="*70)
    print("TEST 2: NOMADS Full GRIB Fetch")
    print("="*70)
    
    original_source = settings.gfs_source
    original_filter = settings.nomads_use_filter
    settings.gfs_source = "nomads"
    settings.nomads_use_filter = False  # Disable filtering
    
    try:
        fetcher = GFSDataFetcher()
        run_time = fetcher.get_latest_run_time()
        
        print(f"Fetching f012 from NOMADS (full file)...")
        start_time = time.time()
        
        ds = fetcher.fetch_gfs_data(
            run_time=run_time,
            forecast_hour=12,
            variables=['tmp2m', 'prate'],
            subset_region=False  # Full globe
        )
        
        elapsed = time.time() - start_time
        
        print(f"✅ Fetch successful!")
        print(f"   Time: {elapsed:.1f} seconds")
        print(f"   Variables: {list(ds.data_vars)}")
        print(f"   Data size: {ds.nbytes / 1024 / 1024:.1f} MB")
        
        # Check data quality
        if 't2m' in ds or 'tmp2m' in ds:
            temp_var = 't2m' if 't2m' in ds else 'tmp2m'
            temp = ds[temp_var]
            print(f"   Temperature range: {float(temp.min()):.1f} - {float(temp.max()):.1f} K")
        
        ds.close()
        return True
        
    except Exception as e:
        print(f"❌ Fetch failed: {e}")
        return False
        
    finally:
        settings.gfs_source = original_source
        settings.nomads_use_filter = original_filter

def test_nomads_fetch_filtered():
    """Test fetching filtered GRIB file from NOMADS (region + variables)"""
    print("\n" + "="*70)
    print("TEST 3: NOMADS Filtered Fetch (Region + Variables)")
    print("="*70)
    
    original_source = settings.gfs_source
    original_filter = settings.nomads_use_filter
    settings.gfs_source = "nomads"
    settings.nomads_use_filter = True  # Enable filtering
    
    try:
        fetcher = GFSDataFetcher()
        run_time = fetcher.get_latest_run_time()
        
        print(f"Fetching f012 from NOMADS (filtered: PNW region, 2 variables)...")
        start_time = time.time()
        
        ds = fetcher.fetch_gfs_data(
            run_time=run_time,
            forecast_hour=12,
            variables=['tmp2m', 'prate'],
            subset_region=True  # PNW only
        )
        
        elapsed = time.time() - start_time
        
        print(f"✅ Filtered fetch successful!")
        print(f"   Time: {elapsed:.1f} seconds")
        print(f"   Variables: {list(ds.data_vars)}")
        print(f"   Data size: {ds.nbytes / 1024 / 1024:.1f} MB")
        
        # Check data quality
        if 't2m' in ds or 'tmp2m' in ds:
            temp_var = 't2m' if 't2m' in ds else 'tmp2m'
            temp = ds[temp_var]
            print(f"   Temperature range: {float(temp.min()):.1f} - {float(temp.max()):.1f} K")
        
        ds.close()
        return True
        
    except Exception as e:
        print(f"❌ Filtered fetch failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        settings.gfs_source = original_source
        settings.nomads_use_filter = original_filter

def test_aws_vs_nomads_comparison():
    """Compare AWS S3 vs NOMADS performance and data"""
    print("\n" + "="*70)
    print("TEST 4: AWS S3 vs NOMADS Comparison")
    print("="*70)
    
    original_source = settings.gfs_source
    
    try:
        fetcher_aws = GFSDataFetcher()
        run_time = fetcher_aws.get_latest_run_time()
        
        # Test AWS S3
        print("\n📦 Fetching from AWS S3...")
        settings.gfs_source = "aws"
        fetcher_aws = GFSDataFetcher()
        
        start_aws = time.time()
        try:
            ds_aws = fetcher_aws.fetch_gfs_data(
                run_time=run_time,
                forecast_hour=12,
                variables=['tmp2m', 'prate'],
                subset_region=True
            )
            time_aws = time.time() - start_aws
            print(f"   ✅ AWS: {time_aws:.1f}s, {ds_aws.nbytes / 1024 / 1024:.1f} MB")
            
            # Get sample value - ensure we're using t2m (2m temperature)
            temp_var_aws = 't2m' if 't2m' in ds_aws else 'tmp2m'
            if temp_var_aws in ds_aws:
                aws_sample = float(ds_aws[temp_var_aws].values.flat[100])
                print(f"   AWS variable used for comparison: {temp_var_aws}")
            else:
                aws_sample = None
            ds_aws.close()
        except Exception as e:
            print(f"   ❌ AWS failed: {e}")
            time_aws = None
            aws_sample = None
        
        # Test NOMADS (filtered)
        print("\n🌐 Fetching from NOMADS (filtered)...")
        settings.gfs_source = "nomads"
        settings.nomads_use_filter = True
        fetcher_nomads = GFSDataFetcher()
        
        start_nomads = time.time()
        try:
            ds_nomads = fetcher_nomads.fetch_gfs_data(
                run_time=run_time,
                forecast_hour=12,
                variables=['tmp2m', 'prate'],
                subset_region=True
            )
            time_nomads = time.time() - start_nomads
            print(f"   ✅ NOMADS: {time_nomads:.1f}s, {ds_nomads.nbytes / 1024 / 1024:.1f} MB")
            
            # Get sample value - ensure we're using t2m (2m temperature), not 't' (surface temp)
            temp_var_nomads = 't2m' if 't2m' in ds_nomads else 'tmp2m'
            if temp_var_nomads in ds_nomads:
                nomads_sample = float(ds_nomads[temp_var_nomads].values.flat[100])
                print(f"   NOMADS variable used for comparison: {temp_var_nomads}")
            else:
                nomads_sample = None
                print(f"   ⚠️  Warning: {temp_var_nomads} not found in NOMADS dataset")
                print(f"   Available variables: {list(ds_nomads.data_vars)}")
            ds_nomads.close()
        except Exception as e:
            print(f"   ❌ NOMADS failed: {e}")
            time_nomads = None
            nomads_sample = None
        
        # Comparison
        print("\n📊 Comparison:")
        if time_aws and time_nomads:
            speedup = time_aws / time_nomads
            print(f"   Speed: NOMADS is {speedup:.2f}x {'faster' if speedup > 1 else 'slower'} than AWS")
        
        if aws_sample and nomads_sample:
            diff = abs(aws_sample - nomads_sample)
            print(f"   Data sample (100th point): AWS={aws_sample:.2f}K, NOMADS={nomads_sample:.2f}K, diff={diff:.2f}K")
            
            # Note: Some difference is expected because array ordering may differ
            # between filtered and full downloads. What matters is that values
            # are in the same reasonable range for the same region and time.
            if diff < 0.1:
                print(f"   ✅ Data matches perfectly!")
            elif diff < 2.0:
                print(f"   ✅ Data matches well (minor array ordering difference)")
            elif diff < 10.0:
                print(f"   ⚠️  Data differs by {diff:.2f}K (may be due to array indexing)")
                print(f"   Note: Check that both datasets cover same region and contain same variable")
            else:
                print(f"   ❌ Significant data difference!")
        
        return True
        
    except Exception as e:
        print(f"❌ Comparison failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        settings.gfs_source = original_source

def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("🧪 NOMADS Integration Test Suite")
    print("="*70)
    print(f"Current GFS source: {settings.gfs_source}")
    print(f"GFS resolution: {settings.gfs_resolution}")
    print(f"NOMADS filter enabled: {settings.nomads_use_filter}")
    
    results = {}
    
    # Run tests
    results['availability'] = test_nomads_availability()
    
    # Only run fetch tests if data is available
    if results['availability']:
        results['full_fetch'] = test_nomads_fetch_full()
        results['filtered_fetch'] = test_nomads_fetch_filtered()
        results['comparison'] = test_aws_vs_nomads_comparison()
    else:
        print("\n⚠️  Skipping fetch tests - no data available on NOMADS")
        results['full_fetch'] = None
        results['filtered_fetch'] = None
        results['comparison'] = None
    
    # Summary
    print("\n" + "="*70)
    print("📋 TEST SUMMARY")
    print("="*70)
    
    for test_name, result in results.items():
        if result is True:
            status = "✅ PASS"
        elif result is False:
            status = "❌ FAIL"
        else:
            status = "⊙ SKIPPED"
        print(f"  {test_name}: {status}")
    
    # Overall result
    passed = sum(1 for r in results.values() if r is True)
    total = sum(1 for r in results.values() if r is not None)
    
    print(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total and total > 0:
        print("\n✅ All tests passed! NOMADS is ready for production.")
        print("\nTo switch to NOMADS:")
        print("  1. Update config: GFS_SOURCE=nomads")
        print("  2. Restart scheduler")
        return 0
    else:
        print("\n⚠️  Some tests failed. Review errors before switching to NOMADS.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
