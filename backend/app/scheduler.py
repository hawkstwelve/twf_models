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
from app.services.model_factory import ModelFactory
from app.models.model_registry import ModelRegistry
from app.models.variable_requirements import VariableRegistry

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Global concurrency control - prevent resource thrashing
# Adjust based on server capacity (4 workers for 8vCPU/16GB)
_GLOBAL_POOL_SIZE = min(4, os.cpu_count() or 4)

def generate_maps_for_hour(args):
    """
    Generate maps for a specific hour - model agnostic.
    
    **CRITICAL: This is the ONLY place that calls build_dataset_for_maps().**
    MapGenerator NEVER calls fetcher methods.
    """
    model_id, run_time, forecast_hour, variables = args
    
    # Configure logging for the child process
    child_logger = logging.getLogger(f"{model_id}-f{forecast_hour:03d}")
    
    try:
        child_logger.info(f"🚀 Worker starting for {model_id} f{forecast_hour:03d}")
        
        # Create fetcher and generator
        data_fetcher = ModelFactory.create_fetcher(model_id)
        map_generator = MapGenerator()  # Pure, no fetchers inside
        
        # Filter variables based on model capabilities
        model_config = ModelRegistry.get(model_id)
        variables_to_generate = VariableRegistry.filter_by_model_capabilities(
            variables,
            model_config
        )
        
        # Skip f000-specific exclusions
        if forecast_hour == 0:
            skip_vars = ['wind_speed', 'precip', 'mslp_precip', 'radar', 'radar_reflectivity']
            variables_to_generate = [v for v in variables_to_generate if v not in skip_vars]
            if skip_vars:
                child_logger.info(f"  ⊙ Skipping f000-unavailable vars: {skip_vars}")
        
        if not variables_to_generate:
            child_logger.info(f"  ⊙ No variables to generate for {model_id} f{forecast_hour:03d}")
            return forecast_hour
        
        # **SINGLE CALL to build complete dataset with ALL derived fields**
        # This is where ALL data fetching and derived field computation happens
        child_logger.info(f"  📥 Building dataset for {len(variables_to_generate)} variables...")
        ds = data_fetcher.build_dataset_for_maps(
            run_time=run_time,
            forecast_hour=forecast_hour,
            variables=variables_to_generate,
            subset_region=True
        )
        child_logger.info(f"  ✓ Dataset ready with {len(ds.data_vars)} fields")
        
        # Check which maps already exist for this run
        run_str = run_time.strftime("%Y%m%d_%H")
        images_path = Path(settings.storage_path)
        existing_maps = set()
        
        if images_path.exists():
            for var in variables_to_generate:
                expected_filename = f"{model_id.lower()}_{run_str}_{var}_{forecast_hour}.png"
                if (images_path / expected_filename).exists():
                    existing_maps.add(var)
                    child_logger.info(f"  ⊙ {var} already exists, skipping")
        
        # Generate all maps - MapGenerator NEVER fetches, just renders
        success_count = 0
        failed_variables = []
        
        for variable in variables_to_generate:
            # Skip if already exists
            if variable in existing_maps:
                success_count += 1
                continue
            
            try:
                # MapGenerator is PURE - only renders from ds
                map_generator.generate_map(
                    ds=ds,
                    variable=variable,
                    model=model_id,  # Pass model_id as string
                    run_time=run_time,
                    forecast_hour=forecast_hour
                )
                child_logger.info(f"  ✓ {variable}")
                success_count += 1
            except Exception as e:
                child_logger.error(f"  ✗ {variable}: {e}")
                failed_variables.append(variable)
        
        # Cleanup
        ds.close()
        del ds
        gc.collect()
        
        # Only mark as complete if ALL maps exist
        if success_count == len(variables_to_generate):
            child_logger.info(f"✅ {model_id} f{forecast_hour:03d}: Complete ({success_count} maps)")
            return forecast_hour
        else:
            child_logger.warning(f"⚠️  {model_id} f{forecast_hour:03d}: Incomplete ({success_count}/{len(variables_to_generate)}). Failed: {failed_variables}")
            return None
        
    except Exception as e:
        child_logger.error(f"❌ Worker failed for f{forecast_hour:03d}: {e}")
        return None

