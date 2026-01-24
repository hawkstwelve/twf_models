"""Scheduled task scheduler"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
from datetime import datetime, timedelta

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
        """Generate maps for all variables and forecast hours"""
        logger.info("Starting scheduled forecast map generation")
        
        try:
            # Calculate the GFS run time to fetch
            # Always fetch data from the PREVIOUS 6-hour cycle to ensure it's available
            # GFS data becomes available 3-4 hours after run time
            # So when we run at 06:00 UTC, we fetch 00Z data (which is now available)
            now = datetime.utcnow()
            run_hour = ((now.hour // 6) * 6) - 6  # Go back one 6-hour cycle
            if run_hour < 0:
                run_hour = 18
                now = now - timedelta(days=1)
            
            run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
            logger.info(f"Fetching GFS data for run time: {run_time.strftime('%Y-%m-%d %H:00 UTC')}")
            
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
            
            logger.info("Completed forecast map generation")
        except Exception as e:
            logger.error(f"Error in scheduled map generation: {e}")
    
    def start(self):
        """Start the scheduler"""
        # Schedule to run every 6 hours (after GFS updates)
        # GFS runs at 00, 06, 12, 18 UTC
        self.scheduler.add_job(
            self.generate_forecast_maps,
            trigger=CronTrigger(hour='*/6'),  # Every 6 hours
            id='generate_forecasts',
            name='Generate forecast maps',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info("Forecast scheduler started")
    
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
