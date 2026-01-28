#!/usr/bin/env python3
"""
Manual AIGFS Map Generation Script
Generates maps for the latest available AIGFS run immediately.
"""
import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

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

def cleanup_aigfs_maps():
    """Remove existing AIGFS PNG files from the images directory"""
    images_path = Path(settings.storage_path)
    
    if not images_path.exists():
        logger.info(f"📁 Images directory doesn't exist yet: {images_path}")
        images_path.mkdir(parents=True, exist_ok=True)
        return
    
    # Find all AIGFS PNG files
    aigfs_files = list(images_path.glob("aigfs_*.png"))
    
    if not aigfs_files:
        logger.info("📁 No existing AIGFS maps to clean up")
        return
    
    logger.info("="*70)
    logger.info(f"🧹 CLEANING UP OLD AIGFS MAPS")
    logger.info(f"📁 Directory: {images_path}")
    logger.info(f"🗑️  Found {len(aigfs_files)} AIGFS PNG files to remove")
    logger.info("="*70)
    
    removed_count = 0
    failed_count = 0
    
    for png_file in aigfs_files:
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

def force_latest_aigfs_run():
    print("="*70)
    print("🤖 MANUALLY TRIGGERING LATEST AIGFS MAP GENERATION")
    print("="*70)
    print()
    
    # Clean up old AIGFS maps first
    cleanup_aigfs_maps()
    
    scheduler = ForecastScheduler()
    
    # Get the latest AIGFS run time
    from datetime import timezone
    now = datetime.now(timezone.utc)
    
    # AIGFS runs at 00, 06, 12, 18 UTC with 3.5 hour delay
    adjusted_now = now - timedelta(hours=3, minutes=30)
    run_hour = (adjusted_now.hour // 6) * 6
    run_time = adjusted_now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    
    print(f"📡 Generating AIGFS maps for: {run_time.strftime('%Y-%m-%d %HZ')}")
    print(f"📊 Expected ~2-3 GB download (full GRIB2 files)")
    print(f"⏱️  Estimated time: 20-40 minutes depending on connection")
    print()
    print("Note: AIGFS downloads full files (no filter script available)")
    print()
    
    try:
        # Generate AIGFS maps only
        success = scheduler.generate_forecast_for_model('AIGFS')
        
        if success:
            print()
            print("="*70)
            print("✅ AIGFS MAP GENERATION COMPLETE!")
            print("="*70)
            print()
            print(f"Maps saved to: {settings.storage_path}")
            print()
            print("To view generated maps:")
            print(f"  ls -lh {settings.storage_path}/aigfs_*")
            print()
        else:
            print()
            print("="*70)
            print("❌ AIGFS MAP GENERATION FAILED")
            print("="*70)
            print()
            print("Check logs above for errors.")
            print()
            print("Common issues:")
            print("  - AIGFS data not yet available on NOMADS")
            print("  - Network/connection issues")
            print("  - Disk space issues")
            print()
            
    except KeyboardInterrupt:
        print()
        print("⚠️  Manual trigger interrupted by user")
        print()
    except Exception as e:
        print()
        print("="*70)
        print(f"❌ ERROR: {e}")
        print("="*70)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print()
    print("🤖 AIGFS Map Generator")
    print()
    print("This script will:")
    print("  1. Remove all existing AIGFS maps")
    print("  2. Download AIGFS data from NOMADS (full files)")
    print("  3. Generate all forecast maps")
    print()
    
    try:
        force_latest_aigfs_run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
