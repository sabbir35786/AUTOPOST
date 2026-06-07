import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.services.schedule_service import process_due_persona_slots, register_all_todays_slots, prepare_upcoming_persona_slots

logger = logging.getLogger(__name__)

scheduler = None

def get_scheduler():
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
    return scheduler

def setup_scheduler():
    sched = get_scheduler()
    sched.add_job(
        prepare_upcoming_persona_slots,
        IntervalTrigger(minutes=5),
        id="prepare_upcoming_slots",
        name="Prepare upcoming persona slots",
        replace_existing=True,
        max_instances=1,
    )

    sched.add_job(
        process_due_persona_slots,
        IntervalTrigger(minutes=1),
        id="process_due_slots",
        name="Process due persona slots",
        replace_existing=True,
        max_instances=1,
    )

    sched.add_job(
        register_all_todays_slots,
        CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="register_daily_slots",
        name="Register daily slots for all personas at midnight UTC",
        replace_existing=True,
        max_instances=1,
    )

def start_scheduler():
    sched = get_scheduler()
    if not sched.running:
        logger.info("Starting APScheduler")
        setup_scheduler()
        sched.start()
        
def stop_scheduler():
    sched = get_scheduler()
    if sched.running:
        logger.info("Stopping APScheduler")
        sched.shutdown()
