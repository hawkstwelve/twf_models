#!/usr/bin/env python3
"""
Test HTTP caching implementation
Run this locally - it will test the remote API
"""
import requests
import time
from datetime import datetime

API_BASE = "https://api.sodakweather.com/api"

def test_cache_headers():
    """Test that cache headers are present"""
    print("=" * 60)
    print("Testing Cache Headers")
    print("=" * 60)
    
    # Test maps list endpoint
    print("\n1. Testing /maps endpoint:")
    response = requests.get(f"{API_BASE}/maps")
    print(f"   Status: {response.status_code}")
    print(f"   Cache-Control: {response.headers.get('Cache-Control', 'NOT SET')}")
    assert 'max-age' in response.headers.get('Cache-Control', ''), "Cache-Control not set for /maps"
    print("   ✓ Cache headers present")
    
    # Test runs list endpoint
    print("\n2. Testing /runs endpoint:")
    response = requests.get(f"{API_BASE}/runs")
    print(f"   Status: {response.status_code}")
    print(f"   Cache-Control: {response.headers.get('Cache-Control', 'NOT SET')}")
    assert 'max-age' in response.headers.get('Cache-Control', ''), "Cache-Control not set for /runs"
    print("   ✓ Cache headers present")
    
    # Test image endpoint (if we can find an image)
    print("\n3. Testing /images endpoint:")
    maps_response = requests.get(f"{API_BASE}/maps")
    if maps_response.status_code == 200:
        maps = maps_response.json().get('maps', [])
        if maps:
            # Extract filename from image_url
            image_url = maps[0]['image_url']
            filename = image_url.split('/')[-1]
            
            response = requests.head(f"{API_BASE}/images/{filename}")
            print(f"   Image: {filename}")
            print(f"   Status: {response.status_code}")
            print(f"   Cache-Control: {response.headers.get('Cache-Control', 'NOT SET')}")
            print(f"   ETag: {response.headers.get('ETag', 'NOT SET')}")
            print(f"   Expires: {response.headers.get('Expires', 'NOT SET')}")
            
            assert 'immutable' in response.headers.get('Cache-Control', ''), "Immutable not set for images"
            print("   ✓ Immutable cache headers present")
        else:
            print("   ⚠ No maps available to test")
    else:
        print("   ⚠ Could not fetch maps list")


def test_etag_behavior():
    """Test ETag conditional requests"""
    print("\n" + "=" * 60)
    print("Testing ETag Behavior")
    print("=" * 60)
    
    # Get list of maps
    maps_response = requests.get(f"{API_BASE}/maps")
    if maps_response.status_code != 200:
        print("⚠ Could not fetch maps list")
        return
    
    maps = maps_response.json().get('maps', [])
    if not maps:
        print("⚠ No maps available to test")
        return
    
    # Extract filename from first map
    image_url = maps[0]['image_url']
    filename = image_url.split('/')[-1]
    
    print(f"\n1. First request (full download):")
    print(f"   Image: {filename}")
    response1 = requests.head(f"{API_BASE}/images/{filename}")
    print(f"   Status: {response1.status_code}")
    etag = response1.headers.get('ETag')
    print(f"   ETag: {etag}")
    
    if not etag:
        print("   ⚠ ETag not returned")
        return
    
    print("\n2. Second request with ETag (should be 304):")
    response2 = requests.head(
        f"{API_BASE}/images/{filename}",
        headers={'If-None-Match': etag}
    )
    print(f"   Status: {response2.status_code}")
    
    if response2.status_code == 304:
        print("   ✓ 304 Not Modified returned (ETag working!)")
    elif response2.status_code == 200:
        print("   ⚠ 200 OK returned (ETag not working)")
    else:
        print(f"   ⚠ Unexpected status: {response2.status_code}")


def test_cache_duration():
    """Test cache duration settings"""
    print("\n" + "=" * 60)
    print("Testing Cache Duration")
    print("=" * 60)
    
    # Test maps list (should be 300 seconds = 5 minutes)
    print("\n1. Maps list cache duration:")
    response = requests.get(f"{API_BASE}/maps")
    cache_control = response.headers.get('Cache-Control', '')
    print(f"   Cache-Control: {cache_control}")
    
    # Extract max-age
    if 'max-age=' in cache_control:
        max_age = cache_control.split('max-age=')[1].split(',')[0]
        print(f"   Max-Age: {max_age} seconds ({int(max_age) / 60} minutes)")
        assert int(max_age) == 300, f"Expected 300 seconds, got {max_age}"
        print("   ✓ Correct cache duration (5 minutes)")
    else:
        print("   ⚠ max-age not found")
    
    # Test runs list (should be 300 seconds = 5 minutes)
    print("\n2. Runs list cache duration:")
    response = requests.get(f"{API_BASE}/runs")
    cache_control = response.headers.get('Cache-Control', '')
    print(f"   Cache-Control: {cache_control}")
    
    if 'max-age=' in cache_control:
        max_age = cache_control.split('max-age=')[1].split(',')[0]
        print(f"   Max-Age: {max_age} seconds ({int(max_age) / 60} minutes)")
        assert int(max_age) == 300, f"Expected 300 seconds, got {max_age}"
        print("   ✓ Correct cache duration (5 minutes)")
    else:
        print("   ⚠ max-age not found")
    
    # Test image (should be 604800 seconds = 7 days)
    print("\n3. Image cache duration:")
    maps_response = requests.get(f"{API_BASE}/maps")
    if maps_response.status_code == 200:
        maps = maps_response.json().get('maps', [])
        if maps:
            image_url = maps[0]['image_url']
            filename = image_url.split('/')[-1]
            
            response = requests.head(f"{API_BASE}/images/{filename}")
            cache_control = response.headers.get('Cache-Control', '')
            print(f"   Cache-Control: {cache_control}")
            
            if 'max-age=' in cache_control:
                max_age = cache_control.split('max-age=')[1].split(',')[0]
                print(f"   Max-Age: {max_age} seconds ({int(max_age) / 86400} days)")
                assert int(max_age) == 604800, f"Expected 604800 seconds, got {max_age}"
                print("   ✓ Correct cache duration (7 days)")
                assert 'immutable' in cache_control, "immutable flag missing"
                print("   ✓ Immutable flag present")
            else:
                print("   ⚠ max-age not found")
        else:
            print("   ⚠ No maps available")
    else:
        print("   ⚠ Could not fetch maps")


def main():
    """Run all cache tests"""
    print("\n" + "=" * 60)
    print("TWF Models - HTTP Caching Test Suite")
    print("=" * 60)
    print(f"Testing API: {API_BASE}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        test_cache_headers()
        test_etag_behavior()
        test_cache_duration()
        
        print("\n" + "=" * 60)
        print("✓ All cache tests completed!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except requests.exceptions.RequestException as e:
        print(f"\n✗ Network error: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
