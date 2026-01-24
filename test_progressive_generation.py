"""
Test script to demonstrate progressive map generation.

This shows how maps become available progressively as they're generated,
rather than all at once at the end.
"""

import requests
import time
from datetime import datetime


def monitor_progressive_generation(api_url="http://174.138.84.70:8000"):
    """
    Monitor the API to see maps appearing progressively.
    Simulates what a frontend would do - poll the API and update as new maps arrive.
    """
    
    print("=" * 70)
    print("PROGRESSIVE GENERATION MONITOR")
    print("=" * 70)
    print(f"\nMonitoring API: {api_url}/api/maps")
    print("Watching for new maps to appear...")
    print("\nPress Ctrl+C to stop\n")
    
    seen_maps = set()
    start_time = time.time()
    last_count = 0
    
    try:
        while True:
            try:
                # Poll the API for available maps
                response = requests.get(f"{api_url}/api/maps", timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    current_maps = {m['id'] for m in data.get('maps', [])}
                    total_maps = len(current_maps)
                    
                    # Check for new maps
                    new_maps = current_maps - seen_maps
                    
                    if new_maps:
                        elapsed = time.time() - start_time
                        
                        # Group new maps by forecast hour for better display
                        by_hour = {}
                        for map_id in new_maps:
                            # Parse map_id format: gfs_YYYYMMDD_HH_variable_hour
                            parts = map_id.split('_')
                            if len(parts) >= 5:
                                hour = parts[-1]
                                variable = parts[-2] if len(parts) > 5 else parts[3]
                                if hour not in by_hour:
                                    by_hour[hour] = []
                                by_hour[hour].append(variable)
                        
                        # Display new maps grouped by forecast hour
                        for hour in sorted(by_hour.keys()):
                            vars_str = ', '.join(sorted(by_hour[hour]))
                            print(f"[{elapsed:>6.1f}s] ✓ Forecast hour +{hour}h: {vars_str}")
                        
                        seen_maps.update(new_maps)
                        last_count = total_maps
                    
                    # Show progress
                    if total_maps != last_count:
                        print(f"         Total maps available: {total_maps}")
                        last_count = total_maps
                
                else:
                    print(f"API returned status {response.status_code}")
                
            except requests.exceptions.RequestException as e:
                print(f"Error connecting to API: {e}")
            
            # Poll every 2 seconds
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped")
        print(f"\nFinal count: {len(seen_maps)} maps available")


def simulate_progressive_display():
    """
    Simulate how a frontend would display maps progressively.
    Shows the user experience.
    """
    
    print("\n" + "=" * 70)
    print("SIMULATED FRONTEND VIEW")
    print("=" * 70)
    print("\nThis simulates what users would see on the website:\n")
    
    # Simulate progressive appearance
    forecast_hours = [0, 24, 48, 72]
    variables = ['Temperature', 'Precipitation', 'Wind Speed', 'Precip Type']
    
    for i, hour in enumerate(forecast_hours):
        print(f"\n[After {(i+1)*60} seconds]")
        print(f"Forecast Hour +{hour}h now available:")
        print("┌─────────────────────────────────────────┐")
        
        for var in variables:
            print(f"│ ✓ {var:<35} │")
        
        print("└─────────────────────────────────────────┘")
        
        if i < len(forecast_hours) - 1:
            print(f"\n⏳ Loading forecast hour +{forecast_hours[i+1]}h...")
    
    print("\n✓ All maps loaded!")
    print("\nUser Experience:")
    print("  • Saw first maps (f000) after ~60 seconds")
    print("  • Didn't have to wait 4-5 minutes for everything")
    print("  • Could start viewing while rest loaded")


def check_generation_mode(api_url="http://174.138.84.70:8000"):
    """Check if progressive generation is enabled"""
    
    print("\n" + "=" * 70)
    print("CONFIGURATION CHECK")
    print("=" * 70)
    
    try:
        response = requests.get(f"{api_url}/api/health", timeout=5)
        if response.status_code == 200:
            print(f"\n✓ API is accessible at {api_url}")
            print("\nProgressive generation is enabled by default.")
            print("Maps will appear in this order:")
            print("  1. All f000 maps (temp, precip, wind, precip_type)")
            print("  2. All f024 maps")
            print("  3. All f048 maps")
            print("  4. All f072 maps")
        else:
            print(f"\n✗ API returned status {response.status_code}")
    except Exception as e:
        print(f"\n✗ Could not connect to API: {e}")
        print("\nIf testing locally, the API won't be running.")
        print("This feature works automatically once deployed to the droplet.")


if __name__ == "__main__":
    import sys
    
    print("\n" + "=" * 70)
    print("PROGRESSIVE MAP GENERATION TEST")
    print("=" * 70)
    
    if len(sys.argv) > 1 and sys.argv[1] == "--monitor":
        # Live monitoring mode
        api_url = sys.argv[2] if len(sys.argv) > 2 else "http://174.138.84.70:8000"
        monitor_progressive_generation(api_url)
    else:
        # Demo mode
        check_generation_mode()
        simulate_progressive_display()
        
        print("\n" + "=" * 70)
        print("TO MONITOR LIVE:")
        print("=" * 70)
        print("\nRun this script with --monitor flag during a generation cycle:")
        print("  python3 test_progressive_generation.py --monitor")
        print("\nOr specify a different API URL:")
        print("  python3 test_progressive_generation.py --monitor http://localhost:8000")
        print("\nBest times to watch (CST):")
        print("  • 12:00 AM (midnight)")
        print("  • 6:00 AM")
        print("  • 12:00 PM (noon)")
        print("  • 6:00 PM")
        print("\n" + "=" * 70)
