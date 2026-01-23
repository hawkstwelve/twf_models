#!/usr/bin/env python3
"""Comprehensive test: All map types for all forecast hours"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(name)s - %(levelname)s - %(message)s'
)

sys.path.insert(0, str(Path(__file__).parent / "backend"))

def test_all_maps_all_hours():
    """Test all map types for all forecast hours"""
    print("=" * 70)
    print("COMPREHENSIVE TEST: All Map Types × All Forecast Hours")
    print("=" * 70)
    print()
    
    from app.services.map_generator import MapGenerator
    
    # Get latest run time
    now = datetime.utcnow()
    run_hour = ((now.hour // 6) * 6) - 6
    if run_hour < 0:
        run_hour = 18
        now = now - timedelta(days=1)
    
    run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    print(f"Using GFS run time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
    print()
    
    generator = MapGenerator()
    forecast_hours = [0, 24, 48, 72]
    variables = ['temp', 'precip', 'wind_speed', 'precip_type']
    
    results = {
        'success': [],
        'failed': []
    }
    
    total_tests = len(forecast_hours) * len(variables)
    
    print(f"Testing {len(variables)} variables × {len(forecast_hours)} forecast hours = {total_tests} maps")
    print("=" * 70)
    print()
    
    # Test each combination
    for var in variables:
        print(f"\n{'='*70}")
        print(f"Testing: {var.upper()}")
        print('='*70)
        
        for fh in forecast_hours:
            test_name = f"{var}_{fh:03d}h"
            print(f"\n  Forecast Hour {fh:03d}h: ", end='', flush=True)
            
            try:
                map_path = generator.generate_map(
                    variable=var,
                    model="GFS",
                    run_time=run_time,
                    forecast_hour=fh,
                    region="pnw"
                )
                size_kb = map_path.stat().st_size / 1024
                print(f"✅ {map_path.name} ({size_kb:.1f} KB)")
                results['success'].append(test_name)
            except Exception as e:
                error_msg = str(e)[:100]
                print(f"❌ {error_msg}")
                results['failed'].append(test_name)
    
    # Summary
    print()
    print()
    print("=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"✅ Successful: {len(results['success'])}/{total_tests}")
    print(f"❌ Failed: {len(results['failed'])}/{total_tests}")
    print(f"Success Rate: {len(results['success'])/total_tests*100:.1f}%")
    
    if results['success']:
        print()
        print("Successful tests:")
        for test in sorted(results['success']):
            print(f"  ✅ {test}")
    
    if results['failed']:
        print()
        print("Failed tests:")
        for test in sorted(results['failed']):
            print(f"  ❌ {test}")
    
    print()
    print(f"Maps saved to: {generator.storage_path}")
    print()
    
    # Production readiness assessment
    print("=" * 70)
    print("PRODUCTION READINESS ASSESSMENT")
    print("=" * 70)
    
    # Count by variable
    var_results = {}
    for var in variables:
        # Use exact match with underscore to avoid "precip" matching "precip_type"
        var_success = [t for t in results['success'] if t.startswith(var + '_')]
        var_failed = [t for t in results['failed'] if t.startswith(var + '_')]
        var_results[var] = {
            'success': len(var_success),
            'total': len(forecast_hours),
            'rate': len(var_success) / len(forecast_hours) * 100
        }
    
    for var, stats in var_results.items():
        status = "✅ READY" if stats['rate'] == 100 else "⚠️ PARTIAL" if stats['rate'] > 0 else "❌ NOT READY"
        print(f"{var:15s}: {stats['success']}/{stats['total']} ({stats['rate']:5.1f}%) {status}")
    
    print()
    
    overall_rate = len(results['success']) / total_tests * 100
    if overall_rate == 100:
        print("🎉 STATUS: PRODUCTION READY!")
        print("All map types working for all forecast hours.")
    elif overall_rate >= 75:
        print("⚠️  STATUS: MOSTLY READY")
        print("Most maps working. Fix remaining issues before full deployment.")
    else:
        print("❌ STATUS: NOT READY")
        print("Significant issues remain. Continue development.")
    
    print()
    
    # Return 0 if all tests passed, 1 otherwise
    return 0 if len(results['failed']) == 0 else 1

if __name__ == "__main__":
    sys.exit(test_all_maps_all_hours())
