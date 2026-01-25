"""Scheduled task scheduler"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import os
import sys
import logging
import time
import s3fs
import gc
from multiprocessing import Pool
from datetime import datetime, timedelta
from pathlib import Path

# Add the current directory to sys.path to allow absolute imports from 'app'
# This handles cases where the script is run from the root or the backend folder
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)
# Also add the parent directory (backend/) to sys.path
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from app.config import settings
from app.services.map_generator import MapGenerator
from app.services.data_fetcher import GFSDataFetcher

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def generate_maps_for_hour(args):
    """Standalone function for parallel map generation"""
    run_time, forecast_hour, variables = args
    
    # Configure logging for the child process
    child_logger = logging.getLogger(f"f{forecast_hour:03d}")
    
    try:
        child_logger.info(f"🚀 Worker starting for f{forecast_hour:03d}")
        
        # Each process needs its own generator and fetcher
        map_generator = MapGenerator()
        data_fetcher = GFSDataFetcher()
        
        # Determine all variables needed for this hour
        # Note: For f000 (analysis), wind_speed may not be available, so we'll skip it
        all_needed_vars = set()
        variables_to_generate = list(variables)  # Copy list to modify
        
        # Skip wind_speed for f000 since analysis files don't have 10m wind
        if forecast_hour == 0 and "wind_speed" in variables_to_generate:
            variables_to_generate.remove("wind_speed")
            child_logger.info(f"  ⊙ f{forecast_hour:03d}: wind_speed skipped (not available in analysis file)")
        
        for variable in variables_to_generate:
            if variable == "temp":
                all_needed_vars.update(['tmp2m', 'prate'])
            elif variable == "precip":
                # Precipitation handled separately below - needs special summing
                pass
            elif variable == "wind_speed":
                all_needed_vars.update(['ugrd10m', 'vgrd10m'])
            elif variable == "temp_850_wind_mslp":
                all_needed_vars.update(['tmp_850', 'ugrd_850', 'vgrd_850', 'prmsl'])
            elif variable == "mslp_precip":
                all_needed_vars.update(['prate', 'tp', 'prmsl', 'gh', 'gh_1000', 'gh_500', 'crain', 'csnow', 'cicep', 'cfrzr'])
            elif variable == "radar" or variable == "radar_reflectivity":
                all_needed_vars.add('refc')
        
        # Fetch data for non-precipitation variables
        ds = data_fetcher.fetch_gfs_data(
            run_time, 
            forecast_hour,
            variables=list(all_needed_vars),
            subset_region=True
        )
        
        # For precipitation, fetch total accumulated precip (summed across all hours)
        # This is done separately because it requires downloading multiple GRIB files
        if "precip" in variables_to_generate:
            try:
                child_logger.info(f"  Fetching total precipitation (0-{forecast_hour}h)...")
                total_precip = data_fetcher.fetch_total_precipitation(
                    run_time=run_time,
                    forecast_hour=forecast_hour,
                    subset_region=True
                )
                # Add to dataset
                ds['tp'] = total_precip
                child_logger.info(f"  ✓ Total precipitation added to dataset")
            except Exception as e:
                child_logger.error(f"  ✗ Failed to fetch total precipitation: {e}")
                # Remove precip from variables to skip it
                if "precip" in variables_to_generate:
                    variables_to_generate.remove("precip")
                    child_logger.warning(f"  Skipping precip map due to fetch failure")
        
        # Check which maps already exist for this run
        run_str = run_time.strftime("%Y%m%d_%H")
        images_path = Path(settings.storage_path)
        existing_maps = set()
        
        if images_path.exists():
            for var in variables_to_generate:
                expected_filename = f"gfs_{run_str}_{var}_{forecast_hour}.png"
                if (images_path / expected_filename).exists():
                    existing_maps.add(var)
                    child_logger.info(f"  ⊙ f{forecast_hour:03d}: {var} already exists, skipping")
        
        # Generate all maps - track success/failure per variable
        results = {}
        success_count = 0
        failed_variables = []
        skipped_count = len(existing_maps)
        
        for variable in variables_to_generate:
            # Skip if already exists
            if variable in existing_maps:
                results[variable] = True
                success_count += 1
                continue
            
            try:
                map_generator.generate_map(
                    ds=ds,
                    variable=variable,
                    model="GFS",
                    run_time=run_time,
                    forecast_hour=forecast_hour
                )
                child_logger.info(f"  ✓ f{forecast_hour:03d}: {variable}")
                results[variable] = True
                success_count += 1
            except Exception as e:
                child_logger.error(f"  ✗ f{forecast_hour:03d}: {variable}: {e}")
                results[variable] = False
                failed_variables.append(variable)
        
        # Cleanup
        ds.close()
        del ds
        gc.collect()
        
        # Only mark as complete if ALL maps exist (either pre-existing or newly generated)
        # Note: variables_to_generate may be fewer than variables (e.g., wind_speed skipped for f000)
        expected_count = len(variables_to_generate)
        if success_count == expected_count:
            if skipped_count > 0:
                child_logger.info(f"✅ f{forecast_hour:03d}: All {expected_count} maps present ({skipped_count} existed, {expected_count - skipped_count} generated)")
            else:
                child_logger.info(f"✅ f{forecast_hour:03d}: All {expected_count} maps generated successfully")
            return forecast_hour
        else:
            child_logger.warning(f"⚠️  f{forecast_hour:03d}: Only {success_count}/{expected_count} maps present. Failed: {failed_variables}")
            # Return None to indicate incomplete - scheduler will retry this hour
            return None
        
    except Exception as e:
        child_logger.error(f"❌ Worker failed for f{forecast_hour:03d}: {e}")
        return None

class ForecastScheduler:
    """Schedules forecast map generation"""
    
    def __init__(self):
        self.scheduler = BlockingScheduler()
        self.map_generator = MapGenerator()
        self.data_fetcher = GFSDataFetcher()
        # PNW-focused variables
        self.variables = ['temp', 'precip', 'wind_speed', 'mslp_precip', 'temp_850_wind_mslp', 'radar']
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
            # Use '000' for forecast hour 0, but GFS sometimes uses 'anl' for analysis
            grib_path = f"noaa-gfs-bdp-pds/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.{settings.gfs_resolution}.f{hour_padded}"
            
            exists = self.s3.exists(grib_path)
            
            # If f000 doesn't exist, try 'anl' (some GFS versions use this for hour 0)
            if not exists and forecast_hour == 0:
                anl_path = f"noaa-gfs-bdp-pds/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.{settings.gfs_resolution}.anl"
                exists = self.s3.exists(anl_path)
                if exists:
                    logger.info(f"Found analysis file (anl) for f000")
            
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
        newly_generated = []  # Initialize here to avoid NameError
        
        while True:
            check_count += 1
            elapsed_minutes = (datetime.utcnow() - start_time).total_seconds() / 60
            
            # Check if we've exceeded the monitoring duration
            if elapsed_minutes >= duration_minutes:
                logger.info(f"⏰ Monitoring duration reached ({duration_minutes} minutes)")
                break
            
            logger.info(f"🔍 Check #{check_count} (elapsed: {elapsed_minutes:.1f} min)")
            
            # Check each forecast hour we haven't generated yet
            available_now = []
            for forecast_hour in settings.forecast_hours_list:
                if forecast_hour > settings.max_forecast_hour:
                    continue
                if forecast_hour in generated_hours:
                    continue
                if self.check_data_available(run_time, forecast_hour):
                    available_now.append(forecast_hour)
            
            if available_now:
                logger.info(f"✅ Found {len(available_now)} new forecast hours: {available_now}")
                
                # Use Pool with maxtasksperchild to prevent memory leaks
                pool_args = [(run_time, hour, self.variables) for hour in available_now]
                
                # Use 4 processes to balance speed and memory on 8vCPU/16GB
                with Pool(processes=4, maxtasksperchild=5) as pool:
                    results = pool.map(generate_maps_for_hour, pool_args)
                
                # Track newly generated hours for this check
                newly_generated = []
                # Update generated_hours set
                for hour in results:
                    if hour is not None:
                        generated_hours.add(hour)
                        newly_generated.append(hour)
            else:
                logger.debug(f"⏳ No new data available yet")
            
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
        self.scheduler.add_job(
            self.generate_forecast_maps,
            trigger=CronTrigger(hour='3,9,15,21', minute='30'),
            id='generate_forecasts',
            name='Generate forecast maps',
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600  # Allow catching up if missed by up to 1 hour
        )
        
        logger.info("Forecast scheduler started")
        logger.info("Schedule: 03:30, 09:30, 15:30, 21:30 UTC")
        
        # Catch-up logic: If we start within 90 minutes of a scheduled time, run now
        now = datetime.utcnow()
        logger.info(f"Checking for catch-up... Current UTC: {now.strftime('%H:%M')}")
        for sched_hour in [3, 9, 15, 21]:
            sched_time = now.replace(hour=sched_hour, minute=30, second=0, microsecond=0)
            # If current time is between sched_time and sched_time + 90 minutes
            # Handle the case where sched_time might be from "yesterday" for the 21:30 run if it's currently 00:15
            if sched_hour == 21 and now.hour < 3:
                sched_time = sched_time - timedelta(days=1)
            
            diff_minutes = (now - sched_time).total_seconds() / 60
            logger.info(f"  Checking {sched_hour}:30 UTC run... (diff: {diff_minutes:.1f} min)")
            
            if 0 <= diff_minutes <= 90:
                logger.info(f"🕒 Catch-up triggered: Starting missed run (scheduled for {sched_hour}:30 UTC)")
                # Run the function directly in a separate thread or just call it if using BlockingScheduler
                # Since it's a blocking scheduler, we add it as a 'date' job to run immediately
                self.scheduler.add_job(
                    self.generate_forecast_maps,
                    trigger='date',
                    run_date=datetime.now(), # Local time for the scheduler's internal clock
                    id='catch_up_run',
                    name='Catch-up run'
                )
                break

        self.scheduler.start()
    
    def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Forecast scheduler stopped")


if __name__ == "__main__":
    # Configure logging for direct execution
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger.info("Starting TWF Models Scheduler")
    scheduler = ForecastScheduler()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler interrupted, shutting down...")
        scheduler.stop()
