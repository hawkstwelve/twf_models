import os
import sys
import logging
from datetime import datetime

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

def force_18z_run():
    print("="*70)
    print("🚀 MANUALLY TRIGGERING 18z GFS MAP GENERATION")
    print("="*70)
    
    scheduler = ForecastScheduler()
    
    # Calculate 18z for today
    now = datetime.utcnow()
    run_time = datetime(now.year, now.month, now.day, 18)
    
    print(f"📡 Force-starting monitoring for: {run_time.strftime('%Y-%m-%d %Hz')}")
    print(f"⏱️  Will check S3 every 60 seconds for 18z data...")
    
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
    force_18z_run()
