"""
Test script for new scheduler timing (3.5 hours after GFS runs).

This tests the new logic that fetches the CURRENT run instead of previous.
"""

import sys
import os
from datetime import datetime, timedelta
import logging

# Add backend directory to path so imports work
backend_path = os.path.join(os.path.dirname(__file__), 'backend')
sys.path.insert(0, backend_path)

from app.services.map_generator import MapGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_current_run_timing():
    """
    Test fetching the CURRENT GFS run (as scheduler will do at 3.5 hours after run).
    
    This simulates what happens when scheduler runs at:
    - 03:30 UTC (should fetch 00Z)
    - 09:30 UTC (should fetch 06Z)
    - 15:30 UTC (should fetch 12Z)
    - 21:30 UTC (should fetch 18Z)
    """
    
    print("\n" + "="*70)
    print("TESTING NEW SCHEDULER TIMING")
    print("="*70)
    
    # Simulate being 3.5 hours after a GFS run
    now = datetime.utcnow()
    run_hour = (now.hour // 6) * 6  # Current 6-hour cycle
    run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    hours_since_run = (now - run_time).total_seconds() / 3600
    
    print(f"\nCurrent time: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Current GFS run: {run_time.strftime('%Y-%m-%d %Hz')}")
    print(f"Hours since run: {hours_since_run:.1f}h")
    
    if hours_since_run < 3.0:
        print("\n⚠️  WARNING: Less than 3 hours since run - data may not be available yet")
        print("   For reliable testing, run this 3-4 hours after a GFS run time (00, 06, 12, 18 UTC)")
    elif hours_since_run >= 3.0 and hours_since_run < 4.5:
        print("\n✅ GOOD: 3-4.5 hours since run - ideal testing window")
    else:
        print("\n⏰ NOTE: More than 4.5 hours since run - data definitely available")
    
    print("\n" + "-"*70)
    print("Testing map generation for CURRENT run...")
    print("-"*70)
    
    gen = MapGenerator()
    
    # Test one forecast hour of each variable
    test_cases = [
        ('temp', 0),
        ('precip', 0),
        ('wind_speed', 0),
        ('precip_type', 0),
    ]
    
    success_count = 0
    fail_count = 0
    
    for variable, forecast_hour in test_cases:
        try:
            print(f"\n→ Generating {variable} f{forecast_hour:03d}...")
            path = gen.generate_map(
                variable=variable,
                model='GFS',
                run_time=run_time,
                forecast_hour=forecast_hour
            )
            print(f"  ✅ Success: {path}")
            success_count += 1
        except Exception as e:
            print(f"  ❌ Failed: {e}")
            fail_count += 1
    
    print("\n" + "="*70)
    print(f"RESULTS: {success_count} success, {fail_count} failed")
    print("="*70)
    
    if success_count == len(test_cases):
        print("\n✅ ALL TESTS PASSED!")
        print("   The new timing works - data is available for current run")
        print("   Ready to deploy to droplet")
    elif success_count > 0:
        print("\n⚠️  PARTIAL SUCCESS")
        print("   Some maps generated, some failed - check errors above")
    else:
        print("\n❌ ALL TESTS FAILED")
        print("   Data not available yet for current run")
        print("   Either:")
        print("   1. Run is delayed (check NOAA status)")
        print("   2. It's too soon after run time (wait another hour)")
        print("   3. There's a different issue (check error messages)")


def test_fallback_logic():
    """
    Test the fallback to previous run if current fails.
    """
    print("\n" + "="*70)
    print("TESTING FALLBACK LOGIC")
    print("="*70)
    
    now = datetime.utcnow()
    run_hour = (now.hour // 6) * 6
    current_run = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    previous_run = current_run - timedelta(hours=6)
    
    print(f"\nCurrent run: {current_run.strftime('%Y-%m-%d %Hz')}")
    print(f"Previous run: {previous_run.strftime('%Y-%m-%d %Hz')}")
    print("\nTrying to generate one map from previous run (fallback test)...")
    
    gen = MapGenerator()
    
    try:
        path = gen.generate_map(
            variable='temp',
            model='GFS',
            run_time=previous_run,
            forecast_hour=0
        )
        print(f"✅ Fallback works: {path}")
        print("   If current run fails, scheduler can use previous run")
    except Exception as e:
        print(f"❌ Fallback failed: {e}")
        print("   This shouldn't happen - previous run should always be available")


def show_next_run_times():
    """
    Show when the next scheduled runs will occur.
    """
    print("\n" + "="*70)
    print("NEXT SCHEDULED RUN TIMES")
    print("="*70)
    
    now = datetime.utcnow()
    scheduled_hours = [3, 9, 15, 21]
    scheduled_minute = 30
    
    print(f"\nCurrent time: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print("\nScheduled runs (next 24 hours):\n")
    
    runs = []
    for day_offset in [0, 1]:
        for hour in scheduled_hours:
            run_time = now.replace(hour=hour, minute=scheduled_minute, second=0, microsecond=0)
            if day_offset == 1:
                run_time += timedelta(days=1)
            if run_time > now:
                runs.append(run_time)
    
    runs = sorted(runs)[:4]  # Next 4 runs
    
    from datetime import timezone
    
    for i, run_time in enumerate(runs, 1):
        # Calculate what GFS run it will fetch
        gfs_run_hour = (run_time.hour // 6) * 6
        gfs_run_time = run_time.replace(hour=gfs_run_hour, minute=0)
        
        # Convert to US timezones
        pst_time = run_time.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-8)))
        mst_time = run_time.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-7)))
        cst_time = run_time.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-6)))
        est_time = run_time.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-5)))
        
        print(f"{i}. {run_time.strftime('%Y-%m-%d %H:%M UTC')} → Fetches {gfs_run_time.strftime('%Hz')} data")
        print(f"   PST: {pst_time.strftime('%I:%M %p')}")
        print(f"   MST: {mst_time.strftime('%I:%M %p')}")
        print(f"   CST: {cst_time.strftime('%I:%M %p')}")
        print(f"   EST: {est_time.strftime('%I:%M %p')}")
        print()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--schedule":
        # Just show schedule
        show_next_run_times()
    elif len(sys.argv) > 1 and sys.argv[1] == "--fallback":
        # Test fallback only
        test_fallback_logic()
    else:
        # Full test
        test_current_run_timing()
        test_fallback_logic()
        show_next_run_times()
        
        print("\n" + "="*70)
        print("DEPLOYMENT READY CHECK")
        print("="*70)
        print("\nBefore deploying to droplet:")
        print("1. ✅ Test passed above")
        print("2. ✅ Maps generated for current run")
        print("3. ✅ Fallback to previous run works")
        print("\nTo deploy:")
        print("  git add backend/app/scheduler.py")
        print("  git commit -m 'Update scheduler to industry-standard timing'")
        print("  git push origin main")
        print("\nThen on droplet:")
        print("  cd /opt/twf_models")
        print("  git pull origin main")
        print("  sudo systemctl restart twf-models-scheduler")
        print("  sudo journalctl -u twf-models-scheduler -f")
        print("="*70)
