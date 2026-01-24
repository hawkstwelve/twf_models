"""Scheduled task scheduler"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
from datetime import datetime

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
            run_time = datetime.utcnow()
            
            for variable in self.variables:
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
                        logger.info(f"Generated map: {variable} at +{forecast_hour}h")
                    except Exception as e:
                        logger.error(f"Error generating map {variable} +{forecast_hour}h: {e}")
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
