#!/usr/bin/env python3
"""Run MSLP & Precip map generation for the latest 12z run (GFS + AIGFS)."""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
import logging

# Use local storage path when running from workspace
os.environ.setdefault(
    "STORAGE_PATH",
    "/Users/brianaustin/twf_models/backend/app/static/images",
)

# Ensure backend package is on sys.path
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.services.map_generator import MapGenerator
from app.services.model_factory import ModelFactory
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def latest_12z(run_time: datetime) -> datetime:
    rt = run_time.astimezone(timezone.utc) if run_time.tzinfo else run_time.replace(tzinfo=timezone.utc)
    if rt.hour >= 12:
        return rt.replace(hour=12, minute=0, second=0, microsecond=0)
    return (rt - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)


def run_test() -> None:
    generator = MapGenerator()
    target_hour = int(os.environ.get("FORECAST_HOUR", "12"))
    forecast_hours = [target_hour]
    models = ["GFS", "AIGFS"]

    total_success = 0
    total_attempts = 0

    for model_id in models:
        print("\n" + "=" * 70)
        print(f"MODEL: {model_id}")
        print("=" * 70)

        fetcher = ModelFactory.create_fetcher(model_id)
        latest_rt = fetcher.get_latest_run_time()
        run_time = latest_12z(latest_rt)

        print(f"Run Time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")

        success_count = 0
        for hour in forecast_hours:
            total_attempts += 1
            print(f"\nGenerating MSLP & Precip map for +{hour}h...")
            try:
                ds = fetcher.build_dataset_for_maps(
                    run_time=run_time,
                    forecast_hour=hour,
                    variables=["mslp_precip"],
                    subset_region=True,
                )

                output_path = generator.generate_map(
                    ds=ds,
                    variable="mslp_precip",
                    model=model_id,
                    run_time=run_time,
                    forecast_hour=hour,
                    region="pnw",
                )

                file_size = output_path.stat().st_size / 1024
                print(f"  Success: {output_path.name} ({file_size:.1f} KB)")
                success_count += 1
                total_success += 1
            except Exception as exc:
                print(f"  Error: {exc}")
                import traceback

                traceback.print_exc()

        print(f"\n{model_id} Results: {success_count}/{len(forecast_hours)} maps generated")

    print("\n" + "=" * 70)
    print(f"OVERALL RESULTS: {total_success}/{total_attempts} maps generated")
    print("=" * 70)


if __name__ == "__main__":
    run_test()
