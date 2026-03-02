import logging
from apscheduler.schedulers.background import BackgroundScheduler
from services.cleanup_service import CleanupService
from services.scraper_service import KnowledgeFreshnessService

logger = logging.getLogger(__name__)

def start_background_tasks():
    """Initializes the production job scheduler."""
    scheduler = BackgroundScheduler()
    
    # 1. Heartbeat TTL Sweep (Runs every hour)
    scheduler.add_job(CleanupService.sweep_stale_sessions, 'interval', hours=1, id='ttl_sweep')
    
    # 2. Knowledge Freshness Scrape (Runs every Sunday at 2 AM)
    scraper = KnowledgeFreshnessService()
    scheduler.add_job(scraper.run_weekly_update, 'cron', day_of_week='sun', hour=2, id='global_scrape')
    
    scheduler.start()
    logger.info("Background Job Scheduler initialized and running.")