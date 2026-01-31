"""Scheduled task scheduler"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import os
import sys
import logging
import time
import s3fs
import gc
import threading
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
# Dynamic worker count based on available memory
# Reserve 6GB for OS/API/overhead, allocate 3GB per worker
def calculate_optimal_workers():
    """Calculate worker count based on available system memory"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        mem_gb = mem.total / (1024**3)
        available_gb = mem.available / (1024**3)
        
        # Optimized for 32GB server with 12 vCPUs:
        # Reserve 6GB base (OS/API/overhead), use 3GB per worker, max 10 workers
        # This provides better CPU utilization across 12 cores
        # 32GB server: (32 - 6) / 3 = 8.7 → capped at 10 → 8 workers typical
        # 16GB server: (16 - 6) / 3 = 3.3 → 3 workers (safe fallback)
        workers = max(1, min(10, int((mem_gb - 6) / 3)))
        
        # If available memory is critically low, reduce workers
        if available_gb < 8:
            workers = max(1, workers // 2)
            logger.warning(f"⚠️  Low memory ({available_gb:.1f}GB available), reduced to {workers} worker(s)")
        
        logger.info(f"💾 System: {mem_gb:.1f}GB total, {available_gb:.1f}GB available → {workers} workers")
        return workers
    except ImportError:
        logger.warning("psutil not installed, using default 2 workers")
        return 2
    except Exception as e:
        logger.warning(f"Failed to calculate workers dynamically: {e}, using default 2")
        return 2

_GLOBAL_POOL_SIZE = calculate_optimal_workers()

def allocate_workers_per_model(total_workers: int, enabled_models: dict) -> dict:
    """
    Allocate workers across models based on their characteristics.
    
    Args:
        total_workers: Total available workers
        enabled_models: Dict of enabled model configs
    
    Returns:
        Dict mapping model_id -> worker_count
    """
    if len(enabled_models) == 0:
        return {}
    
    if len(enabled_models) == 1:
        # Single model gets all workers
        return {list(enabled_models.keys())[0]: total_workers}
    
    # Multi-model allocation strategy:
    # - GFS: Highest priority (global model, most forecast hours)
    # - AIGFS: Medium priority (global model, similar to GFS)
    # - HRRR: Lower priority (regional, fewer variables, many hours but fast)
    # 
    # Strategy: Allocate proportionally based on expected workload
    # GFS: 40%, AIGFS: 35%, HRRR: 25% of workers
    
    allocation = {}
    model_ids = list(enabled_models.keys())
    
    if len(enabled_models) == 2:
        # Two models: 60/40 split
        allocation[model_ids[0]] = max(2, int(total_workers * 0.6))
        allocation[model_ids[1]] = max(2, total_workers - allocation[model_ids[0]])
    elif len(enabled_models) == 3:
        # Three models: GFS/AIGFS/HRRR typical case
        # Allocate based on model priority
        for model_id in model_ids:
            if model_id == "GFS":
                allocation[model_id] = max(2, int(total_workers * 0.40))
            elif model_id == "AIGFS":
                allocation[model_id] = max(2, int(total_workers * 0.35))
            elif model_id == "HRRR":
                allocation[model_id] = max(2, int(total_workers * 0.25))
            else:
                # Unknown model: equal share
                allocation[model_id] = max(2, total_workers // len(enabled_models))
        
        # Adjust if total doesn't match (due to rounding)
        allocated = sum(allocation.values())
        if allocated < total_workers:
            # Give remainder to GFS (highest priority)
            gfs_id = "GFS" if "GFS" in allocation else model_ids[0]
            allocation[gfs_id] += (total_workers - allocated)
    else:
        # 4+ models: Equal distribution
        per_model = max(2, total_workers // len(enabled_models))
        for model_id in model_ids:
            allocation[model_id] = per_model
    
    return allocation

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
        
        # Clear matplotlib state after all maps for this forecast hour
        # This prevents memory accumulation across variables
        try:
            import matplotlib.pyplot as plt
            plt.clf()
            plt.cla()
            plt.close('all')
        except Exception:
            pass  # Non-critical
        
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
        self.variables = ['temp', 'precip', 'wind_speed', 'mslp_precip', 'temp_850_wind_mslp', 'radar', 'snowfall']
        # Initialize S3 filesystem only if using AWS
        self.s3 = None
        if settings.gfs_source == "aws":
            self.s3 = s3fs.S3FileSystem(anon=True)
    
    def generate_forecast_for_model(self, model_id: str, worker_count: int = None):
        """Generate forecast for a specific model"""
        if worker_count is None:
            worker_count = _GLOBAL_POOL_SIZE
        
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
            
            # Determine forecast hours (use model-specific if available)
            if model_id == "HRRR":
                configured_hours = settings.hrrr_forecast_hours_list
            else:
                configured_hours = [int(h) for h in settings.forecast_hours.split(',')]
            max_hour = self._get_effective_max_forecast_hour(model_id, run_time, model_config)
            forecast_hours = [h for h in configured_hours if h <= max_hour]
            
            logger.info(f"🎯 Forecast hours: {forecast_hours}")
            
            # Filter variables for this model
            variables = VariableRegistry.filter_by_model_capabilities(
                self.variables,
                model_config
            )
            logger.info(f"📊 Variables: {variables}")
            
            # Generate maps in parallel by forecast hour
            # Use allocated worker count for this model
            logger.info(f"💻 Using {worker_count} worker processes")
            
            with Pool(processes=worker_count, maxtasksperchild=5) as pool:
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
    
    def generate_forecast_for_model_progressive(
        self, 
        model_id: str,
        max_duration_minutes: int = 120,
        check_interval_seconds: int = 60,
        worker_count: int = None
    ):
        """
        Generate forecast for a specific model with progressive polling.
        
        Polls NOMADS every check_interval_seconds and generates maps as forecast
        hours become available. Continues until all forecast hours are complete
        or max_duration_minutes is reached.
        
        Args:
            model_id: Model to generate (e.g., 'GFS', 'AIGFS')
            max_duration_minutes: Maximum time to poll (default 120 = 2 hours)
            check_interval_seconds: Seconds between availability checks (default 60)
            worker_count: Number of workers to use (default: global pool size)
        
        Returns:
            bool: True if all forecast hours completed successfully
        """
        if worker_count is None:
            worker_count = _GLOBAL_POOL_SIZE
        
        logger.info(f"\n{'='*80}")
        logger.info(f"🔄 Starting PROGRESSIVE generation for {model_id}")
        logger.info(f"{'='*80}\n")
        
        try:
            # Create fetcher
            data_fetcher = ModelFactory.create_fetcher(model_id)
            run_time = data_fetcher.get_latest_run_time()
            
            logger.info(f"📅 {model_id} Run Time: {run_time.strftime('%Y-%m-%d %HZ')}")
            logger.info(f"⏱️  Max Duration: {max_duration_minutes} minutes")
            logger.info(f"🔍 Check Interval: {check_interval_seconds} seconds")
            
            # Get model config
            model_config = ModelRegistry.get(model_id)
            
            # Determine forecast hours (use model-specific if available)
            if model_id == "HRRR":
                configured_hours = settings.hrrr_forecast_hours_list
            else:
                configured_hours = [int(h) for h in settings.forecast_hours.split(',')]
            max_hour = self._get_effective_max_forecast_hour(model_id, run_time, model_config)
            forecast_hours = sorted([h for h in configured_hours if h <= max_hour])
            
            logger.info(f"🎯 Forecast hours needed: {forecast_hours}")
            
            # Filter variables for this model
            variables = VariableRegistry.filter_by_model_capabilities(
                self.variables,
                model_config
            )
            logger.info(f"📊 Variables: {variables}")
            logger.info(f"💻 Using {worker_count} worker processes")
            logger.info("")
            
            # Track which hours have been generated
            completed_hours = set()
            pending_hours = set(forecast_hours)
            failed_attempts = {}  # Track failures per hour
            
            start_time = time.time()
            max_duration_seconds = max_duration_minutes * 60
            poll_cycle = 0
            
            while pending_hours:
                poll_cycle += 1
                elapsed = time.time() - start_time
                elapsed_minutes = elapsed / 60
                
                # Check if we've exceeded max duration
                if elapsed >= max_duration_seconds:
                    logger.warning(f"⏰ Max duration ({max_duration_minutes} min) reached")
                    logger.warning(f"   Still pending: {sorted(pending_hours)}")
                    break
                
                logger.info(f"🔍 Poll cycle #{poll_cycle} at +{elapsed_minutes:.1f} min")
                logger.info(f"   Completed: {len(completed_hours)}/{len(forecast_hours)} hours")
                if pending_hours:
                    logger.info(f"   Pending: {sorted(pending_hours)}")
                
                # Check which pending hours are now available
                available_hours = []
                for fh in sorted(pending_hours):
                    if self.check_forecast_hour_available(model_id, run_time, fh):
                        available_hours.append(fh)
                
                if available_hours:
                    logger.info(f"✅ Found {len(available_hours)} available: {available_hours}")
                    
                    # Generate maps for available hours in parallel
                    with Pool(processes=worker_count, maxtasksperchild=5) as pool:
                        args = [(model_id, run_time, fh, variables) for fh in available_hours]
                        results = pool.map(generate_maps_for_hour, args)
                    
                    # Process results
                    for fh, result in zip(available_hours, results):
                        if result is not None:
                            completed_hours.add(fh)
                            pending_hours.discard(fh)
                            logger.info(f"   ✓ f{fh:03d} generation complete")
                        else:
                            failed_attempts[fh] = failed_attempts.get(fh, 0) + 1
                            if failed_attempts[fh] >= 3:
                                logger.error(f"   ✗ f{fh:03d} failed {failed_attempts[fh]} times, giving up")
                                pending_hours.discard(fh)
                            else:
                                logger.warning(f"   ⚠️  f{fh:03d} generation failed (attempt {failed_attempts[fh]}/3)")
                    
                    # Check if we're done immediately after generating
                    if not pending_hours:
                        logger.info(f"\n🎉 All {len(completed_hours)} forecast hours complete!")
                        logger.info(f"⏱️  Total time: {elapsed_minutes:.1f} minutes ({poll_cycle} poll cycles)")
                        break
                else:
                    logger.info(f"⏳ No new data available, waiting {check_interval_seconds}s...")
                
                # Wait before next check (only if there are still pending hours)
                if pending_hours:
                    time.sleep(check_interval_seconds)
            
            # Final summary (only show if we didn't already report completion)
            final_elapsed = time.time() - start_time
            final_elapsed_minutes = final_elapsed / 60
            
            # Only show summary if we exited via timeout or failure (not normal completion)
            if pending_hours or failed_attempts:
                logger.info(f"\n{'='*80}")
                logger.info(f"📊 {model_id} PROGRESSIVE GENERATION SUMMARY")
                logger.info(f"{'='*80}")
                logger.info(f"✅ Completed: {len(completed_hours)}/{len(forecast_hours)} hours")
                logger.info(f"⏱️  Duration: {final_elapsed_minutes:.1f} minutes ({poll_cycle} poll cycles)")
                
                if pending_hours:
                    logger.warning(f"⚠️  Still pending: {sorted(pending_hours)}")
                
                if failed_attempts:
                    logger.warning(f"❌ Failed attempts:")
                    for fh, count in sorted(failed_attempts.items()):
                        if fh not in completed_hours:
                            logger.warning(f"   f{fh:03d}: {count} failures")
                
                logger.info(f"{'='*80}\n")
            
            return len(completed_hours) == len(forecast_hours)
        
        except Exception as e:
            logger.error(f"❌ {model_id} progressive generation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def check_forecast_hour_available(self, model_id: str, run_time: datetime, forecast_hour: int) -> bool:
        """
        Check if a specific forecast hour is available.
        
        For Herbie-based models (GFS, HRRR), delegate to Herbie's availability check.
        For NOMADS-based models (AIGFS), check NOMADS directly.
        
        Args:
            model_id: Model ID (e.g., 'GFS', 'AIGFS', 'HRRR')
            run_time: Model run time
            forecast_hour: Forecast hour to check
        
        Returns:
            bool: True if data is available
        """
        try:
            model_config = ModelRegistry.get(model_id)
            if not model_config:
                return False
            
            # Route based on fetcher type
            if model_config.fetcher_type == "herbie":
                # Use Herbie's built-in availability check
                logger.debug(f"{model_id} uses Herbie - checking availability via Herbie")
                try:
                    from herbie import Herbie
                    
                    # Map to Herbie model name
                    herbie_model_map = {
                        "GFS": "gfs",
                        "HRRR": "hrrr",
                        "RAP": "rap",
                    }
                    herbie_model = herbie_model_map.get(model_id)
                    if not herbie_model:
                        logger.warning(f"{model_id} not in Herbie model map, assuming available")
                        return True
                    
                    # Check if Herbie can find the file
                    run_time_naive = run_time.replace(tzinfo=None) if run_time.tzinfo else run_time
                    H = Herbie(
                        date=run_time_naive,
                        model=herbie_model,
                        fxx=forecast_hour,
                        verbose=False
                    )
                    
                    # If Herbie found a grib file, it's available
                    available = H.grib is not None
                    if available:
                        logger.debug(f"✓ {model_id} f{forecast_hour:03d} available via Herbie")
                    return available
                    
                except ImportError:
                    logger.warning("Herbie not installed, assuming data available")
                    return True
                except Exception as e:
                    logger.debug(f"Herbie availability check failed for {model_id} f{forecast_hour:03d}: {e}")
                    # If Herbie fails, let the fetcher handle it (may succeed or fail gracefully)
                    return True
            
            # NOMADS direct check (for AIGFS and legacy models)
            import requests
            
            date_str = run_time.strftime("%Y%m%d")
            run_hour = run_time.strftime("%H")
            forecast_hour_str = f"{forecast_hour:03d}"
            
            # Build check URL based on model
            base_url = "https://nomads.ncep.noaa.gov/pub/data/nccf/com"
            
            if model_id == "AIGFS":
                # Check AIGFS location (try sfc first as it's most common)
                if forecast_hour == 0 and model_config.has_analysis_file:
                    filename = f"aigfs.t{run_hour}z.sfc.f000.grib2"
                else:
                    filename = f"aigfs.t{run_hour}z.sfc.f{forecast_hour_str}.grib2"
                url = f"{base_url}/aigfs/prod/aigfs.{date_str}/{run_hour}/model/atmos/grib2/{filename}"
            else:
                logger.warning(f"Don't know how to check availability for {model_id} (not Herbie, not AIGFS)")
                return True  # Assume available for unknown models
            
            # Try HEAD request (faster than GET)
            response = requests.head(url, timeout=10, allow_redirects=True)
            return response.status_code == 200
            
        except requests.exceptions.RequestException:
            return False
        except Exception as e:
            logger.debug(f"Error checking availability for {model_id} f{forecast_hour:03d}: {e}")
            return False

    def _get_effective_max_forecast_hour(self, model_id: str, run_time: datetime, model_config) -> int:
        """
        Determine the effective max forecast hour for a model/run.

        HRRR runs out to f48 only at 00z/06z/12z/18z. Other cycles run to f18.
        """
        configured_hours = [int(h) for h in settings.forecast_hours.split(',')]
        max_configured = max(configured_hours)
        max_model = model_config.max_forecast_hour

        if model_id == "HRRR":
            run_hour = run_time.hour
            if run_hour not in {0, 6, 12, 18}:
                max_model = min(max_model, 18)

        return min(max_configured, max_model)
    def generate_all_models(self, use_progressive: bool = True, parallel: bool = True):
        """
        Generate forecasts for all enabled models.
        
        Args:
            use_progressive: If True, use progressive polling; if False, generate all at once
            parallel: If True, run models in parallel; if False, run sequentially
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"🌐 MULTI-MODEL FORECAST GENERATION")
        logger.info(f"{'='*80}\n")
        
        enabled_models = ModelRegistry.get_enabled()
        
        if not enabled_models:
            logger.error("No models enabled!")
            return
        
        logger.info(f"Enabled models: {list(enabled_models.keys())}")
        logger.info(f"Total workers available: {_GLOBAL_POOL_SIZE}")
        logger.info(f"Generation mode: {'PROGRESSIVE (polling)' if use_progressive else 'IMMEDIATE (all at once)'}")
        logger.info(f"Execution mode: {'PARALLEL' if parallel else 'SEQUENTIAL'}\n")
        
        if parallel and len(enabled_models) > 1:
            # PARALLEL EXECUTION: Run all models concurrently with allocated workers
            logger.info("🚀 Running models in PARALLEL")
            
            # Allocate workers per model
            worker_allocation = allocate_workers_per_model(_GLOBAL_POOL_SIZE, enabled_models)
            logger.info(f"Worker allocation: {worker_allocation}\n")
            
            # Thread-safe result storage
            results = {}
            results_lock = threading.Lock()
            
            def run_model(model_id: str, workers: int):
                """Thread worker function to run a single model"""
                try:
                    if use_progressive:
                        success = self.generate_forecast_for_model_progressive(
                            model_id,
                            max_duration_minutes=120,
                            check_interval_seconds=60,
                            worker_count=workers
                        )
                    else:
                        success = self.generate_forecast_for_model(
                            model_id,
                            worker_count=workers
                        )
                    
                    with results_lock:
                        results[model_id] = success
                        
                except Exception as e:
                    logger.error(f"❌ {model_id} thread failed: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    with results_lock:
                        results[model_id] = False
            
            # Create and start threads for each model
            threads = []
            for model_id, worker_count in worker_allocation.items():
                thread = threading.Thread(
                    target=run_model,
                    args=(model_id, worker_count),
                    name=f"{model_id}-generator"
                )
                thread.start()
                threads.append(thread)
                logger.info(f"✓ Started {model_id} thread with {worker_count} workers")
            
            logger.info(f"\n⏳ Waiting for {len(threads)} model threads to complete...\n")
            
            # Wait for all threads to complete
            for thread in threads:
                thread.join()
                logger.info(f"✓ {thread.name} completed")
            
            logger.info(f"\n{'='*80}")
            
        else:
            # SEQUENTIAL EXECUTION: Original behavior (safer fallback)
            logger.info("🔄 Running models SEQUENTIALLY")
            logger.info(f"Global pool size: {_GLOBAL_POOL_SIZE} workers\n")
            
            results = {}
            for model_id in enabled_models.keys():
                if use_progressive:
                    success = self.generate_forecast_for_model_progressive(
                        model_id,
                        max_duration_minutes=120,
                        check_interval_seconds=60
                    )
                else:
                    success = self.generate_forecast_for_model(model_id)
                
                results[model_id] = success
                
                # Memory cleanup between models to prevent accumulation
                try:
                    import psutil
                    mem_before = psutil.virtual_memory()
                    logger.info(f"  🧹 Cleaning up after {model_id}...")
                    logger.info(f"     Memory before cleanup: {mem_before.percent:.1f}% used, {mem_before.available / (1024**3):.1f}GB available")
                    
                    gc.collect()
                    time.sleep(5)  # Let OS reclaim memory
                    
                    mem_after = psutil.virtual_memory()
                    freed_mb = (mem_after.available - mem_before.available) / (1024**2)
                    logger.info(f"     Memory after cleanup:  {mem_after.percent:.1f}% used, {mem_after.available / (1024**3):.1f}GB available")
                    if freed_mb > 0:
                        logger.info(f"     ✓ Freed {freed_mb:.0f}MB")
                except ImportError:
                    # Fallback if psutil not available
                    logger.info(f"  🧹 Cleaning up after {model_id}...")
                    gc.collect()
                    time.sleep(5)
                
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
        Uses progressive generation (polling) if enabled in config.
        Runs models in parallel by default for 32GB server efficiency.
        """
        logger.info("="*80)
        logger.info("🚀 Starting forecast map generation")
        logger.info("="*80)
        
        try:
            # Use progressive generation setting from config
            use_progressive = settings.progressive_generation
            
            # Use parallel execution by default (2+ models run concurrently)
            # Can be disabled via parallel=False for debugging
            self.generate_all_models(use_progressive=use_progressive, parallel=True)
            
            logger.info("="*80)
            logger.info("✅ Forecast generation complete")
            logger.info("="*80)
            
        except Exception as e:
            logger.error(f"❌ Error in forecast generation: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
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
        
        # Schedule: Run every 6 hours at 30 minutes past the hour
        # (3:30, 9:30, 15:30, 21:30 UTC - allows 3h30m after model run for data availability)
        # Corresponds to: 9:30PM, 3:30AM, 9:30AM, 3:30PM CST
        self.scheduler.add_job(
            self.generate_forecast_maps,
            trigger=CronTrigger(hour='3,9,15,21', minute='30'),
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
