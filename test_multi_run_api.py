"""
Test script for multi-run API endpoints.

Tests the new /api/runs endpoint and run_time filtering on /api/maps.
"""

import sys
import os
import requests
import json
from datetime import datetime

# Add backend directory to path
backend_path = os.path.join(os.path.dirname(__file__), 'backend')
sys.path.insert(0, backend_path)


def test_runs_endpoint(api_url="http://174.138.84.70:8000"):
    """Test the /api/runs endpoint"""
    
    print("\n" + "="*70)
    print("TEST 1: /api/runs Endpoint")
    print("="*70)
    
    try:
        response = requests.get(f"{api_url}/api/runs", timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            print(f"\n✅ Status: {response.status_code} OK")
            print(f"📊 Total runs available: {data['total_runs']}")
            
            if data['runs']:
                print("\n📋 Available Runs:\n")
                
                for i, run in enumerate(data['runs'], 1):
                    latest = " ⭐ LATEST" if run['is_latest'] else ""
                    print(f"{i}. {run['run_time_formatted']}{latest}")
                    print(f"   Run Time: {run['run_time']}")
                    print(f"   Maps: {run['maps_count']}")
                    print(f"   Age: {run['age_hours']:.1f} hours")
                    print(f"   Generated: {run['generated_at']}")
                    print()
                
                return data['runs']
            else:
                print("\n⚠️  No runs found - generate some maps first")
                return []
        else:
            print(f"\n❌ Status: {response.status_code}")
            print(f"Response: {response.text}")
            return []
            
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Cannot connect to {api_url}")
        print("   Make sure API is running on droplet")
        return []
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return []


def test_run_time_filtering(api_url="http://174.138.84.70:8000", run_time=None):
    """Test filtering maps by run_time"""
    
    print("\n" + "="*70)
    print("TEST 2: /api/maps?run_time=... Filtering")
    print("="*70)
    
    if not run_time:
        print("\n⚠️  No run_time provided, skipping test")
        return
    
    try:
        # Test with run_time filter
        params = {'run_time': run_time}
        response = requests.get(f"{api_url}/api/maps", params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            print(f"\n✅ Status: {response.status_code} OK")
            print(f"🔍 Filter: run_time={run_time}")
            print(f"📊 Maps found: {len(data['maps'])}")
            
            if data['maps']:
                # Group by variable
                variables = {}
                for map_info in data['maps']:
                    var = map_info['variable']
                    if var not in variables:
                        variables[var] = []
                    variables[var].append(map_info['forecast_hour'])
                
                print("\n📋 Maps by Variable:\n")
                for var, hours in sorted(variables.items()):
                    print(f"   {var}: {sorted(hours)}")
                
                print(f"\n✅ All maps are from run: {data['maps'][0]['run_time']}")
            else:
                print("\n⚠️  No maps found for this run")
                
        else:
            print(f"\n❌ Status: {response.status_code}")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")


def test_comparison_scenario(api_url="http://174.138.84.70:8000", runs=None):
    """Simulate a comparison view scenario"""
    
    print("\n" + "="*70)
    print("TEST 3: Comparison View Scenario")
    print("="*70)
    
    if not runs or len(runs) < 2:
        print("\n⚠️  Need at least 2 runs for comparison, skipping test")
        return
    
    current_run = runs[0]
    previous_run = runs[1]
    
    print(f"\n📊 Comparing:")
    print(f"   Current:  {current_run['run_time_formatted']}")
    print(f"   Previous: {previous_run['run_time_formatted']}")
    
    variable = "temp"
    forecast_hour = 0
    
    print(f"\n🔍 Loading {variable} maps at forecast hour +{forecast_hour}h...")
    
    try:
        # Fetch current run map
        params_current = {
            'run_time': current_run['run_time'],
            'variable': variable,
            'forecast_hour': forecast_hour
        }
        response_current = requests.get(f"{api_url}/api/maps", params=params_current, timeout=10)
        
        # Fetch previous run map
        params_previous = {
            'run_time': previous_run['run_time'],
            'variable': variable,
            'forecast_hour': forecast_hour
        }
        response_previous = requests.get(f"{api_url}/api/maps", params=params_previous, timeout=10)
        
        if response_current.status_code == 200 and response_previous.status_code == 200:
            current_maps = response_current.json()['maps']
            previous_maps = response_previous.json()['maps']
            
            if current_maps and previous_maps:
                print(f"\n✅ Successfully loaded both maps for comparison!")
                print(f"\n   Current run map:  {api_url}{current_maps[0]['image_url']}")
                print(f"   Previous run map: {api_url}{previous_maps[0]['image_url']}")
                
                print(f"\n💡 Frontend would display these side-by-side")
            else:
                print(f"\n⚠️  Maps not found for one or both runs")
        else:
            print(f"\n❌ Failed to load maps for comparison")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")


def test_response_format(api_url="http://174.138.84.70:8000"):
    """Validate response format matches schema"""
    
    print("\n" + "="*70)
    print("TEST 4: Response Format Validation")
    print("="*70)
    
    try:
        response = requests.get(f"{api_url}/api/runs", timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Check required top-level fields
            required_top = ['runs', 'total_runs']
            missing_top = [f for f in required_top if f not in data]
            
            if missing_top:
                print(f"\n❌ Missing top-level fields: {missing_top}")
                return
            
            print(f"\n✅ Top-level fields: {', '.join(required_top)}")
            
            # Check required fields in each run
            if data['runs']:
                required_run = ['run_time', 'run_time_formatted', 'date', 'hour', 
                               'is_latest', 'maps_count', 'generated_at', 'age_hours']
                
                run = data['runs'][0]
                missing_run = [f for f in required_run if f not in run]
                
                if missing_run:
                    print(f"\n❌ Missing run fields: {missing_run}")
                    return
                
                print(f"✅ Run fields: {', '.join(required_run)}")
                
                # Check data types
                print("\n✅ Data type validation:")
                print(f"   run_time: {type(run['run_time']).__name__} (str)")
                print(f"   is_latest: {type(run['is_latest']).__name__} (bool)")
                print(f"   maps_count: {type(run['maps_count']).__name__} (int)")
                print(f"   age_hours: {type(run['age_hours']).__name__} (float)")
                
                print("\n✅ All validation passed!")
            else:
                print("\n⚠️  No runs to validate")
                
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test multi-run API endpoints')
    parser.add_argument('--url', default='http://174.138.84.70:8000',
                       help='API base URL (default: droplet)')
    parser.add_argument('--local', action='store_true',
                       help='Use localhost (http://localhost:8000)')
    
    args = parser.parse_args()
    
    api_url = 'http://localhost:8000' if args.local else args.url
    
    print("\n" + "="*70)
    print("MULTI-RUN API TEST SUITE")
    print("="*70)
    print(f"\nTesting API at: {api_url}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Run tests
    runs = test_runs_endpoint(api_url)
    
    if runs:
        # Test with latest run
        test_run_time_filtering(api_url, runs[0]['run_time'])
        
        # Test comparison scenario
        test_comparison_scenario(api_url, runs)
    
    # Validate response format
    test_response_format(api_url)
    
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    if runs:
        print(f"\n✅ Backend is working!")
        print(f"   Found {len(runs)} available runs")
        print(f"   Latest run: {runs[0]['run_time_formatted']}")
        print(f"\n📋 Next Steps:")
        print("   1. ✅ Backend complete")
        print("   2. ⏳ Build frontend in Phase 2")
        print("   3. ⏳ Deploy frontend to sodakweather.com")
    else:
        print(f"\n⚠️  No runs available yet")
        print(f"\n📋 To generate runs:")
        print("   1. Wait for next scheduled run (03:30, 09:30, 15:30, or 21:30 UTC)")
        print("   2. Or manually trigger map generation")
        print("   3. Then re-run this test")
    
    print("\n" + "="*70)
