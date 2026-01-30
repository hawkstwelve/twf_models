"""Quick HRRR radar debug script.

Usage:
  python scripts/tests/test_hrrr_radar_debug.py --run 2026-01-30T19:00:00Z --fxx 12
"""
from datetime import datetime, timezone
import argparse
import logging
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("STORAGE_PATH", str(ROOT / "backend" / "app" / "static" / "images"))
sys.path.insert(0, str(ROOT / "backend"))

from app.services.model_factory import ModelFactory
from app.services.map_generator import MapGenerator


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hrrr-radar-debug")


def parse_run_time(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1]
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="HRRR radar debug")
    parser.add_argument("--run", required=True, help="Run time, e.g. 2026-01-30T19:00:00Z")
    parser.add_argument("--fxx", type=int, required=True, help="Forecast hour")
    parser.add_argument("--region", default=None, help="Override region (e.g. us, pnw)")
    args = parser.parse_args()

    run_time = parse_run_time(args.run)
    forecast_hour = args.fxx

    fetcher = ModelFactory.create_fetcher("HRRR")
    variables = ["radar"]

    logger.info(f"Building dataset for HRRR f{forecast_hour:03d} @ {run_time.isoformat()}")
    ds = fetcher.build_dataset_for_maps(run_time, forecast_hour, variables, subset_region=True)

    # Trigger radar processing and logging
    mg = MapGenerator()
    _ = mg.generate_map(ds, "radar", model="HRRR", run_time=run_time, forecast_hour=forecast_hour, region=args.region)


if __name__ == "__main__":
    main()
