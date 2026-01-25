#!/usr/bin/env python3
"""
Test script to verify HTTP caching headers on API endpoints.
"""
import requests
import sys

API_BASE = "http://localhost:8000/api"

def test_endpoint(endpoint_name, url):
    """Test an endpoint for proper cache headers"""
    print(f"\n{'='*60}")
    print(f"Testing: {endpoint_name}")
    print(f"URL: {url}")
    print(f"{'='*60}")
    
    try:
        response = requests.get(url)
        print(f"Status: {response.status_code}")
        
        # Check for cache headers
        cache_control = response.headers.get('Cache-Control', 'Not set')
        etag = response.headers.get('ETag', 'Not set')
        expires = response.headers.get('Expires', 'Not set')
        
        print(f"\nCache Headers:")
        print(f"  Cache-Control: {cache_control}")
        print(f"  ETag: {etag}")
        print(f"  Expires: {expires}")
        
        # Test ETag if present
        if etag != 'Not set' and endpoint_name == "Image":
            print(f"\n  Testing ETag validation...")
            response2 = requests.get(url, headers={'If-None-Match': etag})
            print(f"  Response with matching ETag: {response2.status_code}")
            if response2.status_code == 304:
                print(f"  ✅ ETag validation working (304 Not Modified)")
            else:
                print(f"  ⚠️  Expected 304, got {response2.status_code}")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Could not connect to API. Is the server running?")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    print("=" * 60)
    print("HTTP Cache Headers Test")
    print("=" * 60)
    print("This test verifies that proper HTTP caching is implemented.")
    print("Make sure the API server is running on localhost:8000")
    
    # Test /api/maps endpoint
    test_endpoint("Maps List", f"{API_BASE}/maps")
    
    # Test /api/runs endpoint
    test_endpoint("Runs List", f"{API_BASE}/runs")
    
    # Test /api/images endpoint (if any images exist)
    print("\n" + "="*60)
    print("Checking for available images...")
    print("="*60)
    
    try:
        maps_response = requests.get(f"{API_BASE}/maps")
        if maps_response.status_code == 200:
            maps_data = maps_response.json()
            if maps_data.get('maps'):
                # Get first image
                first_map = maps_data['maps'][0]
                image_url = first_map['image_url']
                full_url = f"http://localhost:8000{image_url}"
                test_endpoint("Image", full_url)
            else:
                print("No maps available to test image caching")
        else:
            print(f"Could not fetch maps list (status: {maps_response.status_code})")
    except Exception as e:
        print(f"Error checking for images: {e}")
    
    print("\n" + "="*60)
    print("Test Complete!")
    print("="*60)


if __name__ == "__main__":
    main()
