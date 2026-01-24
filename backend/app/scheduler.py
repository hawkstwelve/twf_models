"""Scheduled task scheduler"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
import time
import s3fs
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
        # Initialize S3 filesystem for data availability checks
        self.s3 = s3fs.S3FileSystem(anon=True)
    
    def check_data_available(self, run_time, forecast_hour):
        """
        Check if GFS data is available on S3 for a specific forecast hour.
        
        Args:
            run_time: GFS run time (datetime)
            forecast_hour: Forecast hour (int)
            
        Returns:
            bool: True if data exists on S3
        """
        try:
            date_str = run_time.strftime('%Y%m%d')
            hour_str = run_time.strftime('%H')
            hour_padded = f"{forecast_hour:03d}"
            
            # Check GRIB file (primary data source)
            grib_path = f"noaa-gfs-bdp-pds/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.{settings.gfs_resolution}.f{hour_padded}"
            
            exists = self.s3.exists(grib_path)
            return exists
            
        except Exception as e:
            logger.debug(f"Error checking data availability for f{forecast_hour:03d}: {e}")
            return False
    
    def generate_forecast_maps(self):
        """
        Progressive map generation with real-time monitoring.
        
        Monitors S3 every minute for new GFS data and generates maps as soon as
        each forecast hour becomes available. This provides a real-time, TropicalTidbits-style
        user experience where maps appear progressively.
        
        Runs at 03:30, 09:30, 15:30, 21:30 UTC (3.5 hours after each GFS run).
        Monitors for up to 90 minutes to capture all forecast hours as they're uploaded.
        """
        logger.info("="*70)
        logger.info("🚀 Starting progressive map generation")
        logger.info("="*70)
        
        try:
            # Calculate the CURRENT GFS run time
            now = datetime.utcnow()
            run_hour = (now.hour // 6) * 6  # Current 6-hour cycle
            run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
            
            logger.info(f"📡 Monitoring GFS {run_time.strftime('%Y-%m-%d %Hz')} run")
            logger.info(f"⏱️  Will check S3 every 60 seconds for up to 90 minutes")
            logger.info(f"🎯 Target forecast hours: {', '.join([str(h) for h in settings.forecast_hours_list])}")
            
            # Monitor and generate progressively
            self._progressive_generation_loop(run_time, duration_minutes=90, check_interval_seconds=60)
            
            # Cleanup old runs after completion
            self.cleanup_old_runs()
            
            logger.info("="*70)
            logger.info("✅ Progressive generation complete")
            logger.info("="*70)
            
        except Exception as e:
            logger.error(f"❌ Error in progressive generation: {e}")
    
    def _progressive_generation_loop(self, run_time, duration_minutes=90, check_interval_seconds=60):
        """
        Monitor S3 and generate maps progressively as data becomes available.
        
        Args:
            run_time: GFS run time to monitor
            duration_minutes: How long to monitor (default: 90 minutes)
            check_interval_seconds: How often to check S3 (default: 60 seconds)
        """
        start_time = datetime.utcnow()
        generated_hours = set()
        total_forecast_hours = len([h for h in settings.forecast_hours_list if h <= settings.max_forecast_hour])
        
        check_count = 0
        
        while True:
            check_count += 1
            elapsed_minutes = (datetime.utcnow() - start_time).total_seconds() / 60
            
            # Check if we've exceeded the monitoring duration
            if elapsed_minutes >= duration_minutes:
                logger.info(f"⏰ Monitoring duration reached ({duration_minutes} minutes)")
                break
            
            logger.info(f"🔍 Check #{check_count} (elapsed: {elapsed_minutes:.1f} min)")
            
            # Check each forecast hour we haven't generated yet
            newly_generated = []
            
            for forecast_hour in settings.forecast_hours_list:
                if forecast_hour > settings.max_forecast_hour:
                    continue
                    
                if forecast_hour in generated_hours:
                    continue  # Already generated
                
                # Check if data is available for this forecast hour
                if self.check_data_available(run_time, forecast_hour):
                    logger.info(f"✅ f{forecast_hour:03d} data available! Generating maps...")
                    
                    # Generate all variables for this forecast hour
                    success_count = 0
                    for variable in self.variables:
                        try:
                            self.map_generator.generate_map(
                                variable=variable,
                                model="GFS",
                                run_time=run_time,
                                forecast_hour=forecast_hour
                            )
                            logger.info(f"  ✓ {variable}")
                            success_count += 1
                        except Exception as e:
                            logger.error(f"  ✗ {variable}: {e}")
                    
                    if success_count > 0:
                        generated_hours.add(forecast_hour)
                        newly_generated.append(forecast_hour)
                        logger.info(f"🎉 +{forecast_hour}h complete! Progress: {len(generated_hours)}/{total_forecast_hours} forecast hours")
                else:
                    logger.debug(f"⏳ f{forecast_hour:03d} not available yet")
            
            # Check if all forecast hours are complete
            if len(generated_hours) == total_forecast_hours:
                logger.info("="*70)
                logger.info(f"🎊 All {total_forecast_hours} forecast hours generated!")
                logger.info(f"📊 Total time: {elapsed_minutes:.1f} minutes")
                logger.info(f"📊 Total checks: {check_count}")
                logger.info("="*70)
                break
            
            # Status update
            if newly_generated:
                logger.info(f"📈 Generated this check: {newly_generated}")
            else:
                logger.info(f"⏳ Still waiting for data... ({len(generated_hours)}/{total_forecast_hours} complete)")
            
            # Wait before next check
            logger.info(f"💤 Sleeping for {check_interval_seconds} seconds...")
            time.sleep(check_interval_seconds)
        
        # Final summary
        if len(generated_hours) < total_forecast_hours:
            missing_hours = [h for h in settings.forecast_hours_list if h not in generated_hours and h <= settings.max_forecast_hour]
            logger.warning(f"⚠️  Incomplete: Generated {len(generated_hours)}/{total_forecast_hours} forecast hours")
            logger.warning(f"⚠️  Missing hours: {missing_hours}")
        else:
            logger.info(f"✅ Complete: All {total_forecast_hours} forecast hours generated")
    
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
        # Schedule progressive generation at 03:30, 09:30, 15:30, 21:30 UTC
        # Starts 3.5 hours after each GFS run (00Z, 06Z, 12Z, 18Z)
        # Then monitors S3 every 60 seconds for up to 90 minutes
        # Generates maps in real-time as forecast hours become available
        # 
        # CST times: 9:30 PM, 3:30 AM, 9:30 AM, 3:30 PM
        # PST times: 7:30 PM, 1:30 AM, 7:30 AM, 1:30 PM
        # EST times: 10:30 PM, 4:30 AM, 10:30 AM, 4:30 PM
        self.scheduler.add_job(
            self.generate_forecast_maps,
            trigger=CronTrigger(hour='3,9,15,21', minute='30'),  # Start monitoring 3.5h after each GFS run
            id='generate_forecasts',
            name='Generate forecast maps',
            replace_existing=True,
            max_instances=1  # Ensure only one monitoring session runs at a time
        )
        
        logger.info("Forecast scheduler started")
        logger.info("Schedule: 03:30, 09:30, 15:30, 21:30 UTC")
        logger.info("Mode: Progressive real-time generation (checks S3 every 60 seconds)")
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
