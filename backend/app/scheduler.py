"""Scheduled task scheduler"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
from datetime import datetime, timedelta
from pathlib import Path

from app.config import settings
from app.services.map_generator import MapGenerator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class ForecastScheduler:
    """Schedules forecast map generation"""
    
    def __init__(self):
        self.scheduler = BlockingScheduler()
        self.map_generator = MapGenerator()
        # PNW-focused variables (wind gusts to be added later)
        self.variables = ['temp', 'precip', 'precip_type', 'wind_speed']
    
    def generate_forecast_maps(self):
        """
        Generate maps for all variables and forecast hours.
        
        Runs at 03:30, 09:30, 15:30, 21:30 UTC (3.5 hours after each GFS run).
        This matches industry standard timing (TropicalTidbits, etc.) when GFS data
        becomes reliably available on AWS S3.
        """
        logger.info("Starting scheduled forecast map generation")
        
        try:
            # Calculate the CURRENT GFS run time (not previous)
            # We run 3.5 hours after each model run when data is reliably available
            # Example: Run at 03:30 UTC → Fetch 00Z data (3.5 hours old)
            now = datetime.utcnow()
            run_hour = (now.hour // 6) * 6  # Current 6-hour cycle
            run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
            
            logger.info(f"Attempting to fetch GFS {run_time.strftime('%Y-%m-%d %Hz')} data")
            logger.info(f"(Data expected ~3.5 hours after run time)")
            
            # Try to generate maps for current run
            try:
                self._generate_maps_for_run(run_time)
                logger.info(f"✅ Successfully generated maps for {run_time.strftime('%Y-%m-%d %Hz')}")
                
                # Cleanup old runs after successful generation
                self.cleanup_old_runs()
                
            except Exception as e:
                # If current run fails (rare - data delayed), fall back to previous run
                logger.warning(f"⚠️ Current run ({run_time.strftime('%Hz')}) failed: {e}")
                logger.info("Falling back to previous 6-hour cycle...")
                
                previous_run = run_time - timedelta(hours=6)
                try:
                    self._generate_maps_for_run(previous_run)
                    logger.info(f"✅ Fallback successful - generated maps for {previous_run.strftime('%Y-%m-%d %Hz')}")
                except Exception as e2:
                    logger.error(f"❌ Both current and previous runs failed: {e2}")
                    raise
            
            logger.info("Completed forecast map generation")
            
        except Exception as e:
            logger.error(f"Error in scheduled map generation: {e}")
    
    def _generate_maps_for_run(self, run_time):
        """
        Generate all maps for a specific GFS run time.
        Separated into its own method to support fallback logic.
        """
        # Progressive generation: Generate by forecast hour (f000 first) so users
        # see the most current data appear first, then progressively older forecasts
        if settings.progressive_generation:
            logger.info("Using progressive generation (by forecast hour)")
            for forecast_hour in settings.forecast_hours_list:
                if forecast_hour > settings.max_forecast_hour:
                    continue
                
                logger.info(f"→ Generating forecast hour +{forecast_hour}h...")
                
                for variable in self.variables:
                    try:
                        self.map_generator.generate_map(
                            variable=variable,
                            model="GFS",
                            run_time=run_time,
                            forecast_hour=forecast_hour
                        )
                        logger.info(f"  ✓ {variable}")
                    except Exception as e:
                        logger.error(f"  ✗ {variable}: {e}")
                        continue
        else:
            # Standard generation: Generate by variable (all hours of temp, then all hours of precip, etc.)
            logger.info("Using standard generation (by variable)")
            for variable in self.variables:
                logger.info(f"→ Generating variable: {variable}")
                for forecast_hour in settings.forecast_hours_list:
                    if forecast_hour > settings.max_forecast_hour:
                        continue
                    
                    try:
                        self.map_generator.generate_map(
                            variable=variable,
                            model="GFS",
                            run_time=run_time,
                            forecast_hour=forecast_hour
                        )
                        logger.info(f"  ✓ +{forecast_hour}h")
                    except Exception as e:
                        logger.error(f"  ✗ +{forecast_hour}h: {e}")
                        continue
    
    def cleanup_old_runs(self, keep_last_n=4):
        """
        Keep only the last N GFS runs, delete older ones.
        
        This ensures we always have recent runs available for comparison
        while preventing unlimited disk space growth.
        
        Args:
            keep_last_n: Number of most recent runs to keep (default: 4 = last 24 hours)
        """
        try:
            images_path = Path(settings.storage_path)
            
            if not images_path.exists():
                logger.warning("Images directory doesn't exist, skipping cleanup")
                return
            
            # Parse all image filenames to extract unique run times
            image_files = list(images_path.glob("gfs_*.png"))
            
            if not image_files:
                logger.info("No images found, skipping cleanup")
                return
            
            # Extract unique run times (format: YYYYMMDD_HH)
            run_times = set()
            for img in image_files:
                try:
                    parts = img.stem.split('_')
                    if len(parts) >= 3:
                        run_time_str = f"{parts[1]}_{parts[2]}"  # e.g., "20260124_00"
                        run_times.add(run_time_str)
                except Exception as e:
                    logger.warning(f"Failed to parse filename {img.name}: {e}")
                    continue
            
            # Sort run times (newest first)
            sorted_runs = sorted(run_times, reverse=True)
            
            logger.info(f"Found {len(sorted_runs)} unique GFS runs")
            
            # Keep newest N, delete rest
            if len(sorted_runs) > keep_last_n:
                runs_to_keep = sorted_runs[:keep_last_n]
                runs_to_delete = sorted_runs[keep_last_n:]
                
                logger.info(f"Keeping {len(runs_to_keep)} runs: {', '.join(runs_to_keep)}")
                logger.info(f"Deleting {len(runs_to_delete)} old runs: {', '.join(runs_to_delete)}")
                
                deleted_count = 0
                for old_run in runs_to_delete:
                    # Delete all images from this run
                    old_images = list(images_path.glob(f"gfs_{old_run}_*.png"))
                    for img in old_images:
                        try:
                            img.unlink()
                            deleted_count += 1
                            logger.debug(f"Deleted: {img.name}")
                        except Exception as e:
                            logger.error(f"Failed to delete {img.name}: {e}")
                
                logger.info(f"✅ Cleanup complete: Deleted {deleted_count} images from {len(runs_to_delete)} old runs")
                
                # Log current disk usage
                total_size = sum(f.stat().st_size for f in images_path.glob("*.png"))
                logger.info(f"Current storage: {total_size / (1024*1024):.1f} MB ({len(list(images_path.glob('*.png')))} images)")
            else:
                logger.info(f"Only {len(sorted_runs)} runs found, keeping all (threshold: {keep_last_n})")
                
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    def start(self):
        """Start the scheduler"""
        # Schedule to run at 03:30, 09:30, 15:30, 21:30 UTC
        # This is 3.5 hours after each GFS run (00Z, 06Z, 12Z, 18Z)
        # Matches industry standard timing when data is reliably available
        # 
        # CST times: 9:30 PM, 3:30 AM, 9:30 AM, 3:30 PM
        # PST times: 7:30 PM, 1:30 AM, 7:30 AM, 1:30 PM
        # EST times: 10:30 PM, 4:30 AM, 10:30 AM, 4:30 PM
        self.scheduler.add_job(
            self.generate_forecast_maps,
            trigger=CronTrigger(hour='3,9,15,21', minute='30'),  # 3.5h after each GFS run
            id='generate_forecasts',
            name='Generate forecast maps',
            replace_existing=True
        )
        
        logger.info("Forecast scheduler started")
        logger.info("Schedule: 03:30, 09:30, 15:30, 21:30 UTC (3.5h after GFS runs)")
        self.scheduler.start()
    
    def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Forecast scheduler stopped")


if __name__ == "__main__":
    logger.info("Starting TWF Models Scheduler")
    scheduler = ForecastScheduler()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler interrupted, shutting down...")
        scheduler.stop()
