#!/usr/bin/env python3
"""
Manual Multi-Model Map Generation Script
Generates maps for all enabled models for the latest available run.
Use run_latest_gfs_now.py or run_latest_aigfs_now.py to run individual models.
"""
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
from app.models.model_registry import ModelRegistry

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
    print("🌐 MANUALLY TRIGGERING LATEST MULTI-MODEL MAP GENERATION")
    print("="*70)
    print()
    
    # Clean up old maps first
    cleanup_old_maps()
    
    scheduler = ForecastScheduler()
    
    # Get enabled models
    enabled_models = ModelRegistry.get_enabled()
    
    print(f"📊 Enabled Models: {', '.join(enabled_models.keys())}")
    print()
    print("💡 Tip: Use run_latest_gfs_now.py or run_latest_aigfs_now.py")
    print("   to generate maps for individual models.")
    print()
    print("="*70)
    print()
    
    try:
        # Generate all enabled models
        scheduler.generate_all_models()
        
        print()
        print("="*70)
        print("✅ MULTI-MODEL MAP GENERATION COMPLETE!")
        print("="*70)
        print()
        print(f"Maps saved to: {settings.storage_path}")
        print()
        print("To view generated maps:")
        print(f"  ls -lh {settings.storage_path}/")
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
    print("🌐 Multi-Model Map Generator")
    print()
    print("This script will:")
    print("  1. Remove all existing maps")
    print("  2. Generate maps for all enabled models")
    print("  3. Process models sequentially (GFS, then AIGFS, etc.)")
    print()
    print("For testing individual models, use:")
    print("  - run_latest_gfs_now.py (GFS only)")
    print("  - run_latest_aigfs_now.py (AIGFS only)")
    print()
    
    try:
        force_latest_run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
