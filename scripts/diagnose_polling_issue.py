#!/usr/bin/env python3
"""
Diagnostic script to identify which model/forecast hours are stuck in pending state.

This script helps diagnose polling issues where certain forecast hours remain pending
indefinitely, causing the scheduler to loop continuously.

Usage:
    python3 scripts/diagnose_polling_issue.py
    
    # Or to test a specific model:
    python3 scripts/diagnose_polling_issue.py --model GFS
    python3 scripts/diagnose_polling_issue.py --model HRRR
    python3 scripts/diagnose_polling_issue.py --model AIGFS
"""

import sys
import os
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Add the current directory to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from backend.app.config import settings
from backend.app.services.model_factory import ModelFactory
from backend.app.models.model_registry import ModelRegistry
from backend.app.models.variable_requirements import VariableRegistry

def diagnose_model(model_id: str):
    """Diagnose polling issues for a specific model"""
    print(f"\n{'='*80}")
    print(f"🔍 DIAGNOSING: {model_id}")
    print(f"{'='*80}\n")
    
    # Get model config
    config = ModelRegistry.get(model_id)
    if not config:
        print(f"❌ Model {model_id} not found in registry")
        return False
    
    print(f"Model config:")
    print(f"  - Enabled: {config.enabled}")
    print(f"  - Fetcher type: {config.fetcher_type}")
    print(f"  - Max forecast hour: {config.max_forecast_hour}")
    print(f"  - Has analysis file: {config.has_analysis_file}")
    
    # Get latest run time
    try:
        fetcher = ModelFactory.create_fetcher(model_id)
        latest_run = fetcher.get_latest_run_time()
        print(f"\n✓ Latest run time: {latest_run.strftime('%Y-%m-%d %H:%M UTC')}")
        run_str = latest_run.strftime("%Y%m%d_%H")
    except Exception as e:
        print(f"\n❌ Failed to get latest run time: {e}")
        return False
    
    # Determine forecast hours
    if model_id == "HRRR":
        configured_hours = settings.hrrr_forecast_hours_list
        print(f"\n📋 Configured HRRR forecast hours: {configured_hours}")
        
        # Check if this is a major run (00z/06z/12z/18z)
        run_hour = latest_run.hour
        is_major_run = run_hour in {0, 6, 12, 18}
        max_hour = 48 if is_major_run else 18
        
        print(f"   Run hour: {run_hour:02d}z")
        print(f"   Major run cycle: {'YES' if is_major_run else 'NO'}")
        print(f"   Max forecast hour for this run: f{max_hour:03d}")
        
        # Filter forecast hours based on max
        forecast_hours = [h for h in configured_hours if h <= max_hour]
    else:
        configured_hours = [int(h) for h in settings.forecast_hours.split(',')]
        print(f"\n📋 Configured forecast hours: {configured_hours}")
        max_hour = config.max_forecast_hour
        forecast_hours = [h for h in configured_hours if h <= max_hour]
    
    print(f"\n🎯 Forecast hours to generate: {forecast_hours}")
    print(f"   Total: {len(forecast_hours)} hours")
    
    # Check which forecast hours are available
    print(f"\n🔍 Checking data availability for each forecast hour...")
    print(f"   (This may take a moment...)\n")
    
    available = []
    unavailable = []
    errors = []
    
    for fh in forecast_hours:
        try:
            # Use Herbie or NOMADS to check availability
            if config.fetcher_type == "herbie":
                from herbie import Herbie
                
                herbie_model_map = {
                    "GFS": "gfs",
                    "HRRR": "hrrr",
                    "RAP": "rap",
                }
                herbie_model = herbie_model_map.get(model_id)
                
                run_time_naive = latest_run.replace(tzinfo=None) if latest_run.tzinfo else latest_run
                H = Herbie(
                    date=run_time_naive,
                    model=herbie_model,
                    fxx=fh,
                    verbose=False
                )
                
                if H.grib is not None:
                    available.append(fh)
                    print(f"   ✅ f{fh:03d}: Available")
                else:
                    unavailable.append(fh)
                    print(f"   ❌ f{fh:03d}: NOT available")
                    
            elif config.fetcher_type == "nomads":
                # Check NOMADS directly
                import requests
                
                date_str = latest_run.strftime("%Y%m%d")
                run_hour = latest_run.strftime("%H")
                forecast_hour_str = f"{fh:03d}"
                
                if model_id == "AIGFS":
                    if fh == 0 and config.has_analysis_file:
                        filename = f"aigfs.t{run_hour}z.sfc.f000.grib2"
                    else:
                        filename = f"aigfs.t{run_hour}z.sfc.f{forecast_hour_str}.grib2"
                    url = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/aigfs/prod/aigfs.{date_str}/{run_hour}/model/atmos/grib2/{filename}"
                    
                    response = requests.head(url, timeout=10, allow_redirects=True)
                    if response.status_code == 200:
                        available.append(fh)
                        print(f"   ✅ f{fh:03d}: Available")
                    else:
                        unavailable.append(fh)
                        print(f"   ❌ f{fh:03d}: NOT available (HTTP {response.status_code})")
                else:
                    print(f"   ⚠️  f{fh:03d}: Don't know how to check (unknown NOMADS model)")
                    errors.append(fh)
                    
        except Exception as e:
            errors.append(fh)
            print(f"   ⚠️  f{fh:03d}: Error checking availability: {e}")
    
    # Check existing images on disk
    print(f"\n💾 Checking existing images on disk...")
    images_path = Path(settings.storage_path)
    existing_images = list(images_path.glob(f"{model_id.lower()}_{run_str}_*.png"))
    print(f"   Found {len(existing_images)} existing images for run {run_str}")
    
    # Analyze existing images by forecast hour
    existing_by_hour = {}
    for img in existing_images:
        # Extract forecast hour from filename: model_YYYYMMDD_HH_variable_FH.png
        parts = img.stem.split('_')
        if len(parts) >= 4:
            try:
                fh = int(parts[-1])
                existing_by_hour[fh] = existing_by_hour.get(fh, 0) + 1
            except ValueError:
                pass
    
    # Get expected variables for this model
    variables = VariableRegistry.filter_by_model_capabilities(
        ['temp', 'wind_speed', 'precip', 'mslp', 'temp_850mb', 'mslp_precip', 'radar', 'radar_reflectivity', 'snowfall'],
        config
    )
    print(f"   Expected variables: {variables}")
    
    # Summary
    print(f"\n{'='*80}")
    print(f"📊 DIAGNOSIS SUMMARY")
    print(f"{'='*80}\n")
    
    print(f"Forecast hours breakdown:")
    print(f"  ✅ Available:   {len(available)}/{len(forecast_hours)} hours")
    print(f"  ❌ Unavailable: {len(unavailable)}/{len(forecast_hours)} hours")
    print(f"  ⚠️  Errors:      {len(errors)}/{len(forecast_hours)} hours")
    
    if unavailable:
        print(f"\n⚠️  PROBLEM DETECTED: {len(unavailable)} forecast hours are NOT available:")
        print(f"   Hours: {sorted(unavailable)}")
        print(f"\n   This could cause continuous polling if these hours never become available!")
        print(f"\n   Possible causes:")
        print(f"   1. Model run hasn't finished producing all forecast hours yet (normal)")
        print(f"   2. These forecast hours don't exist for this model/run cycle")
        print(f"   3. Data source (NOMADS/AWS) is delayed or incomplete")
        print(f"   4. Configuration mismatch (requesting hours beyond model capabilities)")
        
        # Check if unavailable hours are beyond model capabilities
        beyond_max = [h for h in unavailable if h > max_hour]
        if beyond_max:
            print(f"\n   ❌ CONFIGURATION ERROR: {len(beyond_max)} hours exceed max for this run:")
            print(f"      Hours: {sorted(beyond_max)}")
            print(f"      Max forecast hour for this run: f{max_hour:03d}")
            print(f"\n   🔧 FIX: Update settings to not request these hours, or wait for them to become available")
    
    if errors:
        print(f"\n⚠️  {len(errors)} forecast hours had errors during availability check:")
        print(f"   Hours: {sorted(errors)}")
        print(f"   These may or may not be available - check manually")
    
    # Check completion status
    print(f"\n📸 Image generation status:")
    for fh in forecast_hours[:10]:  # Show first 10
        count = existing_by_hour.get(fh, 0)
        expected = len(variables)
        if fh == 0:
            # f000 typically skips certain variables
            skip_vars = ['wind_speed', 'precip', 'mslp_precip', 'radar', 'radar_reflectivity']
            expected = len([v for v in variables if v not in skip_vars])
        
        status = "✅ Complete" if count >= expected else f"⊙ Partial ({count}/{expected})"
        if count == 0:
            status = "❌ Missing"
        print(f"   f{fh:03d}: {status}")
    
    if len(forecast_hours) > 10:
        print(f"   ... (showing first 10 of {len(forecast_hours)} hours)")
    
    print(f"\n{'='*80}\n")
    
    # Return True if we found a problem
    return len(unavailable) > 0


