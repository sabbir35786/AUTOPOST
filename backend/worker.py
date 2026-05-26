import asyncio
import logging
import time
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import create_database_tables, SessionLocal
from app.posts import run_scheduled_posts
from app.learning.service import run_engagement_snapshot_job, run_weekly_learning_job

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("worker")

async def main():
    print("Background worker started successfully")
    logger.info("Starting background worker...")
    
    # Initialize DB tables and verify database connection
    try:
        create_database_tables()
        db = SessionLocal()
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        db.close()
        logger.info("Database connection verified successfully.")
    except Exception as exc:
        logger.error(f"Error initializing database/connection in worker: {exc}")
        
    scheduler = AsyncIOScheduler()
    
    scheduler.add_job(
        run_scheduled_posts,
        CronTrigger(minute="*/5"),
        id="scheduled_posts",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_engagement_snapshot_job,
        CronTrigger(hour="*/6"),
        id="engagement_snapshots",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_weekly_learning_job,
        CronTrigger(day_of_week="sun", hour=0, minute=0),
        id="weekly_learning",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    
    try:
        scheduler.start()
        logger.info("Scheduler started successfully — background jobs are running")
    except Exception as exc:
        logger.error(f"Failed to start scheduler: {exc}")
        
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker stopping...")
        scheduler.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
