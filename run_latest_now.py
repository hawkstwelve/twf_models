import os
import sys
import logging
from datetime import datetime, timedelta

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

def force_latest_run():
    print("="*70)
    print("🚀 MANUALLY TRIGGERING LATEST GFS MAP GENERATION")
    print("="*70)
    
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
    print(f"⏱️  Will check S3 every 60 seconds for data...")
    
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
