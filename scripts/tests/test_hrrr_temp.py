#!/usr/bin/env python3
"""
Focused test for HRRR temperature map generation.

Generates a single 2m temperature map with station overlays for HRRR.
"""

import os
import sys
from pathlib import Path
import logging

# Add backend to path
repo_root = Path(__file__).parents[2]
sys.path.insert(0, str(repo_root / "backend"))

# Force local storage path for test output
os.environ.setdefault(
    "STORAGE_PATH",
    str(repo_root / "backend" / "app" / "static" / "images")
)

from app.services.map_generator import MapGenerator
from app.services.model_factory import ModelFactory
from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_hrrr_temp():
    """Test HRRR 2m temperature map generation."""
    print("=" * 70)
    print("TEST: HRRR 2m Temperature Map Generation")
    print("=" * 70)

    generator = MapGenerator()
    fetcher = ModelFactory.create_fetcher("HRRR")
    run_time = fetcher.get_latest_run_time()

    # Pick the first available forecast hour > 0
    forecast_hours = [h for h in settings.hrrr_forecast_hours_list if h > 0]
    if not forecast_hours:
        raise ValueError("No forecast hours > 0 configured for temperature test")

    hour = forecast_hours[0]
    print(f"Run Time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
    print(f"Forecast Hour: +{hour}h")

    ds = fetcher.build_dataset_for_maps(
        run_time=run_time,
        forecast_hour=hour,
        variables=['temperature_2m'],
        subset_region=True
    )

    output_path = generator.generate_map(
        ds=ds,
        variable='temperature_2m',
        model='HRRR',
        run_time=run_time,
        forecast_hour=hour,
        region='pnw'
    )

    file_size = output_path.stat().st_size / 1024
    print(f"✅ Success: {output_path.name} ({file_size:.1f} KB)")


if __name__ == "__main__":
    test_hrrr_temp()