class ForecastScheduler:
    """Multi-model scheduler with global concurrency control"""
    
    def __init__(self):
        self.scheduler = BlockingScheduler()
        self.map_generator = MapGenerator()
        self.variables = ['temp', 'precip', 'wind_speed', 'mslp_precip', 'temp_850_wind_mslp', 'radar']
        # Initialize S3 filesystem only if using AWS
        self.s3 = None
        if settings.gfs_source == "aws":
            self.s3 = s3fs.S3FileSystem(anon=True)
    
    def generate_forecast_for_model(self, model_id: str):
        """Generate forecast for a specific model"""
        logger.info(f"\n{'='*80}")
        logger.info(f"🌍 Starting forecast generation for {model_id}")
        logger.info(f"{'='*80}\n")
        
        try:
            # Create fetcher
            data_fetcher = ModelFactory.create_fetcher(model_id)
            run_time = data_fetcher.get_latest_run_time()
            
            logger.info(f"📅 {model_id} Run Time: {run_time.strftime('%Y-%m-%d %HZ')}")
            
            # Get model config
            model_config = ModelRegistry.get(model_id)
            
            # Determine forecast hours
            configured_hours = [int(h) for h in settings.forecast_hours.split(',')]
            max_hour = min(max(configured_hours), model_config.max_forecast_hour)
            forecast_hours = [h for h in configured_hours if h <= max_hour]
            
            logger.info(f"🎯 Forecast hours: {forecast_hours}")
            
            # Filter variables for this model
            variables = VariableRegistry.filter_by_model_capabilities(
                self.variables,
                model_config
            )
            logger.info(f"📊 Variables: {variables}")
            
            # Generate maps in parallel by forecast hour
            # Use GLOBAL pool size to prevent resource thrashing
            logger.info(f"💻 Using {_GLOBAL_POOL_SIZE} worker processes")
            
            with Pool(processes=_GLOBAL_POOL_SIZE, maxtasksperchild=5) as pool:
                args = [(model_id, run_time, fh, variables) for fh in forecast_hours]
                results = pool.map(generate_maps_for_hour, args)
            
            # Summary
            successful = [r for r in results if r is not None]
            logger.info(f"\n✅ {model_id}: {len(successful)}/{len(forecast_hours)} forecast hours complete")
            
            return len(successful) == len(forecast_hours)
        
        except Exception as e:
            logger.error(f"❌ {model_id} generation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def generate_all_models(self):
        """
        Generate forecasts for all enabled models.
        
        **CRITICAL: Run sequentially to avoid CPU/memory thrashing.**
        Each model uses a shared pool of workers.
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"🌐 MULTI-MODEL FORECAST GENERATION")
        logger.info(f"{'='*80}\n")
        
        enabled_models = ModelRegistry.get_enabled()
        
        if not enabled_models:
            logger.error("No models enabled!")
            return
        
        logger.info(f"Enabled models: {list(enabled_models.keys())}")
        logger.info(f"Global pool size: {_GLOBAL_POOL_SIZE} workers\n")
        
        # Generate SEQUENTIALLY (safer, prevents resource contention)
        # With global pool size limit, this is efficient enough
        results = {}
        for model_id in enabled_models.keys():
            success = self.generate_forecast_for_model(model_id)
            results[model_id] = success
            logger.info(f"\n{'-'*80}\n")
        
        # Summary
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 GENERATION SUMMARY")
        logger.info(f"{'='*80}")
        for model_id, success in results.items():
            status = "✅ SUCCESS" if success else "❌ FAILED"
            logger.info(f"  {model_id}: {status}")
        logger.info(f"{'='*80}\n")
        
        # Cleanup old runs after completion
        self.cleanup_old_runs()
    
    def check_data_available(self, run_time, forecast_hour):
        """
        Check if GFS data is available (AWS S3 or NOMADS).
        
        Args:
            run_time: GFS run time (datetime)
            forecast_hour: Forecast hour (int)
            
        Returns:
            bool: True if data exists
        """
        try:
            date_str = run_time.strftime('%Y%m%d')
            hour_str = run_time.strftime('%H')
            hour_padded = f"{forecast_hour:03d}"
            
            if settings.gfs_source == "aws":
                # Check AWS S3
                grib_path = f"noaa-gfs-bdp-pds/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.{settings.gfs_resolution}.f{hour_padded}"
                
                exists = self.s3.exists(grib_path)
                
                # If f000 doesn't exist, try 'anl'
                if not exists and forecast_hour == 0:
                    anl_path = f"noaa-gfs-bdp-pds/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.{settings.gfs_resolution}.anl"
                    exists = self.s3.exists(anl_path)
                    if exists:
                        logger.info(f"Found analysis file (anl) for f000")
                
                return exists
                
            elif settings.gfs_source == "nomads":
                # Check NOMADS via HTTP HEAD request
                import requests
                
                url = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.{settings.gfs_resolution}.f{hour_padded}"
                
                # Try HEAD request (faster than GET)
                try:
                    response = requests.head(url, timeout=10)
                    exists = response.status_code == 200
                    
                    # If f000 doesn't exist, try 'anl'
                    if not exists and forecast_hour == 0:
                        anl_url = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{date_str}/{hour_str}/atmos/gfs.t{hour_str}z.pgrb2.{settings.gfs_resolution}.anl"
                        response = requests.head(anl_url, timeout=10)
                        exists = response.status_code == 200
                        if exists:
                            logger.info(f"Found analysis file (anl) for f000")
                    
                    return exists
                except requests.exceptions.RequestException:
                    return False
            else:
                logger.warning(f"Unknown GFS source: {settings.gfs_source}")
                return False
            
        except Exception as e:
            logger.debug(f"Error checking data availability for f{forecast_hour:03d}: {e}")
            return False
    
    def generate_forecast_maps(self):
        """
        Generate forecast maps for all enabled models.
        
        This is the main entry point called by the scheduler.
        Replaces old progressive generation with multi-model support.
        """
        logger.info("="*80)
        logger.info("🚀 Starting forecast map generation")
        logger.info("="*80)
        
        try:
            # Call new multi-model generation method
            self.generate_all_models()
            
            logger.info("="*80)
            logger.info("✅ Forecast generation complete")
            logger.info("="*80)
            
        except Exception as e:
            logger.error(f"❌ Error in forecast generation: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    # Old progressive generation loop removed - now using multi-model generation
    # If needed in the future for specific models, can be re-added
    
    def cleanup_old_runs(self, keep_last_n=4):
        """
        Keep only the last N model runs for each model, delete older ones.
        
        Multi-model aware: Tracks run times separately per model.
        
        Args:
            keep_last_n: Number of most recent runs to keep per model (default: 4 = last 24 hours)
        """
        try:
            images_path = Path(settings.storage_path)
            
            if not images_path.exists():
                logger.warning("Images directory doesn't exist, skipping cleanup")
                return
            
            # Get enabled models
            enabled_models = ModelRegistry.get_enabled()
            
            for model_id in enabled_models.keys():
                model_prefix = f"{model_id.lower()}_"
                
                # Parse all image filenames for this model
                image_files = list(images_path.glob(f"{model_prefix}*.png"))
                
                if not image_files:
                    logger.info(f"No images found for {model_id}, skipping cleanup")
                    continue
                
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
                
                logger.info(f"Found {len(sorted_runs)} unique {model_id} runs")
                
                # Keep newest N, delete rest
                if len(sorted_runs) > keep_last_n:
                    runs_to_keep = sorted_runs[:keep_last_n]
                    runs_to_delete = sorted_runs[keep_last_n:]
                    
                    logger.info(f"Keeping {len(runs_to_keep)} {model_id} runs: {', '.join(runs_to_keep)}")
                    logger.info(f"Deleting {len(runs_to_delete)} old {model_id} runs: {', '.join(runs_to_delete)}")
                    
                    deleted_count = 0
                    for old_run in runs_to_delete:
                        # Delete all images from this run
                        old_images = list(images_path.glob(f"{model_prefix}{old_run}_*.png"))
                        for img in old_images:
                            try:
                                img.unlink()
                                deleted_count += 1
                                logger.debug(f"Deleted: {img.name}")
                            except Exception as e:
                                logger.error(f"Failed to delete {img.name}: {e}")
                    
                    logger.info(f"✅ {model_id} cleanup complete: Deleted {deleted_count} images from {len(runs_to_delete)} old runs")
                else:
                    logger.info(f"Only {len(sorted_runs)} {model_id} runs found, keeping all (threshold: {keep_last_n})")
            
            # Log current disk usage
            total_size = sum(f.stat().st_size for f in images_path.glob("*.png"))
            total_images = len(list(images_path.glob("*.png")))
            logger.info(f"Current storage: {total_size / (1024*1024):.1f} MB ({total_images} images)")
                
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    def start(self):
        """Start the multi-model scheduler"""
        logger.info("Starting Multi-Model Forecast Scheduler...")
        logger.info(f"Global pool size: {_GLOBAL_POOL_SIZE} workers")
        
        # Schedule: Run every 6 hours at 45 minutes past the hour
        # (3:45, 9:45, 15:45, 21:45 UTC - allows 3h45m after model run for data availability)
        self.scheduler.add_job(
            self.generate_forecast_maps,
            trigger=CronTrigger(hour='3,9,15,21', minute='45'),
            id='multi_model_forecast',
            name='Multi-Model Forecast Generation',
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600  # Allow catching up if missed by up to 1 hour
        )
        
        logger.info("Scheduler started. Jobs:")
        for job in self.scheduler.get_jobs():
            logger.info(f"  - {job.name}: {job.trigger}")
        
        # Run once immediately on startup
        logger.info("\n🚀 Running initial forecast generation...")
        self.generate_forecast_maps()
        
        # Start scheduler
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
