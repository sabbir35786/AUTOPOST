import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from app.services.schedule_service import process_due_persona_slots, register_all_todays_slots, prepare_upcoming_persona_slots

logger = logging.getLogger(__name__)


def keep_db_alive():
    """Lightweight keepalive query to prevent database connections from going stale."""
    try:
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db.commit()
            logger.info("Database connection is healthy (keepalive)")
        except Exception as exc:
            logger.error("Database keepalive query failed: %s", exc)
        finally:
            db.close()
    except Exception as exc:
        logger.error("Database keepalive session failed: %s", exc)

scheduler = None

def get_scheduler():
    global scheduler
    if scheduler is None:
        # Use the current running event loop (for async contexts)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        scheduler = AsyncIOScheduler(event_loop=loop)
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

    sched.add_job(
        keep_db_alive,
        IntervalTrigger(minutes=10),
        id="keep_db_alive",
        name="Keep database connection alive",
        replace_existing=True,
        max_instances=1,
    )

def start_scheduler():
    sched = get_scheduler()
    if not sched.running:
        logger.info("=" * 60)
        logger.info("[SCHEDULER] Starting APScheduler")
        logger.info("=" * 60)
        setup_scheduler()
        sched.start()
        jobs = sched.get_jobs()
        logger.info(f"[SCHEDULER] Started with {len(jobs)} jobs:")
        for job in jobs:
            logger.info(f"  - {job.name} (id={job.id}, trigger={job.trigger})")
        logger.info("=" * 60)
        print(f"[SCHEDULER] APScheduler started with {len(jobs)} jobs")
    else:
        logger.info("[SCHEDULER] Scheduler already running")
        
def stop_scheduler():
    sched = get_scheduler()
    if sched.running:
        logger.info("[SCHEDULER] Stopping APScheduler")
        sched.shutdown()
