"""
Test progressive monitoring and generation.

This simulates the new real-time monitoring behavior.
"""

import sys
import os
from datetime import datetime, timedelta
import time

# Add backend to path
backend_path = os.path.join(os.path.dirname(__file__), 'backend')
sys.path.insert(0, backend_path)

from app.scheduler import ForecastScheduler


def test_data_availability_check():
    """Test the S3 data availability check"""
    
    print("\n" + "="*70)
    print("TEST 1: S3 Data Availability Check")
    print("="*70)
    
    scheduler = ForecastScheduler()
    
    # Check the most recent GFS run that should have data
    now = datetime.utcnow()
    
    # Use a run from 6+ hours ago (guaranteed to have data)
    run_hour = (now.hour // 6) * 6 - 6
    if run_hour < 0:
        run_hour = 18
        now = now - timedelta(days=1)
    
    run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    print(f"\nTesting with GFS run: {run_time.strftime('%Y-%m-%d %Hz')}")
    print(f"Hours since run: {(datetime.utcnow() - run_time).total_seconds() / 3600:.1f}h")
    print("\nChecking forecast hours:\n")
    
    for forecast_hour in [0, 24, 48, 72]:
        available = scheduler.check_data_available(run_time, forecast_hour)
        status = "✅ Available" if available else "❌ Not found"
        print(f"  f{forecast_hour:03d}: {status}")
    
    print("\n" + "-"*70)


def test_progressive_generation_dry_run():
    """
    Simulate progressive generation without actually generating maps.
    Shows what the monitoring loop would do.
    """
    
    print("\n" + "="*70)
    print("TEST 2: Progressive Generation Simulation")
    print("="*70)
    
    scheduler = ForecastScheduler()
    
    # Use a recent run that should have data
    now = datetime.utcnow()
    run_hour = (now.hour // 6) * 6 - 6
    if run_hour < 0:
        run_hour = 18
        now = now - timedelta(days=1)
    
    run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    print(f"\nSimulating monitoring for: {run_time.strftime('%Y-%m-%d %Hz')}")
    print(f"Forecast hours to monitor: {[0, 24, 48, 72]}")
    print("\nMonitoring checks (dry run - not generating):\n")
    
    generated_hours = set()
    max_checks = 5  # Limit checks for testing
    
    for check in range(1, max_checks + 1):
        print(f"Check #{check}:")
        
        for forecast_hour in [0, 24, 48, 72]:
            if forecast_hour in generated_hours:
                print(f"  f{forecast_hour:03d}: Already generated ✓")
                continue
            
            available = scheduler.check_data_available(run_time, forecast_hour)
            
            if available:
                print(f"  f{forecast_hour:03d}: ✅ Available - would generate now!")
                generated_hours.add(forecast_hour)
            else:
                print(f"  f{forecast_hour:03d}: ⏳ Not yet available")
        
        if len(generated_hours) == 4:
            print("\n🎊 All forecast hours would be complete!")
            break
        
        if check < max_checks:
            print(f"\nSleeping 60 seconds before next check...\n")
            time.sleep(1)  # Shortened for testing
    
    print(f"\nFinal status: Generated {len(generated_hours)}/4 forecast hours")


def test_actual_generation():
    """
    Actually run the progressive generation (full test).
    Only use this if you want to generate real maps.
    """
    
    print("\n" + "="*70)
    print("TEST 3: LIVE Progressive Generation")
    print("="*70)
    print("\n⚠️  WARNING: This will actually generate maps!")
    print("⚠️  It will monitor for 5 minutes (not the full 90)")
    
    response = input("\nContinue? (yes/no): ")
    if response.lower() != 'yes':
        print("Cancelled.")
        return
    
    scheduler = ForecastScheduler()
    
    # Use current run time
    now = datetime.utcnow()
    run_hour = (now.hour // 6) * 6
    run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    print(f"\n🚀 Starting progressive generation for {run_time.strftime('%Y-%m-%d %Hz')}")
    print("This will run for up to 5 minutes...\n")
    
    # Run for only 5 minutes with 30-second checks (for testing)
    scheduler._progressive_generation_loop(
        run_time, 
        duration_minutes=5, 
        check_interval_seconds=30
    )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test progressive monitoring')
    parser.add_argument('--live', action='store_true', help='Run actual generation (5 min test)')
    
    args = parser.parse_args()
    
    if args.live:
        test_actual_generation()
    else:
        # Run non-destructive tests
        test_data_availability_check()
        test_progressive_generation_dry_run()
        
        print("\n" + "="*70)
        print("✅ TESTS COMPLETE")
        print("="*70)
        print("\nTo test actual generation (5 minute run):")
        print("  python3 test_progressive_monitoring.py --live")
        print("\nTo deploy:")
        print("  git add backend/app/scheduler.py test_progressive_monitoring.py")
        print("  git commit -m 'Implement real-time progressive monitoring'")
        print("  git push origin main")
        print("="*70)
