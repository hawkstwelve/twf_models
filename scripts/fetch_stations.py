"""
Fetch weather stations from NWS API and cache locally.

Usage:
    python scripts/fetch_stations.py --states WA,OR,ID --bbox -125.0,42.0,-110.0,49.0 --output backend/app/data/station_cache.json
    
Note: --states is required for the API query. --bbox is optional metadata for documentation.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_bbox(bbox_str: str) -> Tuple[float, float, float, float]:
    """
    Parse bbox string in NWS API format: west,south,east,north
    
    Args:
        bbox_str: Comma-separated "west_lon,south_lat,east_lon,north_lat"
    
    Returns:
        Tuple of (west_lon, south_lat, east_lon, north_lat)
    
    Raises:
        ValueError: If bbox is invalid
    """
    try:
        west, south, east, north = map(float, bbox_str.split(','))
    except ValueError:
        raise ValueError("Bbox must be 4 comma-separated numbers")
    
    # Validate ranges
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise ValueError(f"Longitude must be -180 to 180, got west={west}, east={east}")
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        raise ValueError(f"Latitude must be -90 to 90, got south={south}, north={north}")
    if west >= east:
        raise ValueError(f"West longitude must be < east, got {west} >= {east}")
    if south >= north:
        raise ValueError(f"South latitude must be < north, got {south} >= {north}")
    
    return (west, south, east, north)


def fetch_stations_from_nws(
    states: str,
    max_stations: Optional[int] = None
) -> List[Dict]:
    """
    Fetch stations from NWS API with pagination.
    
    Args:
        states: Comma-separated state abbreviations (e.g., "WA,OR,ID")
        max_stations: Maximum number of stations to fetch (None = all)
    
    Returns:
        List of station dicts with normalized fields
        
    Raises:
        requests.RequestException: If API request fails
        SystemExit: If fatal error occurs
    """
    base_url = "https://api.weather.gov/stations"
    
    stations = []
    seen_ids: Set[str] = set()  # Deduplicate stations
    page = 1
    
    # Build initial request URL with params
    request_url = base_url
    params = {'state': states}
    
    while True:
        
        logger.info(f"Fetching page {page} from NWS API...")
        
        # Retry loop with exponential backoff
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                response = requests.get(
                    request_url,
                    params=params,
                    headers={
                        'User-Agent': 'TWF-Models/1.0 (contact: brian@sodakweather.com)',
                        'Accept': 'application/geo+json'
                    },
                    timeout=30
                )
                
                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            wait_time = int(retry_after)
                        except ValueError:
                            # Retry-After might be HTTP-date format, fall back to exponential backoff
                            wait_time = retry_delay * (2 ** attempt)
                        logger.warning(f"Rate limited (429). Waiting {wait_time}s as requested by Retry-After header")
                        time.sleep(wait_time)
                        continue
                    else:
                        wait_time = retry_delay * (2 ** attempt)
                        logger.warning(f"Rate limited (429). Retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                
                # Debug 400 errors before raising
                if response.status_code == 400:
                    logger.error(f"400 Bad Request from NWS API:")
                    logger.error(f"Request URL: {response.url}")
                    logger.error(f"Response body: {response.text}")
                
                response.raise_for_status()
                data = response.json()
                break  # Success, exit retry loop
                
            except requests.RequestException as e:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(f"Request failed: {e}. Retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    logger.error(f"API request failed after {max_retries} attempts: {e}")
                    logger.error("Aborting to avoid saving partial/incomplete data")
                    sys.exit(1)
        else:
            # All retries exhausted
            logger.error(f"Failed to fetch page {page} after {max_retries} attempts")
            sys.exit(1)
        
        features = data.get('features', [])
        if not features:
            break
        
        logger.info(f"  Retrieved {len(features)} features")
        
        # Normalize station data
        for feature in features:
            props = feature.get('properties', {})
            geom = feature.get('geometry', {})
            
            # Validate geometry type
            if geom.get('type') != 'Point':
                logger.debug(f"Skipping non-Point geometry: {geom.get('type')}")
                continue
            
            coords = geom.get('coordinates', [None, None])
            
            # Extract and validate coordinates
            station_lon = coords[0]
            station_lat = coords[1]
            station_id = props.get('stationIdentifier', '')
            
            # Skip invalid stations
            if not station_id:
                continue
            
            # Validate coordinate ranges
            if station_lat is None or station_lon is None:
                continue
            if not (-90 <= station_lat <= 90):
                logger.debug(f"Invalid latitude for {station_id}: {station_lat}")
                continue
            if not (-180 <= station_lon <= 180):
                logger.debug(f"Invalid longitude for {station_id}: {station_lon}")
                continue
            
            # Deduplicate by station ID
            if station_id in seen_ids:
                logger.debug(f"Skipping duplicate station: {station_id}")
                continue
            
            seen_ids.add(station_id)
            
            station = {
                'id': station_id,
                'name': props.get('name', ''),
                'lat': station_lat,
                'lon': station_lon,
                'elevation_m': props.get('elevation', {}).get('value'),
                'state': None,  # Extract from name if possible
                'abbr': station_id[:4],
                'station_type': 'nws',
                'display_weight': 1.0
            }
            
            stations.append(station)
        
        # Check for more pages
        next_val = data.get('pagination', {}).get('next')
        if not next_val:
            break
        
        # Follow pagination URL directly (more robust than extracting cursor)
        if next_val.startswith('http'):
            # NWS returned full URL - use it directly
            request_url = next_val
            params = {}  # URL already has all params
            logger.debug(f"Following pagination URL: {next_val}")
        else:
            # Fallback: assume it's a cursor token
            logger.debug(f"Using cursor token: {next_val}")
            request_url = base_url
            params = {'state': states, 'cursor': next_val}
        
        if max_stations and len(stations) >= max_stations:
            stations = stations[:max_stations]
            break
        
        page += 1
    
    logger.info(f"Total stations fetched: {len(stations)}")
    return stations


def save_station_cache(stations: List[Dict], output_path: Path, states: str, bbox: Optional[Tuple[float, float, float, float]] = None):
    """Save stations to JSON cache file with metadata."""
    from datetime import datetime
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    cache_data = {
        'version': '1.0',
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'source': 'nws',
        'coverage_states': states,
        'station_count': len(stations),
        'stations': stations
    }
    
    # Add coverage_bbox if provided (optional metadata)
    if bbox:
        cache_data['coverage_bbox'] = {
            'west': bbox[0],
            'south': bbox[1],
            'east': bbox[2],
            'north': bbox[3]
        }
    
    with open(output_path, 'w') as f:
        json.dump(cache_data, f, indent=2)
    
    logger.info(f"Saved {len(stations)} stations to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Fetch stations from NWS API')
    parser.add_argument(
        '--states',
        required=True,
        help='Comma-separated state abbreviations (e.g., WA,OR,ID)'
    )
    parser.add_argument(
        '--bbox',
        required=False,
        help='Optional coverage bbox metadata: west_lon,south_lat,east_lon,north_lat'
    )
    parser.add_argument(
        '--output',
        type=Path,
        required=True,
        help='Output JSON file path'
    )
    parser.add_argument(
        '--max',
        type=int,
        default=None,
        help='Maximum number of stations to fetch'
    )
    
    args = parser.parse_args()
    
    try:
        logger.info(f"Fetching stations for states: {args.states}")
        
        # Parse bbox if provided (optional metadata)
        bbox = None
        if args.bbox:
            bbox = parse_bbox(args.bbox)
            logger.info(f"Coverage bbox (metadata): {bbox}")
        
        stations = fetch_stations_from_nws(args.states, args.max)
        
        if not stations:
            logger.error("No stations fetched")
            sys.exit(1)
        
        save_station_cache(stations, args.output, args.states, bbox)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
