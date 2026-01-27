import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
import glob

# Add the backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from app.scheduler import ForecastScheduler
from app.config import settings

# Configure logging to see output in terminal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def cleanup_old_maps():
    """Remove all existing PNG files from the images directory"""
    images_path = Path(settings.storage_path)
    
    if not images_path.exists():
        logger.info(f"📁 Images directory doesn't exist yet: {images_path}")
        images_path.mkdir(parents=True, exist_ok=True)
        return
    
    # Find all PNG files
    png_files = list(images_path.glob("*.png"))
    
    if not png_files:
        logger.info("📁 No existing maps to clean up")
        return
    
    logger.info("="*70)
    logger.info(f"🧹 CLEANING UP OLD MAPS")
    logger.info(f"📁 Directory: {images_path}")
    logger.info(f"🗑️  Found {len(png_files)} PNG files to remove")
    logger.info("="*70)
    
    removed_count = 0
    failed_count = 0
    
    for png_file in png_files:
        try:
            png_file.unlink()
            removed_count += 1
            logger.debug(f"   ✓ Removed: {png_file.name}")
        except Exception as e:
            failed_count += 1
            logger.error(f"   ✗ Failed to remove {png_file.name}: {e}")
    
    logger.info(f"✅ Cleanup complete: {removed_count} removed, {failed_count} failed")
    logger.info("="*70)
    print()  # Empty line for readability

def force_latest_run():
    print("="*70)
    print("🚀 MANUALLY TRIGGERING LATEST GFS MAP GENERATION")
    print("="*70)
    
    # Clean up old maps first
    cleanup_old_maps()
    
    scheduler = ForecastScheduler()
    
    # Calculate the most likely available GFS run time
    # GFS runs at 00, 06, 12, 18 UTC
    from datetime import timezone
    now = datetime.now(timezone.utc)
    # Go back 3.5 hours to find which run should be finishing/available
    adjusted_now = now - timedelta(hours=3, minutes=30)
    run_hour = (adjusted_now.hour // 6) * 6
    run_time = adjusted_now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    print(f"📡 Force-starting monitoring for: {run_time.strftime('%Y-%m-%d %Hz')}")
    print(f"⏱️  Will check NOMADS every 60 seconds for data...")
    
    try:
        # Run the same loop the scheduler uses
        scheduler._progressive_generation_loop(
            run_time, 
            duration_minutes=120, # Monitor for 2 hours
            check_interval_seconds=60
        )
    except KeyboardInterrupt:
        print("\nStopping manual trigger...")

if __name__ == "__main__":
    force_latest_run()