def main():
    parser = argparse.ArgumentParser(description="Diagnose scheduler polling issues")
    parser.add_argument('--model', help='Specific model to diagnose (GFS, HRRR, AIGFS)', default=None)
    args = parser.parse_args()
    
    print(f"\n{'='*80}")
    print(f"🏥 SCHEDULER POLLING DIAGNOSTICS")
    print(f"{'='*80}\n")
    
    if args.model:
        # Diagnose specific model
        model_id = args.model.upper()
        diagnose_model(model_id)
    else:
        # Diagnose all enabled models
        enabled_models = ModelRegistry.get_enabled()
        print(f"Enabled models: {list(enabled_models.keys())}\n")
        
        problems_found = False
        for model_id in enabled_models.keys():
            has_problem = diagnose_model(model_id)
            problems_found = problems_found or has_problem
            print("\n")
        
        if problems_found:
            print(f"\n⚠️  PROBLEMS DETECTED - See diagnostics above")
            print(f"\nNext steps:")
            print(f"  1. Review the unavailable forecast hours for each model")
            print(f"  2. Check if configuration requests hours beyond model capabilities")
            print(f"  3. Verify data source (NOMADS/AWS) is accessible and up-to-date")
            print(f"  4. Consider adding max polling duration safeguard if not present")
            print(f"  5. Check scheduler logs for specific error messages")
        else:
            print(f"\n✅ No obvious problems detected - all configured forecast hours appear available")


if __name__ == "__main__":
    main()
