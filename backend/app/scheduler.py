import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.services.schedule_service import process_due_persona_slots, register_all_todays_slots

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

def setup_scheduler():
    scheduler.add_job(
        process_due_persona_slots,
        IntervalTrigger(minutes=1),
        id="process_due_slots",
        name="Process due persona slots",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        register_all_todays_slots,
        CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="register_daily_slots",
        name="Register daily slots for all personas at midnight UTC",
        replace_existing=True,
        max_instances=1,
    )

def start_scheduler():
    if not scheduler.running:
        logger.info("Starting APScheduler")
        setup_scheduler()
        scheduler.start()
        
def stop_scheduler():
    if scheduler.running:
        logger.info("Stopping APScheduler")
        scheduler.shutdown()
